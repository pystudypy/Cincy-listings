"""
Coldwell Banker scraper for Cincinnati metro listings.

Covers Cincinnati OH (~1,800 listings across 75 pages) and major NKY cities
(Covington, Newport, Florence, Fort Thomas, Independence, Erlanger, etc.).

Static HTML — no JavaScript rendering or API auth needed.
Azure AppService host, reCAPTCHA V3 (non-blocking), just needs User-Agent.
"""

import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://www.coldwellbankerhomes.com"

# Search entry points — (label, base_path, max_pages)
SEARCH_TARGETS = [
    ("Cincinnati OH",    "/oh/cincinnati/",     80),
    ("Covington KY",     "/ky/covington/",      10),
    ("Newport KY",       "/ky/newport/",        10),
    ("Florence KY",      "/ky/florence/",       10),
    ("Fort Thomas KY",   "/ky/fort-thomas/",    10),
    ("Independence KY",  "/ky/independence/",   10),
    ("Erlanger KY",      "/ky/erlanger/",        8),
    ("Edgewood KY",      "/ky/edgewood/",        5),
    ("Villa Hills KY",   "/ky/villa-hills/",     5),
    ("Cold Spring KY",   "/ky/cold-spring/",     5),
    ("Alexandria KY",    "/ky/alexandria/",      5),
    ("Burlington KY",    "/ky/burlington/",      8),
    ("Union KY",         "/ky/union/",           8),
    ("Hebron KY",        "/ky/hebron/",          5),
    ("Walton KY",        "/ky/walton/",          5),
    ("Fort Mitchell KY", "/ky/fort-mitchell/",   5),
    ("Fort Wright KY",   "/ky/fort-wright/",     5),
    ("Bellevue KY",      "/ky/bellevue/",        5),
    ("Dayton KY",        "/ky/dayton/",          5),
    ("Silver Grove KY",  "/ky/silver-grove/",    3),
    ("Petersburg KY",    "/ky/petersburg/",      3),
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

PAGE_DELAY = 0.8  # seconds between requests


def _listing_id(address: str) -> str:
    key = f"coldwell_banker:{address.lower().strip()}"
    return hashlib.md5(key.encode()).hexdigest()[:16]


def _safe_int(val) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(re.sub(r"[^\d]", "", str(val)) or "0") or None
    except (ValueError, TypeError):
        return None


def _safe_float(val) -> Optional[float]:
    try:
        return float(val) or None
    except (ValueError, TypeError):
        return None


def _parse_card(card) -> Optional[dict]:
    try:
        street_el  = card.select_one(".street-address")
        city_el    = card.select_one(".city-st-zip")
        street = (street_el.get_text(strip=True) if street_el else "").replace("\u00a0", " ").strip()
        city_state_zip = (city_el.get_text(strip=True) if city_el else "").replace("\u00a0", " ").strip()

        if not street:
            return None

        csz_m = re.match(r"^(.*?),\s*([A-Z]{2})\s+(\d{5})", city_state_zip)
        if csz_m:
            city    = csz_m.group(1).strip()
            state   = csz_m.group(2)
            zipcode = csz_m.group(3)
        else:
            city, state, zipcode = city_state_zip, "", ""

        full_address = f"{street}, {city}, {state} {zipcode}".strip(", ")

        price_el = card.select_one(".price-normal")
        price = _safe_int(price_el.get_text() if price_el else None)

        beds  = _safe_int((card.select_one("li.beds .val") or card.select_one(".beds .val") or BeautifulSoup("", "lxml")).get_text() if card.select_one("li.beds .val") else None)
        baths_el = card.select_one("li.total-baths .val") or card.select_one("li.full-bath .val")
        baths = _safe_float(baths_el.get_text() if baths_el else None)
        sqft_el = card.select_one("li.sq-ft .val") or card.select_one("[class*='sq'] .val")
        sqft  = _safe_int(sqft_el.get_text() if sqft_el else None)

        # Image — data-src-psr (PSR = property snapshot)
        img = card.select_one("img[data-src-psr]") or card.select_one("img[data-src]")
        image_url = ""
        if img:
            image_url = img.get("data-src-psr") or img.get("data-src") or ""
            # Upgrade to medium size (replace /s23cc with /m23cc)
            image_url = image_url.replace("/s23cc", "/m23cc")
        images = [image_url] if image_url else []

        detail_path = card.get("data-detailurl", "")
        url = BASE_URL + detail_path if detail_path else ""

        lat = _safe_float(card.get("data-lat"))
        lng = _safe_float(card.get("data-lng"))

        # Status — appears as a plain <li> e.g. "Active", "Pending", "Contingent"
        _STATUS_VALS = {"active", "pending", "contingent", "under contract", "sold", "backup"}
        status = "FOR_SALE"
        for li in card.find_all("li"):
            txt = li.get_text(strip=True).lower()
            if txt in _STATUS_VALS:
                status = li.get_text(strip=True)
                break

        return {
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
            "status": status,
            "days_on_market": None,
            "images": images,
            "url": url,
            "source": "coldwell_banker",
            "lat": lat,
            "lng": lng,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.debug(f"Coldwell Banker card parse error: {e}")
        return None


def _scrape_target(session: requests.Session, label: str, base_path: str, max_pages: int) -> list[dict]:
    listings = []
    seen_ids: set[str] = set()

    for page in range(1, max_pages + 1):
        path = base_path if page == 1 else f"{base_path}p_{page}/"
        url = BASE_URL + path

        try:
            resp = session.get(url, headers=HEADERS, timeout=20)
            if resp.status_code == 404:
                break
            resp.raise_for_status()
        except Exception as e:
            logger.warning(f"Coldwell Banker {label} p{page}: {e}")
            break

        soup = BeautifulSoup(resp.text, "lxml")
        cards = soup.find_all("div", class_="property-snapshot-psr-panel")
        if not cards:
            break

        new = 0
        for card in cards:
            parsed = _parse_card(card)
            if parsed and parsed["id"] not in seen_ids:
                seen_ids.add(parsed["id"])
                listings.append(parsed)
                new += 1

        logger.info(f"Coldwell Banker {label} p{page}: {new} new listings (total {len(listings)})")
        time.sleep(PAGE_DELAY)

    return listings


def scrape() -> list[dict]:
    session = requests.Session()
    all_listings: list[dict] = []
    seen_ids: set[str] = set()

    for label, base_path, max_pages in SEARCH_TARGETS:
        results = _scrape_target(session, label, base_path, max_pages)
        for l in results:
            if l["id"] not in seen_ids:
                seen_ids.add(l["id"])
                all_listings.append(l)
        time.sleep(1)

    logger.info(f"Coldwell Banker: {len(all_listings)} total unique listings")
    return all_listings


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = scrape()
    print(f"\nGot {len(results)} listings")
    if results:
        print(json.dumps(results[0], indent=2))
