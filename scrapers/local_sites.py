"""
Scrapers for Cincinnati-area local real estate sites.

Covers:
  - Sibcy Cline (sibcycline.com) — largest Cincinnati/Dayton brokerage
  - Comey & Shepherd (comey.com) — Cincinnati/NKY brokerage using mfmidx
    WordPress plugin backed by the Cincinnati MLS and Northern KY MLS

Each scraper returns a list of normalized listing dicts using the same schema
as zillow.py and redfin.py so the deduplicator can work across all sources.
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

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)

# All cities/neighborhoods in the Cincinnati metro area
CINCINNATI_CITIES = {
    "Cincinnati", "Covington", "Newport", "Florence", "Blue Ash", "Norwood",
    "Mason", "West Chester", "Hyde Park", "Anderson", "Delhi", "Loveland",
    "Madeira", "Mariemont", "Montgomery", "Indian Hill", "Clifton", "Oakley",
    "Mt. Lookout", "Price Hill", "Westwood", "Pleasant Ridge", "Milford",
    "Kenwood", "Amberley Village", "Silverton", "Deer Park", "Golf Manor",
    "Reading", "Sharonville", "Springdale", "Forest Park", "Finneytown",
    "Colerain", "Cheviot", "Cleves", "North Bend", "Anderson Township",
    "Delhi Township", "Green Township", "Sycamore Township", "Columbia Township",
    "Miami Township", "Harrison", "Morrow", "Maineville", "Landen", "Symmes",
    "Dent", "Groesbeck", "Winton Place", "Avondale", "Mt. Auburn",
    "Over-the-Rhine", "OTR", "East Walnut Hills", "Walnut Hills", "Evanston",
    "College Hill", "Roselawn", "Bond Hill", "Paddock Hills", "Hartwell",
    "Kennedy Heights", "Madisonville", "Mt. Washington", "California",
    "Newtown", "Terrace Park", "Fairfax", "Columbia-Tusculum", "Linwood",
    "Pendleton", "Corryville", "Mohawk", "Camp Washington",
    "Lower Price Hill", "Sedamsville", "Sayler Park", "Riverside", "Addyston",
    "Erlanger", "Independence", "Fort Mitchell", "Fort Thomas",
    "Highland Heights", "Edgewood", "Lakeside Park", "Villa Hills",
    "Crescent Springs", "Taylor Mill", "Cold Spring", "Alexandria",
    "Wilder", "Bellevue", "Silver Grove", "Woodlawn", "Lincoln Heights",
    "Lockland", "Evendale", "Glendale", "Wyoming", "White Oak", "Bridgetown",
    "Mack", "Clippard", "Dunlap", "Ryland Heights", "Visalia", "Elsmere",
    "Park Hills", "Bromley", "Ludlow", "Latonia", "Burlington", "Florence",
    "Union", "Hebron", "Walton", "Morning View", "Verona",
    "Colerain Twp", "Colerain Township", "Delhi Twp", "Delhi Township",
    "Anderson Twp", "Anderson Township", "Milford Twp", "Milford Township",
    "Miami Twp", "Miami Township", "Hamilton Township",
}


def _listing_id(address: str, source: str) -> str:
    key = f"{source}:{address.lower().strip()}"
    return hashlib.md5(key.encode()).hexdigest()[:16]


def _safe_int(val) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(re.sub(r"[^\d]", "", str(val)) or 0) or None
    except (ValueError, TypeError):
        return None


def _safe_float(val) -> Optional[float]:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _is_cincinnati(listing: dict) -> bool:
    city = listing.get("city", "")
    zipcode = str(listing.get("zip", ""))[:5]
    if city in CINCINNATI_CITIES:
        return True
    if zipcode.startswith("452") or zipcode.startswith("451") or zipcode.startswith("450"):
        return True
    if zipcode.startswith("410") or zipcode.startswith("411"):
        return True
    return False


# ---------------------------------------------------------------------------
# Comey & Shepherd — comey.com
#
# Uses the mfmidx WordPress plugin with a WP-AJAX endpoint.
# We search county-by-county across the Cincinnati metro to get full coverage.
# Server-side cap is 500 listings per query; using map view returns all at once.
# ---------------------------------------------------------------------------

# Cincinnati metro counties and their mfmidx autocomplete values
CINCY_COUNTIES = [
    ("county:Hamilton County-OH-mls_cincy",  "Hamilton County, OH"),  # Cincinnati proper
    ("county:Butler County-OH-mls_cincy",    "Butler County, OH"),     # West Chester, Mason
    ("county:Warren County-OH-mls_cincy",    "Warren County, OH"),     # Lebanon, Springboro
    ("county:Clermont County-OH-mls_cincy",  "Clermont County, OH"),   # Milford, Loveland
    ("county:Kenton County-KY-mls_nky",      "Kenton County, KY"),     # Covington, Independence
    ("county:Campbell County-KY-mls_nky",    "Campbell County, KY"),   # Newport, Alexandria
    ("county:Boone County-KY-mls_nky",       "Boone County, KY"),      # Florence, Burlington
]

COMEY_AJAX_URL = "https://www.comey.com/wp-admin/admin-ajax.php"
COMEY_HOME_SEARCH = "https://www.comey.com/home-search/"


def _get_comey_nonce(session: requests.Session) -> Optional[str]:
    """Fetch a fresh nonce from Comey's home-search page."""
    for attempt in range(4):
        try:
            r = session.get(
                COMEY_HOME_SEARCH,
                headers={"User-Agent": BROWSER_UA, "Referer": "https://www.comey.com/"},
                timeout=90,
                stream=True,
            )
            content = b""
            for chunk in r.iter_content(8192):
                content += chunk
                if len(content) > 200_000:
                    break
            r.close()
            text = content.decode("utf-8", errors="ignore")
            nonces = re.findall(r"nonce\s*=\s*[\"']([\w]+)[\"'|;,]", text)
            if nonces:
                logger.info(f"Comey: got nonce on attempt {attempt + 1}")
                return nonces[0]
            logger.warning(f"Comey: page loaded ({len(text)}B) but no nonce found")
        except Exception as e:
            logger.warning(f"Comey: nonce fetch attempt {attempt + 1} failed: {e}")
            time.sleep(3)
    return None


