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

OLLAMA_HOST                 = "http://localhost:11434"
OLLAMA_MODEL                = "qwen2.5vl:72b"
CLAUDE_MODEL                = "claude-haiku-4-5-20251001"
MAX_IMAGES_PER_LISTING      = 20   # stored / sent to Claude
MAX_IMAGES_OLLAMA           = 8    # Ollama: 72B struggles with more than 8-10 images
OLLAMA_IMAGE_MAX_PX         = 768  # resize images to max this dimension before sending
REQUEST_DELAY               = 0.3

PROMPT = """You are helping everyday home buyers understand what they are looking at in listing photos. Write like a knowledgeable friend walking through the house with them — clear, honest, no real estate jargon.

For EACH image, identify:

1. room_type — pick EXACTLY one based strictly on what you can see:
   - "kitchen": countertops, cabinets, stove, sink, or appliances are visible
   - "living_room": sofa or seating area is the main focus — NOT a bedroom
   - "master_bedroom": the largest bedroom, often has more space or an attached sitting area
   - "bedroom": any other bedroom with a bed as the main focus
   - "master_bathroom": large bathroom with double sinks, soaking tub, or oversized shower
   - "bathroom": smaller bathroom, single sink, or powder/half bath
   - "dining_room": dining table and chairs are the clear focus
   - "backyard": outdoor yard, patio, deck, or pool
   - "garage": car parking area, garage doors visible
   - "basement": below-grade finished or unfinished space
   - "exterior": outside view of the house from the street or yard
   - "other": laundry room, hallway, home office, gym, or anything else

2. modernity_score: 1–10
   10=brand new ultra-modern, 8-9=very modern updated feel, 6-7=updated but not cutting edge,
   4-5=dated but functional, 2-3=clearly old-fashioned, 1=very run-down look

3. luxury_score: 1–10
   10=high-end luxury (think magazine-worthy), 8-9=upscale finishes, 6-7=above average quality,
   4-5=standard builder finishes, 2-3=very basic, 1=cheap materials visible

4. condition_score: 1–10
   10=looks brand new or just renovated, 8-9=excellent shape, 6-7=good condition minor wear,
   4-5=needs cosmetic updates (paint, fixtures), 2-3=needs real work, 1=major renovation needed

5. features: up to 5 things a buyer would actually notice and care about, in plain language.
   Good examples: "big island with seating", "brand new appliances", "walk-in shower with glass doors",
   "soaking tub", "tons of cabinet storage", "hardwood floors throughout", "lots of natural light",
   "open layout — kitchen connects to living area", "finished basement", "two-car garage",
   "large fenced backyard", "in-ground pool", "high ceilings".
   Avoid jargon like "coffered ceiling", "waterfall edge", "quartz substrate".

6. insight: 2–3 sentences written like a friend explaining this room to the buyer.
   Focus on: Is this room ready to use as-is or does it need work? What's the best thing about it?
   What would a buyer with a family / who likes to cook / who entertains notice most?
   Be honest — if something looks dated or basic, say so clearly but constructively.
   Example: "The kitchen looks fully updated with new counters and appliances — you could move in and
   start cooking day one. The big island has seating for four, which is great if you like to cook and
   have people over. Storage looks generous with cabinets on all sides."

Then provide overall:
- overall_score: 1–10, weighted average giving extra weight to kitchen and master bathroom
- summary: 2–3 plain-English sentences answering: Is this home move-in ready? What style does it lean toward?
  Who is this home a good fit for? Be direct and practical — mention things like basement, garage, outdoor
  space if visible. Avoid vague phrases like "appeals to discerning buyers".

Respond ONLY with valid JSON, no markdown fences, no explanation before or after:
{
  "rooms": [
    {
      "image_index": 1,
      "room_type": "kitchen",
      "modernity_score": 9,
      "luxury_score": 8,
      "condition_score": 10,
      "features": ["big island with seating", "brand new appliances", "tons of cabinet storage"],
      "insight": "The kitchen looks completely updated and ready to use from day one. The large island has room for four people to sit, making it great for families or anyone who likes to cook and entertain. Storage is generous with cabinets covering all walls."
    }
  ],
  "overall_score": 8.5,
  "summary": "This home is move-in ready — the kitchen and bathrooms have already been updated so you won't need to spend extra fixing them up right away. The style is clean and modern without being cold. Good fit for a family or couple who wants a turnkey home and space to entertain."
}"""


def _fetch_image_b64(url: str, timeout: int = 10, max_px: int = 0) -> Optional[tuple[str, str]]:
    """Download an image, optionally resize it, return (base64_data, media_type) or None."""
    try:
        resp = requests.get(url, timeout=timeout, headers={
            "User-Agent": "Mozilla/5.0 (compatible; CincyListings/1.0)"
        })
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        if content_type not in ("image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"):
            content_type = "image/jpeg"

        img_bytes = resp.content

        # Resize if requested (keeps aspect ratio, caps longest side to max_px)
        if max_px > 0:
            try:
                from PIL import Image as PILImage
                import io
                img = PILImage.open(io.BytesIO(img_bytes))
                w, h = img.size
                if max(w, h) > max_px:
                    scale = max_px / max(w, h)
                    img = img.resize((int(w * scale), int(h * scale)), PILImage.LANCZOS)
                buf = io.BytesIO()
                img.convert("RGB").save(buf, format="JPEG", quality=85)
                img_bytes = buf.getvalue()
                content_type = "image/jpeg"
            except ImportError:
                pass  # PIL not installed — send original size
            except Exception:
                pass  # resize failed — send original size

        return base64.standard_b64encode(img_bytes).decode("utf-8"), content_type
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
    selected = images[:MAX_IMAGES_OLLAMA]

    # Fetch, resize, and encode images
    encoded = []
    url_map = {}
    for url in selected:
        result = _fetch_image_b64(url, max_px=OLLAMA_IMAGE_MAX_PX)
        if result:
            b64, _ = result
            idx = len(encoded) + 1
            encoded.append(b64)
            url_map[idx] = url

    if not encoded:
        return None

    # Native Ollama API: images go in the `images` field, text in `content`
    img_markers = "\n".join([f"[Image {i+1}]" for i in range(len(encoded))])
    message_content = img_markers + "\n\n" + PROMPT

    try:
        # Use native Ollama API so num_ctx is respected (OpenAI compat ignores it)
        resp = requests.post(
            f"{OLLAMA_HOST}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "stream": False,
                "options": {
                    "num_ctx": 12288,   # fits comfortably in 128GB: ~8GB KV cache
                    "temperature": 0.1,
                    "num_predict": 4096,
                },
                "messages": [{"role": "user", "content": message_content, "images": encoded}],
            },
            timeout=600,
        )
        resp.raise_for_status()
        raw = resp.json()["message"]["content"]
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
