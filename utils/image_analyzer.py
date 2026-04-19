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
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

OLLAMA_HOST                 = "http://localhost:11434"
OLLAMA_MODEL                = "qwen2.5vl:7b"
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
    checkpoint_every: int = 10,
    checkpoint_fn=None,       # called with (listings) every checkpoint_every successes
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

        if done % checkpoint_every == 0 and done > 0:
            logger.info(f"Image analysis: {done}/{total} done…")
            if checkpoint_fn:
                checkpoint_fn(listings)

        time.sleep(REQUEST_DELAY)

    logger.info(f"Image analysis complete: {done} analyzed, {errors} failed")
    return listings


# ---------------------------------------------------------------------------
# Feature extraction — two-pass, room-specific, structured taxonomy tags
# ---------------------------------------------------------------------------

_SKILLS_DIR = Path(__file__).parent.parent / "ai_agent" / "skills"
_TAXONOMY_FILE = Path(__file__).parent.parent / "ai_agent" / "knowledge" / "feature_taxonomy.md"

# Maps room_type strings (returned by classification) → skill filename stem
_ROOM_TO_SKILL = {
    "kitchen":          "kitchen",
    "bathroom":         "bathroom",
    "master_bathroom":  "bathroom",
    "living_room":      "living_space",
    "dining_room":      "living_space",
    "family_room":      "living_space",
    "master_bedroom":   "bedroom",
    "bedroom":          "bedroom",
    "exterior":         "exterior",
    "backyard":         "exterior",
    "garage":           "exterior",
    "basement":         "basement",
    "other":            None,   # no focused skill — skip structured extraction
}

# Taxonomy tags grouped by the skill they belong to (for focused prompts)
_TAXONOMY_BY_SKILL = {
    "kitchen": [
        "kitchen_island", "kitchen_island_seating",
        "quartz_counters", "granite_counters", "marble_counters",
        "butcher_block_counters", "laminate_counters",
        "white_cabinets", "dark_cabinets", "wood_cabinets", "custom_cabinets", "open_shelving",
        "stainless_appliances", "black_appliances", "white_appliances", "luxury_appliances",
        "double_oven", "gas_range", "farmhouse_sink",
        "tile_backsplash", "subway_tile_backsplash",
        "pendant_lights_kitchen", "under_cabinet_lighting",
        "open_concept_kitchen", "breakfast_bar", "pantry",
        "updated_kitchen", "dated_kitchen",
    ],
    "bathroom": [
        "walk_in_shower", "frameless_glass_shower", "soaking_tub", "clawfoot_tub",
        "double_vanity", "floating_vanity", "vessel_sink",
        "marble_tile_bath", "rain_shower_head",
        "updated_bathroom", "dated_bathroom", "spa_bathroom",
    ],
    "living_space": [
        "fireplace", "gas_fireplace", "wood_burning_fireplace",
        "built_ins", "coffered_ceiling", "tray_ceiling", "vaulted_ceiling",
        "crown_molding", "wainscoting",
        "hardwood_floors", "luxury_vinyl_floors", "tile_floors",
        "open_floor_plan", "high_ceilings", "recessed_lighting", "natural_light",
        "home_office", "home_theater", "wet_bar", "sunroom",
    ],
    "bedroom": [
        "walk_in_closet", "custom_closet", "en_suite_bathroom",
        "tray_ceiling_bedroom", "vaulted_ceiling_bedroom",
    ],
    "exterior": [
        "inground_pool", "hot_tub", "deck", "patio", "covered_porch",
        "pergola", "outdoor_kitchen", "fire_pit",
        "fenced_yard", "landscaped_yard", "large_lot",
        "three_car_garage", "two_car_garage", "detached_garage",
        "ev_charger", "solar_panels",
    ],
    "basement": [
        "finished_basement", "walkout_basement", "in_law_suite",
        "sauna", "home_gym", "wine_cellar",
        "laundry_room", "mudroom",
    ],
}

_CONDITION_TAGS = {
    "move_in_ready", "needs_cosmetic_update", "fixer_upper",
    "new_construction_feel", "historic_character",
}

