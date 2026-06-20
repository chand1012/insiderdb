from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Iterable
from xml.etree import ElementTree


class OwnershipParseError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedOwner:
    cik: str | None
    name: str | None
    is_director: bool
    is_officer: bool
    is_ten_percent_owner: bool
    is_other: bool
    officer_title: str | None
    other_text: str | None

    @property
    def role(self) -> str | None:
        roles: list[str] = []
        if self.is_director:
            roles.append("director")
        if self.is_officer:
            roles.append("officer")
        if self.is_ten_percent_owner:
            roles.append("ten_percent_owner")
        if self.is_other:
            roles.append("other")
        return ",".join(roles) or None


@dataclass(frozen=True)
class ParsedTransaction:
    ordinal: int
    transaction_hash: str
    is_derivative: bool
    security_title: str | None
    transaction_date: date | None
    transaction_form_type: str | None
    transaction_code: str | None
    acquired_disposed_code: str | None
    shares: Decimal | None
    price: Decimal | None
    value: Decimal | None
    shares_owned_following_transaction: Decimal | None
    ownership_type: str | None
    direct_or_indirect_ownership: str | None
    ownership_nature: str | None
    underlying_security_title: str | None


@dataclass(frozen=True)
class ParsedFiling:
    accession_number: str
    form_type: str
    filing_date: date
    source_url: str
    issuer_cik: str | None
    issuer_name: str | None
    issuer_trading_symbol: str | None
    period_of_report: date | None
    owners: tuple[ParsedOwner, ...]
    transactions: tuple[ParsedTransaction, ...]

    @property
    def primary_owner(self) -> ParsedOwner | None:
        return self.owners[0] if self.owners else None


def extract_ownership_xml(filing_text: str) -> str:
    match = re.search(r"<ownershipDocument[\s>].*?</ownershipDocument>", filing_text, flags=re.DOTALL)
    if not match:
        raise OwnershipParseError("ownershipDocument XML was not found")
    return match.group(0)


def parse_ownership_filing(
    filing_text: str,
    *,
    accession_number: str,
    source_url: str,
    fallback_form_type: str,
    fallback_filing_date: date,
) -> ParsedFiling:
    xml_text = extract_ownership_xml(filing_text)
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise OwnershipParseError(f"invalid ownershipDocument XML: {exc}") from exc

    issuer = _child(root, "issuer")
    document_type = _text(root, "documentType") or fallback_form_type
    period_of_report = _date(_text(root, "periodOfReport"))

    issuer_cik = _text(issuer, "issuerCik") if issuer is not None else None
    issuer_name = _text(issuer, "issuerName") if issuer is not None else None
    issuer_trading_symbol = _text(issuer, "issuerTradingSymbol") if issuer is not None else None

    owners = tuple(_parse_owner(owner) for owner in _children(root, "reportingOwner"))
    transactions = tuple(
        _parse_transactions(
            root,
            accession_number=accession_number,
            owner=owners[0] if owners else None,
        )
    )

    return ParsedFiling(
        accession_number=accession_number,
        form_type=document_type,
        filing_date=fallback_filing_date,
        source_url=source_url,
        issuer_cik=issuer_cik,
        issuer_name=issuer_name,
        issuer_trading_symbol=issuer_trading_symbol,
        period_of_report=period_of_report,
        owners=owners,
        transactions=transactions,
    )


def _parse_owner(owner: ElementTree.Element) -> ParsedOwner:
    owner_id = _child(owner, "reportingOwnerId")
    relationship = _child(owner, "reportingOwnerRelationship")
    return ParsedOwner(
        cik=_text(owner_id, "rptOwnerCik") if owner_id is not None else None,
        name=_text(owner_id, "rptOwnerName") if owner_id is not None else None,
        is_director=_bool(_text(relationship, "isDirector") if relationship is not None else None),
        is_officer=_bool(_text(relationship, "isOfficer") if relationship is not None else None),
        is_ten_percent_owner=_bool(_text(relationship, "isTenPercentOwner") if relationship is not None else None),
        is_other=_bool(_text(relationship, "isOther") if relationship is not None else None),
        officer_title=_text(relationship, "officerTitle") if relationship is not None else None,
        other_text=_text(relationship, "otherText") if relationship is not None else None,
    )


