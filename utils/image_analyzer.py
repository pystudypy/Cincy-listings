"""
AI-powered listing image analysis using Claude's vision API.

For each listing, analyzes up to 5 images:
  - Identifies the room type
  - Rates modernity, luxury, and condition (1–10)
  - Lists key features visible in the image
  - Writes a short insight

Results are stored in the listing dict under the "image_analysis" key so
the frontend can display them without any server-side API calls.

Usage:
    from utils.image_analyzer import analyze_listings
    listings = analyze_listings(listings, api_key="sk-ant-...")
"""

import base64
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Use Haiku for cost efficiency — still excellent at vision tasks
MODEL = "claude-haiku-4-5-20251001"
MAX_IMAGES_PER_LISTING = 20
REQUEST_DELAY = 0.5  # seconds between API calls


def _fetch_image_b64(url: str, timeout: int = 10) -> Optional[tuple[str, str]]:
    """Download an image and return (base64_data, media_type) or None on failure."""
    try:
        resp = requests.get(url, timeout=timeout, headers={
            "User-Agent": "Mozilla/5.0 (compatible; CincyListings/1.0)"
        })
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        if content_type not in ("image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"):
            content_type = "image/jpeg"
        return base64.standard_b64encode(resp.content).decode("utf-8"), content_type
    except Exception as e:
        logger.debug(f"Image fetch failed ({url[:60]}…): {e}")
        return None


def _analyze_images(images: list[str], client) -> Optional[dict]:
    """
    Send up to MAX_IMAGES_PER_LISTING images to Claude and get structured analysis.
    Returns a dict with overall_score, summary, and per-room breakdowns.
    """
    selected = images[:MAX_IMAGES_PER_LISTING]
    if not selected:
        return None

    # Build the message content — interleave images with a numbering prompt
    content = []
    fetched_count = 0
    for i, url in enumerate(selected):
        result = _fetch_image_b64(url)
        if not result:
            continue
        b64, media_type = result
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": b64},
        })
        content.append({"type": "text", "text": f"[Image {fetched_count + 1}]"})
        fetched_count += 1

    if fetched_count == 0:
        return None

    content.append({
        "type": "text",
        "text": (
            "You are a real estate interior design expert helping home buyers who care about "
            "modern, luxury, and high-quality design. Analyze the listing images above.\n\n"
            "For EACH image, identify:\n"
            "1. room_type: (kitchen, living_room, master_bedroom, bedroom, bathroom, "
            "master_bathroom, dining_room, backyard, garage, basement, exterior, or other)\n"
            "2. modernity_score: 1–10 (10 = ultra-modern 2024 design, 1 = very dated)\n"
            "3. luxury_score: 1–10 (10 = luxury finishes/fixtures, 1 = builder-grade basic)\n"
            "4. condition_score: 1–10 (10 = pristine/new, 1 = needs major work)\n"
            "5. features: list up to 5 notable features visible (e.g. 'quartz countertops', "
            "'waterfall island', 'smart home panel', 'heated floors', 'soaking tub', "
            "'coffered ceiling', 'hardwood floors', 'open concept', 'floor-to-ceiling windows')\n"
            "6. insight: one sentence highlighting what makes this room stand out (or not)\n\n"
            "Then provide an overall assessment:\n"
            "- overall_score: weighted average of all rooms (1–10)\n"
            "- summary: 2–3 sentences describing the home's overall design quality, "
            "what style it leans toward, and who it would appeal to\n\n"
            "Respond ONLY with valid JSON in this exact format:\n"
            "{\n"
            '  "rooms": [\n'
            "    {\n"
            '      "image_index": 1,\n'
            '      "room_type": "kitchen",\n'
            '      "modernity_score": 8,\n'
            '      "luxury_score": 7,\n'
            '      "condition_score": 9,\n'
            '      "features": ["quartz countertops", "stainless appliances"],\n'
            '      "insight": "Clean modern kitchen with quality finishes."\n'
            "    }\n"
            "  ],\n"
            '  "overall_score": 8.0,\n'
            '  "summary": "Well-maintained modern home..."\n'
            "}"
        ),
    })

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": content}],
        )
        raw = response.content[0].text.strip()

        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        analysis = json.loads(raw)

        # Attach the actual image URLs back to each room
        url_map = {i + 1: url for i, url in enumerate(selected[:fetched_count])}
        for room in analysis.get("rooms", []):
            idx = room.get("image_index", 0)
            room["image_url"] = url_map.get(idx, "")

        analysis["analyzed_at"] = datetime.now(timezone.utc).isoformat()
        return analysis

    except json.JSONDecodeError as e:
        logger.warning(f"Claude returned invalid JSON: {e}")
        return None
    except Exception as e:
        logger.warning(f"Claude API error: {e}")
        return None


def analyze_listings(
    listings: list[dict],
    api_key: str,
    force: bool = False,
    max_per_run: int = 200,
) -> list[dict]:
    """
    Analyze images for listings that don't yet have analysis.

    Args:
        listings:    Full listing list (modified in place).
        api_key:     Anthropic API key.
        force:       Re-analyze listings that already have analysis.
        max_per_run: Cap to avoid long runs / runaway costs.

    Returns:
        The same listings list with image_analysis fields filled in.
    """
    try:
        import anthropic
    except ImportError:
        logger.error("anthropic package not installed. Run: pip install anthropic")
        return listings

    client = anthropic.Anthropic(api_key=api_key)

    to_analyze = [
        l for l in listings
        if l.get("images")
        and (l.get("price") or 0) >= 900_000
        and (force or not l.get("image_analysis"))
    ]

    if not to_analyze:
        logger.info("Image analysis: all listings already analyzed — nothing to do")
        return listings

    total = min(len(to_analyze), max_per_run)
    logger.info(f"Image analysis: analyzing {total} listings (of {len(to_analyze)} pending)…")

    done = 0
    errors = 0
    for listing in to_analyze[:max_per_run]:
        try:
            analysis = _analyze_images(listing["images"], client)
            if analysis:
                listing["image_analysis"] = analysis
                done += 1
            else:
                errors += 1
        except Exception as e:
            logger.warning(f"Analysis failed for {listing.get('address', '?')}: {e}")
            errors += 1

        if done % 10 == 0 and done > 0:
            logger.info(f"Image analysis: {done}/{total} done…")

        time.sleep(REQUEST_DELAY)

    logger.info(f"Image analysis complete: {done} analyzed, {errors} failed")
    return listings