CLASSIFICATION_PROMPT = """For each image shown, return ONLY image_index and room_type.

Room types (use EXACTLY one of these):
kitchen | bathroom | master_bathroom | living_room | dining_room | master_bedroom | bedroom | backyard | garage | basement | exterior | other

Return ONLY valid JSON — no explanation, no markdown:
{"rooms": [{"image_index": 1, "room_type": "kitchen"}, ...]}"""

EXTRACTION_PROMPT_TEMPLATE = """\
You are analyzing {room_label} photo(s) for a real estate listing on behalf of a home buyer.

=== SKILL GUIDE ===
{skill_content}

=== FEATURE TAXONOMY — use ONLY these exact tag strings ===
{taxonomy_tags}

=== CONDITION TAGS — emit exactly one of these ===
move_in_ready | needs_cosmetic_update | fixer_upper | new_construction_feel | historic_character

For the {count} image(s) shown, return ONLY valid JSON — no markdown, no explanation:
{{
  "features_tags": ["tag1", "tag2"],
  "condition": "move_in_ready",
  "insight": "2-3 sentences a buyer would find genuinely useful."
}}

Rules:
- Only emit tags where you have CLEAR visual evidence — do not guess
- features_tags must contain ONLY strings from the taxonomy above
- condition must be EXACTLY one of the five strings above
- insight should be specific, honest, buyer-focused (no agent language)"""


def _load_skill(skill_name: str) -> str:
    """Load a skill file, returning empty string if not found."""
    path = _SKILLS_DIR / f"{skill_name}.md"
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _classify_images_claude(images: list[str], client) -> list[dict]:
    """Pass 1: classify room types for all images. Returns [{image_index, room_type}, ...]."""
    content = []
    url_map = {}
    fetched = 0
    for url in images[:MAX_IMAGES_PER_LISTING]:
        result = _fetch_image_b64(url)
        if not result:
            continue
        b64, media_type = result
        fetched += 1
        url_map[fetched] = url
        content.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}})
        content.append({"type": "text", "text": f"[Image {fetched}]"})

    if not fetched:
        return []

    content.append({"type": "text", "text": CLASSIFICATION_PROMPT})

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": content}],
        )
        parsed = _parse_json_response(response.content[0].text)
        if not parsed:
            return []
        rooms = parsed.get("rooms", [])
        # Attach original URL to each classified room
        for r in rooms:
            r["image_url"] = url_map.get(r.get("image_index", 0), "")
        return rooms
    except Exception as e:
        logger.warning(f"Classification API error: {e}")
        return []


def _extract_room_features_claude(
    skill_name: str,
    room_label: str,
    image_urls: list[str],
    client,
) -> Optional[dict]:
    """Pass 2: extract structured tags for a single room type using the room skill."""
    skill_content = _load_skill(skill_name)
    taxonomy_tags = "\n".join(f"  {t}" for t in _TAXONOMY_BY_SKILL.get(skill_name, []))

    content = []
    fetched = 0
    for url in image_urls[:6]:  # cap at 6 images per room type
        result = _fetch_image_b64(url)
        if not result:
            continue
        b64, media_type = result
        fetched += 1
        content.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}})
        content.append({"type": "text", "text": f"[Image {fetched}]"})

    if not fetched:
        return None

    prompt = EXTRACTION_PROMPT_TEMPLATE.format(
        room_label=room_label,
        skill_content=skill_content if skill_content else f"Analyze this {room_label} carefully.",
        taxonomy_tags=taxonomy_tags,
        count=fetched,
    )
    content.append({"type": "text", "text": prompt})

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": content}],
        )
        parsed = _parse_json_response(response.content[0].text)
        if not parsed:
            return None
        parsed["room_type"] = skill_name
        parsed["room_label"] = room_label
        return parsed
    except Exception as e:
        logger.warning(f"Extraction API error ({room_label}): {e}")
        return None


