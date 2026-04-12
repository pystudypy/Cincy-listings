"""
Zillow scraper for Cincinnati, OH listings.

Zillow embeds listing data as JSON inside <script id="__NEXT_DATA__"> on their
search pages. We extract that blob and normalize it into our common schema.
Pagination is handled by stepping through Zillow's internal search API.
"""

import json
import re
import time
import hashlib
import logging
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Cincinnati bounding box for Zillow search
SEARCH_URL = "https://www.zillow.com/cincinnati-oh/"
SEARCH_QUERY_STATE = {
    "pagination": {},
    "isMapVisible": True,
    "filterState": {
        "sort": {"value": "days"},
        "fsba": {"value": False},
        "fsbo": {"value": False},
        "nc": {"value": False},
        "cmsn": {"value": False},
        "auc": {"value": False},
        "fore": {"value": False},
    },
    "isListVisible": True,
    "mapZoom": 11,
    "regionSelection": [{"regionId": 14639, "regionType": 6}],
}


def _make_listing_id(address: str, source: str = "zillow") -> str:
    key = f"{source}:{address.lower().strip()}"
    return hashlib.md5(key.encode()).hexdigest()[:16]


def _parse_price(raw) -> Optional[int]:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return int(raw)
    cleaned = re.sub(r"[^\d]", "", str(raw))
    return int(cleaned) if cleaned else None


def _parse_listing(item: dict) -> Optional[dict]:
    """Convert a raw Zillow listing dict to our common schema."""
    try:
        address_parts = []
        if item.get("streetAddress"):
            address_parts.append(item["streetAddress"])
        if item.get("city"):
            address_parts.append(item["city"])
        if item.get("state"):
            address_parts.append(item["state"])
        if item.get("zipcode"):
            address_parts.append(item["zipcode"])

        full_address = ", ".join(address_parts) if address_parts else item.get("address", "")
        if not full_address:
            return None

        price = _parse_price(item.get("price") or item.get("unformattedPrice"))

        listing = {
            "id": _make_listing_id(full_address),
            "address": item.get("streetAddress", ""),
            "city": item.get("city", "Cincinnati"),
            "state": item.get("state", "OH"),
            "zip": item.get("zipcode", ""),
            "price": price,
            "beds": item.get("beds") or item.get("bedrooms"),
            "baths": item.get("baths") or item.get("bathrooms"),
            "sqft": item.get("area") or item.get("livingArea"),
            "lot_size": item.get("lotAreaValue"),
            "property_type": item.get("homeType", ""),
            "status": item.get("statusType", "FOR_SALE"),
            "days_on_market": item.get("daysOnZillow"),
            "images": [item["imgSrc"]] if item.get("imgSrc") else [],
            "url": f"https://www.zillow.com{item['detailUrl']}" if item.get("detailUrl") else "",
            "source": "zillow",
            "lat": item.get("latLong", {}).get("latitude") if isinstance(item.get("latLong"), dict) else item.get("latitude"),
            "lng": item.get("latLong", {}).get("longitude") if isinstance(item.get("latLong"), dict) else item.get("longitude"),
            "last_updated": datetime.utcnow().isoformat(),
        }
        return listing
    except Exception as e:
        logger.debug(f"Failed to parse listing: {e}")
        return None


def _extract_from_next_data(html: str) -> list[dict]:
    """Pull listings out of the __NEXT_DATA__ JSON blob embedded in the page."""
    soup = BeautifulSoup(html, "lxml")
    script = soup.find("script", {"id": "__NEXT_DATA__"})
    if not script or not script.string:
        return []

    try:
        data = json.loads(script.string)
    except json.JSONDecodeError:
        return []

    # Navigate the nested structure — Zillow's shape changes, so we try multiple paths
    paths = [
        ["props", "pageProps", "searchPageState", "cat1", "searchResults", "listResults"],
        ["props", "pageProps", "searchPageState", "cat1", "searchResults", "mapResults"],
        ["props", "pageProps", "initialData", "cat1", "searchResults", "listResults"],
    ]

    for path in paths:
        node = data
        try:
            for key in path:
                node = node[key]
            if isinstance(node, list) and node:
                return node
        except (KeyError, TypeError):
            continue

    return []


def _extract_search_results_api(session: requests.Session, page: int = 1) -> list[dict]:
    """
    Use Zillow's internal search API to get paginated results.
    URL: https://www.zillow.com/async-create-search-page-state
    """
    query_state = SEARCH_QUERY_STATE.copy()
    if page > 1:
        query_state["pagination"] = {"currentPage": page}

    params = {
        "searchQueryState": json.dumps(query_state),
        "wants": json.dumps({"cat1": ["listResults", "mapResults"], "cat2": ["total"]}),
        "requestId": page,
        "qs": "",
    }

    api_headers = {
        **HEADERS,
        "Accept": "application/json",
        "Referer": "https://www.zillow.com/cincinnati-oh/",
    }

    try:
        resp = session.get(
            "https://www.zillow.com/async-create-search-page-state",
            params=params,
            headers=api_headers,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        results = (
            data.get("cat1", {})
            .get("searchResults", {})
            .get("listResults", [])
        )
        return results
    except Exception as e:
        logger.warning(f"Zillow API page {page} failed: {e}")
        return []


def scrape(max_pages: int = 5) -> list[dict]:
    """
    Scrape Cincinnati listings from Zillow.
    Returns a list of normalized listing dicts.
    """
    listings = []
    session = requests.Session()
    session.headers.update(HEADERS)

    logger.info("Zillow: fetching first page via HTML...")
    try:
        resp = session.get(SEARCH_URL, timeout=20)
        resp.raise_for_status()
        raw = _extract_from_next_data(resp.text)
        logger.info(f"Zillow: got {len(raw)} listings from page HTML")
    except Exception as e:
        logger.warning(f"Zillow: HTML fetch failed ({e}), falling back to API")
        raw = []

    # If HTML extraction worked, also try the API for additional pages
    all_raw = raw
    if not raw:
        # Try the API directly
        for page in range(1, max_pages + 1):
            logger.info(f"Zillow: API page {page}...")
            page_results = _extract_search_results_api(session, page)
            if not page_results:
                break
            all_raw.extend(page_results)
            time.sleep(2)

    for item in all_raw:
        parsed = _parse_listing(item)
        if parsed:
            listings.append(parsed)

    logger.info(f"Zillow: {len(listings)} listings parsed")
    return listings


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = scrape(max_pages=2)
    print(f"Got {len(results)} listings")
    if results:
        print(json.dumps(results[0], indent=2))
