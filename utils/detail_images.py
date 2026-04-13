"""
Detail page image enrichment.

For listings above a price threshold that only have a thumbnail,
visits the listing's detail URL and extracts all gallery images.

Supports: Coldwell Banker, Comey, Sibcy Cline, Redfin, CincinKY, Huff,
and a generic fallback for anything else.
"""

import logging
import re
import time
import json

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

REQUEST_DELAY = 0.6   # seconds between requests
MAX_IMAGES    = 25    # max images to store per listing


def _fetch_html(session: requests.Session, url: str) -> BeautifulSoup | None:
    try:
        resp = session.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    except Exception as e:
        logger.debug(f"Detail fetch failed ({url[:80]}): {e}")
        return None


def _extract_coldwell_banker(soup: BeautifulSoup) -> list[str]:
    """Coldwell Banker detail page — images in data-src-psr / data-src on gallery items."""
    imgs = []
    # Main gallery carousel items
    for el in soup.select("[data-src-psr], [data-src-large], [data-src]"):
        for attr in ("data-src-large", "data-src-psr", "data-src"):
            val = el.get(attr, "")
            if val and val not in imgs:
                # Upgrade to large size
                val = val.replace("/s23cc", "/l23cc").replace("/m23cc", "/l23cc")
                imgs.append(val)
    return imgs[:MAX_IMAGES]


def _extract_comey(soup: BeautifulSoup) -> list[str]:
    """Comey & Shepherd — images in JSON-LD or og:image or gallery divs."""
    imgs = _extract_json_ld_images(soup)
    if not imgs:
        imgs = _extract_og_images(soup)
    if not imgs:
        # Try common gallery img tags
        for el in soup.select(".gallery img, .photos img, .carousel img, .slider img"):
            src = el.get("data-src") or el.get("src") or ""
            if src and src not in imgs and not src.startswith("data:"):
                imgs.append(src)
    return imgs[:MAX_IMAGES]


def _extract_sibcy(soup: BeautifulSoup) -> list[str]:
    """Sibcy Cline — images often in JSON or og tags."""
    imgs = _extract_json_ld_images(soup)
    if not imgs:
        imgs = _extract_og_images(soup)
    if not imgs:
        for el in soup.select("img[data-src], img[src]"):
            src = el.get("data-src") or el.get("src") or ""
            if src and "photo" in src.lower() and src not in imgs:
                imgs.append(src)
    return imgs[:MAX_IMAGES]


def _extract_redfin(soup: BeautifulSoup) -> list[str]:
    """Redfin — images often embedded in a JSON blob in a <script> tag."""
    imgs = []
    for script in soup.find_all("script"):
        text = script.string or ""
        # Redfin embeds photos as photoUrls or similar
        matches = re.findall(r'"(https://ssl\.cdn-redfin\.com[^"]+\.(?:jpg|jpeg|webp|png))"', text)
        for url in matches:
            if url not in imgs:
                imgs.append(url)
        if imgs:
            break
    if not imgs:
        imgs = _extract_og_images(soup)
    return imgs[:MAX_IMAGES]


def _extract_cincinky(soup: BeautifulSoup) -> list[str]:
    """CincinKY — images in gallery or slideshow elements."""
    imgs = []
    for el in soup.select(".photos img, .gallery img, .listing-photos img, img[data-src]"):
        src = el.get("data-src") or el.get("src") or ""
        if src and not src.startswith("data:") and src not in imgs:
            imgs.append(src)
    if not imgs:
        imgs = _extract_og_images(soup)
    return imgs[:MAX_IMAGES]


def _extract_huff(soup: BeautifulSoup) -> list[str]:
    """Huff Realty — Blazor-rendered, try og:image and script JSON."""
    imgs = _extract_og_images(soup)
    if not imgs:
        imgs = _extract_json_ld_images(soup)
    return imgs[:MAX_IMAGES]


