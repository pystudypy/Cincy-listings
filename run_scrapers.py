"""
Main entry point — runs all scrapers, deduplicates, and writes data/listings.json.

Usage:
  python run_scrapers.py              # run all scrapers
  python run_scrapers.py --source zillow   # run one scraper only
  python run_scrapers.py --dry-run    # print stats, don't write file
  python run_scrapers.py --analyze    # also run AI image analysis (needs ANTHROPIC_API_KEY)
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make sure project root is importable
sys.path.insert(0, str(Path(__file__).parent))

from scrapers import zillow, redfin, local_sites
from utils.deduplicator import deduplicate, filter_cincinnati, filter_for_sale

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_scrapers")

DATA_FILE = Path(__file__).parent / "docs" / "data" / "listings.json"


def run_all_scrapers(sources: list[str]) -> list[dict]:
    all_listings: list[dict] = []

    if "zillow" in sources:
        logger.info("=" * 50)
        logger.info("Running Zillow scraper...")
        try:
            results = zillow.scrape(max_pages=5)
            logger.info(f"Zillow returned {len(results)} listings")
            all_listings.extend(results)
        except Exception as e:
            logger.error(f"Zillow scraper crashed: {e}")

    if "redfin" in sources:
        logger.info("=" * 50)
        logger.info("Running Redfin scraper...")
        try:
            results = redfin.scrape(max_listings=1000)
            logger.info(f"Redfin returned {len(results)} listings")
            all_listings.extend(results)
        except Exception as e:
            logger.error(f"Redfin scraper crashed: {e}")

    if "local" in sources:
        logger.info("=" * 50)
        logger.info("Running local Cincinnati scrapers...")
        try:
            results = local_sites.scrape()
            logger.info(f"Local sites returned {len(results)} listings")
            all_listings.extend(results)
        except Exception as e:
            logger.error(f"Local scrapers crashed: {e}")

    return all_listings


def main():
    parser = argparse.ArgumentParser(description="Cincinnati real estate scraper")
    parser.add_argument(
        "--source",
        choices=["zillow", "redfin", "local", "all"],
        default="all",
        help="Which scraper(s) to run (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print stats but do not overwrite listings.json",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="Merge new listings with existing listings.json instead of replacing",
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Run AI image analysis on new listings (requires ANTHROPIC_API_KEY env var)",
    )
    parser.add_argument(
        "--analyze-max",
        type=int,
        default=200,
        help="Max listings to analyze per run (default: 200)",
    )
    args = parser.parse_args()

    sources = ["zillow", "redfin", "local"] if args.source == "all" else [args.source]

    logger.info(f"Starting scrape. Sources: {sources}")
    raw_listings = run_all_scrapers(sources)
    logger.info(f"Total raw listings collected: {len(raw_listings)}")

    # If merging, load existing listings first (preserves image_analysis from prior runs)
    if args.merge and DATA_FILE.exists():
        try:
            existing = json.loads(DATA_FILE.read_text())
            existing_listings = existing.get("listings", [])
            logger.info(f"Loaded {len(existing_listings)} existing listings for merge")
            raw_listings = existing_listings + raw_listings
        except Exception as e:
            logger.warning(f"Could not load existing listings: {e}")

    # Filter to Cincinnati metro area, for-sale only
    filtered = filter_for_sale(filter_cincinnati(raw_listings))

    # Deduplicate
    unique = deduplicate(filtered)

    logger.info("=" * 50)
    logger.info(f"Final: {len(unique)} unique Cincinnati listings")

    # Source breakdown
    source_counts: dict[str, int] = {}
    for listing in unique:
        src = listing.get("source", "unknown")
        source_counts[src] = source_counts.get(src, 0) + 1
    for src, count in sorted(source_counts.items(), key=lambda x: -x[1]):
        logger.info(f"  {src:20s}: {count:,}")

    # AI image analysis (optional — only runs when --analyze flag is passed)
    if args.analyze:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            logger.warning("--analyze passed but ANTHROPIC_API_KEY not set — skipping")
        else:
            logger.info("=" * 50)
            logger.info("Running AI image analysis on new listings…")
            from utils.image_analyzer import analyze_listings
            unique = analyze_listings(unique, api_key=api_key, max_per_run=args.analyze_max)
            analyzed = sum(1 for l in unique if l.get("image_analysis"))
            logger.info(f"Listings with AI analysis: {analyzed}/{len(unique)}")

    if args.dry_run:
        logger.info("Dry run — not writing to disk.")
        return

    output = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "total_count": len(unique),
        "source_counts": source_counts,
        "listings": unique,
    }

    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    logger.info(f"Wrote {len(unique)} listings → {DATA_FILE}")


if __name__ == "__main__":
    main()
