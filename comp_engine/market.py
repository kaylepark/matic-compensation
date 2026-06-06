"""Best-effort live market signal from public ATS job boards.

Pay-transparency laws (CA/CO/NY/WA) push salary ranges into many postings.
We pull peer postings, keep those matching the candidate's role + location,
and regex-extract any disclosed salary range. This is noisy by nature: treat
it as corroborating evidence, not ground truth.

Supported ATS: Greenhouse, Lever, Ashby.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import requests

from .peers import PEERS, Peer

TIMEOUT = 10
HEADERS = {"User-Agent": "matic-comp-tool/0.1 (internal benchmarking)"}

# Matches "$150,000 - $200,000", "$150K–$200K", "150,000 to 200,000", etc.
_RANGE_RE = re.compile(
    r"\$?\s*(\d{2,3}(?:,\d{3})?)\s*[Kk]?\s*(?:-|–|—|to)\s*\$?\s*(\d{2,3}(?:,\d{3})?)\s*[Kk]?"
)

# Matches YOE requirements like "3+ years", "5-8 years of experience", "2+ yrs"
_YOE_RE = re.compile(
    r"(\d{1,2})\s*(?:\+|[-–—]\s*\d{1,2})?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:experience|exp)",
    re.IGNORECASE,
)

# Level prefixes/suffixes to strip when building search phrases.
_LEVEL_SUFFIX_RE = re.compile(
    r"\s+(?:I{1,3}|IV|V|VI|Sr\.?|Jr\.?|Senior|Junior|Lead|Staff|Principal|\d+)\s*$",
    re.IGNORECASE,
)
_LEVEL_PREFIX_RE = re.compile(
    r"^(?:Senior|Sr\.?|Junior|Jr\.?|Lead|Staff|Principal|Distinguished)\s+",
    re.IGNORECASE,
)

MIN_COMPANIES = 5  # Minimum company diversity target for results.


@dataclass
class Posting:
    company: str
    title: str
    location: str
    url: str
    content: str = ""  # description text for broader matching
    salary_low: Optional[int] = None
    salary_high: Optional[int] = None
    yoe_required: Optional[int] = None
    match_type: str = "exact"  # "exact" = phrase in title, "broad" = keywords in title/description


@dataclass
class MarketResult:
    postings: list[Posting] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def with_salary(self) -> list[Posting]:
        return [p for p in self.postings if p.salary_low and p.salary_high]

    @property
    def company_count(self) -> int:
        return len(set(p.company for p in self.postings))


def _parse_salary(text: str) -> tuple[Optional[int], Optional[int]]:
    if not text:
        return None, None
    for m in _RANGE_RE.finditer(text):
        lo = _to_int(m.group(1), m.group(0))
        hi = _to_int(m.group(2), m.group(0))
        if lo and hi and 50_000 <= lo <= hi <= 1_200_000:
            return lo, hi
    return None, None


def _parse_yoe(text: str) -> Optional[int]:
    if not text:
        return None
    m = _YOE_RE.search(text)
    return int(m.group(1)) if m else None


def _to_int(num: str, context: str) -> Optional[int]:
    n = int(num.replace(",", ""))
    if "k" in context.lower() and n < 1000:
        n *= 1000
    if "," not in num and n < 1000:
        n *= 1000
    return n


def _matches_exact(posting_title: str, search_phrase: str) -> bool:
    """Exact: the full phrase appears in the posting title."""
    return search_phrase.lower() in posting_title.lower()


_EXCLUDE_TITLE_RE = re.compile(
    r"\b(?:intern|internship|co-?op)\b", re.IGNORECASE
)


def _matches_broad(posting_title: str, posting_content: str,
                   search_phrase: str) -> bool:
    """Broad: the full phrase appears in the posting description (not just title).

    This catches postings where the title is different (e.g. "Design Engineer")
    but the description mentions "mechanical engineer" as a requirement.
    Excludes internships.
    """
    if _EXCLUDE_TITLE_RE.search(posting_title):
        return False
    return search_phrase.lower() in posting_content.lower()


def _yoe_compatible(posting_yoe: Optional[int], candidate_yoe: Optional[float]) -> bool:
    if posting_yoe is None or candidate_yoe is None:
        return True
    return posting_yoe - 2 <= candidate_yoe <= posting_yoe + 6


def _location_ok(loc: str, location_filter: Optional[str]) -> bool:
    if not location_filter:
        return True
    return location_filter.lower() in (loc or "").lower()


def clean_title_for_search(title: str) -> str:
    """Strip level prefixes and suffixes to get a clean role search phrase.

    "Mechanical Engineer II"   -> "Mechanical Engineer"
    "Senior Software Engineer" -> "Software Engineer"
    """
    cleaned = _LEVEL_SUFFIX_RE.sub("", title).strip()
    cleaned = _LEVEL_PREFIX_RE.sub("", cleaned).strip()
    return cleaned


# ---- ATS fetchers --------------------------------------------------------


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
                content=content,
                salary_low=lo,
                salary_high=hi,
                yoe_required=_parse_yoe(content),
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
                content=text,
                salary_low=lo,
                salary_high=hi,
                yoe_required=_parse_yoe(text),
            )
        )
    return out


def _fetch_ashby(peer: Peer) -> list[Posting]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{peer.slug}"
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for j in r.json().get("jobs", []):
        text = j.get("descriptionPlain", "") or j.get("descriptionHtml", "") or ""
        lo, hi = _parse_salary(text)
        out.append(
            Posting(
                company=peer.name,
                title=j.get("title", ""),
                location=j.get("location", ""),
                url=j.get("jobUrl", ""),
                content=text,
                salary_low=lo,
                salary_high=hi,
                yoe_required=_parse_yoe(text),
            )
        )
    return out


_FETCHERS = {
    "greenhouse": _fetch_greenhouse,
    "lever": _fetch_lever,
    "ashby": _fetch_ashby,
}


def fetch_market(
    title_phrase: str,
    location_filter: Optional[str] = None,
    candidate_yoe: Optional[float] = None,
    peers: Optional[list[Peer]] = None,
) -> MarketResult:
    """Fetch matching postings from peer companies.

    Two-pass matching for company diversity:
      1. Exact: full phrase in posting title (e.g. "mechanical engineer").
      2. If fewer than MIN_COMPANIES represented, broaden: search for the
         full phrase in the posting description too (not just title). This
         catches postings at other companies where the title differs but
         the description mentions the role.

    Results are tagged with match_type so the UI can differentiate.
    """
    result = MarketResult()
    search = title_phrase.lower().strip()
    if not search:
        return result

    # Collect ALL postings from all peers first.
    all_postings: list[Posting] = []
    for peer in peers or PEERS:
        fetcher = _FETCHERS.get(peer.ats)
        if not fetcher:
            result.errors.append(f"{peer.name}: unsupported ATS '{peer.ats}'")
            continue
        try:
            raw = fetcher(peer)
        except Exception as e:  # noqa: BLE001
            result.errors.append(f"{peer.name}: {type(e).__name__}")
            continue
        all_postings.extend(raw)

    # Core words for flexible title matching (words > 2 chars).
    core_words = [w for w in search.split() if len(w) > 2]

    # --- Pass 1: exact phrase in title ("Mechanical Engineer" as substring) ---
    exact = []
    for p in all_postings:
        if (
            _matches_exact(p.title, search)
            and _location_ok(p.location, location_filter)
            and _yoe_compatible(p.yoe_required, candidate_yoe)
        ):
            p.match_type = "exact"
            exact.append(p)

    seen_urls = set(p.url for p in exact)
    all_companies = set(p.company for p in exact)

    # --- Pass 2: all core words in title, any order ---
    # Catches "Mechanical Design Engineer", "Hardware Engineer - Mechanical", etc.
    related = []
    if len(all_companies) < MIN_COMPANIES and core_words:
        for p in all_postings:
            if p.url in seen_urls:
                continue
            if _EXCLUDE_TITLE_RE.search(p.title):
                continue
            t = p.title.lower()
            if (
                all(w in t for w in core_words)
                and _location_ok(p.location, location_filter)
                and _yoe_compatible(p.yoe_required, candidate_yoe)
            ):
                p.match_type = "related"
                related.append(p)
                seen_urls.add(p.url)
        all_companies |= set(p.company for p in related)

    # --- Pass 3: full phrase in description (not just title) ---
    # Catches postings with a different title but the role described in the body.
    broad = []
    if len(all_companies) < MIN_COMPANIES:
        for p in all_postings:
            if p.url in seen_urls:
                continue
            if (
                _matches_broad(p.title, p.content, search)
                and _location_ok(p.location, location_filter)
                and _yoe_compatible(p.yoe_required, candidate_yoe)
            ):
                p.match_type = "broad"
                broad.append(p)

    # Combine all matches, then interleave by company so results aren't
    # dominated by one company with many postings. Within each company,
    # prefer salary-disclosed postings and exact matches.
    all_matched = exact + related + broad

    # Sort within each company: salary > no salary, exact > related > broad.
    match_rank = {"exact": 0, "related": 1, "broad": 2}
    all_matched.sort(key=lambda p: (
        0 if (p.salary_low and p.salary_high) else 1,
        match_rank.get(p.match_type, 3),
    ))

    # Round-robin interleave across companies.
    from collections import defaultdict
    by_company: dict[str, list[Posting]] = defaultdict(list)
    for p in all_matched:
        by_company[p.company].append(p)

    interleaved: list[Posting] = []
    queues = list(by_company.values())
    idx = 0
    while queues:
        q = queues[idx % len(queues)]
        interleaved.append(q.pop(0))
        if not q:
            queues.pop(idx % len(queues))
        else:
            idx += 1

    result.postings = interleaved

    # Strip content from results to save memory (no longer needed).
    for p in result.postings:
        p.content = ""

    return result
