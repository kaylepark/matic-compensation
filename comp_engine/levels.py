"""Leveling framework and title/experience normalization.

Levels are a generic IC + management ladder. Equity and sign-on figures are
heuristics for a Series A consumer-robotics company, NOT market reads -- they
should be sanity-checked against the live internal band whenever data exists.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Level:
    code: str
    name: str
    yoe_min: int
    yoe_max: int
    # Heuristic equity as % of fully-diluted company ownership for a NEW hire
    # at a Series A stage. Wide ranges on purpose.
    equity_pct_low: float
    equity_pct_high: float
    # Sign-on typically expressed as % of base; used only as a starting point.
    signon_pct_of_base: float


# Generic ladder. yoe ranges overlap intentionally; title signal breaks ties.
LEVELS = [
    Level("L2", "Junior / Entry", 0, 2, 0.02, 0.05, 0.0),
    Level("L3", "Mid", 2, 5, 0.04, 0.10, 0.05),
    Level("L4", "Senior", 5, 9, 0.08, 0.20, 0.07),
    Level("L5", "Staff", 8, 13, 0.15, 0.35, 0.10),
    Level("L6", "Principal", 12, 18, 0.25, 0.60, 0.12),
    Level("L7", "Director / Senior Staff+", 15, 99, 0.40, 1.00, 0.15),
]

LEVELS_BY_CODE = {lv.code: lv for lv in LEVELS}

FUNCTIONS = [
    "Engineering",
    "Software",
    "ML",
    "Hardware",
    "Robotics",
    "Design",
    "Product",
    "Operations",
    "GTM",
    "G&A",
]

# Title keywords -> level code. Checked longest/most-senior first.
_TITLE_SIGNALS = [
    ("director", "L7"),
    ("vp", "L7"),
    ("head of", "L7"),
    ("principal", "L6"),
    ("distinguished", "L6"),
    ("staff", "L5"),
    ("lead", "L5"),
    ("senior", "L4"),
    ("sr.", "L4"),
    ("sr ", "L4"),
    ("ii", "L4"),
    ("manager", "L4"),
    ("junior", "L2"),
    ("jr.", "L2"),
    ("associate", "L2"),
    ("intern", "L2"),
]

_FUNCTION_SIGNALS = [
    ("machine learning", "ML"),
    (" ml ", "ML"),
    ("ml ", "ML"),
    ("perception", "ML"),
    ("computer vision", "ML"),
    ("autonomy", "Robotics"),
    ("robotics", "Robotics"),
    ("controls", "Robotics"),
    ("mechanical", "Hardware"),
    ("electrical", "Hardware"),
    ("firmware", "Hardware"),
    ("hardware", "Hardware"),
    ("embedded", "Hardware"),
    ("software", "Software"),
    ("backend", "Software"),
    ("frontend", "Software"),
    ("full stack", "Software"),
    ("fullstack", "Software"),
    ("engineer", "Engineering"),
    ("design", "Design"),
    ("product manager", "Product"),
    ("operations", "Operations"),
    ("recruit", "G&A"),
    ("finance", "G&A"),
    ("people", "G&A"),
    ("sales", "GTM"),
    ("marketing", "GTM"),
]


def infer_function(title: str) -> str:
    t = f" {title.lower()} "
    for kw, fn in _FUNCTION_SIGNALS:
        if kw in t:
            return fn
    return "Engineering"


def infer_level(title: str, years_experience: float) -> tuple[str, str]:
    """Return (level_code, rationale). Title signal wins; YOE is the fallback."""
    t = f" {title.lower()} "
    for kw, code in _TITLE_SIGNALS:
        if kw in t:
            return code, f"title contains '{kw.strip()}'"

    for lv in LEVELS:
        if lv.yoe_min <= years_experience <= lv.yoe_max:
            return lv.code, f"{years_experience} yrs experience maps to {lv.code}"
    return "L4", "defaulted to Senior (no strong title or YOE signal)"
