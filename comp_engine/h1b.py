"""H1B / LCA salary lookup from DOL OFLC disclosure data.

The Department of Labor publishes Labor Condition Application (LCA) disclosure
files quarterly. These contain employer + job title + worksite + prevailing
wage + offered wage for every H1B petition. Excellent free signal for base
salary at specific companies.

The file is large (~200MB Excel), so we:
  1. Download once and cache locally as a Parquet file (~20-30MB).
  2. Filter to tech/eng roles on load to keep memory reasonable.
  3. Query by employer name, title keywords, and worksite state/metro.

First run takes 1-2 minutes to download+convert. After that, queries are
instant from the local cache.

Data source: https://www.dol.gov/agencies/eta/foreign-labor/performance
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / ".h1b_cache"

# The DOL OFLC LCA disclosure file URL. Update when new fiscal year is released.
# FY2024 Q4 (most recent as of mid-2025):
LCA_URL = (
    "https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/"
    "LCA_Disclosure_Data_FY2024_Q4.xlsx"
)
LCA_PARQUET = CACHE_DIR / "lca_tech.parquet"

# Columns we keep from the raw Excel file.
_KEEP_COLS = [
    "EMPLOYER_NAME",
    "JOB_TITLE",
    "WORKSITE_CITY",
    "WORKSITE_STATE",
    "WAGE_RATE_OF_PAY_FROM",
    "WAGE_RATE_OF_PAY_TO",
    "WAGE_UNIT_OF_PAY",
    "SOC_CODE",
    "SOC_TITLE",
    "CASE_STATUS",
]

# SOC code prefixes to keep (15-xxxx = computer/math, 17-xxxx = engineering).
_SOC_PREFIXES = ("15-", "17-", "11-9041")

# Fallback column-name variants (DOL changes names between years).
_COL_ALIASES = {
    "EMPLOYER_NAME": ["EMPLOYER_NAME", "EMPLOYER_BUSINESS_NAME"],
    "WAGE_RATE_OF_PAY_FROM": ["WAGE_RATE_OF_PAY_FROM", "WAGE_RATE_OF_PAY_FROM_1"],
    "WAGE_RATE_OF_PAY_TO": ["WAGE_RATE_OF_PAY_TO", "WAGE_RATE_OF_PAY_TO_1"],
    "WORKSITE_CITY": ["WORKSITE_CITY", "WORKSITE_CITY_1"],
    "WORKSITE_STATE": ["WORKSITE_STATE", "WORKSITE_STATE_1"],
}


@dataclass
class H1bRecord:
    employer: str
    title: str
    city: str
    state: str
    wage_low: int
    wage_high: Optional[int]


@dataclass
class H1bResult:
    records: list[H1bRecord] = field(default_factory=list)
    n_total: int = 0
    cached: bool = False
    error: Optional[str] = None

    @property
    def median_wage(self) -> Optional[int]:
        wages = [r.wage_low for r in self.records if r.wage_low]
        if not wages:
            return None
        wages.sort()
        mid = len(wages) // 2
        return wages[mid] if len(wages) % 2 else (wages[mid - 1] + wages[mid]) // 2

    @property
    def p25_wage(self) -> Optional[int]:
        wages = sorted(r.wage_low for r in self.records if r.wage_low)
        if not wages:
            return None
        return wages[max(0, len(wages) // 4)]

    @property
    def p75_wage(self) -> Optional[int]:
        wages = sorted(r.wage_low for r in self.records if r.wage_low)
        if not wages:
            return None
        return wages[min(len(wages) - 1, 3 * len(wages) // 4)]


def _resolve_col(df: pd.DataFrame, canonical: str) -> Optional[str]:
    """Find the actual column name in the DataFrame, trying aliases."""
    if canonical in df.columns:
        return canonical
    for alias in _COL_ALIASES.get(canonical, []):
        if alias in df.columns:
            return alias
    return None


def _download_and_cache() -> pd.DataFrame:
    """Download the LCA disclosure Excel, filter to tech roles, cache as Parquet."""
    import requests

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    r = requests.get(LCA_URL, timeout=120, stream=True)
    r.raise_for_status()

    xlsx_path = CACHE_DIR / "lca_raw.xlsx"
    with open(xlsx_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=1 << 20):
            f.write(chunk)

    df = pd.read_excel(xlsx_path, dtype=str)

    # Normalize column names
    col_map = {}
    for canonical in _KEEP_COLS:
        actual = _resolve_col(df, canonical)
        if actual and actual != canonical:
            col_map[actual] = canonical
    if col_map:
        df.rename(columns=col_map, inplace=True)

    # Filter to certified cases with tech SOC codes.
    if "CASE_STATUS" in df.columns:
        df = df[df["CASE_STATUS"].str.upper().str.contains("CERTIFIED", na=False)]
    if "SOC_CODE" in df.columns:
        df = df[df["SOC_CODE"].str.startswith(tuple(_SOC_PREFIXES), na=False)]

    # Keep only needed columns that exist.
    keep = [c for c in _KEEP_COLS if c in df.columns]
    df = df[keep].copy()

    # Convert wages to numeric.
    for wc in ("WAGE_RATE_OF_PAY_FROM", "WAGE_RATE_OF_PAY_TO"):
        if wc in df.columns:
            df[wc] = pd.to_numeric(df[wc].str.replace(",", "", regex=False), errors="coerce")

    # Normalize hourly→annual.
    if "WAGE_UNIT_OF_PAY" in df.columns:
        hourly = df["WAGE_UNIT_OF_PAY"].str.upper().str.contains("HOUR", na=False)
        for wc in ("WAGE_RATE_OF_PAY_FROM", "WAGE_RATE_OF_PAY_TO"):
            if wc in df.columns:
                df.loc[hourly, wc] = df.loc[hourly, wc] * 2080

    df.to_parquet(LCA_PARQUET, index=False)

    # Clean up raw xlsx to save disk.
    try:
        xlsx_path.unlink()
    except OSError:
        pass

    return df


def _load_cache() -> pd.DataFrame:
    if LCA_PARQUET.exists():
        return pd.read_parquet(LCA_PARQUET)
    return _download_and_cache()


def query_h1b(
    title_keywords: list[str],
    location: Optional[str] = None,
    employer_keywords: Optional[list[str]] = None,
    max_results: int = 200,
) -> H1bResult:
    """Search cached LCA data for matching records."""
    try:
        df = _load_cache()
    except Exception as e:
        return H1bResult(error=f"Failed to load H1B data: {e}")

    mask = pd.Series(True, index=df.index)

    # Title filter
    if title_keywords and "JOB_TITLE" in df.columns:
        # Clean title keywords: strip level suffixes (I, II, III, IV, Sr., etc.)
        # so "Mechanical Engineer II" matches "Mechanical Engineer" filings too.
        cleaned = []
        for kw in title_keywords:
            clean = re.sub(
                r"\s+(?:I{1,3}|IV|V|VI|Sr\.?|Jr\.?|Senior|Junior|Lead|Staff|Principal|\d+)\s*$",
                "", kw, flags=re.IGNORECASE,
            ).strip()
            if clean:
                cleaned.append(clean)
        pattern = "|".join(re.escape(kw) for kw in cleaned)
        mask &= df["JOB_TITLE"].str.contains(pattern, case=False, na=False)

    # Location filter
    if location:
        loc = location.lower()
        loc_mask = pd.Series(False, index=df.index)
        if "WORKSITE_STATE" in df.columns:
            loc_mask |= df["WORKSITE_STATE"].str.lower().str.contains(
                loc.split()[-1] if len(loc.split()) > 1 else loc, na=False
            )
        if "WORKSITE_CITY" in df.columns:
            loc_mask |= df["WORKSITE_CITY"].str.lower().str.contains(
                loc.split()[0], na=False
            )
        mask &= loc_mask

    # Employer filter
    if employer_keywords and "EMPLOYER_NAME" in df.columns:
        emp_pattern = "|".join(re.escape(kw) for kw in employer_keywords)
        mask &= df["EMPLOYER_NAME"].str.contains(emp_pattern, case=False, na=False)

    matched = df[mask].copy()

    # Filter to plausible annual wages.
    if "WAGE_RATE_OF_PAY_FROM" in matched.columns:
        matched = matched[
            (matched["WAGE_RATE_OF_PAY_FROM"] >= 40_000)
            & (matched["WAGE_RATE_OF_PAY_FROM"] <= 1_000_000)
        ]

    n_total = len(matched)
    matched = matched.head(max_results)

    records = []
    for _, row in matched.iterrows():
        wage_from = row.get("WAGE_RATE_OF_PAY_FROM", 0)
        wage_to = row.get("WAGE_RATE_OF_PAY_TO", 0)
        records.append(
            H1bRecord(
                employer=str(row.get("EMPLOYER_NAME", "")),
                title=str(row.get("JOB_TITLE", "")),
                city=str(row.get("WORKSITE_CITY", "")),
                state=str(row.get("WORKSITE_STATE", "")),
                wage_low=int(wage_from) if pd.notna(wage_from) else 0,
                wage_high=int(wage_to) if pd.notna(wage_to) else None,
            )
        )

    return H1bResult(records=records, n_total=n_total, cached=LCA_PARQUET.exists())
