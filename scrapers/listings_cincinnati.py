"""
Scraper for listingscincinnati.com — Cincinnati MLS listings via Brivity/BlueRoof.

The site embeds all listings as HTML-entity-encoded JSON in the page HTML.
No pagination needed — all ~100 active listings load on the first request.
No Cloudflare or bot protection.
"""

import hashlib
import json
import logging
import re
from datetime import datetime
from html import unescape
from typing import Optional

import requests

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.listingscincinnati.com/house-for-sale/"

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
    key = f"listings_cincinnati:{address.lower().strip()}"
    return hashlib.md5(key.encode()).hexdigest()[:16]


def _safe_int(val) -> Optional[int]:
    try:
        return int(val) or None
    except (TypeError, ValueError):
        return None


def _safe_float(val) -> Optional[float]:
    try:
        return float(val) or None
    except (TypeError, ValueError):
        return None


def _parse_listing(item: dict) -> Optional[dict]:
    try:
        street  = item.get("streetAddress", "")
        city    = item.get("city", "")
        state   = item.get("state", "OH")
        zipcode = str(item.get("postalCode", ""))

        if not street:
            return None

        # Skip non-active listings
        status = item.get("standardStatus", "")
        if status.lower() not in ("active", ""):
            return None

        full_address = f"{street}, {city}, {state} {zipcode}".strip(", ")

        # Photos are sorted by order field
        photos = sorted(item.get("photos") or [], key=lambda p: p.get("order", 0))
        images = [p["url"] for p in photos[:1] if p.get("url")]

        return {
            "id": _listing_id(full_address),
            "address": street,
            "city": city,
            "state": state,
            "zip": zipcode,
            "price": _safe_int(item.get("price")),
            "beds": _safe_int(item.get("bedrooms")),
            "baths": _safe_float(item.get("bathsTotalDecimal")),
            "sqft": _safe_int(item.get("squareFeet")),
            "lot_size": None,
            "property_type": item.get("standardPropertyType", ""),
            "status": "FOR_SALE",
            "days_on_market": None,
            "images": images,
            "url": SEARCH_URL,
            "source": "listings_cincinnati",
            "lat": _safe_float(item.get("lat")),
            "lng": _safe_float(item.get("lng")),
            "last_updated": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.debug(f"ListingsCincinnati parse error: {e}")
        return None


def scrape() -> list[dict]:
    """Scrape listingscincinnati.com and return normalized listing dicts."""
    try:
        resp = requests.get(SEARCH_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"ListingsCincinnati: failed to fetch page — {e}")
        return []

    decoded = unescape(resp.text)

    # Extract the listings_response JSON object embedded in the page
    idx = decoded.find('"listings_response":')
    if idx == -1:
        logger.error("ListingsCincinnati: could not find listings_response in page")
        return []

    try:
        obj = json.JSONDecoder().raw_decode(decoded, idx + len('"listings_response":'))[0]
    except Exception as e:
        logger.error(f"ListingsCincinnati: JSON parse error — {e}")
        return []

    raw = obj.get("listings", [])
    logger.info(f"ListingsCincinnati: {len(raw)} raw listings")

    listings = []
    seen_ids = set()
    for item in raw:
        parsed = _parse_listing(item)
        if parsed and parsed["id"] not in seen_ids:
            seen_ids.add(parsed["id"])
            listings.append(parsed)

    logger.info(f"ListingsCincinnati: {len(listings)} listings after parsing")
    return listings


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = scrape()
    print(f"\nGot {len(results)} listings")
    if results:
        print(json.dumps(results[0], indent=2))
