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
from utils.deduplicator import deduplicate, filter_cincinnati, filter_for_sale, _normalize_address

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
        "--analyze-only",
        action="store_true",
        help="Skip scraping — only run AI analysis on existing listings.json",
    )
    parser.add_argument(
        "--analyze-max",
        type=int,
        default=200,
        help="Max listings to analyze per run (default: 200)",
    )
    parser.add_argument(
        "--describe",
        action="store_true",
        help="Fetch description text from each listing's detail page",
    )
    parser.add_argument(
        "--tag",
        action="store_true",
        help="Run feature tagging (keyword + Qwen LLM) on listings with descriptions",
    )
    parser.add_argument(
        "--describe-only",
        action="store_true",
        help="Skip scraping — only fetch descriptions for existing listings",
    )
    parser.add_argument(
        "--tag-only",
        action="store_true",
        help="Skip scraping — only run feature tagging on existing listings",
    )
    parser.add_argument(
        "--photos",
        action="store_true",
        help="Enrich listing photo galleries (Coldwell Banker, Sibcy Cline, Comey, CincinKY, Redfin <15 photos).",
    )
    parser.add_argument(
        "--photos-only",
        action="store_true",
        help="Skip scraping — only enrich photos for existing listings",
    )
    args = parser.parse_args()

    # --describe-only: fetch descriptions without re-scraping
    if args.describe_only:
        if not DATA_FILE.exists():
            logger.error("No listings.json found — run without --describe-only first")
            return
        existing = json.loads(DATA_FILE.read_text())
        unique = existing.get("listings", [])
        logger.info(f"Loaded {len(unique)} existing listings for description enrichment")

        _desc_push_counter = [0]

        def save_desc_checkpoint(listings):
            if args.dry_run:
                return
            existing["listings"] = listings
            existing["last_updated"] = datetime.now(timezone.utc).isoformat()
            DATA_FILE.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
            with_desc = sum(1 for l in listings if l.get("description"))
            logger.info(f"Checkpoint saved — {with_desc} listings with descriptions")
            # Push to GitHub every 500 descriptions
            _desc_push_counter[0] += 50
            if _desc_push_counter[0] % 500 == 0:
                import subprocess
                subprocess.run(
                    ["git", "add", "docs/data/listings.json"],
                    cwd=Path(__file__).parent, check=False,
                )
                subprocess.run(
                    ["git", "commit", "-m",
                     f"chore: description enrichment checkpoint — {with_desc} listings"],
                    cwd=Path(__file__).parent, check=False,
                )
                subprocess.run(
                    ["git", "push"],
                    cwd=Path(__file__).parent, check=False,
                )
                logger.info(f"Pushed to GitHub — {with_desc} listings with descriptions")

        from utils.detail_descriptions import enrich_descriptions, enrich_dom
        unique = enrich_descriptions(
            unique,
            checkpoint_every=50,
            checkpoint_fn=save_desc_checkpoint,
        )
        with_desc = sum(1 for l in unique if l.get("description"))
        logger.info(f"Listings with description: {with_desc}/{len(unique)}")

        # Also enrich CincinKY days_on_market from detail pages
        unique = enrich_dom(
            unique,
            checkpoint_every=50,
            checkpoint_fn=save_desc_checkpoint,
        )
        with_dom = sum(1 for l in unique if l.get("days_on_market") is not None)
        logger.info(f"Listings with days_on_market: {with_dom}/{len(unique)}")

        if not args.dry_run:
            existing["listings"] = unique
            existing["last_updated"] = datetime.now(timezone.utc).isoformat()
            DATA_FILE.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
            logger.info(f"Wrote updated listings → {DATA_FILE}")
        return

    # --tag-only: run feature tagging without re-scraping
    if args.tag_only:
        if not DATA_FILE.exists():
            logger.error("No listings.json found — run without --tag-only first")
            return
        existing = json.loads(DATA_FILE.read_text())
        unique = existing.get("listings", [])
        logger.info(f"Loaded {len(unique)} existing listings for feature tagging")

        _tag_push_counter = [0]

        def save_tag_checkpoint(listings):
            if args.dry_run:
                return
            existing["listings"] = listings
            existing["last_updated"] = datetime.now(timezone.utc).isoformat()
            DATA_FILE.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
            tagged = sum(1 for l in listings if l.get("features") is not None)
            logger.info(f"Checkpoint saved — {tagged} listings tagged")
            _tag_push_counter[0] += 100
            if _tag_push_counter[0] % 500 == 0:
                import subprocess
                subprocess.run(["git", "add", "docs/data/listings.json"],
                               cwd=Path(__file__).parent, check=False)
                subprocess.run(["git", "commit", "-m",
                                f"chore: feature tagging checkpoint — {tagged} listings"],
                               cwd=Path(__file__).parent, check=False)
                subprocess.run(["git", "push"],
                               cwd=Path(__file__).parent, check=False)
                logger.info(f"Pushed to GitHub — {tagged} listings tagged")

        from utils.feature_tagger import tag_listings
        unique = tag_listings(
            unique,
            use_llm=True,
            checkpoint_every=100,
            checkpoint_fn=save_tag_checkpoint,
        )
        tagged = sum(1 for l in unique if l.get("features") is not None)
        logger.info(f"Listings with features: {tagged}/{len(unique)}")

        if not args.dry_run:
            existing["listings"] = unique
            existing["last_updated"] = datetime.now(timezone.utc).isoformat()
            DATA_FILE.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
            logger.info(f"Wrote updated listings → {DATA_FILE}")
        return

    # --photos-only: enrich photos without re-scraping
    if args.photos_only:
        if not DATA_FILE.exists():
            logger.error("No listings.json found — run without --photos-only first")
            return
        existing = json.loads(DATA_FILE.read_text())
        unique = existing.get("listings", [])
        logger.info(f"Loaded {len(unique)} existing listings for photo enrichment")

        def save_photos_checkpoint(listings):
            if args.dry_run:
                return
            existing["listings"] = listings
            existing["last_updated"] = datetime.now(timezone.utc).isoformat()
            DATA_FILE.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
            enriched = sum(1 for l in listings if l.get("photos_enriched"))
            logger.info(f"Checkpoint saved — {enriched} listings photo-enriched")

        from utils.detail_descriptions import enrich_photos
        unique = enrich_photos(
            unique,
            checkpoint_every=100,
            checkpoint_fn=save_photos_checkpoint,
        )
        enriched = sum(1 for l in unique if l.get("photos_enriched"))
        with_multi = sum(1 for l in unique if len(l.get("images", [])) > 2)
        logger.info(f"Photo enrichment complete: {enriched} processed, {with_multi} with 3+ images")

        if not args.dry_run:
            existing["listings"] = unique
            existing["last_updated"] = datetime.now(timezone.utc).isoformat()
            DATA_FILE.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
            logger.info(f"Wrote updated listings → {DATA_FILE}")
        return

    # --analyze-only: skip scraping, load existing listings directly
    if args.analyze_only:
        if not DATA_FILE.exists():
            logger.error("No listings.json found — run without --analyze-only first")
            return
        existing = json.loads(DATA_FILE.read_text())
        unique = existing.get("listings", [])
        source_counts = existing.get("source_counts", {})
        logger.info(f"Loaded {len(unique)} existing listings for analysis-only run")

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")

        # Enrich images from detail pages before analysis
        logger.info("=" * 50)
        logger.info("Fetching gallery images from detail pages…")
        from utils.detail_images import enrich_images
        unique = enrich_images(unique, min_price=900_000)

        def save_checkpoint(listings):
            if args.dry_run:
                return
            existing["listings"] = listings
            existing["last_updated"] = datetime.now(timezone.utc).isoformat()
            DATA_FILE.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
            analyzed = sum(1 for l in listings if l.get("image_analysis"))
            logger.info(f"Checkpoint saved — {analyzed} listings with AI analysis")

        from utils.image_analyzer import analyze_listings
        unique = analyze_listings(
            unique,
            api_key=api_key,
            max_per_run=args.analyze_max,
            checkpoint_every=10,
            checkpoint_fn=save_checkpoint,
        )
        analyzed = sum(1 for l in unique if l.get("image_analysis"))
        logger.info(f"Listings with AI analysis: {analyzed}/{len(unique)}")

        if not args.dry_run:
            existing["listings"] = unique
            existing["last_updated"] = datetime.now(timezone.utc).isoformat()
            DATA_FILE.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
            logger.info(f"Wrote updated listings → {DATA_FILE}")
        return

    sources = ["zillow", "redfin", "local"] if args.source == "all" else [args.source]

    logger.info(f"Starting scrape. Sources: {sources}")
    raw_listings = run_all_scrapers(sources)
    logger.info(f"Total raw listings collected: {len(raw_listings)}")

    # Filter to Cincinnati metro area, for-sale only
    filtered = filter_for_sale(filter_cincinnati(raw_listings))

    # Deduplicate — fresh scrape is the source of truth
    unique = deduplicate(filtered)

    # Carry over enrichment from previous run and handle off-market listings.
    # Listings no longer in the fresh scrape are marked off_market (not dropped).
    # Off-market listings are retained for 30 days then expired.
    off_market: list[dict] = []
    if args.merge and DATA_FILE.exists():
        try:
            old_data = json.loads(DATA_FILE.read_text())
            old_listings = old_data.get("listings", [])
            today = datetime.now(timezone.utc).date().isoformat()
            OFF_MARKET_TTL_DAYS = 30

            # Separate old active vs already-off-market listings
            old_active = [l for l in old_listings if l.get("status") != "off_market"]
            old_off = [l for l in old_listings if l.get("status") == "off_market"]

            # Build lookup: normalized address → old active listing
            old_by_addr: dict[str, dict] = {}
            for l in old_active:
                key = _normalize_address(l.get("address", ""), l.get("zip", ""))
                if key:
                    old_by_addr[key] = l

            # Build lookup for newly active listings
            new_keys: set[str] = set()
            CARRY_FIELDS = ["description", "features", "keywords", "days_on_market", "image_analysis"]
            carried = 0
            for listing in unique:
                key = _normalize_address(listing.get("address", ""), listing.get("zip", ""))
                new_keys.add(key)
                old = old_by_addr.get(key)
                if old:
                    carried += 1
                    # Simple fields: carry over if new listing doesn't have them
                    for field in CARRY_FIELDS:
                        if listing.get(field) is None and old.get(field) is not None:
                            listing[field] = old[field]
                    # Images: carry over enriched gallery if old had more photos than new scrape.
                    # This preserves full galleries (20+ photos) even when fresh scrape only
                    # returns 1 thumbnail (e.g. Comey, CincinKY initial scrape data).
                    old_imgs = old.get("images") or []
                    new_imgs = listing.get("images") or []
                    if len(old_imgs) > len(new_imgs):
                        listing["images"] = old_imgs
                        if old.get("photos_enriched"):
                            listing["photos_enriched"] = True
                    elif old.get("photos_enriched") and not listing.get("photos_enriched"):
                        listing["photos_enriched"] = True

            # Determine which sources returned 0 listings in this scrape (whole-source failure).
            # For those sources, preserve old active listings rather than marking off-market.
            new_source_counts: dict[str, int] = {}
            for listing in unique:
                src = listing.get("source", "unknown")
                new_source_counts[src] = new_source_counts.get(src, 0) + 1

            old_source_counts: dict[str, int] = {}
            for l in old_active:
                src = l.get("source", "unknown")
                old_source_counts[src] = old_source_counts.get(src, 0) + 1

            # Sources that had listings before but returned 0 now → whole-source failure
            failed_sources: set[str] = {
                src for src, cnt in old_source_counts.items()
                if cnt > 0 and new_source_counts.get(src, 0) == 0
            }
            if failed_sources:
                logger.warning(
                    f"Whole-source scraper failure detected for: {failed_sources}. "
                    "Preserving old listings instead of marking off-market."
                )
                for l in old_active:
                    if l.get("source") in failed_sources:
                        src_key = _normalize_address(l.get("address", ""), l.get("zip", ""))
                        if src_key not in new_keys:
                            unique.append(l)  # carry forward as active

            # Listings in old_active but not in new scrape → went off-market
            # (skip listings from failed sources — already carried forward above)
            newly_off = 0
            for l in old_active:
                if l.get("source") in failed_sources:
                    continue  # protected above
                key = _normalize_address(l.get("address", ""), l.get("zip", ""))
                if key not in new_keys:
                    l["status"] = "off_market"
                    l["off_market_since"] = l.get("off_market_since") or today
                    off_market.append(l)
                    newly_off += 1

            # Keep previously off-market listings that haven't expired yet
            from datetime import date
            for l in old_off:
                since = l.get("off_market_since", today)
                try:
                    days_off = (date.fromisoformat(today) - date.fromisoformat(since)).days
                except Exception:
                    days_off = 0
                if days_off <= OFF_MARKET_TTL_DAYS:
                    off_market.append(l)

            expired = len(old_off) - (len(off_market) - newly_off)
            logger.info(
                f"Merge: {carried} enrichments carried forward, "
                f"{newly_off} newly off-market, "
                f"{len(off_market)} total off-market retained, "
                f"{max(0, expired)} expired (>30 days)"
            )
        except Exception as e:
            logger.warning(f"Could not carry over enrichment: {e}")

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
            # Enrich images from detail pages before analysis
            logger.info("=" * 50)
            logger.info("Fetching gallery images from detail pages…")
            from utils.detail_images import enrich_images
            unique = enrich_images(unique, min_price=900_000)

            logger.info("=" * 50)
            logger.info("Running AI image analysis on new listings…")
            from utils.image_analyzer import analyze_listings

            def save_checkpoint_analyze(listings):
                if args.dry_run:
                    return
                out = {
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                    "total_count": len(listings),
                    "source_counts": source_counts,
                    "listings": listings,
                }
                DATA_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False))
                analyzed = sum(1 for l in listings if l.get("image_analysis"))
                logger.info(f"Checkpoint saved — {analyzed} listings with AI analysis")

            unique = analyze_listings(
                unique,
                api_key=api_key,
                max_per_run=args.analyze_max,
                checkpoint_every=10,
                checkpoint_fn=save_checkpoint_analyze,
            )
            analyzed = sum(1 for l in unique if l.get("image_analysis"))
            logger.info(f"Listings with AI analysis: {analyzed}/{len(unique)}")

    # Description enrichment (optional — --describe flag)
    if args.describe:
        logger.info("=" * 50)
        logger.info("Fetching listing descriptions from detail pages…")
        from utils.detail_descriptions import enrich_descriptions, enrich_dom

        def save_desc_checkpoint_main(listings):
            if args.dry_run:
                return
            out = {
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "total_count": len(listings),
                "source_counts": source_counts,
                "listings": listings,
            }
            DATA_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False))
            with_desc = sum(1 for l in listings if l.get("description"))
            logger.info(f"Checkpoint saved — {with_desc} listings with descriptions")

        unique = enrich_descriptions(
            unique,
            checkpoint_every=50,
            checkpoint_fn=save_desc_checkpoint_main,
        )
        with_desc = sum(1 for l in unique if l.get("description"))
        logger.info(f"Listings with description: {with_desc}/{len(unique)}")

        # Also enrich CincinKY days_on_market from detail pages
        unique = enrich_dom(
            unique,
            checkpoint_every=50,
            checkpoint_fn=save_desc_checkpoint_main,
        )
        with_dom = sum(1 for l in unique if l.get("days_on_market") is not None)
        logger.info(f"Listings with days_on_market: {with_dom}/{len(unique)}")

    # Feature tagging (optional — --tag flag, requires descriptions)
    if args.tag:
        logger.info("=" * 50)
        logger.info("Running feature tagging (keyword + Qwen LLM)…")
        from utils.feature_tagger import tag_listings

        def save_tag_checkpoint_main(listings):
            if args.dry_run:
                return
            out = {
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "total_count": len(listings),
                "source_counts": source_counts,
                "listings": listings,
            }
            DATA_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False))

        unique = tag_listings(
            unique,
            use_llm=True,
            checkpoint_every=100,
            checkpoint_fn=save_tag_checkpoint_main,
        )
        tagged = sum(1 for l in unique if l.get("features") is not None)
        logger.info(f"Listings with features: {tagged}/{len(unique)}")

    # Photo gallery enrichment (--photos flag)
    if args.photos:
        logger.info("=" * 50)
        logger.info("Enriching photo galleries from detail pages…")
        from utils.detail_descriptions import enrich_photos

        def save_photos_checkpoint_main(listings):
            if args.dry_run:
                return
            out = {
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "total_count": len(listings),
                "source_counts": source_counts,
                "listings": listings,
                "off_market": off_market,
            }
            DATA_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False))

        unique = enrich_photos(
            unique,
            checkpoint_every=100,
            checkpoint_fn=save_photos_checkpoint_main,
        )
        with_multi = sum(1 for l in unique if len(l.get("images", [])) > 2)
        logger.info(f"Listings with 3+ photos: {with_multi}/{len(unique)}")

    if args.dry_run:
        logger.info("Dry run — not writing to disk.")
        return

    output = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "total_count": len(unique),
        "source_counts": source_counts,
        "listings": unique,
        "off_market": off_market,
    }

    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    logger.info(f"Wrote {len(unique)} listings → {DATA_FILE}")


if __name__ == "__main__":
    main()
