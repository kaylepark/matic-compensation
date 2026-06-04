"""Load internal team comp from CSV and compute bands by level/function."""
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


@dataclass
class Band:
    n: int
    base_p25: float
    base_median: float
    base_p75: float
    equity_grant_median: Optional[float]
    signon_median: Optional[float]

    @property
    def has_data(self) -> bool:
        return self.n > 0


def load_team_comp(file_or_buffer) -> pd.DataFrame:
    """Read a team comp CSV into a normalized DataFrame.

    Raises ValueError with a readable message if required columns are missing.
    """
    df = pd.read_csv(file_or_buffer)
    df.columns = [c.strip().lower() for c in df.columns]

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            "CSV is missing required column(s): "
            + ", ".join(missing)
            + ". Expected at least: "
            + ", ".join(REQUIRED_COLUMNS)
        )

    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in ("function", "level", "location", "title"):
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    return df


def compute_band(
    df: pd.DataFrame,
    level: str,
    function: Optional[str] = None,
) -> Band:
    """Compute an internal band, preferring level+function, then level alone."""
    subset = df[df["level"].str.upper() == level.upper()]
    if function:
        fn_subset = subset[subset["function"].str.lower() == function.lower()]
        if len(fn_subset) >= 2:
            subset = fn_subset

    if subset.empty:
        return Band(0, 0, 0, 0, None, None)

    base = subset["base_salary"].dropna()
    equity = (
        subset["equity_grant_value"].dropna()
        if "equity_grant_value" in subset
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
        equity_grant_median=float(equity.median()) if len(equity) else None,
        signon_median=float(signon.median()) if len(signon) else None,
    )