def extract_features(
    listings: list[dict],
    api_key: str = "",
    force: bool = False,
    max_per_run: int = 500,
    checkpoint_every: int = 25,
    checkpoint_fn=None,
) -> list[dict]:
    """
    Two-pass vision agent that extracts structured feature tags from listing photos.

    Pass 1: Classify room types across all images (1 API call per listing).
    Pass 2: For each room type found, run a focused skill-guided extraction
            (1 API call per room type per listing, typically 3-5 calls).

    Results are stored in listing["features"] — a sorted list of taxonomy tag strings.
    This does NOT modify listing["image_analysis"] (existing display data is preserved).

    Args:
        listings:        Full listing list (modified in place).
        api_key:         Anthropic API key.
        force:           Re-extract even if listing["features"] already set.
        max_per_run:     Max listings to process per run.
        checkpoint_every: Save checkpoint after this many listings.
        checkpoint_fn:   Called with (listings) at each checkpoint.
    """
    if not api_key:
        logger.error("extract_features requires ANTHROPIC_API_KEY — cannot run")
        return listings

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
    except ImportError:
        logger.error("anthropic package not installed. Run: pip install anthropic")
        return listings

    to_process = [
        l for l in listings
        if l.get("images") and (force or not l.get("features"))
    ]

    if not to_process:
        logger.info("Feature extraction: all listings already have features — nothing to do")
        return listings

    total = min(len(to_process), max_per_run)
    logger.info(f"Feature extraction: processing {total} listings (of {len(to_process)} pending)…")

    done = errors = 0
    last_checkpoint = 0

    for listing in to_process[:max_per_run]:
        addr = listing.get("address", "?")
        images = listing.get("images") or []

        try:
            # --- Pass 1: Classify all images ---
            classified = _classify_images_claude(images, client)
            if not classified:
                logger.warning(f"  [{addr}] Classification returned no rooms — skipping")
                errors += 1
                continue

            # Group image URLs by room type
            by_skill: dict[str, list[str]] = {}
            for r in classified:
                room_type = r.get("room_type", "other")
                skill = _ROOM_TO_SKILL.get(room_type)
                if skill is None:
                    continue
                url = r.get("image_url", "")
                if url:
                    by_skill.setdefault(skill, []).append(url)

            room_labels = {
                "kitchen": "kitchen",
                "bathroom": "bathroom (including master bathroom)",
                "living_space": "living/dining/family room",
                "bedroom": "bedroom (including master bedroom)",
                "exterior": "exterior, backyard, and garage",
                "basement": "basement and utility spaces",
            }

            all_tags: set[str] = set()
            condition_votes: list[str] = []
            room_results: list[dict] = []

            # --- Pass 2: Focused extraction per room type ---
            for skill_name, urls in by_skill.items():
                if not urls:
                    continue
                label = room_labels.get(skill_name, skill_name)
                result = _extract_room_features_claude(skill_name, label, urls, client)
                if result:
                    tags = result.get("features_tags") or []
                    # Validate tags against known taxonomy
                    valid_tags = [t for t in tags if t in _TAXONOMY_BY_SKILL.get(skill_name, [])]
                    all_tags.update(valid_tags)
                    condition = result.get("condition", "")
                    if condition in _CONDITION_TAGS:
                        condition_votes.append(condition)
                    room_results.append(result)
                time.sleep(REQUEST_DELAY)

            # Pick the most-voted condition tag (or first if tied)
            if condition_votes:
                from collections import Counter
                condition_winner = Counter(condition_votes).most_common(1)[0][0]
                all_tags.add(condition_winner)

            listing["features"] = sorted(all_tags)
            listing["features_extracted_at"] = datetime.now(timezone.utc).isoformat()
            done += 1

            tag_count = len(all_tags)
            room_count = len(room_results)
            logger.info(f"  [{addr}] {room_count} room types → {tag_count} tags: {sorted(all_tags)[:6]}{'…' if tag_count > 6 else ''}")

        except Exception as e:
            logger.warning(f"  [{addr}] Feature extraction failed: {e}")
            errors += 1

        # Checkpoint
        milestone = (done // checkpoint_every) * checkpoint_every
        if milestone > last_checkpoint and milestone > 0:
            last_checkpoint = milestone
            logger.info(f"Feature extraction: {done}/{total} done, {errors} errors…")
            if checkpoint_fn:
                checkpoint_fn(listings)

        time.sleep(REQUEST_DELAY)

    logger.info(f"Feature extraction complete: {done} processed, {errors} failed")
    if checkpoint_fn and done > 0:
        checkpoint_fn(listings)
    return listings
