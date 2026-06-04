"""Best-effort live market signal from public ATS job boards.

Pay-transparency laws (CA/CO/NY/WA) push salary ranges into many postings.
We pull peer postings, keep those matching the candidate's role + location,
and regex-extract any disclosed salary range. This is noisy by nature: treat
it as corroborating evidence, not ground truth.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import requests

from .peers import PEERS, Peer

TIMEOUT = 8
HEADERS = {"User-Agent": "matic-comp-tool/0.1 (internal benchmarking)"}

# Matches "$150,000 - $200,000", "$150K–$200K", "150,000 to 200,000", etc.
_RANGE_RE = re.compile(
    r"\$?\s*(\d{2,3}(?:,\d{3})?)\s*[Kk]?\s*(?:-|–|—|to)\s*\$?\s*(\d{2,3}(?:,\d{3})?)\s*[Kk]?"
)


@dataclass
class Posting:
    company: str
    title: str
    location: str
    url: str
    salary_low: Optional[int] = None
    salary_high: Optional[int] = None


@dataclass
class MarketResult:
    postings: list[Posting] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def with_salary(self) -> list[Posting]:
        return [p for p in self.postings if p.salary_low and p.salary_high]


def _parse_salary(text: str) -> tuple[Optional[int], Optional[int]]:
    if not text:
        return None, None
    for m in _RANGE_RE.finditer(text):
        lo = _to_int(m.group(1), m.group(0))
        hi = _to_int(m.group(2), m.group(0))
        # Plausible annual base range for tech/eng roles.
        if lo and hi and 50_000 <= lo <= hi <= 1_200_000:
            return lo, hi
    return None, None


def _to_int(num: str, context: str) -> Optional[int]:
    n = int(num.replace(",", ""))
    if "k" in context.lower() and n < 1000:
        n *= 1000
    if "," not in num and n < 1000:  # bare "150" meaning 150K
        n *= 1000
    return n


def _matches(title: str, keywords: list[str]) -> bool:
    t = title.lower()
    return any(kw in t for kw in keywords)


def _location_ok(loc: str, location_filter: Optional[str]) -> bool:
    if not location_filter:
        return True
    return location_filter.lower() in (loc or "").lower()


def _fetch_greenhouse(peer: Peer) -> list[Posting]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{peer.slug}/jobs?content=true"
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for j in r.json().get("jobs", []):
        content = j.get("content", "") or ""
        lo, hi = _parse_salary(content)
        out.append(
            Posting(
                company=peer.name,
                title=j.get("title", ""),
                location=(j.get("location") or {}).get("name", ""),
                url=j.get("absolute_url", ""),
                salary_low=lo,
                salary_high=hi,
            )
        )
    return out


def _fetch_lever(peer: Peer) -> list[Posting]:
    url = f"https://api.lever.co/v0/postings/{peer.slug}?mode=json"
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for j in r.json():
        text = j.get("descriptionPlain", "") or ""
        lo, hi = _parse_salary(text)
        out.append(
            Posting(
                company=peer.name,
                title=j.get("text", ""),
                location=(j.get("categories") or {}).get("location", ""),
                url=j.get("hostedUrl", ""),
                salary_low=lo,
                salary_high=hi,
            )
        )
    return out


def fetch_market(
    role_keywords: list[str],
    location_filter: Optional[str] = None,
    peers: Optional[list[Peer]] = None,
) -> MarketResult:
    result = MarketResult()
    for peer in peers or PEERS:
        try:
            raw = _fetch_greenhouse(peer) if peer.ats == "greenhouse" else _fetch_lever(peer)
        except Exception as e:  # noqa: BLE001 - we want to keep going past any peer
            result.errors.append(f"{peer.name}: {type(e).__name__}")
            continue
        for p in raw:
            if _matches(p.title, role_keywords) and _location_ok(p.location, location_filter):
                result.postings.append(p)
    return result
