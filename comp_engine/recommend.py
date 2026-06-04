"""Combine leveling, internal bands, live market signal, and heuristics
into a base/equity/sign-on recommendation with explicit reasoning."""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from .internal import Band, compute_band
from .levels import LEVELS_BY_CODE, infer_function, infer_level
from .market import MarketResult

# Location multipliers vs. a US national baseline. Rough, editable.
LOCATION_MULTIPLIERS = {
    "san francisco": 1.15,
    "bay area": 1.15,
    "new york": 1.12,
    "seattle": 1.08,
    "boston": 1.05,
    "los angeles": 1.05,
    "austin": 1.0,
    "remote us": 0.95,
    "remote": 0.95,
}

# Labeled heuristic base anchors (USD, national midpoint) used ONLY when there
# is no internal and no market data. Deliberately conservative placeholders.
_HEURISTIC_BASE = {
    "L2": 120_000,
    "L3": 150_000,
    "L4": 185_000,
    "L5": 225_000,
    "L6": 270_000,
    "L7": 320_000,
}


@dataclass
class Recommendation:
    level_code: str
    level_name: str
    function: str
    location: str
    base_low: int
    base_target: int
    base_high: int
    equity_pct_low: float
    equity_pct_high: float
    equity_grant_value: Optional[int]
    signon_target: int
    confidence: str
    reasoning: list[str] = field(default_factory=list)
    market_n: int = 0
    internal_n: int = 0


def _location_multiplier(location: str) -> float:
    loc = (location or "").lower()
    for key, mult in LOCATION_MULTIPLIERS.items():
        if key in loc:
            return mult
    return 1.0


def _round_k(x: float) -> int:
    return int(round(x / 1000.0) * 1000)


def recommend(
    title: str,
    years_experience: float,
    location: str,
    function: Optional[str] = None,
    team_df: Optional[pd.DataFrame] = None,
    market: Optional[MarketResult] = None,
    level_override: Optional[str] = None,
) -> Recommendation:
    fn = function or infer_function(title)
    if level_override:
        level_code, lvl_reason = level_override, "level set manually"
    else:
        level_code, lvl_reason = infer_level(title, years_experience)
    lvl = LEVELS_BY_CODE[level_code]
    reasoning = [f"Leveled as {level_code} ({lvl.name}) — {lvl_reason}."]

    # --- Internal band ---
    band: Optional[Band] = None
    if team_df is not None and not team_df.empty:
        band = compute_band(team_df, level_code, fn)
        if band.has_data:
            reasoning.append(
                f"Internal band from {band.n} current teammate(s) at {level_code}"
                + (f"/{fn}" if fn else "")
                + f": base p25 ${_round_k(band.base_p25):,} / median "
                f"${_round_k(band.base_median):,} / p75 ${_round_k(band.base_p75):,}."
            )
        else:
            reasoning.append(f"No internal teammates found at {level_code} — skipping internal anchor.")

    # --- Market signal ---
    market_mid: Optional[float] = None
    market_n = 0
    if market is not None:
        sal = market.with_salary
        market_n = len(sal)
        if sal:
            mids = [statistics.mean([p.salary_low, p.salary_high]) for p in sal]
            market_mid = statistics.median(mids)
            reasoning.append(
                f"Live market: {market_n} peer posting(s) with disclosed ranges; "
                f"median midpoint ${_round_k(market_mid):,}."
            )
        elif market.postings:
            reasoning.append(
                f"Found {len(market.postings)} matching peer posting(s) but none "
                "disclosed a salary range."
            )

    # --- Blend base target ---
    mult = _location_multiplier(location)
    sources: list[tuple[float, float]] = []  # (value, weight)
    if band and band.has_data:
        sources.append((band.base_median, 0.5))
    if market_mid:
        sources.append((market_mid, 0.4))
    if not sources:
        anchor = _HEURISTIC_BASE[level_code] * mult
        sources.append((anchor, 1.0))
        reasoning.append(
            f"No internal or market data — using a labeled heuristic anchor "
            f"(${_round_k(_HEURISTIC_BASE[level_code]):,} national × {mult:.2f} location)."
        )

    total_w = sum(w for _, w in sources)
    base_target = sum(v * w for v, w in sources) / total_w

    # Band width: use internal p25/p75 spread if available, else ±12%.
    if band and band.has_data and band.base_p75 > band.base_p25:
        base_low = min(base_target * 0.92, band.base_p25)
        base_high = max(base_target * 1.08, band.base_p75)
    else:
        base_low = base_target * 0.90
        base_high = base_target * 1.10

    # --- Equity (heuristic % ownership; internal grant value if we have it) ---
    equity_grant_value = band.equity_grant_median if (band and band.equity_grant_median) else None
    if equity_grant_value:
        reasoning.append(
            f"Equity anchored on internal median grant value ${_round_k(equity_grant_value):,} "
            f"for {level_code}."
        )
    else:
        reasoning.append(
            f"No internal equity data — showing heuristic ownership range "
            f"{lvl.equity_pct_low:.2f}%–{lvl.equity_pct_high:.2f}% for a Series A {level_code}. "
            "Convert to shares using your latest 409A / preferred price."
        )

    # --- Sign-on ---
    if band and band.signon_median:
        signon_target = band.signon_median
        reasoning.append(f"Sign-on from internal median ${_round_k(signon_target):,} at {level_code}.")
    else:
        signon_target = base_target * lvl.signon_pct_of_base
        reasoning.append(
            f"No internal sign-on data — heuristic {int(lvl.signon_pct_of_base*100)}% of base."
        )

    # --- Confidence ---
    if (band and band.has_data) and market_n:
        confidence = "High (internal + live market)"
    elif (band and band.has_data) or market_n:
        confidence = "Medium (one real data source)"
    else:
        confidence = "Low (heuristic only — add team CSV / market data)"

    return Recommendation(
        level_code=level_code,
        level_name=lvl.name,
        function=fn,
        location=location,
        base_low=_round_k(base_low),
        base_target=_round_k(base_target),
        base_high=_round_k(base_high),
        equity_pct_low=lvl.equity_pct_low,
        equity_pct_high=lvl.equity_pct_high,
        equity_grant_value=_round_k(equity_grant_value) if equity_grant_value else None,
        signon_target=_round_k(signon_target),
        confidence=confidence,
        reasoning=reasoning,
        market_n=market_n,
        internal_n=(band.n if band else 0),
    )