def _extract_json_ld_images(soup: BeautifulSoup) -> list[str]:
    """Generic: pull images from JSON-LD structured data."""
    imgs = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            # data can be a list or dict
            items = data if isinstance(data, list) else [data]
            for item in items:
                # RealEstateListing or Product schema often has "image"
                image_field = item.get("image") or []
                if isinstance(image_field, str):
                    image_field = [image_field]
                for img in image_field:
                    url = img.get("url", img) if isinstance(img, dict) else img
                    if isinstance(url, str) and url not in imgs:
                        imgs.append(url)
        except Exception:
            pass
    return imgs


def _extract_og_images(soup: BeautifulSoup) -> list[str]:
    """Generic: pull all og:image meta tags."""
    imgs = []
    for tag in soup.find_all("meta", property="og:image"):
        val = tag.get("content", "")
        if val and val not in imgs:
            imgs.append(val)
    return imgs


def _extract_generic(soup: BeautifulSoup) -> list[str]:
    """Fallback: JSON-LD → og:image → large img tags."""
    imgs = _extract_json_ld_images(soup)
    if not imgs:
        imgs = _extract_og_images(soup)
    if not imgs:
        # Grab any img wider than thumbnail (heuristic: skip small icons/logos)
        for el in soup.find_all("img"):
            src = el.get("data-src") or el.get("src") or ""
            if not src or src.startswith("data:"):
                continue
            # Skip tiny images (logos, icons) by checking width attribute or URL patterns
            width = el.get("width") or el.get("data-width") or 0
            try:
                if int(width) < 200:
                    continue
            except (ValueError, TypeError):
                pass
            if any(skip in src.lower() for skip in ["logo", "icon", "avatar", "sprite", "map"]):
                continue
            if src not in imgs:
                imgs.append(src)
    return imgs[:MAX_IMAGES]


# Source → extractor function map
_EXTRACTORS = {
    "coldwell_banker":     _extract_coldwell_banker,
    "comey":               _extract_comey,
    "sibcy_cline":         _extract_sibcy,
    "redfin":              _extract_redfin,
    "cincinky":            _extract_cincinky,
    "huff":                _extract_huff,
    "listings_cincinnati": _extract_generic,
    "zillow":              _extract_generic,
}


def enrich_images(
    listings: list[dict],
    min_price: int = 500_000,
    force: bool = False,
) -> list[dict]:
    """
    For listings >= min_price that have only 1 image (the thumbnail),
    visit the detail URL and pull all gallery images.

    Args:
        listings:  Full listing list (modified in place).
        min_price: Only enrich listings at or above this price.
        force:     Re-fetch even if listing already has multiple images.

    Returns:
        The same listings list with enriched image arrays.
    """
    session = requests.Session()

    targets = [
        l for l in listings
        if (l.get("price") or 0) >= min_price
        and l.get("url")
        and (force or len(l.get("images") or []) <= 1)
    ]

    if not targets:
        logger.info("Detail image enrichment: nothing to enrich")
        return listings

    logger.info(f"Detail image enrichment: fetching gallery for {len(targets)} listings…")

    done = 0
    for listing in targets:
        url = listing["url"]
        source = listing.get("source", "")
        extractor = _EXTRACTORS.get(source, _extract_generic)

        soup = _fetch_html(session, url)
        if not soup:
            time.sleep(REQUEST_DELAY)
            continue

        imgs = extractor(soup)

        if imgs:
            # Preserve the original thumbnail if not already in the list
            existing = listing.get("images") or []
            merged = list(dict.fromkeys(existing + imgs))  # deduplicate, preserve order
            listing["images"] = merged[:MAX_IMAGES]
            done += 1
            logger.debug(f"  {listing.get('address','?')} → {len(listing['images'])} images")

        time.sleep(REQUEST_DELAY)

    logger.info(f"Detail image enrichment: {done}/{len(targets)} listings enriched")
    return listings