def _parse_transactions(
    root: ElementTree.Element,
    *,
    accession_number: str,
    owner: ParsedOwner | None,
) -> Iterable[ParsedTransaction]:
    ordinal = 0
    non_derivative_table = _child(root, "nonDerivativeTable")
    if non_derivative_table is not None:
        for transaction in _children(non_derivative_table, "nonDerivativeTransaction"):
            ordinal += 1
            yield _parse_transaction(
                transaction,
                ordinal=ordinal,
                accession_number=accession_number,
                owner=owner,
                is_derivative=False,
            )

    derivative_table = _child(root, "derivativeTable")
    if derivative_table is not None:
        for transaction in _children(derivative_table, "derivativeTransaction"):
            ordinal += 1
            yield _parse_transaction(
                transaction,
                ordinal=ordinal,
                accession_number=accession_number,
                owner=owner,
                is_derivative=True,
            )


def _parse_transaction(
    transaction: ElementTree.Element,
    *,
    ordinal: int,
    accession_number: str,
    owner: ParsedOwner | None,
    is_derivative: bool,
) -> ParsedTransaction:
    coding = _child(transaction, "transactionCoding")
    amounts = _child(transaction, "transactionAmounts")
    post_amounts = _child(transaction, "postTransactionAmounts")
    ownership_nature = _child(transaction, "ownershipNature")
    underlying_security = _child(transaction, "underlyingSecurity")

    shares = _decimal(_value(amounts, "transactionShares"))
    price = _decimal(_value(amounts, "transactionPricePerShare"))
    computed_value = None if shares is None or price is None else abs(shares * price)
    transaction_date = _date(_value(transaction, "transactionDate"))
    transaction_code = _value(coding, "transactionCode")
    acquired_disposed_code = _value(amounts, "transactionAcquiredDisposedCode")
    security_title = _value(transaction, "securityTitle")

    hash_source = "|".join(
        [
            accession_number,
            str(ordinal),
            owner.cik if owner and owner.cik else "",
            security_title or "",
            transaction_date.isoformat() if transaction_date else "",
            transaction_code or "",
            acquired_disposed_code or "",
            str(shares or ""),
            str(price or ""),
        ]
    )

    return ParsedTransaction(
        ordinal=ordinal,
        transaction_hash=hashlib.sha256(hash_source.encode("utf-8")).hexdigest(),
        is_derivative=is_derivative,
        security_title=security_title,
        transaction_date=transaction_date,
        transaction_form_type=_value(coding, "transactionFormType"),
        transaction_code=transaction_code,
        acquired_disposed_code=acquired_disposed_code,
        shares=shares,
        price=price,
        value=computed_value.quantize(Decimal("0.01")) if computed_value is not None else None,
        shares_owned_following_transaction=_decimal(_value(post_amounts, "sharesOwnedFollowingTransaction")),
        ownership_type=_value(ownership_nature, "directOrIndirectOwnership"),
        direct_or_indirect_ownership=_value(ownership_nature, "directOrIndirectOwnership"),
        ownership_nature=_value(ownership_nature, "natureOfOwnership"),
        underlying_security_title=_value(underlying_security, "underlyingSecurityTitle"),
    )


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(element: ElementTree.Element, name: str) -> list[ElementTree.Element]:
    return [child for child in list(element) if _local_name(child.tag) == name]


def _child(element: ElementTree.Element | None, name: str) -> ElementTree.Element | None:
    if element is None:
        return None
    for child in list(element):
        if _local_name(child.tag) == name:
            return child
    return None


def _text(element: ElementTree.Element | None, name: str) -> str | None:
    child = _child(element, name)
    if child is None or child.text is None:
        return None
    value = child.text.strip()
    return value or None


def _value(element: ElementTree.Element | None, name: str) -> str | None:
    child = _child(element, name)
    if child is None:
        return None
    value_child = _child(child, "value")
    raw = value_child.text if value_child is not None else child.text
    if raw is None:
        return None
    value = raw.strip()
    return value or None


def _bool(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "y"}


def _date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _decimal(value: str | None) -> Decimal | None:
    if not value:
        return None
    normalized = value.replace(",", "").strip()
    if normalized.lower() in {"n/a", "na", "none"}:
        return None
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None