def _parse_comey_listing(item: dict) -> Optional[dict]:
    """Normalize a Comey/mfmidx listing to our common schema."""
    try:
        address = item.get("address", "")
        city    = item.get("city", "")
        state   = item.get("state", "OH")
        zipcode = str(item.get("zipcode", ""))

        if not address:
            return None

        full_address = f"{address}, {city}, {state} {zipcode}".strip(", ")

        baths_full = _safe_float(item.get("fullbaths", 0)) or 0
        baths_part = _safe_float(item.get("partbaths", 0)) or 0
        baths = baths_full + (baths_part * 0.5) if (baths_full or baths_part) else None

        return {
            "id": _listing_id(full_address, "comey"),
            "address": address,
            "city": city,
            "state": state,
            "zip": zipcode,
            "price": _safe_int(item.get("listprice")),
            "beds": _safe_int(item.get("beds")),
            "baths": baths,
            "sqft": _safe_int(item.get("sqft")),
            "lot_size": None,
            "property_type": item.get("subproptype") or item.get("proptype", ""),
            "status": item.get("status") or item.get("propstatus") or "FOR_SALE",
            "days_on_market": None,
            "images": [item["photo_url"]] if item.get("photo_url") else [],
            "url": item.get("listing_url", ""),
            "source": "comey",
            "lat": _safe_float(item.get("latitude")),
            "lng": _safe_float(item.get("longitude")),
            "last_updated": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.debug(f"Comey parse error: {e}")
        return None


def _scrape_comey(session: requests.Session) -> list[dict]:
    """
    Scrape Comey & Shepherd listings for the Cincinnati metro via their
    mfmidx AJAX endpoint, searching county-by-county.
    """
    nonce = _get_comey_nonce(session)
    if not nonce:
        logger.error("Comey: could not obtain nonce — skipping")
        return []

    ajax_headers = {
        "User-Agent": BROWSER_UA,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*",
        "Referer": COMEY_HOME_SEARCH,
    }

    all_listings: list[dict] = []
    seen_ids: set[str] = set()

    for search_val, county_label in CINCY_COUNTIES:
        try:
            resp = session.post(
                COMEY_AJAX_URL,
                headers=ajax_headers,
                timeout=60,
                data={
                    "action": "mfmsearch_listings",
                    "nonce": nonce,
                    "search[smartsearch]": search_val,
                    "view": "map",
                    "pageNumber": 1,
                    "pageSize": 500,
                    "sort": "listdate_desc",
                },
            )
            resp.raise_for_status()

            if not resp.text.strip():
                logger.warning(f"Comey: empty response for {county_label}")
                continue

            data = resp.json()
            raw = data.get("data", {}).get("listings", [])
            logger.info(f"Comey {county_label}: {len(raw)} listings")

            for item in raw:
                parsed = _parse_comey_listing(item)
                if parsed and parsed["id"] not in seen_ids:
                    seen_ids.add(parsed["id"])
                    all_listings.append(parsed)

        except Exception as e:
            logger.warning(f"Comey {county_label} failed: {e}")

        time.sleep(1.5)

    logger.info(f"Comey total: {len(all_listings)} listings")
    return all_listings


# ---------------------------------------------------------------------------
# Sibcy Cline — sibcycline.com
# ---------------------------------------------------------------------------

def _parse_sibcy_listing(item: dict) -> Optional[dict]:
    try:
        address = item.get("address", "")
        city    = item.get("city", "")
        state   = item.get("state", "OH")
        zipcode = str(item.get("zip", ""))

        if not address:
            return None

        full_address = f"{address}, {city}, {state} {zipcode}".strip(", ")

        price = _safe_int(item.get("priceFormatted", ""))

        images = []
        main_photo = item.get("mainPhoto") or {}
        if isinstance(main_photo, dict):
            img_url = main_photo.get("midSizeImageUrl") or main_photo.get("fullSizeImageUrl")
            if img_url:
                images = [img_url]
        if not images:
            for p in item.get("photos", [])[:1]:
                if isinstance(p, dict):
                    img_url = p.get("midSizeImageUrl") or p.get("fullSizeImageUrl")
                    if img_url:
                        images = [img_url]

        listing_url = item.get("listingUrl", "")
        canonical   = item.get("canonicalUrl", "")
        url = canonical or (f"https://www.sibcycline.com{listing_url}" if listing_url else "")

        return {
            "id": _listing_id(full_address, "sibcy_cline"),
            "address": address,
            "city": city,
            "state": state,
            "zip": zipcode,
            "price": price,
            "beds": _safe_int(item.get("bedroomCount")),
            "baths": _safe_float(item.get("bathroomCount")),
            "sqft": _safe_int(item.get("squareFeet") or item.get("sqFt")),
            "lot_size": None,
            "property_type": item.get("propertyType", item.get("propertySubType", "")),
            "status": item.get("status", "Active"),
            "days_on_market": _safe_int(item.get("daysSinceNew")),
            "images": images,
            "url": url,
            "source": "sibcy_cline",
            "lat": _safe_float(item.get("latitude") or item.get("lat")),
            "lng": _safe_float(item.get("longitude") or item.get("lng")),
            "last_updated": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.debug(f"Sibcy Cline parse error: {e}")
        return None


def _scrape_sibcy_status(
    session: requests.Session,
    status: str,
    seen_ids: set,
    max_pages: int = 40,
) -> list[dict]:
    """Scrape one status category (Active / Pending / Contingent) from Sibcy Cline."""
    listings = []
    headers = {"User-Agent": BROWSER_UA, "Accept": "text/html"}

    for page in range(1, max_pages + 1):
        try:
            resp = session.get(
                f"https://www.sibcycline.com/results?status={status}&page={page}",
                headers=headers,
                timeout=20,
            )
            resp.raise_for_status()

            nd_match = re.search(
                r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                resp.text, re.DOTALL,
            )
            if not nd_match:
                break

            data = json.loads(nd_match.group(1))
            raw = (
                data.get("props", {})
                    .get("pageProps", {})
                    .get("initialData", {})
                    .get("listings", [])
            )
            if not raw:
                break

            page_cincy = 0
            for item in raw:
                parsed = _parse_sibcy_listing(item)
                if parsed and _is_cincinnati(parsed) and parsed["id"] not in seen_ids:
                    seen_ids.add(parsed["id"])
                    listings.append(parsed)
                    page_cincy += 1

            logger.info(
                f"Sibcy Cline [{status}] page {page}: {len(raw)} items, "
                f"{page_cincy} Cincinnati"
            )

        except Exception as e:
            logger.warning(f"Sibcy Cline [{status}] page {page} failed: {e}")
            break

        time.sleep(1.2)

    return listings


def _scrape_sibcy_cline(
    session: requests.Session,
    max_pages: int = 40,
) -> list[dict]:
    seen_ids: set = set()
    listings = []

    for status in ("Active", "Pending", "Contingent"):
        batch = _scrape_sibcy_status(session, status, seen_ids, max_pages=max_pages)
        listings.extend(batch)
        logger.info(f"Sibcy Cline [{status}]: {len(batch)} Cincinnati listings")
        time.sleep(2)

    logger.info(f"Sibcy Cline total: {len(listings)} Cincinnati listings")
    return listings


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def scrape() -> list[dict]:
    """Run all local Cincinnati scrapers and return combined listing dicts."""
    session = requests.Session()
    all_listings: list[dict] = []

    for name, fn in [("Comey & Shepherd", _scrape_comey), ("Sibcy Cline", _scrape_sibcy_cline)]:
        try:
            results = fn(session)
            logger.info(f"{name}: {len(results)} listings")
            all_listings.extend(results)
        except Exception as e:
            logger.error(f"{name} failed entirely: {e}")
        time.sleep(1)

    # Coldwell Banker — Cincinnati OH + NKY cities
    try:
        from scrapers import coldwell_banker as cb_scraper
        results = cb_scraper.scrape()
        logger.info(f"Coldwell Banker: {len(results)} listings")
        all_listings.extend(results)
    except Exception as e:
        logger.error(f"Coldwell Banker failed entirely: {e}")

    # CincinKY Real Estate — 94 community pages via Sierra Interactive IDX
    try:
        from scrapers import cincinky as cincinky_scraper
        results = cincinky_scraper.scrape()
        logger.info(f"CincinKY: {len(results)} listings")
        all_listings.extend(results)
    except Exception as e:
        logger.error(f"CincinKY failed entirely: {e}")

    # ListingsCincinnati.com — Brivity/BlueRoof MLS feed
    try:
        from scrapers import listings_cincinnati as lc_scraper
        results = lc_scraper.scrape()
        logger.info(f"ListingsCincinnati: {len(results)} listings")
        all_listings.extend(results)
    except Exception as e:
        logger.error(f"ListingsCincinnati failed entirely: {e}")

    # Huff Realty — requires Playwright (headless browser)
    try:
        from scrapers import huff as huff_scraper
        results = huff_scraper.scrape()
        logger.info(f"Huff Realty: {len(results)} listings")
        all_listings.extend(results)
    except Exception as e:
        logger.error(f"Huff Realty failed entirely: {e}")

    logger.info(f"Local sites total: {len(all_listings)} listings")
    return all_listings


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = scrape()
    print(f"\nGot {len(results)} listings from local sites")
    if results:
        print(json.dumps(results[0], indent=2))
