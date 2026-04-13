"""
Deduplication utility for Cincinnati real estate listings.

Two listings are considered duplicates when their normalized street addresses
match closely enough (same house number + street name, same zip).  We use a
simple normalized string comparison — no fuzzy matching library needed.

Priority order when merging duplicates (best data wins):
  zillow > redfin > sibcy_cline > comey > huff > cabr
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Higher index = lower priority (data from higher-priority source wins)
SOURCE_PRIORITY = {
    "zillow": 0,
    "redfin": 1,
    "sibcy_cline": 2,
    "comey": 3,
    "huff": 4,
    "cabr": 5,
}


def _normalize_address(address: str, zipcode: str = "") -> str:
    """
    Produce a canonical key for deduplication.
    Examples:
      "123 Main St"  -> "123 main st"
      "123 Main Street" -> "123 main st"  (street suffix normalization)
    """
    if not address:
        return ""

    addr = address.lower().strip()

    # Remove unit / apt / suite designators — they cause false non-matches
    addr = re.sub(r"\b(apt|unit|suite|ste|#)\s*[\w-]+", "", addr)

    # Normalize common street suffixes
    suffix_map = {
        r"\bstreet\b": "st",
        r"\bavenue\b": "ave",
        r"\bboulevard\b": "blvd",
        r"\bdrive\b": "dr",
        r"\blane\b": "ln",
        r"\broad\b": "rd",
        r"\bcourt\b": "ct",
        r"\bcircle\b": "cir",
        r"\bplace\b": "pl",
        r"\bway\b": "way",
        r"\bterrace\b": "ter",
        r"\bparkway\b": "pkwy",
    }
    for pattern, replacement in suffix_map.items():
        addr = re.sub(pattern, replacement, addr)

    # Collapse whitespace
    addr = re.sub(r"\s+", " ", addr).strip()

    # Append zip for uniqueness across Cincinnati suburbs
    if zipcode:
        addr = f"{addr}|{zipcode.strip()[:5]}"

    return addr


def _merge(primary: dict, secondary: dict) -> dict:
    """
    Merge secondary into primary, filling None fields in primary with
    non-None values from secondary.  Primary always wins on non-None fields.
    """
    merged = dict(primary)
    for key, val in secondary.items():
        if key == "source":
            continue  # keep primary source
        if key == "images":
            # Combine image lists, deduplicate
            existing = set(merged.get("images") or [])
            new_imgs = [img for img in (val or []) if img not in existing]
            merged["images"] = list(existing) + new_imgs
        elif merged.get(key) is None and val is not None:
            merged[key] = val
    return merged


def deduplicate(listings: list[dict]) -> list[dict]:
    """
    Remove duplicate listings across all sources.

    Algorithm:
    1. Sort listings by source priority (best source first).
    2. Build a dict keyed by normalized address.
    3. If a key already exists, merge — primary (higher priority) wins.

    Returns the deduplicated list, sorted by price ascending.
    """
    if not listings:
        return []

    # Sort so highest-priority source comes first
    sorted_listings = sorted(
        listings,
        key=lambda x: SOURCE_PRIORITY.get(x.get("source", ""), 99),
    )

    seen: dict[str, dict] = {}
    duplicates_found = 0

    for listing in sorted_listings:
        key = _normalize_address(
            listing.get("address", ""),
            listing.get("zip", ""),
        )
        if not key:
            # No address — keep it but give it a unique key
            key = listing.get("id", "") or listing.get("url", "") or str(id(listing))

        if key in seen:
            duplicates_found += 1
            seen[key] = _merge(seen[key], listing)
        else:
            seen[key] = listing

    result = list(seen.values())

    logger.info(
        f"Deduplication: {len(listings)} listings → {len(result)} unique "
        f"({duplicates_found} duplicates removed)"
    )

    # Sort by price ascending (None prices go to the end)
    result.sort(key=lambda x: (x.get("price") is None, x.get("price") or 0))
    return result


def filter_for_sale(listings: list[dict]) -> list[dict]:
    """Remove rental listings — keep only for-sale properties."""
    rental_keywords = ("rent", "rental", "for_rent", "for rent", "lease")
    result = [
        l for l in listings
        if not any(kw in (l.get("status") or "").lower() for kw in rental_keywords)
    ]
    removed = len(listings) - len(result)
    if removed:
        logger.info(f"Rental filter: removed {removed} rental listings")
    return result


def filter_cincinnati(listings: list[dict]) -> list[dict]:
    """
    Keep only listings that appear to be in the Cincinnati metro area.
    Rejects listings with clearly wrong city/state if scrapers pull extras.
    """
    cincinnati_zips = {
        # Cincinnati proper
        "45201", "45202", "45203", "45204", "45205", "45206", "45207",
        "45208", "45209", "45210", "45211", "45212", "45213", "45214",
        "45215", "45216", "45217", "45218", "45219", "45220", "45221",
        "45222", "45223", "45224", "45225", "45226", "45227", "45228",
        "45229", "45230", "45231", "45232", "45233", "45234", "45235",
        "45236", "45237", "45238", "45239", "45240", "45241", "45242",
        "45243", "45244", "45245", "45246", "45247", "45248", "45249",
        "45250", "45251", "45252", "45253", "45254", "45255",
        # Northern KY — Kenton County (Covington, Independence, Erlanger, Fort Mitchell, Fort Wright, Edgewood)
        "41011", "41012", "41014", "41015", "41016", "41017", "41018", "41019",
        "41051", "41053", "41059",
        # Northern KY — Campbell County (Newport, Fort Thomas, Cold Spring, Alexandria, Bellevue, Dayton, Silver Grove)
        "41071", "41072", "41073", "41074", "41075", "41076",
        "41001", "41007", "41085",
        # Northern KY — Boone County (Florence, Burlington, Union, Hebron, Walton, Petersburg, Verona)
        "41042", "41005", "41048", "41080", "41091", "41092", "41094",
        # Northern KY — Grant & Pendleton Counties (border communities)
        "41010", "41035", "41040", "41097",
        # Ohio suburbs
        "45030", "45033", "45040", "45041", "45042", "45044", "45050",
        "45052", "45053", "45054", "45056", "45064", "45065", "45067",
        "45068", "45069", "45070",
    }

    filtered = []
    for listing in listings:
        state = (listing.get("state") or "").upper()
        city = (listing.get("city") or "").lower()
        zipcode = (listing.get("zip") or "")[:5]

        in_ohio_or_ky = state in ("OH", "KY", "")
        in_cincinnati_zip = zipcode in cincinnati_zips
        city_mentions_cincy = any(
            term in city
            for term in ["cincinnati", "covington", "newport", "florence",
                         "fairfield", "mason", "west chester", "blue ash",
                         "norwood", "hyde park", "anderson", "delhi",
                         "loveland", "milford", "madeira", "mariemont",
                         "montgomery", "kenwood", "clifton", "oakley",
                         "mt. lookout", "mt lookout", "mt. auburn",
                         "price hill", "westwood", "pleasant ridge"]
        )

        if in_ohio_or_ky and (in_cincinnati_zip or city_mentions_cincy):
            filtered.append(listing)

    logger.info(f"Geo filter: {len(listings)} → {len(filtered)} Cincinnati-area listings")
    return filtered
