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


LEGACY_FORM_4 = """
<SEC-DOCUMENT>
<SEC-HEADER>
ACCESSION NUMBER:        0000874015-03-000008
CONFORMED SUBMISSION TYPE:    4
CONFORMED PERIOD OF REPORT:   20030102
REPORTING-OWNER:
    COMPANY DATA:
        COMPANY CONFORMED NAME:         LEVIN ARTHUR A
        CENTRAL INDEX KEY:              0001181556
        RELATIONSHIP:                   OFFICER
SUBJECT COMPANY:
    COMPANY DATA:
        COMPANY CONFORMED NAME:         ISIS PHARMACEUTICALS INC
        CENTRAL INDEX KEY:              0000874015
</SEC-HEADER>
<DOCUMENT>
<TYPE>4
<TEXT>
<HTML><BODY>
<table><tr><td>1. Name and Address of Reporting Person*</td><td>2. Issuer Name <b>and</b> Ticker or Trading Symbol<br><B>Isis Pharmaceuticals, Inc. (ISIS)</B></td><td>6. Relationship of Reporting Person(s)<br><b><U><B>X</B></U></b> Officer (give title below)<br><U><B>Vice President</B></U></td></tr></table>
<table><tr><td><b>Table I - Non-Derivative Securities Acquired, Disposed of, or Beneficially Owned</b></td></tr></table>
<table>
<tr><td>Title</td><td>Transaction Date</td><td>Deemed</td><td>Code</td><td>V</td><td>Amount</td><td>A/D</td><td>Price</td><td>Owned</td><td>D/I</td><td>Nature</td></tr>
<tr><td><B>Common Stock</B></td><td><B>1/1/03</B></td><td><B>1/2/03</B></td><td><B>J</B></td><td><B>V</B></td><td><B>352</B><Sup>(1)</Sup></td><td><B>A</B></td><td><B>$5.6015</B></td><td><B>530</B></td><td><B>D</B></td><td>&nbsp;</td></tr>
</table>
<table><tr><td><b>Table II - Derivative Securities Acquired, Disposed of, or Beneficially Owned</b></td></tr></table>
</BODY></HTML>
</TEXT>
</DOCUMENT>
</SEC-DOCUMENT>
"""


def test_parse_legacy_html_form_4_transaction() -> None:
    parsed = parse_ownership_filing(
        LEGACY_FORM_4,
        accession_number="0000874015-03-000008",
        source_url="https://www.sec.gov/Archives/edgar/data/874015/0000874015-03-000008.txt",
        fallback_form_type="4",
        fallback_filing_date=date(2003, 1, 3),
    )

    assert parsed.form_type == "4"
    assert parsed.period_of_report == date(2003, 1, 2)
    assert parsed.issuer_cik == "0000874015"
    assert parsed.issuer_name == "Isis Pharmaceuticals, Inc."
    assert parsed.issuer_trading_symbol == "ISIS"
    assert parsed.primary_owner is not None
    assert parsed.primary_owner.cik == "0001181556"
    assert parsed.primary_owner.is_officer is True
    assert parsed.primary_owner.officer_title == "Vice President"

    transaction = parsed.transactions[0]
    assert transaction.security_title == "Common Stock"
    assert transaction.transaction_date == date(2003, 1, 1)
    assert transaction.transaction_code == "J"
    assert transaction.acquired_disposed_code == "A"
    assert transaction.shares == Decimal("352")
    assert transaction.price == Decimal("5.6015")
    assert transaction.value == Decimal("1971.73")
    assert transaction.direct_or_indirect_ownership == "D"
