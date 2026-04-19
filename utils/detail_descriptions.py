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
import time
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
WORKERS = 30           # parallel fetches — more threads = faster photo enrichment

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
    """
    Comey & Shepherd — description lives in .cs-prop-details-main after the
    Print/Share buttons, or in .cs-property-flyer after 'Agent Remarks:'.
    """
    # 1. Main detail div — text after the Print/Share gallery buttons
    main = soup.select_one(".cs-prop-details-main")
    if main:
        txt = main.get_text(" ", strip=True)
        m = re.search(
            r"(?:Print|Share)\s+(.{80,}?)(?:\s+Property Details|\s+Virtual|\s+Floor Plan|\s+Map|\Z)",
            txt, re.DOTALL | re.IGNORECASE,
        )
        if m:
            candidate = re.sub(r"\s+", " ", m.group(1)).strip()
            # Strip any residual nav words at the start
            candidate = re.sub(r"^(Print|Save|Saved|Share|Email|Gallery|Showing)\s+", "", candidate, flags=re.IGNORECASE).strip()
            if len(candidate) > 80 and _RE_ESTATE_WORDS.search(candidate):
                return candidate

    # 2. Property flyer section — "Agent Remarks: ..."
    flyer = soup.select_one(".cs-property-flyer")
    if flyer:
        ftxt = flyer.get_text(" ", strip=True)
        m2 = re.search(r"Agent Remarks[:\s]+(.{80,})", ftxt, re.DOTALL | re.IGNORECASE)
        if m2:
            candidate = re.sub(r"\s+", " ", m2.group(1)).strip()
            if len(candidate) > 80:
                return candidate

    # 3. Legacy selectors
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
    """Redfin — description lives in JSON-LD structured data or JS bundles."""
    import html as html_module

    # 1. JSON-LD structured data (most reliable — type RealEstateListing)
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            items = data if isinstance(data, list) else [data]
            for item in items:
                types = item.get("@type", [])
                if isinstance(types, str):
                    types = [types]
                if "RealEstateListing" in types or "Product" in types:
                    desc = item.get("description", "")
                    if len(desc) > 80 and _RE_ESTATE_WORDS.search(desc):
                        return html_module.unescape(desc)
        except Exception:
            pass

    # 2. JS bundle — escape-aware regex for several field names
    _js_str = r'"((?:[^"\\]|\\.){80,})"'
    for field in ("publicRemarks", "remarks", "agentDescription", "marketingRemarks"):
        pat = rf'"{field}"\s*:\s*' + _js_str
        for script in soup.find_all("script"):
            text = script.string or ""
            m = re.search(pat, text)
            if m:
                try:
                    decoded = json.loads(f'"{m.group(1)}"')
                except Exception:
                    decoded = m.group(1)
                decoded = html_module.unescape(decoded)
                if _RE_ESTATE_WORDS.search(decoded):
                    return decoded

    # 3. Meta description — strip Redfin's "(Cincy MLS) For Sale: X beds..." prefix
    desc = _extract_meta_description(soup)
    # Strip syndication header up to the first ∙ that precedes real prose
    stripped = re.sub(r'^.*?∙\s*(?:MLS#\s*\S+\s*∙\s*)?', "", desc).strip()
    if len(stripped) > 80 and _RE_ESTATE_WORDS.search(stripped):
        return stripped
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


def _extract_cincinky_dom(soup: BeautifulSoup) -> int | None:
    """
    CincinKY detail pages show: <span class="text-gray-700">On Site</span>
                                 <strong class="font-medium">12 Days</strong>
    """
    for span in soup.find_all("span", class_="text-gray-700"):
        if span.get_text(strip=True) == "On Site":
            strong = span.find_next_sibling("strong")
            if strong:
                m = re.search(r"(\d+)", strong.get_text())
                if m:
                    return int(m.group(1))
    return None


def _parse_relative_days(text: str) -> int | None:
    """
    Parse Coldwell Banker's relative date strings into integer days.
      "Today"        → 0
      "Yesterday"    → 1
      "28 day(s) ago"  → 28
      "2 week(s) ago"  → 14
    """
    t = text.strip().lower()
    if t == "today":
        return 0
    if t == "yesterday":
        return 1
    m = re.search(r"(\d+)\s+day", t)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s+week", t)
    if m:
        return int(m.group(1)) * 7
    m = re.search(r"(\d+)\s+month", t)
    if m:
        return int(m.group(1)) * 30
    return None


