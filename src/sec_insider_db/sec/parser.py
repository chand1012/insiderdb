from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
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
    try:
        xml_text = extract_ownership_xml(filing_text)
    except OwnershipParseError:
        return _parse_legacy_html_filing(
            filing_text,
            accession_number=accession_number,
            source_url=source_url,
            fallback_form_type=fallback_form_type,
            fallback_filing_date=fallback_filing_date,
        )

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


class _LegacyHTMLTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None
        self._cell_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._current_row = []
        elif tag in {"td", "th"} and self._current_row is not None:
            self._current_cell = []
            self._cell_depth += 1
        elif tag == "br" and self._current_cell is not None:
            self._current_cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._current_row is not None and self._current_cell is not None:
            self._cell_depth = max(0, self._cell_depth - 1)
            if self._cell_depth == 0:
                self._current_row.append(_clean_legacy_text("".join(self._current_cell)))
                self._current_cell = None
        elif tag == "tr" and self._current_row is not None:
            if any(cell for cell in self._current_row):
                self.rows.append(self._current_row)
            self._current_row = None
            self._current_cell = None
            self._cell_depth = 0

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)


def _parse_legacy_html_filing(
    filing_text: str,
    *,
    accession_number: str,
    source_url: str,
    fallback_form_type: str,
    fallback_filing_date: date,
) -> ParsedFiling:
    if "<html" not in filing_text.lower() and "<table" not in filing_text.lower():
        raise OwnershipParseError("ownershipDocument XML was not found")

    parser = _LegacyHTMLTableParser()
    try:
        parser.feed(filing_text)
    except Exception as exc:
        raise OwnershipParseError(f"legacy HTML ownership filing could not be parsed: {exc}") from exc

    issuer_name, issuer_ticker = _legacy_issuer_name_and_ticker(filing_text)
    issuer_name = issuer_name or _header_field(filing_text, "SUBJECT COMPANY", "COMPANY CONFORMED NAME")
    issuer_cik = _header_field(filing_text, "SUBJECT COMPANY", "CENTRAL INDEX KEY")

    owner_name = _legacy_reporting_owner_name(filing_text) or _header_field(
        filing_text, "REPORTING-OWNER", "COMPANY CONFORMED NAME"
    )
    owner_cik = _header_field(filing_text, "REPORTING-OWNER", "CENTRAL INDEX KEY")
    is_director = _legacy_checked_role(filing_text, "Director")
    is_officer = _legacy_checked_role(filing_text, "Officer") or _header_relationship(filing_text) == "OFFICER"
    is_ten_percent_owner = _legacy_checked_role(filing_text, "10% Owner")
    is_other = _legacy_checked_role(filing_text, "Other")
    officer_title = _legacy_officer_title(filing_text) if is_officer else None

    owner = ParsedOwner(
        cik=owner_cik,
        name=owner_name,
        is_director=is_director,
        is_officer=is_officer,
        is_ten_percent_owner=is_ten_percent_owner,
        is_other=is_other,
        officer_title=officer_title,
        other_text=None,
    )
    owners = (owner,) if owner.name or owner.cik else ()
    transactions = tuple(
        _parse_legacy_transactions(
            parser.rows,
            accession_number=accession_number,
            owner=owner if owners else None,
            fallback_form_type=fallback_form_type,
            fallback_filing_date=fallback_filing_date,
        )
    )

    return ParsedFiling(
        accession_number=accession_number,
        form_type=fallback_form_type,
        filing_date=fallback_filing_date,
        source_url=source_url,
        issuer_cik=issuer_cik,
        issuer_name=issuer_name,
        issuer_trading_symbol=issuer_ticker,
        period_of_report=_legacy_period_of_report(filing_text),
        owners=owners,
        transactions=transactions,
    )


def _parse_legacy_transactions(
    rows: list[list[str]],
    *,
    accession_number: str,
    owner: ParsedOwner | None,
    fallback_form_type: str,
    fallback_filing_date: date,
) -> Iterable[ParsedTransaction]:
    section: str | None = None
    ordinal = 0

    for row in rows:
        row_text = " ".join(row)
        if "Table I" in row_text and "Non-Derivative" in row_text:
            section = "non_derivative"
            continue
        if "Table II" in row_text and "Derivative" in row_text:
            section = "derivative"
            continue

        if section != "non_derivative" or len(row) < 8:
            continue

        transaction_date = _legacy_date(row[1], fallback_filing_date)
        transaction_code = _clean_legacy_code(row[3])
        if transaction_date is None or transaction_code is None:
            continue

        ordinal += 1
        shares = _decimal(row[5])
        price = _decimal(row[7])
        computed_value = None if shares is None or price is None else abs(shares * price)
        security_title = row[0] or None
        acquired_disposed_code = _clean_legacy_code(row[6])
        ownership_type = _clean_legacy_code(row[9]) if len(row) > 9 else None

        hash_source = "|".join(
            [
                accession_number,
                str(ordinal),
                owner.cik if owner and owner.cik else "",
                security_title or "",
                transaction_date.isoformat(),
                transaction_code,
                acquired_disposed_code or "",
                str(shares or ""),
                str(price or ""),
            ]
        )

        yield ParsedTransaction(
            ordinal=ordinal,
            transaction_hash=hashlib.sha256(hash_source.encode("utf-8")).hexdigest(),
            is_derivative=False,
            security_title=security_title,
            transaction_date=transaction_date,
            transaction_form_type=fallback_form_type,
            transaction_code=transaction_code,
            acquired_disposed_code=acquired_disposed_code,
            shares=shares,
            price=price,
            value=computed_value.quantize(Decimal("0.01")) if computed_value is not None else None,
            shares_owned_following_transaction=_decimal(row[8]) if len(row) > 8 else None,
            ownership_type=ownership_type,
            direct_or_indirect_ownership=ownership_type,
            ownership_nature=(row[10] or None) if len(row) > 10 else None,
            underlying_security_title=None,
        )


