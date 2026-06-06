"""Load internal team comp from CSV and compute bands by level/function/location."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

REQUIRED_COLUMNS = [
    "function",
    "title",
    "level",
    "location",
    "base_salary",
]

NUMERIC_COLUMNS = [
    "base_salary",
    "equity_units",
    "equity_pct",
    "equity_grant_value",
    "sign_on_bonus",
    "years_experience",
]

# Flexible column name aliases — maps canonical name to common variants.
_COLUMN_ALIASES = {
    "equity_grant_value": [
        "equity_grant_value", "equity_value", "equity_grant", "equity",
        "stock_grant_value", "stock_value", "option_value", "rsu_value",
        "equity_amount", "grant_value", "total_equity",
    ],
    "sign_on_bonus": [
        "sign_on_bonus", "signon_bonus", "sign_on", "signon",
        "signing_bonus", "signing", "sign_bonus",
    ],
    "equity_units": [
        "equity_units", "shares", "options", "rsus", "stock_units",
        "equity_shares", "option_count", "rsu_count",
    ],
    "equity_pct": [
        "equity_pct", "equity_percent", "equity_percentage",
        "ownership_pct", "ownership", "equity_ownership_pct",
        "equity_ownership",
    ],
    "base_salary": [
        "base_salary", "base", "salary", "base_pay", "annual_salary",
        "base_comp",
    ],
    "years_experience": [
        "years_experience", "yoe", "experience", "years_exp",
        "total_experience",
    ],
}

# Location normalization: map common location strings to metro buckets
# so "Fremont", "Palo Alto", "San Francisco" all roll up to "Bay Area".
_LOCATION_BUCKETS = {
    "fremont": "bay area",
    "palo alto": "bay area",
    "san francisco": "bay area",
    "san jose": "bay area",
    "sunnyvale": "bay area",
    "mountain view": "bay area",
    "oakland": "bay area",
    "redwood city": "bay area",
    "menlo park": "bay area",
    "cupertino": "bay area",
    "santa clara": "bay area",
    "san mateo": "bay area",
    "berkeley": "bay area",
    "san bruno": "bay area",
    "new york": "new york",
    "nyc": "new york",
    "brooklyn": "new york",
    "seattle": "seattle",
    "bellevue": "seattle",
    "boston": "boston",
    "cambridge": "boston",
    "austin": "austin",
    "los angeles": "los angeles",
    "remote": "remote us",
    "remote us": "remote us",
}


def _to_bucket(location: str) -> str:
    """Normalize a location string to a metro bucket."""
    loc = location.lower().strip()
    for key, bucket in _LOCATION_BUCKETS.items():
        if key in loc:
            return bucket
    return loc  # Unknown location — keep as-is


@dataclass
class Band:
    n: int
    base_p25: float
    base_median: float
    base_p75: float
    equity_grant_median: Optional[float]
    equity_pct_p25: Optional[float] = None
    equity_pct_median: Optional[float] = None
    equity_pct_p75: Optional[float] = None
    signon_median: Optional[float] = None
    label: str = ""  # description of what subset this band covers

    @property
    def has_data(self) -> bool:
        return self.n > 0

    @property
    def has_equity(self) -> bool:
        return (self.equity_grant_median is not None) or (self.equity_pct_median is not None)


def load_team_comp(file_or_buffer) -> pd.DataFrame:
    """Read a team comp CSV into a normalized DataFrame.

    Auto-detects common column name variants (e.g. "equity" → "equity_grant_value",
    "signing_bonus" → "sign_on_bonus") so users don't have to match exact names.

    Raises ValueError with a readable message if required columns are missing.
    """
    df = pd.read_csv(file_or_buffer)
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    # Rename recognized aliases to canonical names.
    rename_map = {}
    for canonical, aliases in _COLUMN_ALIASES.items():
        if canonical in df.columns:
            continue  # Already has the canonical name.
        for alias in aliases:
            if alias in df.columns:
                rename_map[alias] = canonical
                break
    if rename_map:
        df.rename(columns=rename_map, inplace=True)

    # Also try matching required columns by alias.
    for req in REQUIRED_COLUMNS:
        if req in df.columns:
            continue
        for canonical, aliases in _COLUMN_ALIASES.items():
            if canonical == req:
                for alias in aliases:
                    if alias in df.columns:
                        df.rename(columns={alias: req}, inplace=True)
                        break

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            "CSV is missing required column(s): "
            + ", ".join(missing)
            + ". Expected at least: "
            + ", ".join(REQUIRED_COLUMNS)
            + ". Your columns: "
            + ", ".join(df.columns.tolist())
        )

    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            # Strip currency symbols and commas before converting.
            if df[col].dtype == object:
                df[col] = df[col].astype(str).str.replace(r"[\$,]", "", regex=True)
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in ("function", "level", "location", "title"):
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    # Add a normalized location bucket column for geo-aware band computation.
    if "location" in df.columns:
        df["_location_bucket"] = df["location"].apply(_to_bucket)

    return df


def _compute_band_from_subset(subset: pd.DataFrame, label: str) -> Band:
    """Compute percentiles from a pre-filtered DataFrame subset."""
    if subset.empty:
        return Band(0, 0, 0, 0, None, label=label)

    base = subset["base_salary"].dropna()
    equity_val = (
        subset["equity_grant_value"].dropna()
        if "equity_grant_value" in subset
        else pd.Series(dtype=float)
    )
    equity_pct = (
        subset["equity_pct"].dropna()
        if "equity_pct" in subset
        else pd.Series(dtype=float)
    )
    signon = (
        subset["sign_on_bonus"].dropna()
        if "sign_on_bonus" in subset
        else pd.Series(dtype=float)
    )

    return Band(
        n=len(base),
        base_p25=float(base.quantile(0.25)) if len(base) else 0.0,
        base_median=float(base.median()) if len(base) else 0.0,
        base_p75=float(base.quantile(0.75)) if len(base) else 0.0,
        equity_grant_median=float(equity_val.median()) if len(equity_val) else None,
        equity_pct_p25=float(equity_pct.quantile(0.25)) if len(equity_pct) else None,
        equity_pct_median=float(equity_pct.median()) if len(equity_pct) else None,
        equity_pct_p75=float(equity_pct.quantile(0.75)) if len(equity_pct) else None,
        signon_median=float(signon.median()) if len(signon) else None,
        label=label,
    )


def compute_band(
    df: pd.DataFrame,
    level: str,
    function: Optional[str] = None,
    location: Optional[str] = None,
) -> Band:
    """Compute an internal band with progressive filtering.

    Priority order (most specific → broadest):
      1. level + function + location bucket  (ideal: same role, same geo)
      2. level + location bucket             (same level, same geo)
      3. level + function                    (same role, all locations)
      4. level only                          (broadest fallback)

    We pick the most specific subset that has >= 3 data points. If none
    meet that threshold, we use the broadest available.
    """
    # Flexible level matching: "L3" matches "L3", "3", "IC3", "l3", "Mid/L3", etc.
    level_up = level.upper()
    level_num = level_up.replace("L", "")  # "L3" -> "3"
    by_level = df[
        df["level"].str.upper().str.strip().apply(
            lambda x: x == level_up            # exact: "L3"
            or x == level_num                   # bare number: "3"
            or x == f"IC{level_num}"            # IC ladder: "IC3"
            or x == f"E{level_num}"             # E ladder: "E3"
            or x.startswith(f"{level_up}/")     # compound: "L3/M1"
            or x.endswith(f"/{level_up}")        # compound: "Mid/L3"
        )
    ]

    # Build candidate subsets from most specific to broadest.
    candidates: list[tuple[pd.DataFrame, str]] = []

    loc_bucket = _to_bucket(location) if location else None

    if function and loc_bucket and "_location_bucket" in df.columns:
        subset = by_level[
            (by_level["function"].str.lower() == function.lower())
            & (by_level["_location_bucket"] == loc_bucket)
        ]
        candidates.append((subset, f"{level}/{function}/{loc_bucket}"))

    if loc_bucket and "_location_bucket" in df.columns:
        subset = by_level[by_level["_location_bucket"] == loc_bucket]
        candidates.append((subset, f"{level}/{loc_bucket}"))

    if function:
        subset = by_level[by_level["function"].str.lower() == function.lower()]
        candidates.append((subset, f"{level}/{function}"))

    candidates.append((by_level, f"{level}"))

    # Pick the most specific with enough data (>= 3), or fall back to broadest.
    MIN_DATA_POINTS = 3
    for subset, label in candidates:
        if len(subset) >= MIN_DATA_POINTS:
            return _compute_band_from_subset(subset, label)

    # Nothing hit the minimum — use whatever we have.
    for subset, label in candidates:
        if not subset.empty:
            return _compute_band_from_subset(subset, label)

    return Band(0, 0, 0, 0, None, None, label=level)
