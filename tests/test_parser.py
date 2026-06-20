from __future__ import annotations

from datetime import date
from decimal import Decimal

from sec_insider_db.sec.parser import parse_ownership_filing


SAMPLE_FORM_4 = """
<SEC-DOCUMENT>
<XML>
<ownershipDocument>
  <documentType>4</documentType>
  <periodOfReport>2024-01-03</periodOfReport>
  <issuer>
    <issuerCik>0000000001</issuerCik>
    <issuerName>Example Inc</issuerName>
    <issuerTradingSymbol>EXM</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>0000000002</rptOwnerCik>
      <rptOwnerName>Jane Insider</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>1</isDirector>
      <isOfficer>1</isOfficer>
      <officerTitle>CEO</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2024-01-03</value></transactionDate>
      <transactionCoding>
        <transactionFormType>4</transactionFormType>
        <transactionCode>P</transactionCode>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>1000</value></transactionShares>
        <transactionPricePerShare><value>25.50</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>5000</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
      <ownershipNature>
        <directOrIndirectOwnership><value>D</value></directOrIndirectOwnership>
      </ownershipNature>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
</XML>
</SEC-DOCUMENT>
"""


def test_parse_form_4_purchase_transaction() -> None:
    parsed = parse_ownership_filing(
        SAMPLE_FORM_4,
        accession_number="0000000001-24-000001",
        source_url="https://www.sec.gov/Archives/edgar/data/1/0000000001-24-000001.txt",
        fallback_form_type="4",
        fallback_filing_date=date(2024, 1, 4),
    )

    assert parsed.form_type == "4"
    assert parsed.issuer_trading_symbol == "EXM"
    assert parsed.primary_owner is not None
    assert parsed.primary_owner.name == "Jane Insider"
    assert parsed.primary_owner.role == "director,officer"

    transaction = parsed.transactions[0]
    assert transaction.transaction_code == "P"
    assert transaction.transaction_date == date(2024, 1, 3)
    assert transaction.shares == Decimal("1000")
    assert transaction.price == Decimal("25.50")
    assert transaction.value == Decimal("25500.00")
