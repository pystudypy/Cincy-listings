"""
Redfin scraper for Cincinnati, OH listings.

Uses Redfin's internal GIS/stingray API with a bounding-box polygon search.
No authentication required — same calls the browser makes.
"""

import hashlib
import json
import logging
import re
import time
from datetime import datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.redfin.com/city/3684/OH/Cincinnati",
}

BASE_SEARCH_URL = "https://www.redfin.com/stingray/api/gis"

# Cincinnati metro bounding box — split into tiles to get past the 350-result cap
# Each tile is a polygon string: "lng1 lat1,lng2 lat1,lng2 lat2,lng1 lat2,lng1 lat1"
CINCINNATI_TILES = [
    # NW quadrant
    "-84.75 39.10,-84.50 39.10,-84.50 39.35,-84.75 39.35,-84.75 39.10",
    # NE quadrant
    "-84.50 39.10,-84.25 39.10,-84.25 39.35,-84.50 39.35,-84.50 39.10",
    # SW quadrant (includes NKY)
    "-84.75 38.85,-84.50 38.85,-84.50 39.10,-84.75 39.10,-84.75 38.85",
    # SE quadrant
    "-84.50 38.85,-84.25 38.85,-84.25 39.10,-84.50 39.10,-84.50 38.85",
]


def _make_listing_id(address: str, source: str = "redfin") -> str:
    key = f"{source}:{address.lower().strip()}"
    return hashlib.md5(key.encode()).hexdigest()[:16]


def _safe_int(val) -> Optional[int]:
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _safe_float(val) -> Optional[float]:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _unwrap(field) -> Optional[any]:
    """Redfin wraps many fields as {'value': X, 'level': N}. Unwrap them."""
    if isinstance(field, dict):
        return field.get("value")
    return field


def _parse_listing(item: dict) -> Optional[dict]:
    """Normalize a Redfin GIS result item to our common schema."""
    try:
        street = _unwrap(item.get("streetLine")) or ""
        city   = _unwrap(item.get("city")) or "Cincinnati"
        state  = _unwrap(item.get("state")) or "OH"
        zipcode = str(_unwrap(item.get("zip")) or "")

        if not street:
            return None

        full_address = f"{street}, {city}, {state} {zipcode}".strip(", ")

        price = _safe_int(_unwrap(item.get("price")))

        # beds/baths can be direct values or wrapped
        beds  = _safe_int(_unwrap(item.get("beds")))
        baths = _safe_float(_unwrap(item.get("baths")))
        sqft  = _safe_int(_unwrap(item.get("sqFt")))

        # latLong is {"value": {"latitude": X, "longitude": Y}, "level": N}
        ll = _unwrap(item.get("latLong"))
        lat = _safe_float(ll.get("latitude") if isinstance(ll, dict) else None)
        lng = _safe_float(ll.get("longitude") if isinstance(ll, dict) else None)

        url_path = item.get("url", "")
        url = f"https://www.redfin.com{url_path}" if url_path else ""

        # Photos — reconstruct full gallery from GIS metadata
        # photos.value is a range string like "0-52:0" → 53 photos at index 0..52
        # URL pattern: ssl.cdn-redfin.com/photo/{dataSourceId}/bigphoto/{last3}/{mls}_{i}.jpg
        #   index 0  → {mls}_0.jpg
        #   index 1+ → {mls}_{i}_0.jpg
        images = []
        mls_raw  = item.get("mlsId") or {}
        mls_num  = str(mls_raw.get("value", "") if isinstance(mls_raw, dict) else mls_raw)
        ds_id    = item.get("dataSourceId", "")
        photos_raw = item.get("photos") or {}
        photos_val = (photos_raw.get("value", "") if isinstance(photos_raw, dict) else str(photos_raw)) or ""
        _m = re.match(r"(\d+)-(\d+)", photos_val)
        if _m and mls_num and ds_id:
            count  = int(_m.group(2)) - int(_m.group(1)) + 1
            last3  = mls_num[-3:]
            base   = f"https://ssl.cdn-redfin.com/photo/{ds_id}/bigphoto/{last3}/{mls_num}"
            images = (
                [f"{base}_0.jpg"] +
                [f"{base}_{i}.jpg" for i in range(1, count)]
            )

        dom_raw = item.get("dom")
        days_on_market = _safe_int(_unwrap(dom_raw))

        property_type_map = {
            1: "Single Family", 2: "Condo", 3: "Townhouse",
            4: "Multi-Family",  5: "Land",  6: "Other",
        }
        prop_type_code = item.get("propertyType")
        property_type = property_type_map.get(prop_type_code, str(prop_type_code) if prop_type_code else "")

        status = item.get("mlsStatus") or "FOR_SALE"
        description = (item.get("listingRemarks") or "").strip() or None

        listing = {
            "id": _make_listing_id(full_address),
            "address": street,
            "city": str(city),
            "state": str(state),
            "zip": zipcode,
            "price": price,
            "beds": beds,
            "baths": baths,
            "sqft": sqft,
            "lot_size": None,
            "property_type": property_type,
            "status": status,
            "days_on_market": days_on_market,
            "images": images,
            "url": url,
            "source": "redfin",
            "lat": lat,
            "lng": lng,
            "last_updated": datetime.utcnow().isoformat(),
        }
        if description:
            listing["description"] = description
        return listing
    except Exception as e:
        logger.debug(f"Redfin parse error: {e}")
        return None


def _fetch_tile(session: requests.Session, polygon: str, num: int = 350) -> list[dict]:
    params = {
        "al": 1,
        "num": num,
        "poly": polygon,
        "status": 9,
        "uipt": "1,2,3,4,5,6,7,8",
        "v": 8,
    }

    try:
        resp = session.get(BASE_SEARCH_URL, params=params, headers=HEADERS, timeout=20)
        resp.raise_for_status()

        text = resp.text
        if text.startswith("{}&&"):
            text = text[4:]

        data = json.loads(text)

        # "Success" is Redfin's way of saying OK — only bail on actual errors
        error_msg = data.get("errorMessage", "")
        if error_msg and error_msg.lower() not in ("success", "ok", ""):
            logger.warning(f"Redfin error: {error_msg}")
            return []

        homes = data.get("payload", {}).get("homes", [])
        logger.info(f"Redfin tile: {len(homes)} homes")
        return homes

    except Exception as e:
        logger.warning(f"Redfin tile fetch failed: {e}")
        return []


def scrape(max_listings: int = 1400) -> list[dict]:
    """
    Scrape Cincinnati metro listings from Redfin using tiled bounding boxes.
    Returns a list of normalized listing dicts.
    """
    session = requests.Session()
    listings = []
    seen_ids = set()

    for i, tile in enumerate(CINCINNATI_TILES):
        if len(listings) >= max_listings:
            break
        logger.info(f"Redfin: tile {i+1}/{len(CINCINNATI_TILES)}...")
        raw_homes = _fetch_tile(session, tile)

        for item in raw_homes:
            parsed = _parse_listing(item)
            if parsed and parsed["id"] not in seen_ids:
                seen_ids.add(parsed["id"])
                listings.append(parsed)

        if i < len(CINCINNATI_TILES) - 1:
            time.sleep(2)

    logger.info(f"Redfin: {len(listings)} listings total")
    return listings


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = scrape()
    print(f"Got {len(results)} listings")
    if results:
        print(json.dumps(results[0], indent=2))
