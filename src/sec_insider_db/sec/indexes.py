from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import PurePosixPath
from typing import Iterable, Iterator

from sec_insider_db.sec.client import SecClient

OWNERSHIP_FORMS = frozenset({"3", "4", "5", "3/A", "4/A", "5/A"})


@dataclass(frozen=True)
class IndexEntry:
    cik: str
    company_name: str
    form_type: str
    filing_date: date
    filename: str

    @property
    def accession_number(self) -> str:
        return PurePosixPath(self.filename).name.removesuffix(".txt")

    @property
    def source_url(self) -> str:
        return f"{SecClient.archives_base_url}/{self.filename}"


def quarter_for_date(value: date) -> int:
    return ((value.month - 1) // 3) + 1


def iter_quarters(start_year: int, end: date | None = None) -> Iterator[tuple[int, int]]:
    end_date = end or date.today()
    end_quarter = quarter_for_date(end_date)
    for year in range(start_year, end_date.year + 1):
        first_quarter = 1
        last_quarter = 4
        if year == end_date.year:
            last_quarter = end_quarter
        for quarter in range(first_quarter, last_quarter + 1):
            yield year, quarter


def master_index_url(year: int, quarter: int) -> str:
    return f"{SecClient.archives_base_url}/edgar/full-index/{year}/QTR{quarter}/master.idx"


def daily_index_directory_url(year: int, quarter: int) -> str:
    return f"{SecClient.archives_base_url}/edgar/daily-index/{year}/QTR{quarter}/index.json"


def daily_index_url(day: date) -> str:
    quarter = quarter_for_date(day)
    return f"{SecClient.archives_base_url}/edgar/daily-index/{day.year}/QTR{quarter}/master.{day:%Y%m%d}.idx"


def parse_master_index(text: str, forms: Iterable[str] = OWNERSHIP_FORMS) -> Iterator[IndexEntry]:
    accepted_forms = set(forms)
    in_records = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not in_records:
            if line.startswith("-----"):
                in_records = True
            continue
        if not line or "|" not in line:
            continue
        parts = line.split("|")
        if len(parts) != 5:
            continue
        cik, company_name, form_type, filing_date_text, filename = (part.strip() for part in parts)
        if form_type not in accepted_forms:
            continue
        yield IndexEntry(
            cik=cik,
            company_name=company_name,
            form_type=form_type,
            filing_date=date.fromisoformat(filing_date_text),
            filename=filename,
        )


def iter_daily_index_urls(client: SecClient, start: date, end: date) -> Iterator[str]:
    seen: set[str] = set()
    for year, quarter in iter_quarters(start.year, end):
        quarter_start_month = ((quarter - 1) * 3) + 1
        quarter_start = date(year, quarter_start_month, 1)
        if quarter == 4:
            quarter_end = date(year, 12, 31)
        else:
            quarter_end = date(year, quarter_start_month + 3, 1) - timedelta(days=1)
        window_start = max(start, quarter_start)
        window_end = min(end, quarter_end)
        if window_start > window_end:
            continue

        try:
            directory = client.get_json(daily_index_directory_url(year, quarter))
            items = directory.get("directory", {}).get("item", [])
            names = sorted(item.get("name", "") for item in items)
            for name in names:
                if not name.startswith("master.") or not name.endswith(".idx"):
                    continue
                date_text = name.removeprefix("master.").removesuffix(".idx")
                try:
                    index_day = date.fromisoformat(f"{date_text[:4]}-{date_text[4:6]}-{date_text[6:8]}")
                except ValueError:
                    continue
                if window_start <= index_day <= window_end:
                    url = f"{SecClient.archives_base_url}/edgar/daily-index/{year}/QTR{quarter}/{name}"
                    if url not in seen:
                        seen.add(url)
                        yield url
        except Exception:
            day = window_start
            while day <= window_end:
                if day.weekday() < 5:
                    url = daily_index_url(day)
                    if url not in seen:
                        seen.add(url)
                        yield url
                day += timedelta(days=1)
