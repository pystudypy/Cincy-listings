"""
AI-powered listing image analysis.

Supports two backends:
  - Ollama  (local, free)  — default when OLLAMA_HOST is reachable
  - Claude  (Anthropic API) — fallback, requires ANTHROPIC_API_KEY

For each listing, analyzes up to MAX_IMAGES_PER_LISTING images:
  - Identifies the room type
  - Rates modernity, luxury, and condition (1–10)
  - Lists key features visible in the image
  - Writes a short insight

Usage:
    # Local Ollama (recommended)
    from utils.image_analyzer import analyze_listings
    listings = analyze_listings(listings, backend="ollama")

    # Claude fallback
    listings = analyze_listings(listings, api_key="sk-ant-...", backend="claude")
"""

import base64
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)

OLLAMA_HOST            = "http://localhost:11434"
OLLAMA_MODEL           = "qwen2.5vl:72b"
CLAUDE_MODEL           = "claude-haiku-4-5-20251001"
MAX_IMAGES_PER_LISTING = 20
REQUEST_DELAY          = 0.3   # seconds between API calls (local is fast)

PROMPT = """You are a real estate interior design expert helping home buyers who care about modern, luxury, and high-quality design. Analyze each listing image carefully.

For EACH image, identify:
1. room_type — pick EXACTLY one from this list based on what you actually see:
   - "kitchen": visible countertops, cabinets, appliances, or sink
   - "living_room": sofas/seating area, TV, fireplace — NOT a bedroom
   - "master_bedroom": large bedroom, often with ensuite or sitting area
   - "bedroom": any other bedroom
   - "master_bathroom": large bathroom with double vanity, soaking tub, or walk-in shower
   - "bathroom": smaller bathroom, single vanity or powder room
   - "dining_room": dining table and chairs as the main focus
   - "backyard": outdoor space, yard, pool, patio
   - "garage": cars, garage doors, or workshop
   - "basement": below-grade space, recreation room
   - "exterior": front/back of house from outside
   - "other": laundry, hallway, office, gym, or anything else

2. modernity_score: 1–10 (10 = ultra-modern 2024 design, 1 = very dated 1980s style)
3. luxury_score: 1–10 (10 = high-end luxury finishes, 1 = basic builder-grade)
4. condition_score: 1–10 (10 = pristine/new, 1 = needs major renovation)
5. features: up to 5 notable features visible (e.g. "quartz countertops", "waterfall island", "soaking tub", "coffered ceiling", "hardwood floors", "floor-to-ceiling windows", "smart home panel")
6. insight: one sentence about what makes this room stand out (or not)

Then provide overall:
- overall_score: weighted average 1–10 (weight kitchens and master bathrooms more heavily)
- summary: 2–3 sentences on design quality, style, and who this home would appeal to

Respond ONLY with valid JSON, no markdown, no explanation:
{
  "rooms": [
    {
      "image_index": 1,
      "room_type": "kitchen",
      "modernity_score": 9,
      "luxury_score": 8,
      "condition_score": 10,
      "features": ["quartz countertops", "waterfall island", "stainless appliances"],
      "insight": "Stunning modern kitchen with premium finishes throughout."
    }
  ],
  "overall_score": 8.5,
  "summary": "A beautifully renovated contemporary home..."
}"""


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


def _parse_json_response(raw: str) -> Optional[dict]:
    """Strip markdown fences and parse JSON."""
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    # Sometimes the model wraps in extra text — find the JSON object
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    if start != -1 and end > start:
        raw = raw[start:end]
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse error: {e} | raw: {raw[:200]}")
        return None


