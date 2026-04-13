"""
Scraper for cincinkyrealestate.com — Cincinnati & NKY listings via Sierra Interactive IDX.

Iterates through all 83+ community pages listed at /communities/.
Each page is static HTML (server-side rendered), no JavaScript rendering needed.
Cloudflare is present but lenient — a proper User-Agent is sufficient.
"""

import hashlib
import json
import logging
import re
import time
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL  = "https://www.cincinkyrealestate.com"
COMMUNITIES_URL = f"{BASE_URL}/communities/"
REQUEST_DELAY = 0.8  # seconds between page requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def _listing_id(address: str) -> str:
    key = f"cincinky:{address.lower().strip()}"
    return hashlib.md5(key.encode()).hexdigest()[:16]


def _safe_int(val) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(re.sub(r"[^\d]", "", str(val)) or "0") or None
    except (ValueError, TypeError):
        return None


def _parse_baths(span) -> Optional[float]:
    """
    Baths on this site can be formatted as:
      "2"           → 2.0
      "1 1/2"       → 1.5
      "3F1 1/2"     → 3.5  (3 full + 1 half)
    The <small> tags hold "F" and fraction labels; get_text joins them.
    """
    if span is None:
        return None
    text = span.get_text(" ", strip=True)
    half = 0.5 if "1/2" in text else 0.0
    full_m = re.search(r"(\d+)\s*F", text, re.IGNORECASE)
    if full_m:
        return float(full_m.group(1)) + half
    nums = re.findall(r"\d+", text)
    return float(nums[0]) + half if nums else None


def _get_community_urls(session: requests.Session) -> list[str]:
    """Scrape the /communities/ page and return all community URLs."""
    try:
        resp = session.get(COMMUNITIES_URL, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        urls = []
        seen = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            # Keep only internal community-style paths
            if href.startswith("/") and href not in ("/", "/communities/"):
                full = BASE_URL + href.rstrip("/") + "/"
                if full not in seen:
                    seen.add(full)
                    urls.append(full)
            elif href.startswith(BASE_URL) and "/communities" not in href:
                if href not in seen:
                    seen.add(href)
                    urls.append(href)
        logger.info(f"CincinKY: found {len(urls)} community URLs")
        return urls
    except Exception as e:
        logger.error(f"CincinKY: failed to fetch communities page — {e}")
        return []


def _parse_listings_from_page(html: str, community_url: str) -> list[dict]:
    """Parse all listing cards from a community page."""
    soup = BeautifulSoup(html, "lxml")
    cards = soup.find_all("div", class_="si-listing")
    listings = []

    for card in cards:
        try:
            # Price
            price_span = card.select_one(".si-listing__photo-price > span")
            price = _safe_int(price_span.get_text() if price_span else None)

            # Address
            street_el  = card.select_one(".si-listing__title-main")
            city_el    = card.select_one(".si-listing__title-description")
            street = street_el.get_text(strip=True) if street_el else ""
            city_state_zip = city_el.get_text(strip=True) if city_el else ""

            if not street:
                continue

            # Parse "Cincinnati, OH 45208"
            csz_m = re.match(r"^(.*?),\s*([A-Z]{2})\s+(\d{5})", city_state_zip)
            if csz_m:
                city    = csz_m.group(1).strip()
                state   = csz_m.group(2)
                zipcode = csz_m.group(3)
            else:
                city, state, zipcode = city_state_zip, "OH", ""

            full_address = f"{street}, {city}, {state} {zipcode}".strip(", ")

            # Beds / Baths / Sqft — three info divs in order
            info_divs = card.select(".si-listing__info > div")
            beds  = None
            baths = None
            sqft  = None
            if len(info_divs) >= 1:
                v = info_divs[0].select_one(".si-listing__info-value span")
                beds = _safe_int(v.get_text() if v else None)
            if len(info_divs) >= 2:
                v = info_divs[1].select_one(".si-listing__info-value span")
                baths = _parse_baths(v)
            if len(info_divs) >= 3:
                v = info_divs[2].select_one(".si-listing__info-value span")
                sqft = _safe_int(v.get_text() if v else None)

            # Image — lazy-loaded via data-src
            img = card.select_one("img.si-listing-photo")
            image_url = img.get("data-src", "") if img else ""
            images = [image_url] if image_url else []

            # Detail page URL
            link = card.get("data-url") or ""
            url = BASE_URL + link if link.startswith("/") else link

            listings.append({
                "id": _listing_id(full_address),
                "address": street,
                "city": city,
                "state": state,
                "zip": zipcode,
                "price": price,
                "beds": beds,
                "baths": baths,
                "sqft": sqft,
                "lot_size": None,
                "property_type": "",
                "status": "FOR_SALE",
                "days_on_market": None,
                "images": images,
                "url": url,
                "source": "cincinky",
                "lat": None,
                "lng": None,
                "last_updated": datetime.utcnow().isoformat(),
            })
        except Exception as e:
            logger.debug(f"CincinKY: card parse error — {e}")

    return listings


def scrape() -> list[dict]:
    """Scrape all community pages on cincinkyrealestate.com."""
    session = requests.Session()
    community_urls = _get_community_urls(session)

    if not community_urls:
        return []

    all_listings: list[dict] = []
    seen_ids: set[str] = set()

    for i, url in enumerate(community_urls):
        try:
            resp = session.get(url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            page_listings = _parse_listings_from_page(resp.text, url)
            new = 0
            for l in page_listings:
                if l["id"] not in seen_ids:
                    seen_ids.add(l["id"])
                    all_listings.append(l)
                    new += 1
            if new:
                logger.info(f"CincinKY [{i+1}/{len(community_urls)}] {url.split('/')[-2]}: {new} listings")
        except Exception as e:
            logger.warning(f"CincinKY: failed to scrape {url} — {e}")

        time.sleep(REQUEST_DELAY)

    logger.info(f"CincinKY: {len(all_listings)} total unique listings")
    return all_listings


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = scrape()
    print(f"\nGot {len(results)} listings")
    if results:
        print(json.dumps(results[0], indent=2))
