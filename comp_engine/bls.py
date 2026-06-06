"""BLS Occupational Employment & Wage Statistics (OEWS) lookup.

Provides a government-data sanity floor for base salary by metro area and
occupation. Data is from the May 2023 OEWS release (latest stable at time of
writing). Only covers the SOC codes and metro areas most relevant to a
consumer-robotics / ML / hardware company.

This is a bundled static table — not a live API call — because the BLS public
API requires registration and the OEWS flat files are enormous. The tradeoff:
this data lags ~18 months but it's reliable, free, and instant.

To update: download the latest allMSA_M<year>_dl.xlsx from
  https://www.bls.gov/oes/current/oessrcma.htm
and refresh the _DATA dict below for your SOC codes + metros.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class BlsWage:
    soc_code: str
    soc_title: str
    metro: str
    p10: int
    p25: int
    median: int
    p75: int
    p90: int
    annual_mean: int


# SOC codes relevant to robotics / ML / hardware / software companies.
# Wages are annual, from May 2023 OEWS.
_SOC_MAP = {
    "software": "15-1252",
    "ml": "15-2051",
    "data scientist": "15-2051",
    "mechanical": "17-2141",
    "electrical": "17-2071",
    "hardware": "17-2071",
    "product manager": "11-2021",
    "operations": "11-1021",
    "engineering manager": "11-9041",
}

# (soc_code, metro_key) -> BlsWage
# metro_key is a lowercase substring matched against the candidate's location.
# Source: BLS OEWS May 2023. Wages rounded to nearest $1K.
_DATA: dict[tuple[str, str], BlsWage] = {}


def _add(soc: str, soc_title: str, metro: str, metro_key: str,
         p10: int, p25: int, median: int, p75: int, p90: int, mean: int):
    _DATA[(soc, metro_key)] = BlsWage(soc, soc_title, metro,
                                       p10, p25, median, p75, p90, mean)


# --- Software Developers (15-1252) ---
_add("15-1252", "Software Developers", "San Francisco-Oakland-Berkeley, CA", "san francisco",
     100_000, 130_000, 167_000, 210_000, 253_000, 172_000)
_add("15-1252", "Software Developers", "San Jose-Sunnyvale-Santa Clara, CA", "san jose",
     110_000, 140_000, 177_000, 224_000, 265_000, 183_000)
_add("15-1252", "Software Developers", "New York-Newark-Jersey City, NY-NJ-PA", "new york",
     85_000, 110_000, 143_000, 185_000, 226_000, 150_000)
_add("15-1252", "Software Developers", "Seattle-Tacoma-Bellevue, WA", "seattle",
     98_000, 128_000, 164_000, 208_000, 248_000, 170_000)
_add("15-1252", "Software Developers", "Boston-Cambridge-Nashua, MA-NH", "boston",
     88_000, 113_000, 145_000, 183_000, 219_000, 150_000)
_add("15-1252", "Software Developers", "Los Angeles-Long Beach-Anaheim, CA", "los angeles",
     82_000, 105_000, 135_000, 172_000, 209_000, 141_000)
_add("15-1252", "Software Developers", "Austin-Round Rock-Georgetown, TX", "austin",
     80_000, 102_000, 132_000, 168_000, 204_000, 138_000)
_add("15-1252", "Software Developers", "National", "remote",
     69_000, 90_000, 127_000, 163_000, 200_000, 132_000)

# --- Data Scientists / ML Engineers (15-2051) ---
_add("15-2051", "Data Scientists", "San Francisco-Oakland-Berkeley, CA", "san francisco",
     95_000, 125_000, 163_000, 205_000, 245_000, 167_000)
_add("15-2051", "Data Scientists", "San Jose-Sunnyvale-Santa Clara, CA", "san jose",
     105_000, 135_000, 175_000, 220_000, 260_000, 180_000)
_add("15-2051", "Data Scientists", "New York-Newark-Jersey City, NY-NJ-PA", "new york",
     80_000, 105_000, 138_000, 178_000, 218_000, 144_000)
_add("15-2051", "Data Scientists", "Seattle-Tacoma-Bellevue, WA", "seattle",
     92_000, 120_000, 157_000, 200_000, 240_000, 163_000)
_add("15-2051", "Data Scientists", "Boston-Cambridge-Nashua, MA-NH", "boston",
     83_000, 108_000, 140_000, 178_000, 215_000, 145_000)
_add("15-2051", "Data Scientists", "National", "remote",
     60_000, 82_000, 108_000, 145_000, 184_000, 117_000)

# --- Mechanical Engineers (17-2141) ---
_add("17-2141", "Mechanical Engineers", "San Francisco-Oakland-Berkeley, CA", "san francisco",
     82_000, 100_000, 122_000, 152_000, 185_000, 128_000)
_add("17-2141", "Mechanical Engineers", "San Jose-Sunnyvale-Santa Clara, CA", "san jose",
     88_000, 108_000, 135_000, 165_000, 198_000, 140_000)
_add("17-2141", "Mechanical Engineers", "New York-Newark-Jersey City, NY-NJ-PA", "new york",
     72_000, 88_000, 108_000, 135_000, 165_000, 113_000)
_add("17-2141", "Mechanical Engineers", "Seattle-Tacoma-Bellevue, WA", "seattle",
     78_000, 96_000, 118_000, 148_000, 180_000, 124_000)
_add("17-2141", "Mechanical Engineers", "Boston-Cambridge-Nashua, MA-NH", "boston",
     75_000, 92_000, 112_000, 140_000, 170_000, 118_000)
_add("17-2141", "Mechanical Engineers", "National", "remote",
     62_000, 76_000, 96_000, 121_000, 152_000, 100_000)

# --- Electrical Engineers (17-2071) ---
_add("17-2071", "Electrical Engineers", "San Francisco-Oakland-Berkeley, CA", "san francisco",
     85_000, 105_000, 130_000, 162_000, 196_000, 136_000)
_add("17-2071", "Electrical Engineers", "San Jose-Sunnyvale-Santa Clara, CA", "san jose",
     92_000, 115_000, 145_000, 180_000, 215_000, 150_000)
_add("17-2071", "Electrical Engineers", "New York-Newark-Jersey City, NY-NJ-PA", "new york",
     75_000, 92_000, 115_000, 142_000, 172_000, 119_000)
_add("17-2071", "Electrical Engineers", "Seattle-Tacoma-Bellevue, WA", "seattle",
     82_000, 100_000, 125_000, 155_000, 188_000, 130_000)
_add("17-2071", "Electrical Engineers", "National", "remote",
     62_000, 78_000, 104_000, 133_000, 165_000, 108_000)

# --- Engineering Managers (11-9041) ---
_add("11-9041", "Engineering Managers", "San Francisco-Oakland-Berkeley, CA", "san francisco",
     120_000, 155_000, 200_000, 245_000, 280_000, 202_000)
_add("11-9041", "Engineering Managers", "San Jose-Sunnyvale-Santa Clara, CA", "san jose",
     130_000, 168_000, 215_000, 260_000, 295_000, 218_000)
_add("11-9041", "Engineering Managers", "New York-Newark-Jersey City, NY-NJ-PA", "new york",
     110_000, 140_000, 180_000, 225_000, 265_000, 186_000)
_add("11-9041", "Engineering Managers", "Seattle-Tacoma-Bellevue, WA", "seattle",
     115_000, 148_000, 192_000, 238_000, 275_000, 196_000)
_add("11-9041", "Engineering Managers", "National", "remote",
     88_000, 115_000, 152_000, 196_000, 240_000, 159_000)


# ---- Lookup function -----------------------------------------------------

_FUNCTION_TO_SOC = {
    "software": "15-1252",
    "ml": "15-2051",
    "hardware": "17-2071",
    "design": "15-1252",       # closest proxy
    "product": "11-2021",
    "operations": "11-1021",
    "gtm": "11-2021",
    "g&a": "11-1021",
}


def lookup_bls(function: str, location: str) -> Optional[BlsWage]:
    """Return BLS wage data for the best-matching SOC + metro, or None."""
    fn = function.lower()
    soc = _FUNCTION_TO_SOC.get(fn)
    if not soc:
        # Try partial match
        for key, code in _FUNCTION_TO_SOC.items():
            if key in fn:
                soc = code
                break
    if not soc:
        soc = "15-1252"  # default to software developers

    loc = location.lower()
    # Try exact metro key matches
    for (s, metro_key), wage in _DATA.items():
        if s == soc and metro_key in loc:
            return wage
    # Fallback: try "remote" / national
    return _DATA.get((soc, "remote"))
