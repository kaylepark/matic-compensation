"""Combine leveling, internal bands, live market signal, BLS wage floor,
H1B/LCA data, and heuristics into a base/equity/sign-on recommendation
with explicit reasoning."""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from .bls import BlsWage, lookup_bls
from .h1b import H1bResult
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
    # Internal equity % (from team CSV) — overrides heuristic pct_low/pct_high when set.
    internal_equity_pct_p25: Optional[float] = None
    internal_equity_pct_median: Optional[float] = None
    internal_equity_pct_p75: Optional[float] = None
    reasoning: list[str] = field(default_factory=list)
    market_n: int = 0
    internal_n: int = 0
    bls_floor: Optional[int] = None
    h1b_n: int = 0
    h1b_median: Optional[int] = None


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
    h1b: Optional[H1bResult] = None,
    level_override: Optional[str] = None,
) -> Recommendation:
    fn = function or infer_function(title)
    if level_override:
        level_code, lvl_reason = level_override, "level set manually"
    else:
        level_code, lvl_reason = infer_level(title, years_experience)
    lvl = LEVELS_BY_CODE[level_code]
    reasoning = [f"Leveled as {level_code} ({lvl.name}) — {lvl_reason}."]

    # --- Internal band (location-aware) ---
    band: Optional[Band] = None
    if team_df is not None and not team_df.empty:
        band = compute_band(team_df, level_code, fn, location)
        if band.has_data:
            reasoning.append(
                f"Internal band from {band.n} current teammate(s) "
                f"matching [{band.label}]: "
                f"base p25 ${_round_k(band.base_p25):,} / median "
                f"${_round_k(band.base_median):,} / p75 ${_round_k(band.base_p75):,}."
            )
        else:
            reasoning.append(f"No internal teammates found at {level_code} — skipping internal anchor.")

    # --- Live market signal ---
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

    # --- H1B / LCA signal ---
    h1b_median: Optional[int] = None
    h1b_n = 0
    if h1b is not None and not h1b.error:
        h1b_n = h1b.n_total
        h1b_median = h1b.median_wage
        if h1b_median:
            reasoning.append(
                f"H1B/LCA data: {h1b_n} matching filing(s); "
                f"median offered wage ${_round_k(h1b_median):,} "
                f"(p25 ${_round_k(h1b.p25_wage):,} / p75 ${_round_k(h1b.p75_wage):,})."
            )
        elif h1b_n:
            reasoning.append(f"H1B/LCA: {h1b_n} filings matched but wage data unavailable.")

    # --- BLS wage floor ---
    bls: Optional[BlsWage] = lookup_bls(fn, location)
    bls_floor: Optional[int] = None
    if bls:
        bls_floor = bls.median
        reasoning.append(
            f"BLS OEWS floor ({bls.soc_title}, {bls.metro}): "
            f"median ${bls.median:,}, p75 ${bls.p75:,}, p90 ${bls.p90:,}."
        )

    # --- Blend base target ---
    mult = _location_multiplier(location)
    sources: list[tuple[float, float]] = []  # (value, weight)
    if band and band.has_data:
        sources.append((band.base_median, 0.45))
    if market_mid:
        sources.append((market_mid, 0.30))
    if h1b_median:
        sources.append((h1b_median, 0.15))
    if bls and bls.p75:
        # Use BLS p75 (not median) as the anchor — we're hiring senior tech talent,
        # which skews above the occupation median.
        sources.append((float(bls.p75), 0.10))

    if not sources:
        anchor = _HEURISTIC_BASE[level_code] * mult
        sources.append((anchor, 1.0))
        reasoning.append(
            f"No real data sources available — using a labeled heuristic anchor "
            f"(${_round_k(_HEURISTIC_BASE[level_code]):,} national × {mult:.2f} location)."
        )

    total_w = sum(w for _, w in sources)
    base_target = sum(v * w for v, w in sources) / total_w

    # Enforce BLS floor: if our blend falls below BLS median, flag it.
    if bls_floor and base_target < bls_floor:
        reasoning.append(
            f"Warning: blended target ${_round_k(base_target):,} is below BLS median "
            f"${bls_floor:,} — raised to BLS median as floor."
        )
        base_target = float(bls_floor)

    # Band width: use internal p25/p75 spread if available, else ±10%.
    if band and band.has_data and band.base_p75 > band.base_p25:
        base_low = min(base_target * 0.92, band.base_p25)
        base_high = max(base_target * 1.08, band.base_p75)
    else:
        base_low = base_target * 0.90
        base_high = base_target * 1.10

    # --- Equity ---
    # Prefer internal data: grant value (dollars) or ownership % from the team CSV.
    # Fall back to heuristic ranges only if neither exists.
    equity_grant_value = band.equity_grant_median if (band and band.equity_grant_median) else None
    if equity_grant_value:
        reasoning.append(
            f"Equity anchored on internal median grant value ${_round_k(equity_grant_value):,} "
            f"for [{band.label}]."
        )
    elif band and band.equity_pct_median is not None:
        # Use internal ownership % data from the team CSV.
        reasoning.append(
            f"Equity from internal team data [{band.label}]: "
            f"p25 {band.equity_pct_p25:.3f}% / median {band.equity_pct_median:.3f}% / "
            f"p75 {band.equity_pct_p75:.3f}%."
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
    real_sources = sum([
        bool(band and band.has_data),
        bool(market_n),
        bool(h1b_median),
        bool(bls),
    ])
    if real_sources >= 3:
        confidence = "High (multiple corroborating sources)"
    elif real_sources == 2:
        confidence = "Medium-High (two real data sources)"
    elif real_sources == 1:
        confidence = "Medium (one real data source)"
    else:
        confidence = "Low (heuristic only — add team CSV / enable market data)"

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
        internal_equity_pct_p25=band.equity_pct_p25 if band else None,
        internal_equity_pct_median=band.equity_pct_median if band else None,
        internal_equity_pct_p75=band.equity_pct_p75 if band else None,
        signon_target=_round_k(signon_target),
        confidence=confidence,
        reasoning=reasoning,
        market_n=market_n,
        internal_n=(band.n if band else 0),
        bls_floor=bls_floor,
        h1b_n=h1b_n,
        h1b_median=_round_k(h1b_median) if h1b_median else None,
    )