def _extract_coldwell_dom(soup: BeautifulSoup) -> int | None:
    """
    Coldwell Banker detail pages show:
      <li><strong>Added to Site:</strong> 28 day(s) ago</li>
    """
    for strong in soup.find_all("strong"):
        if "Added to Site" in strong.get_text():
            # The date text is a sibling text node after the <strong>
            parent = strong.parent
            if parent:
                full = parent.get_text(" ", strip=True)
                # Strip the label and parse what remains
                after = re.sub(r"Added to Site\s*:?\s*", "", full, flags=re.IGNORECASE)
                return _parse_relative_days(after)
    return None


# Map source → DOM extractor function
_DOM_EXTRACTORS: dict[str, callable] = {
    "cincinky":       _extract_cincinky_dom,
    "coldwell_banker": _extract_coldwell_dom,
}


def enrich_dom(
    listings: list[dict],
    sources: list[str] | None = None,
    force: bool = False,
    checkpoint_every: int = 50,
    checkpoint_fn=None,
) -> list[dict]:
    """
    Visit detail pages to populate days_on_market for sources that don't
    include it in their search results (currently: cincinky, coldwell_banker).

    Args:
        listings:         Full listing list (modified in place).
        sources:          Which sources to enrich (default: all supported).
        force:            Re-fetch listings that already have DOM set.
        checkpoint_every: Call checkpoint_fn every N successful fetches.
        checkpoint_fn:    Optional callback(listings) for incremental saves.
    """
    if sources is None:
        sources = list(_DOM_EXTRACTORS.keys())

    to_enrich = [
        l for l in listings
        if l.get("source") in sources
        and l.get("url")
        and (force or l.get("days_on_market") is None)
    ]

    if not to_enrich:
        logger.info("DOM enrichment: all listings already have DOM data")
        return listings

    total = len(to_enrich)
    logger.info(f"DOM enrichment: fetching {total} detail pages ({', '.join(sources)})…")

    def fetch_one(listing: dict) -> tuple[dict, int | None]:
        soup = _fetch_html(listing["url"])
        if not soup:
            return listing, None
        extractor = _DOM_EXTRACTORS.get(listing.get("source", ""))
        return listing, extractor(soup) if extractor else None

    done = errors = 0
    lock = threading.Lock()
    last_checkpoint = 0

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(fetch_one, l): l for l in to_enrich}
        for future in as_completed(futures):
            try:
                listing, dom = future.result()
                if dom is not None:
                    listing["days_on_market"] = dom
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
                logger.debug(f"DOM fetch error: {e}")
                milestone = 0

            if milestone > 0:
                with lock:
                    if milestone > last_checkpoint:
                        last_checkpoint = milestone
                        do_checkpoint = True
                    else:
                        do_checkpoint = False
                if do_checkpoint:
                    logger.info(f"DOM enrichment: {milestone}/{total} done…")
                    if checkpoint_fn:
                        checkpoint_fn(listings)

    logger.info(f"DOM enrichment complete: {done} fetched, {errors} failed")
    return listings