def _legacy_issuer_name_and_ticker(filing_text: str) -> tuple[str | None, str | None]:
    match = re.search(
        r"Issuer\s+Name.*?Trading\s+Symbol\s*<br\s*/?>\s*<b>(.*?)</b>",
        filing_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None, None
    value = _clean_legacy_text(_strip_html(match.group(1)))
    ticker_match = re.match(r"(?P<name>.*?)\s*\((?P<ticker>[^()]+)\)\s*$", value)
    if ticker_match:
        return ticker_match.group("name").strip() or None, ticker_match.group("ticker").strip() or None
    return value or None, None


def _legacy_reporting_owner_name(filing_text: str) -> str | None:
    match = re.search(
        r"Name\s+and\s+Address\s+of\s+Reporting\s+Person\*?.*?<b>(.*?)</b>",
        filing_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    return _clean_legacy_text(_strip_html(match.group(1))) or None


def _legacy_checked_role(filing_text: str, role: str) -> bool:
    pattern = rf"<U>\s*(?:<B>)?\s*X\s*(?:</B>)?\s*</U>\s*</b>?\s*{re.escape(role)}"
    return re.search(pattern, filing_text, flags=re.IGNORECASE | re.DOTALL) is not None


def _legacy_officer_title(filing_text: str) -> str | None:
    match = re.search(
        r"Officer\s*\(give\s+title\s+below\).*?<U>\s*<B>(.*?)</B>",
        filing_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    value = _clean_legacy_text(_strip_html(match.group(1)))
    return value or None


def _legacy_period_of_report(filing_text: str) -> date | None:
    match = re.search(r"CONFORMED PERIOD OF REPORT:\s*(\d{8})", filing_text)
    if not match:
        return None
    raw = match.group(1)
    try:
        return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
    except ValueError:
        return None


def _legacy_date(value: str | None, fallback_filing_date: date) -> date | None:
    if not value:
        return None
    value = _clean_legacy_text(value)
    match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", value)
    if not match:
        return _date(value)
    month, day, year = (int(part) for part in match.groups())
    if year < 100:
        century = (fallback_filing_date.year // 100) * 100
        year += century
        if year > fallback_filing_date.year + 20:
            year -= 100
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _header_field(filing_text: str, section_name: str, field_name: str) -> str | None:
    section = _header_section(filing_text, section_name)
    if section is None:
        return None
    match = re.search(rf"{re.escape(field_name)}:\s*([^\n]+)", section, flags=re.IGNORECASE)
    if not match:
        return None
    return _clean_legacy_text(match.group(1)) or None


def _header_relationship(filing_text: str) -> str | None:
    value = _header_field(filing_text, "REPORTING-OWNER", "RELATIONSHIP")
    return value.upper() if value else None


def _header_section(filing_text: str, section_name: str) -> str | None:
    marker = f"{section_name}:"
    start = filing_text.find(marker)
    if start == -1:
        return None
    end_candidates = [
        index for index in (
            filing_text.find("\nSUBJECT COMPANY:", start + len(marker)),
            filing_text.find("\nREPORTING-OWNER:", start + len(marker)),
            filing_text.find("\n</SEC-HEADER>", start + len(marker)),
        ) if index != -1
    ]
    end = min(end_candidates) if end_candidates else len(filing_text)
    return filing_text[start:end]


def _strip_html(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", value)


def _clean_legacy_text(value: str) -> str:
    value = value.replace("\xa0", " ").replace("&nbsp;", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _clean_legacy_code(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"[A-Z]", value.upper())
    return match.group(0) if match else None


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
    normalized = value.replace(",", "").replace("$", "").strip()
    normalized = re.sub(r"\([^)]*\)", "", normalized).strip()
    if normalized.lower() in {"", "n/a", "na", "none"}:
        return None
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None
