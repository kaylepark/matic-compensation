"""Extract candidate signals from a LinkedIn URL or resume link.

Best-effort parsing — profiles and resumes are wildly inconsistent, so every
field is Optional and the UI lets the user correct anything that's wrong.

LinkedIn note: public profiles return limited structured data without auth.
We fetch the page HTML and extract what we can from meta tags, JSON-LD,
and visible text. This works for public profiles; private ones will yield
less data — the user can always fill in the gaps manually.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Optional

import requests

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
_TIMEOUT = 15


@dataclass
class ResumeData:
    raw_text: str = ""
    name: Optional[str] = None
    title: Optional[str] = None
    location: Optional[str] = None
    years_experience: Optional[float] = None
    companies: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    education: list[str] = field(default_factory=list)
    source: str = ""  # "linkedin", "pdf_url", "html", "file"


# --------------- text extraction ---------------

def _extract_pdf_bytes(file_bytes: bytes) -> str:
    import pdfplumber
    text_parts = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text_parts.append(t)
    return "\n".join(text_parts)


def _extract_html(html: str) -> str:
    """Pull visible text from HTML."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    # Kill script/style tags
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


def _extract_meta(html: str, property_name: str) -> Optional[str]:
    """Extract an og: or name= meta tag value."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    tag = soup.find("meta", attrs={"property": property_name})
    if not tag:
        tag = soup.find("meta", attrs={"name": property_name})
    if tag and tag.get("content"):
        return tag["content"].strip()
    return None


# --------------- LinkedIn-specific parsing ---------------

def _parse_linkedin(html: str) -> ResumeData:
    """Extract what we can from a LinkedIn public profile page."""
    raw = _extract_html(html)

    # LinkedIn puts good structured data in og: meta tags.
    og_title = _extract_meta(html, "og:title") or ""
    og_desc = _extract_meta(html, "og:description") or ""
    og_type = _extract_meta(html, "og:type") or ""

    # og:title formats:
    #   "Name - Title - Company | LinkedIn"   (3 parts — ideal)
    #   "Name - Company | LinkedIn"           (2 parts — no title in og:title)
    #   "Name | LinkedIn"                     (1 part)
    name = None
    title = None
    current_company = None
    if " - " in og_title:
        parts = [p.strip().replace(" | LinkedIn", "").strip()
                 for p in og_title.split(" - ")]
        if parts:
            name = parts[0]
        if len(parts) == 3:
            # Name - Title - Company
            title = parts[1]
            current_company = parts[2]
        elif len(parts) == 2:
            # Name - Company (no title). Don't mistake company for title.
            current_company = parts[1]
            # Try to find the real title from the page text or og:description
            title = None
    elif " | " in og_title:
        name = og_title.replace(" | LinkedIn", "").strip()

    # og:description often has "Experience: Company1 · Company2 · ... Education: ..."
    companies = []
    if current_company:
        companies.append(current_company)

    # Parse experience section from description
    exp_match = re.search(r"Experience[:\s]+(.+?)(?:Education|Skills|$)", og_desc, re.I)
    if exp_match:
        exp_text = exp_match.group(1)
        for comp in re.split(r"\s*[·•|]\s*", exp_text):
            comp = comp.strip()
            if comp and comp not in companies and len(comp) < 60:
                companies.append(comp)

    # Parse education from description
    education = []
    edu_match = re.search(r"Education[:\s]+(.+?)(?:Skills|$)", og_desc, re.I)
    if edu_match:
        edu_text = edu_match.group(1)
        for edu in re.split(r"\s*[·•|]\s*", edu_text):
            edu = edu.strip()
            if edu and len(edu) > 3:
                education.append(edu)

    # For LinkedIn, only trust the title from og:title (3-part format).
    # The page text is too noisy (articles, ads, other people's titles)
    # to guess from — better to leave blank and let the user fill it in.

    # Location from visible text — LinkedIn often shows "City, State" near top
    location = _guess_location(raw)

    # YOE — use LinkedIn-aware version that excludes education years
    yoe = _guess_yoe_linkedin(raw, og_desc)

    # Skills from full text
    skills = _guess_skills(raw)

    # Also check for known companies in full text
    for comp in _guess_known_companies(raw):
        if comp not in companies:
            companies.append(comp)

    return ResumeData(
        raw_text=raw,
        name=name,
        title=title,
        location=location,
        years_experience=yoe,
        companies=companies,
        skills=skills,
        education=education,
        source="linkedin",
    )


# --------------- generic field extraction ---------------

_DEPT_WORDS = (
    r"(?:Engineering|Software|Hardware|Mechanical|Electrical|Firmware|"
    r"Robotics|Autonomy|Product|Design|Operations|Manufacturing|"
    r"ML|Machine Learning|Data|Supply Chain|Quality|Sales|Marketing|"
    r"People|Finance|Business|Strategy|Technology|R&D|Research)"
)

_TITLE_PATTERNS = [
    # VP/Director must be followed by a real department, not any random word.
    r"(?:VP|Vice President)\s+(?:of\s+)?" + _DEPT_WORDS,
    r"(?:Head|Director)\s+of\s+" + _DEPT_WORDS,
    # Level prefix + function + role
    r"(?:Principal|Distinguished|Staff|Senior|Lead|Sr\.?)\s+"
    r"(?:Software|ML|Machine Learning|Data|Hardware|Mechanical|Electrical|"
    r"Firmware|Robotics|Autonomy|Product|Design|DevOps|Infrastructure|"
    r"Backend|Frontend|Full[ -]?Stack)\s+(?:Engineer|Scientist|Manager|Designer)",
    # Function + role (no level prefix)
    r"(?:Software|ML|Machine Learning|Data|Hardware|Mechanical|Electrical|"
    r"Firmware|Robotics|Autonomy|Product|Design|DevOps|Infrastructure|"
    r"Backend|Frontend|Full[ -]?Stack)\s+(?:Engineer|Scientist|Manager|Designer)",
    r"(?:Engineering|Product|Design|Technical|Program)\s+Manager",
]

_YEAR_RE = re.compile(r"\b(19[89]\d|20[0-2]\d)\b")

_LOCATION_RE = re.compile(
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?,\s*"
    r"(?:CA|NY|WA|MA|TX|CO|IL|PA|GA|OR|VA|NC|FL|OH|NJ|"
    r"California|New York|Washington|Massachusetts|Texas|Colorado))\b"
)

_SKILL_KEYWORDS = [
    "Python", "C++", "C#", "Java", "JavaScript", "TypeScript", "Go", "Rust",
    "ROS", "ROS2", "PyTorch", "TensorFlow", "CUDA", "OpenCV",
    "Kubernetes", "Docker", "AWS", "GCP", "Azure",
    "CAD", "SolidWorks", "MATLAB", "Simulink",
    "PCB", "FPGA", "Verilog", "VHDL",
    "React", "Node.js", "PostgreSQL", "MongoDB",
    "Machine Learning", "Computer Vision", "NLP", "Reinforcement Learning",
    "SLAM", "Motion Planning", "Controls", "Perception",
]

_KNOWN_COMPANIES = [
    "Google", "Meta", "Apple", "Amazon", "Microsoft", "Tesla", "Rivian",
    "Waymo", "Cruise", "Nuro", "Skydio", "Anduril", "SpaceX", "Netflix",
    "Uber", "Lyft", "Airbnb", "Stripe", "Coinbase", "Robinhood",
    "NVIDIA", "Intel", "AMD", "Qualcomm", "Broadcom",
    "Boston Dynamics", "iRobot", "Figure AI", "Physical Intelligence",
    "Zipline", "Lucid", "Cobalt Robotics", "Bear Robotics",
    "JPMorgan", "Goldman Sachs", "Morgan Stanley",
    "McKinsey", "Bain", "BCG", "Deloitte",
]


def _guess_name(text: str) -> Optional[str]:
    for line in text.split("\n")[:8]:
        line = line.strip()
        if not line or len(line) > 60:
            continue
        if re.search(r"@|http|phone|address|\d{3}[-.]?\d{3}", line, re.I):
            continue
        words = line.split()
        if 2 <= len(words) <= 4 and all(w[0].isupper() for w in words if w.isalpha()):
            return line
    return None


def _guess_title(text: str) -> Optional[str]:
    for pattern in _TITLE_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(0).strip()
    return None


def _guess_location(text: str) -> Optional[str]:
    m = _LOCATION_RE.search(text)
    return m.group(1).strip() if m else None


_CURRENT_YEAR = 2026

_DEGREE_RE = re.compile(
    r"\b(?:B\.S\.?|B\.A\.?|B\.Eng|BS|BA|BEng"
    r"|M\.S\.?|M\.A\.?|M\.Eng|MS|MA|MEng|MBA"
    r"|Ph\.?D\.?"
    r"|Bachelor(?:'?s)?|Master(?:'?s)?|Doctorate|Doctor)\b"
)
_YEAR_RANGE_RE = re.compile(r"((?:19|20)\d{2})\s*[-–—]\s*((?:19|20)\d{2})")
_SINGLE_YEAR_RE = re.compile(r"(20[0-2]\d)")


def _find_graduation_year(text: str) -> Optional[int]:
    """Find the latest graduation year in the text.

    FTE experience = current_year - graduation_year.
    Internships during school don't count — only post-degree.

    Strategy:
      1. "Class of YYYY" / "Graduated YYYY" — explicit, trust it.
      2. Degree keyword near a year range (YYYY-YYYY) — take the END year.
      3. Degree keyword near a single year — take that year.
      4. Year ranges inside an Education section — take end years.
      5. Return the MAX (latest degree = when FTE starts).
    """
    grad_years: list[int] = []

    # --- Explicit graduation markers ---
    for m in re.finditer(r"(?:class\s+of|graduated?)\s*:?\s*(20[0-2]\d)", text, re.I):
        y = int(m.group(1))
        if 2000 <= y < _CURRENT_YEAR:
            grad_years.append(y)

    # --- Degree keyword + nearby year(s) ---
    for m in _DEGREE_RE.finditer(text):
        # Look at the 120 chars after the degree keyword for years.
        window = text[m.start():m.start() + 120]

        # Prefer a year range (YYYY-YYYY) — take the END year.
        range_match = _YEAR_RANGE_RE.search(window)
        if range_match:
            end_year = int(range_match.group(2))
            if 2000 <= end_year < _CURRENT_YEAR:
                grad_years.append(end_year)
                continue

        # Single year near the degree keyword.
        single_match = _SINGLE_YEAR_RE.search(window)
        if single_match:
            y = int(single_match.group(1))
            if 2000 <= y < _CURRENT_YEAR:
                grad_years.append(y)

    # --- Education section: any year ranges are likely enrollment periods ---
    edu_start = re.search(
        r"(?:^|\n)\s*(?:education|academic|degrees?)\s*\n",
        text, re.IGNORECASE,
    )
    if edu_start:
        edu_section = text[edu_start.end():edu_start.end() + 800]
        for m in _YEAR_RANGE_RE.finditer(edu_section):
            end_year = int(m.group(2))
            if 2000 <= end_year < _CURRENT_YEAR:
                grad_years.append(end_year)

    return max(grad_years) if grad_years else None


def _guess_yoe(text: str) -> Optional[float]:
    """Estimate full-time YOE. Internships do NOT count.

    Primary method: find graduation year, compute current_year - grad_year.
    Fallback: explicit "X years of experience" text.
    """
    # 1. Explicit "X years of experience"
    m = re.search(r"(\d{1,2})\+?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:full[- ]?time\s+)?experience", text, re.I)
    if m:
        return float(m.group(1))

    # 2. Graduation-based: FTE starts after latest degree
    grad = _find_graduation_year(text)
    if grad:
        yoe = _CURRENT_YEAR - grad
        if 0 <= yoe <= 35:
            return float(yoe)

    return None


def _guess_yoe_linkedin(text: str, og_desc: str) -> Optional[float]:
    """LinkedIn-aware YOE estimation. Only counts full-time experience
    (post-graduation). Internships during school are excluded.
    """
    # 1. Explicit "X years of experience"
    m = re.search(r"(\d{1,2})\+?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:full[- ]?time\s+)?experience", text, re.I)
    if m:
        return float(m.group(1))

    # 2. Find graduation year from page text — best signal
    grad = _find_graduation_year(text)
    if grad:
        yoe = _CURRENT_YEAR - grad
        if 0 <= yoe <= 35:
            return float(yoe)

    # 3. Find graduation year from og:description education section
    edu_match = re.search(r"Education[:\s]+(.+?)(?:Skills|$)", og_desc, re.I)
    if edu_match:
        grad = _find_graduation_year(edu_match.group(1))
        if grad:
            yoe = _CURRENT_YEAR - grad
            if 0 <= yoe <= 35:
                return float(yoe)

    return None


def _guess_known_companies(text: str) -> list[str]:
    found = []
    for company in _KNOWN_COMPANIES:
        if re.search(r"\b" + re.escape(company) + r"\b", text, re.IGNORECASE):
            found.append(company)
    return found


def _guess_skills(text: str) -> list[str]:
    found = []
    for skill in _SKILL_KEYWORDS:
        if re.search(r"\b" + re.escape(skill) + r"\b", text):
            found.append(skill)
    return found


def _guess_education(text: str) -> list[str]:
    edu = []
    for m in re.finditer(
        r"((?:B\.?S\.?|M\.?S\.?|Ph\.?D\.?|MBA|Bachelor|Master|Doctor)\w*"
        r"[^.\n]{5,80})",
        text,
    ):
        edu.append(m.group(0).strip())
        if len(edu) >= 3:
            break
    return edu


# --------------- URL fetching ---------------

def fetch_url(url: str) -> ResumeData:
    """Fetch a URL and extract candidate signals.

    Handles:
      - LinkedIn profile URLs (linkedin.com/in/...)
      - Direct PDF links (anything ending in .pdf or returning application/pdf)
      - Any other HTML page (generic extraction)
    """
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url

    is_linkedin = "linkedin.com" in url

    try:
        r = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT, allow_redirects=True)
        # LinkedIn returns 999 when it detects automated requests — don't
        # crash, just treat it as a blocked response.
        if not is_linkedin:
            r.raise_for_status()
    except Exception as e:
        msg = str(e)
        if "403" in msg or "Forbidden" in msg:
            hint = (
                "Link expired or access denied (403). "
                "If this is an ATS resume link, grab a fresh one — "
                "they typically expire after 30 minutes."
            )
        elif "404" in msg:
            hint = "Page not found (404). Check the URL."
        elif "Timeout" in msg:
            hint = "Request timed out. Try again or check the URL."
        else:
            hint = f"Could not fetch: {type(e).__name__}"
        return ResumeData(raw_text=hint, source="error")

    content_type = r.headers.get("Content-Type", "")

    # PDF link
    if "application/pdf" in content_type or url.rstrip("/").lower().endswith(".pdf"):
        raw = _extract_pdf_bytes(r.content)
        if not raw.strip():
            return ResumeData(raw_text="(No text extracted from PDF.)", source="pdf_url")
        return ResumeData(
            raw_text=raw,
            name=_guess_name(raw),
            title=_guess_title(raw),
            location=_guess_location(raw),
            years_experience=_guess_yoe(raw),
            companies=_guess_known_companies(raw),
            skills=_guess_skills(raw),
            education=_guess_education(raw),
            source="pdf_url",
        )

    html = r.text

    # LinkedIn — try to parse whatever we got, even from a partial/blocked page.
    # LinkedIn often blocks automated fetches (status 999 or login redirect),
    # so _parse_linkedin extracts whatever is available and leaves the rest blank.
    if is_linkedin:
        return _parse_linkedin(html)

    # Generic HTML page
    raw = _extract_html(html)
    if not raw.strip():
        return ResumeData(raw_text="(No text extracted from page.)", source="html")

    return ResumeData(
        raw_text=raw,
        name=_guess_name(raw),
        title=_guess_title(raw),
        location=_guess_location(raw),
        years_experience=_guess_yoe(raw),
        companies=_guess_known_companies(raw),
        skills=_guess_skills(raw),
        education=_guess_education(raw),
        source="html",
    )