# Keep old name as alias for backwards compatibility
def enrich_cincinky_dom(listings, force=False, checkpoint_every=50, checkpoint_fn=None):
    return enrich_dom(listings, sources=["cincinky"], force=force,
                      checkpoint_every=checkpoint_every, checkpoint_fn=checkpoint_fn)


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
    # Sources that need sequential (rate-limited) fetching to avoid Cloudflare blocks
    SLOW_SOURCES = {"comey"}
    SLOW_DELAY   = 1.0   # seconds between requests for slow sources

    to_enrich = [
        l for l in listings
        if l.get("url") and (force or not l.get("description"))
    ]

    if not to_enrich:
        logger.info("Description enrichment: all listings already have descriptions")
        return listings

    # Split into fast (parallel) and slow (sequential) batches
    fast_batch = [l for l in to_enrich if l.get("source") not in SLOW_SOURCES]
    slow_batch = [l for l in to_enrich if l.get("source") in SLOW_SOURCES]

    total = len(to_enrich)
    logger.info(
        f"Description enrichment: {total} listings "
        f"({len(fast_batch)} parallel, {len(slow_batch)} sequential for {', '.join(SLOW_SOURCES)})"
    )

    def fetch_one(listing: dict) -> tuple[dict, str]:
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

    def _handle_result(listing, desc):
        nonlocal done, errors, last_checkpoint
        if desc:
            listing["description"] = desc
            with lock:
                done += 1
                milestone = (done // checkpoint_every) * checkpoint_every
        else:
            with lock:
                errors += 1
            milestone = 0

        if milestone > 0:
            with lock:
                if milestone > last_checkpoint:
                    last_checkpoint = milestone
                    do_ckpt = True
                else:
                    do_ckpt = False
            if do_ckpt:
                logger.info(f"Description enrichment: {milestone}/{total} done…")
                if checkpoint_fn:
                    checkpoint_fn(listings)

    # Fast parallel pass
    if fast_batch:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(fetch_one, l): l for l in fast_batch}
            for future in as_completed(futures):
                try:
                    listing, desc = future.result()
                    _handle_result(listing, desc)
                except Exception as e:
                    with lock:
                        errors += 1
                    logger.debug(f"Fetch error: {e}")

    # Slow sequential pass (Comey etc. — Cloudflare blocks parallel requests)
    if slow_batch:
        logger.info(f"Description enrichment: starting sequential pass for {len(slow_batch)} listings…")
        for listing in slow_batch:
            try:
                _, desc = fetch_one(listing)
                _handle_result(listing, desc)
            except Exception as e:
                with lock:
                    errors += 1
                logger.debug(f"Fetch error: {e}")
            time.sleep(SLOW_DELAY)

    logger.info(f"Description enrichment complete: {done} fetched, {errors} failed")
    return listings


# ── Photo extraction ─────────────────────────────────────────────────────────

def _extract_photos_coldwell(html: str) -> list[str]:
    """
    Coldwell Banker — all photo URLs embedded in page HTML as:
    https://m[N].cbhomes.com/p/{num}/{num}/{HASH}/{format}.webp
    Deduplicate by hash, prefer m23cc then pdl23tp then full variants.
    """
    all_urls = re.findall(
        r'https://m\d*\.cbhomes\.com/p/\d+/\d+/[A-Za-z0-9]+/[a-z0-9]+\.[a-z]+',
        html,
    )
    # Build hash → best_url map
    PREF = {"m23cc": 3, "pdl23tp": 2, "full": 1}
    best: dict[str, tuple[int, str]] = {}
    for url in all_urls:
        parts = url.split("/")
        if len(parts) < 8:
            continue
        photo_hash = parts[6]          # unique per photo
        fmt_file   = parts[7]          # e.g. "m23cc.webp"
        score = next((v for k, v in PREF.items() if k in fmt_file), 0)
        if photo_hash not in best or score > best[photo_hash][0]:
            best[photo_hash] = (score, url)
    return [v for _, v in best.values()][:25]


def _extract_photos_cincinky(soup: BeautifulSoup) -> list[str]:
    """
    CincinKY (Sierra Interactive) — photos in img[src] with sierrastatic.com.
    Multiple DPI variants: pics1x, pics2x, pics3x, large.  Prefer large/.
    Deduplicate by photo identifier (e.g. 27_1835895_01).
    """
    best: dict[str, tuple[int, str]] = {}
    for img in soup.find_all("img"):
        src = img.get("src", "") or ""
        if "sierrastatic.com" not in src:
            continue
        m = re.search(r"(\d+_\d+_\d+)\.", src)
        if not m:
            continue
        photo_id = m.group(1)
        score = 3 if "/large/" in src else (2 if "pics3x" in src else (1 if "pics2x" in src else 0))
        if photo_id not in best or score > best[photo_id][0]:
            best[photo_id] = (score, src)
    return [v for _, v in best.values()][:25]


