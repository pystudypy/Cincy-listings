"""
Detail page description enrichment.

Visits each listing's URL and extracts the agent-written property description text.
Supports: Coldwell Banker, Comey, CincinKY, Sibcy Cline, Redfin, Huff, and a
generic fallback that works on most MLS-powered pages.

Usage:
    from utils.detail_descriptions import enrich_descriptions
    listings = enrich_descriptions(listings)
"""

import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

REQUEST_TIMEOUT = 12   # fail fast — slow sites aren't worth waiting for
WORKERS = 8            # parallel fetches (8 threads, one per source roughly)

# Words that signal we're looking at actual listing description text
_RE_ESTATE_WORDS = re.compile(
    r"\b(bedroom|bathroom|kitchen|garage|basement|floor|roof|updated|renovated|"
    r"hardwood|appliance|fireplace|backyard|patio|deck|pool|sq\s*ft|sqft|acre|"
    r"open\s+concept|move.in|turnkey|remodel|renovated|quartz|granite|hvac|"
    r"furnace|new\s+roof|stainless|master\s+suite|walk.in)\b",
    re.IGNORECASE,
)


def _fetch_html(url: str) -> BeautifulSoup | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        logger.debug(f"Fetch failed ({url[:80]}): {e}")
        return None


# ── per-source extractors ────────────────────────────────────────────────────

def _extract_coldwell_banker(soup: BeautifulSoup) -> str:
    """Coldwell Banker — description lives in 'Property Description' section."""
    # Try labelled section first
    for heading in soup.find_all(["h2", "h3", "h4", "strong", "span"]):
        if "property description" in heading.get_text(strip=True).lower():
            sib = heading.find_next_sibling()
            if sib:
                txt = sib.get_text(" ", strip=True)
                if len(txt) > 80:
                    return txt
    return _extract_generic(soup)


def _extract_comey(soup: BeautifulSoup) -> str:
    """Comey & Shepherd."""
    # Try itemprop or class hints
    for sel in ["[itemprop='description']", ".property-remarks", ".listing-remarks",
                ".remarks", ".property-description", "#remarks"]:
        el = soup.select_one(sel)
        if el:
            txt = el.get_text(" ", strip=True)
            if len(txt) > 80:
                return txt
    return _extract_generic(soup)


def _extract_cincinky(soup: BeautifulSoup) -> str:
    """CincinKY — description is in a plain <p> or <div> block."""
    # Check JSON-LD first (often has good description)
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            desc = data.get("description", "")
            # JSON-LD description is often just "Home for sale at..." — skip if short/generic
            if len(desc) > 120 and _RE_ESTATE_WORDS.search(desc):
                return desc
        except Exception:
            pass
    return _extract_generic(soup)


def _extract_sibcy(soup: BeautifulSoup) -> str:
    """Sibcy Cline — JS-heavy but description often in meta or JSON-LD."""
    desc = _extract_meta_description(soup)
    if len(desc) > 100 and _RE_ESTATE_WORDS.search(desc):
        return desc
    return _extract_generic(soup)


def _extract_redfin(soup: BeautifulSoup) -> str:
    """Redfin — description is embedded in a JS bundle as 'remarks' or 'description'."""
    for script in soup.find_all("script"):
        text = script.string or ""
        # Look for publicRemarks / description fields in JSON blobs
        m = re.search(r'"publicRemarks"\s*:\s*"([^"]{80,})"', text)
        if m:
            return m.group(1).encode().decode("unicode_escape", errors="replace")
        m = re.search(r'"remarks"\s*:\s*"([^"]{80,})"', text)
        if m:
            return m.group(1).encode().decode("unicode_escape", errors="replace")
    # Fall back to meta description
    desc = _extract_meta_description(soup)
    if len(desc) > 80:
        return desc
    return ""


def _extract_huff(soup: BeautifulSoup) -> str:
    """Huff Realty — Blazor-rendered, meta + generic heuristic."""
    desc = _extract_meta_description(soup)
    if len(desc) > 100 and _RE_ESTATE_WORDS.search(desc):
        return desc
    return _extract_generic(soup)