def _analyze_with_ollama(images: list[str]) -> Optional[dict]:
    """Send images to local Ollama qwen2.5vl model via OpenAI-compatible API."""
    selected = images[:MAX_IMAGES_PER_LISTING]

    # Fetch and encode images
    encoded = []
    url_map = {}
    for url in selected:
        result = _fetch_image_b64(url)
        if result:
            b64, _ = result
            idx = len(encoded) + 1
            encoded.append(b64)
            url_map[idx] = url

    if not encoded:
        return None

    # Build OpenAI-compatible message with images
    content = []
    for i, b64 in enumerate(encoded):
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
        })
        content.append({"type": "text", "text": f"[Image {i + 1}]"})
    content.append({"type": "text", "text": PROMPT})

    try:
        resp = requests.post(
            f"{OLLAMA_HOST}/v1/chat/completions",
            json={
                "model": OLLAMA_MODEL,
                "messages": [{"role": "user", "content": content}],
                "temperature": 0.1,
                "max_tokens": 4096,
            },
            timeout=300,  # local model can be slow for many images
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]
        analysis = _parse_json_response(raw)
        if not analysis:
            return None

        for room in analysis.get("rooms", []):
            idx = room.get("image_index", 0)
            room["image_url"] = url_map.get(idx, "")

        analysis["analyzed_at"] = datetime.now(timezone.utc).isoformat()
        analysis["backend"] = "ollama"
        return analysis

    except Exception as e:
        logger.warning(f"Ollama error: {e}")
        return None


def _analyze_with_claude(images: list[str], client) -> Optional[dict]:
    """Send images to Claude API."""
    selected = images[:MAX_IMAGES_PER_LISTING]

    content = []
    fetched_count = 0
    url_map = {}
    for url in selected:
        result = _fetch_image_b64(url)
        if not result:
            continue
        b64, media_type = result
        fetched_count += 1
        url_map[fetched_count] = url
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": b64},
        })
        content.append({"type": "text", "text": f"[Image {fetched_count}]"})

    if not fetched_count:
        return None

    content.append({"type": "text", "text": PROMPT})

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": content}],
        )
        raw = response.content[0].text
        analysis = _parse_json_response(raw)
        if not analysis:
            return None

        for room in analysis.get("rooms", []):
            idx = room.get("image_index", 0)
            room["image_url"] = url_map.get(idx, "")

        analysis["analyzed_at"] = datetime.now(timezone.utc).isoformat()
        analysis["backend"] = "claude"
        return analysis

    except Exception as e:
        logger.warning(f"Claude API error: {e}")
        return None


def _ollama_available() -> bool:
    try:
        r = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=3)
        # Check the model is actually pulled
        models = [m["name"] for m in r.json().get("models", [])]
        return any(OLLAMA_MODEL.split(":")[0] in m for m in models)
    except Exception:
        return False


def analyze_listings(
    listings: list[dict],
    api_key: str = "",
    backend: str = "auto",   # "auto" | "ollama" | "claude"
    force: bool = False,
    max_per_run: int = 400,
) -> list[dict]:
    """
    Analyze images for listings that don't yet have analysis.

    Args:
        listings:    Full listing list (modified in place).
        api_key:     Anthropic API key (only needed for claude backend).
        backend:     "auto" tries Ollama first, falls back to Claude.
        force:       Re-analyze listings that already have analysis.
        max_per_run: Cap to avoid very long runs.
    """
    # Resolve backend
    use_ollama = False
    claude_client = None

    if backend in ("auto", "ollama"):
        if _ollama_available():
            use_ollama = True
            logger.info(f"Using local Ollama backend ({OLLAMA_MODEL})")
        elif backend == "ollama":
            logger.error(f"Ollama not available or {OLLAMA_MODEL} not pulled. Run: ollama pull {OLLAMA_MODEL}")
            return listings
        else:
            logger.info("Ollama not available — falling back to Claude")

    if not use_ollama:
        if not api_key:
            logger.error("No ANTHROPIC_API_KEY set and Ollama unavailable — cannot analyze")
            return listings
        try:
            import anthropic
            claude_client = anthropic.Anthropic(api_key=api_key)
            logger.info(f"Using Claude backend ({CLAUDE_MODEL})")
        except ImportError:
            logger.error("anthropic package not installed. Run: pip install anthropic")
            return listings

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
            if use_ollama:
                analysis = _analyze_with_ollama(listing["images"])
            else:
                analysis = _analyze_with_claude(listing["images"], claude_client)

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