def _extract_photos_sibcy(html: str) -> list[str]:
    """
    Sibcy Cline — parse __NEXT_DATA__ JSON embedded in the listing detail page.
    Each photo has extraLargeImageUrl (1500px) or midSizeImageUrl.
    Falls back to regex scan if JSON parsing fails.
    """
    import json as _json
    # Primary: parse __NEXT_DATA__ (server-rendered, always present)
    nd_m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if nd_m:
        try:
            data = _json.loads(nd_m.group(1))
            photos_raw = (
                data.get("props", {})
                    .get("pageProps", {})
                    .get("photos", [])
            )
            seen: set[str] = set()
            photos = []
            for p in photos_raw:
                url = (p.get("extraLargeImageUrl") or p.get("midSizeImageUrl") or "").split("?")[0]
                if url and url not in seen:
                    seen.add(url)
                    photos.append(url)
            if photos:
                return photos[:60]
        except Exception:
            pass

    # Fallback: regex scan for retsphotos URLs, filter to primary listing's MLS ID
    all_urls = re.findall(
        r'https://online\.sibcycline\.com/retsphotos/[^\s"\'<>]+',
        html,
    )
    primary_id: str | None = None
    og_m = re.search(r'og:image.*?content=["\']https://online\.sibcycline\.com/retsphotos/[^/]+/(\d+)_', html)
    if og_m:
        primary_id = og_m.group(1)
    else:
        from collections import Counter
        id_counts: Counter = Counter()
        for u in all_urls:
            m = re.search(r'/(\d+)_\d+\.', u)
            if m:
                id_counts[m.group(1)] += 1
        if id_counts:
            primary_id = id_counts.most_common(1)[0][0]

    seen2: set[str] = set()
    photos2 = []
    for url in all_urls:
        if primary_id and f"/{primary_id}_" not in url:
            continue
        key = url.split("?")[0]
        if key not in seen2:
            seen2.add(key)
            photos2.append(key)
    return photos2[:60]


def _extract_photos_redfin(html: str, mls_number: str, data_source_id: str) -> list[str]:
    """
    Redfin — find max photo index from mbphotov3 thumbnail URLs embedded in the listing page,
    then build full-size bigphoto URLs.

    Page embeds URLs like:
      ssl.cdn-redfin.com/photo/158/mbphotov3/371/genMid.1874371_39_1.jpg
    We extract all {mls}_{index} pairs, find the highest index, and build:
      ssl.cdn-redfin.com/photo/{ds_id}/bigphoto/{last3}/{mls}_0.jpg     (index 0)
      ssl.cdn-redfin.com/photo/{ds_id}/bigphoto/{last3}/{mls}_{i}.jpg   (index 1+)
    """
    if not mls_number or not data_source_id:
        return []
    # Find all photo indices mentioned for this MLS number
    pattern = re.compile(rf'{re.escape(mls_number)}_(\d+)')
    indices = {int(m.group(1)) for m in pattern.finditer(html)}
    if not indices:
        return []
    max_index = max(indices)
    last3 = mls_number[-3:]
    base = f"https://ssl.cdn-redfin.com/photo/{data_source_id}/bigphoto/{last3}/{mls_number}"
    photos = [f"{base}_0.jpg"] + [f"{base}_{i}.jpg" for i in range(1, max_index + 1)]
    return photos


def _extract_photos_comey(soup: BeautifulSoup) -> list[str]:
    """
    Comey & Shepherd — photos in Splide carousel as data-splide-lazy attributes.
    URL pattern: https://cdn-idxphotos.mfm.com/propimgs/mls_*/full/{4}/{listingid}l[N].jpg?timestamp
    Deduplicate by stripping query string.
    """
    seen: set[str] = set()
    photos = []
    for el in soup.find_all(attrs={"data-splide-lazy": True}):
        src = el["data-splide-lazy"]
        if "cdn-idxphotos.mfm.com" not in src:
            continue
        key = src.split("?")[0]
        if key not in seen:
            seen.add(key)
            photos.append(key)
    return photos[:50]


# Sources that benefit from photo enrichment and what strategy to use
# redfin: GIS API provides photo count inline, but new listings may have stale counts;
#         only enrich listings with < 15 photos to catch under-photographed new listings.
_PHOTO_SOURCES = {"coldwell_banker", "cincinky", "sibcy_cline", "comey", "redfin"}
SLOW_PHOTO_SOURCES: set[str] = {"comey"}   # Comey blocks parallel requests
REDFIN_ENRICH_THRESHOLD = 15  # only enrich Redfin listings with fewer than this many photos