def _extract_meta_description(soup: BeautifulSoup) -> str:
    """Pull og:description or meta description."""
    for prop in ("og:description", "description"):
        tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
        if tag:
            val = tag.get("content", "").strip()
            if val:
                return val
    return ""


def _extract_generic(soup: BeautifulSoup) -> str:
    """
    Heuristic fallback that works on most MLS-powered pages:
    - JSON-LD description field
    - og:description / meta description
    - Longest text block that contains real estate vocabulary
    """
    # 1. JSON-LD
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            desc = data.get("description", "")
            if len(desc) > 120 and _RE_ESTATE_WORDS.search(desc):
                return desc
        except Exception:
            pass

    # 2. Meta description
    desc = _extract_meta_description(soup)
    if len(desc) > 100 and _RE_ESTATE_WORDS.search(desc):
        return desc

    # 3. Heuristic: find the richest plain-text block
    best = ""
    for el in soup.find_all(["p", "div", "section"]):
        # Skip elements with lots of child tags (navigation, headers, etc.)
        if len(el.find_all()) > 8:
            continue
        txt = el.get_text(" ", strip=True)
        if 100 < len(txt) < 3000 and _RE_ESTATE_WORDS.search(txt):
            if len(txt) > len(best):
                best = txt
    return best


# ── router ───────────────────────────────────────────────────────────────────

_EXTRACTORS = {
    "coldwell_banker":      _extract_coldwell_banker,
    "comey":                _extract_comey,
    "cincinky":             _extract_cincinky,
    "sibcy_cline":          _extract_sibcy,
    "redfin":               _extract_redfin,
    "huff":                 _extract_huff,
    "listings_cincinnati":  _extract_generic,
    "zillow":               _extract_generic,
}


def _clean(text: str) -> str:
    """Normalize whitespace."""
    return re.sub(r"\s+", " ", text).strip()


def enrich_descriptions(
    listings: list[dict],
    force: bool = False,
    checkpoint_every: int = 50,
    checkpoint_fn=None,
) -> list[dict]:
    """
    Visit each listing's detail page and store the description text.

    Args:
        listings:         Full listing list (modified in place).
        force:            Re-fetch listings that already have a description.
        checkpoint_every: Call checkpoint_fn every N successful fetches.
        checkpoint_fn:    Optional callback(listings) for incremental saves.
    """
    to_enrich = [
        l for l in listings
        if l.get("url") and (force or not l.get("description"))
    ]

    if not to_enrich:
        logger.info("Description enrichment: all listings already have descriptions")
        return listings

    total = len(to_enrich)
    logger.info(f"Description enrichment: fetching {total} listing descriptions…")

    def fetch_one(listing: dict) -> tuple[dict, str]:
        """Fetch description for a single listing. Returns (listing, desc_or_empty)."""
        url    = listing["url"]
        source = listing.get("source", "")
        if source == "zillow" and url.startswith("https://www.zillow.comhttps://"):
            url = url.replace("https://www.zillow.comhttps://", "https://")
        soup = _fetch_html(url)
        if not soup:
            return listing, ""
        extractor = _EXTRACTORS.get(source, _extract_generic)
        return listing, _clean(extractor(soup))

    done = errors = 0
    lock = threading.Lock()
    last_checkpoint = 0

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(fetch_one, l): l for l in to_enrich}
        for future in as_completed(futures):
            try:
                listing, desc = future.result()
                if desc:
                    listing["description"] = desc
                    with lock:
                        done += 1
                        milestone = (done // checkpoint_every) * checkpoint_every
                else:
                    with lock:
                        errors += 1
                    milestone = 0
            except Exception as e:
                with lock:
                    errors += 1
                logger.debug(f"Fetch error: {e}")
                milestone = 0

            # Only checkpoint once per milestone (lock prevents duplicates)
            if milestone > 0:
                with lock:
                    if milestone > last_checkpoint:
                        last_checkpoint = milestone
                        do_checkpoint = True
                    else:
                        do_checkpoint = False
                if do_checkpoint:
                    logger.info(f"Description enrichment: {milestone}/{total} done…")
                    if checkpoint_fn:
                        checkpoint_fn(listings)

    logger.info(f"Description enrichment complete: {done} fetched, {errors} failed")
    return listings
