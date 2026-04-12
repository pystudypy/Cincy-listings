"""
Huff Realty scraper for Cincinnati listings.

huff.com uses Microsoft Blazor Server (WebSocket/SignalR) so listings
render dynamically — no static HTML, no JSON API.  We use Playwright
with playwright-stealth to bypass Cloudflare and drive the real browser
rendering.  Pagination is handled by evaluating the site's own
GoToPage(N) JS function after the Blazor circuit is established.

Usage:
    python -m scrapers.huff
"""

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

HUFF_SEARCH_URL = "https://www.huff.com/realestate/search"
MAX_PAGES = 20        # ≈ 100 listings/page × 20 = 2 000 raw; ~56% Cincinnati
TARGET_CINCY = 1000   # stop early once we have enough Cincinnati listings

# Cincinnati-metro ZIP prefixes accepted by the deduplicator
CINCY_ZIP_PREFIXES = ("450", "451", "452", "410", "411")


def _listing_id(address: str) -> str:
    key = f"huff:{address.lower().strip()}"
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


def _is_cincy(zipcode: str) -> bool:
    z = (zipcode or "").strip()[:5]
    return any(z.startswith(p) for p in CINCY_ZIP_PREFIXES)


def _parse_card(card_html: str) -> Optional[dict]:
    """
    Parse one prop-card HTML snippet into our common listing dict.
    We use simple regex so we don't need BeautifulSoup in this module.
    """
    try:
        # Price — e.g. "$329,900"
        price_m = re.search(r'class="price[^"]*"[^>]*>([^<]+)<', card_html)
        price = _safe_int(price_m.group(1)) if price_m else None

        # Address lines — two <h3 class="address"> tags
        addr_parts = re.findall(r'<h3 class="address[^"]*"[^>]*>(.*?)</h3>', card_html, re.DOTALL)
        street  = re.sub(r"<[^>]+>", "", addr_parts[0]).strip() if len(addr_parts) > 0 else ""
        city_state_zip = re.sub(r"<[^>]+>", "", addr_parts[1]).strip() if len(addr_parts) > 1 else ""

        # Parse "Cincinnati, OH 45202" or "Cincinnati OH 45202"
        csz_m = re.match(r"^(.*?),?\s+([A-Z]{2})\s+(\d{5})", city_state_zip)
        if csz_m:
            city    = csz_m.group(1).strip()
            state   = csz_m.group(2)
            zipcode = csz_m.group(3)
        else:
            city, state, zipcode = city_state_zip, "OH", ""

        if not street:
            return None

        full_address = f"{street}, {city}, {state} {zipcode}".strip(", ")

        # Info list items — type, beds, baths, sqft
        info_items = re.findall(r'<li[^>]*>(.*?)</li>', card_html, re.DOTALL)
        info_texts = [re.sub(r"<[^>]+>", "", i).strip() for i in info_items]

        beds, baths, sqft, prop_type = None, None, None, ""
        for txt in info_texts:
            t = txt.lower()
            if "bed" in t:
                beds = _safe_int(re.search(r"[\d.]+", txt).group() if re.search(r"[\d.]+", txt) else None)
            elif "bath" in t:
                baths = _safe_float(re.search(r"[\d.]+", txt).group() if re.search(r"[\d.]+", txt) else None)
            elif "sq" in t:
                sqft = _safe_int(re.search(r"[\d,]+", txt).group() if re.search(r"[\d,]+", txt) else None)
            elif txt and not any(c.isdigit() for c in txt):
                prop_type = txt.strip()

        # Image — data-lazy attribute
        img_m = re.search(r'data-lazy="([^"]+)"', card_html)
        image_url = img_m.group(1) if img_m else ""
        images = [image_url] if image_url else []

        # Listing URL — href on the card link
        url_m = re.search(r'href="(/realestate/listing/[^"]+)"', card_html)
        url = f"https://www.huff.com{url_m.group(1)}" if url_m else ""

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
            "property_type": prop_type,
            "status": "FOR_SALE",
            "days_on_market": None,
            "images": images,
            "url": url,
            "source": "huff",
            "lat": None,
            "lng": None,
            "last_updated": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.debug(f"Huff card parse error: {e}")
        return None


async def _scrape_async() -> list[dict]:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("playwright not installed. Run: pip install playwright && playwright install chromium")
        return []

    try:
        from playwright_stealth import Stealth
        stealth = Stealth()
    except ImportError:
        stealth = None
        logger.warning("playwright-stealth not installed — Cloudflare bypass may fail")

    listings: list[dict] = []
    seen_ids: set[str] = set()

    # Huff uses Blazor Server (SSR per request) — each page URL renders its own
    # 100 listings server-side, so we can navigate directly to page-N URLs
    # instead of fighting the Blazor WebSocket circuit for in-page pagination.
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)

        for page_num in range(1, MAX_PAGES + 1):
            if len(listings) >= TARGET_CINCY:
                logger.info("Huff: reached target — stopping early")
                break

            url = (
                HUFF_SEARCH_URL
                if page_num == 1
                else f"{HUFF_SEARCH_URL}/page-{page_num}"
            )

            # Fresh browser context per page keeps each request clean for Cloudflare
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/123.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
                locale="en-US",
            )
            page = await ctx.new_page()
            if stealth:
                await stealth.apply_stealth_async(page)

            logger.info(f"Huff: loading page {page_num} ({url})…")
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                await page.wait_for_selector("article.prop-card", timeout=20_000)
            except Exception as e:
                logger.warning(f"Huff page {page_num}: failed to load — {e}")
                await ctx.close()
                break

            cards = await page.query_selector_all("article.prop-card")
            if not cards:
                logger.info(f"Huff page {page_num}: no cards — stopping")
                await ctx.close()
                break

            page_cincy = 0
            for card in cards:
                try:
                    card_html = await card.inner_html()
                    parsed = _parse_card(card_html)
                    if parsed and parsed["id"] not in seen_ids:
                        seen_ids.add(parsed["id"])
                        if _is_cincy(parsed["zip"]):
                            listings.append(parsed)
                            page_cincy += 1
                except Exception as e:
                    logger.debug(f"Huff: error reading card: {e}")

            logger.info(
                f"Huff page {page_num}: {len(cards)} cards, "
                f"{page_cincy} Cincinnati, total {len(listings)}"
            )

            await ctx.close()

        await browser.close()

    logger.info(f"Huff: {len(listings)} Cincinnati listings total")
    return listings


def scrape() -> list[dict]:
    """Synchronous entry point called by local_sites.scrape() and run_scrapers.py."""
    return asyncio.run(_scrape_async())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = scrape()
    print(f"\nGot {len(results)} Huff listings")
    if results:
        print(json.dumps(results[0], indent=2))