def enrich_photos(
    listings: list[dict],
    sources: list[str] | None = None,
    force: bool = False,
    checkpoint_every: int = 100,
    checkpoint_fn=None,
) -> list[dict]:
    """
    Visit each listing's detail page and extract all gallery photos.

    Supported sources: coldwell_banker (23+ photos), cincinky (15+ photos),
    sibcy_cline (all retsphotos), comey (Splide carousel).
    Redfin photos are built directly in the scraper from GIS metadata — no enrichment pass needed.

    Sets listing["images"] to the full gallery list and listing["photos_enriched"] = True.
    """
    if sources is None:
        sources = list(_PHOTO_SOURCES)

    to_enrich = [
        l for l in listings
        if l.get("source") in sources
        and l.get("url")
        and (force or not l.get("photos_enriched"))
        # Note: Redfin threshold removed — Redfin GIS API URLs expire, so all Redfin listings
        # must be enriched from the detail page to get stable, non-expiring photo URLs.
    ]

    if not to_enrich:
        logger.info("Photo enrichment: all listings already enriched")
        return listings

    # Split into fast (parallel) and slow (sequential) batches
    fast_batch = [l for l in to_enrich if l.get("source") not in SLOW_PHOTO_SOURCES]
    slow_batch = [l for l in to_enrich if l.get("source") in SLOW_PHOTO_SOURCES]

    total = len(to_enrich)
    logger.info(
        f"Photo enrichment: {total} listings "
        f"({len(fast_batch)} parallel, {len(slow_batch)} sequential for {', '.join(SLOW_PHOTO_SOURCES or ['none'])})…"
    )

    def fetch_one(listing: dict) -> tuple[dict, list[str]]:
        url    = listing["url"]
        source = listing.get("source", "")

        try:
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        except Exception as e:
            logger.debug(f"Photo fetch failed ({url[:80]}): {e}")
            return listing, []

        if source == "coldwell_banker":
            photos = _extract_photos_coldwell(resp.text)
        elif source == "cincinky":
            soup = BeautifulSoup(resp.text, "html.parser")
            photos = _extract_photos_cincinky(soup)
        elif source == "sibcy_cline":
            photos = _extract_photos_sibcy(resp.text)
        elif source == "comey":
            soup = BeautifulSoup(resp.text, "html.parser")
            photos = _extract_photos_comey(soup)
        elif source == "redfin":
            # Derive MLS number + dataSourceId: try existing image URLs first,
            # fall back to mbphotov3 URLs embedded in the listing page HTML.
            existing = (listing.get("images") or [])
            mls_num = ds_id = ""
            if existing:
                m = re.search(r'/photo/(\d+)/bigphoto/\d+/(\d+)_', existing[0])
                if m:
                    ds_id, mls_num = m.group(1), m.group(2)
            if not mls_num or not ds_id:
                # fallback: parse from mbphotov3 thumbnails in page HTML
                mb = re.search(
                    r'ssl\.cdn-redfin\.com/photo/(\d+)/mbphotov3/\d+/genMid\.(\d+)_',
                    resp.text,
                )
                if mb:
                    ds_id, mls_num = mb.group(1), mb.group(2)
            photos = _extract_photos_redfin(resp.text, mls_num, ds_id)
        else:
            photos = []
        return listing, photos

    done = errors = 0
    lock = threading.Lock()
    last_checkpoint = 0

    def _handle_photo_result(listing, photos):
        nonlocal done, errors, last_checkpoint
        listing["photos_enriched"] = True
        if photos:
            listing["images"] = photos
            with lock:
                done += 1
                milestone = (done // checkpoint_every) * checkpoint_every
        else:
            with lock:
                errors += 1
            milestone = 0

        if milestone > 0:
            with lock:
                if milestone > last_checkpoint:
                    last_checkpoint = milestone
                    do_ckpt = True
                else:
                    do_ckpt = False
            if do_ckpt:
                logger.info(f"Photo enrichment: {done}/{total} done…")
                if checkpoint_fn:
                    checkpoint_fn(listings)

    # Fast parallel pass
    if fast_batch:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(fetch_one, l): l for l in fast_batch}
            for future in as_completed(futures):
                try:
                    listing, photos = future.result()
                    _handle_photo_result(listing, photos)
                except Exception as e:
                    with lock:
                        errors += 1
                    logger.debug(f"Photo enrich error: {e}")

    # Slow pass (Comey etc.) — truly sequential with a polite delay to avoid blocks.
    # Comey blocks even 3 concurrent workers; 1 worker + 300ms delay is reliable.
    if slow_batch:
        logger.info(f"Photo enrichment: starting slow pass for {len(slow_batch)} listings (1 worker, 300ms delay)…")
        for listing in slow_batch:
            try:
                listing, photos = fetch_one(listing)
                _handle_photo_result(listing, photos)
            except Exception as e:
                with lock:
                    errors += 1
                logger.debug(f"Photo enrich error: {e}")
            time.sleep(0.3)

    logger.info(f"Photo enrichment complete: {done} enriched, {errors} failed/no-photos")
    return listings
