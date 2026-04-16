"""
Local AI Deep Dive server for testing.

Runs a lightweight HTTP server on port 5001 that accepts listing data,
calls Claude with vision, and returns a structured room analysis.

Usage:
    ANTHROPIC_API_KEY=sk-... python server.py
    # or export the key first:
    export ANTHROPIC_API_KEY=sk-...
    python server.py
"""

import base64
import json
import logging
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PORT = int(os.environ.get("PORT", 8080))
MAX_IMAGES = 50
DOCS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

def sanitize_json(raw: str) -> str:
    """Replace literal control characters that make JSON invalid inside string values."""
    return re.sub(r'[\x00-\x1f\x7f]', ' ', raw)


def call_claude(api_key: str, messages: list, max_tokens: int) -> str:
    """Call Claude REST API directly via requests — avoids httpx/GCP incompatibility."""
    resp = requests.post(
        ANTHROPIC_API_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={"model": CLAUDE_MODEL, "max_tokens": max_tokens, "messages": messages},
        timeout=300,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]

AI_AGENT_DIR = os.path.join(os.path.dirname(__file__), "ai_agent")


# ── Knowledge base ────────────────────────────────────────────────────────────

def load_knowledge_base() -> str:
    """Load all ai_agent/*.md files and return as a single context block."""
    files = ["knowledge.md", "luxury.md", "skills.md", "cincinnati_context.md", "buyer_profiles.md"]
    sections = []
    loaded = []
    for fname in files:
        path = os.path.join(AI_AGENT_DIR, fname)
        if os.path.exists(path):
            content = open(path, encoding="utf-8").read().strip()
            sections.append(f"=== {fname.upper()} ===\n{content}")
            loaded.append(fname)
    if loaded:
        logger.info(f"Knowledge base loaded: {', '.join(loaded)}")
    else:
        logger.warning(f"No knowledge base files found in {AI_AGENT_DIR}")
    return "\n\n".join(sections)


def infer_buyer_profile(body: dict) -> str:
    """Infer the most likely buyer type from listing data."""
    price = body.get("price") or 0
    beds  = body.get("beds") or 0
    desc  = (body.get("description") or "").lower()
    investor_signals = any(w in desc for w in ["as-is", "investor", "estate", "needs tlc", "tlc", "potential"])
    if investor_signals or price < 180_000:
        return "investor_or_renovator — focus on structural bones, system costs, and ROI potential. Use terse contractor-speak. Do not over-explain cosmetic issues."
    if price >= 700_000:
        return "luxury_buyer — focus on finish quality, craftsmanship, and uniqueness. Use discerning, elevated language. Flag anything that undermines premium positioning."
    if price >= 350_000 and beds >= 3:
        return "move_up_family_buyer — focus on livability, safety, storage, outdoor space, and 5-year cost horizon."
    return "first_time_buyer — be protective and thorough. Explain what things mean. Err on side of caution. Provide clear cost estimates."


KNOWLEDGE_BASE = load_knowledge_base()


# ── Prompt ────────────────────────────────────────────────────────────────────

BASE_PROMPT = """You are helping everyday home buyers understand what they are looking at in listing photos. Write like a knowledgeable friend walking through the house with them — clear, honest, no real estate jargon.

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

2. modernity_score: 1–10 (10=ultra-modern, 1=very run-down look)
3. luxury_score: 1–10 (10=high-end luxury, 1=cheap materials)
4. condition_score: 1–10 (10=brand new, 1=major renovation needed)

5. features: up to 5 things a buyer would notice and care about, in plain language.

6. insight: 2–3 sentences written like a friend explaining this room. Is it ready to use or needs work? What stands out?

Then provide overall:
- overall_score: 1–10 weighted average (extra weight to kitchen and master bathroom)
- summary: exactly 3 short bullet points as a single string, each on its own line starting with "• ". Cover: (1) move-in readiness, (2) style/feel, (3) ideal buyer.

Also provide two additional buyer-focused arrays using the listing context above:
- red_flags: up to 3 short strings — specific things a buyer should ask about or have inspected.
  Examples: "Roof age not mentioned in listing — ask seller", "Basement image suggests possible moisture",
  "Kitchen described as 'updated' but photos show dated appliances — verify what was actually updated",
  "No HVAC age mentioned for a home this old", "Exterior paint is peeling in multiple spots"
  Base these on BOTH what you see in the photos AND any gaps/inconsistencies in the listing description.

- hidden_value: up to 3 short strings — underpriced features or opportunities the buyer might miss.
  Examples: "Large unfinished basement — could add 400+ sqft of living space relatively cheaply",
  "Corner lot with full privacy fence — rare in this ZIP code", "Original hardwood floors visible under carpet",
  "Detached garage has extra storage loft", "South-facing backyard gets full sun all day"
  Focus on things that are genuinely valuable but easy to overlook in a quick browse.

Respond ONLY with valid JSON, no markdown fences, no explanation:
{
  "rooms": [
    {
      "image_index": 1,
      "room_type": "kitchen",
      "modernity_score": 9,
      "luxury_score": 8,
      "condition_score": 10,
      "features": ["big island with seating", "brand new appliances"],
      "insight": "The kitchen looks fully updated — move in and start cooking day one. The large island seats four, great for families or entertaining. Storage is generous with cabinets on all walls."
    }
  ],
  "overall_score": 8.5,
  "summary": "• Move-in ready — kitchen and bathrooms already updated.\n• Clean modern style without feeling cold.\n• Best for a family or couple wanting a turnkey home with space to entertain.",
  "red_flags": ["Roof age not mentioned — ask seller before making an offer"],
  "hidden_value": ["Large unfinished basement could add significant living space"]
}"""


def fetch_image_b64(url: str) -> tuple[str, str] | None:
    """Download image URL and return (base64_data, media_type) or None."""
    try:
        resp = requests.get(url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (compatible; CincyListings/1.0)",
            "Referer": "",
        })
        resp.raise_for_status()
        ct = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip().lower()
        # Normalize non-standard variants; Claude accepts only these four
        if ct == "image/jpg":
            ct = "image/jpeg"
        elif ct not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
            ct = "image/jpeg"
        return base64.standard_b64encode(resp.content).decode(), ct
    except Exception as e:
        logger.debug(f"Image fetch failed {url[:60]}: {e}")
        return None


def build_context_block(body: dict) -> str:
    parts = []
    if body.get("price"):
        parts.append(f"List price: ${body['price']:,}")
    if body.get("address"):
        parts.append(f"Address: {body['address']}")
    beds, baths, sqft = body.get("beds"), body.get("baths"), body.get("sqft")
    if beds or baths:
        parts.append(f"Beds/Baths: {beds or '?'} bd / {baths or '?'} ba")
    if sqft:
        parts.append(f"Size: {sqft:,} sqft")
    if body.get("days_on_market") is not None:
        parts.append(f"This listing's days on market: {body['days_on_market']}")
    if body.get("description"):
        parts.append(f"Listing description: \"{body['description'][:600]}\"")
    if body.get("features"):
        parts.append(f"Tagged features: {', '.join(body['features'])}")
    return "\n".join(parts)


def analyze(body: dict, api_key: str) -> dict | None:
    """Fetch images, call Claude, return analysis dict."""
    images = (body.get("images") or [])[:MAX_IMAGES]
    if not images:
        return None

    # Fetch images in parallel
    encoded = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch_image_b64, url): i for i, url in enumerate(images)}
        for future in as_completed(futures):
            i = futures[future]
            result = future.result()
            if result:
                encoded[i] = result

    if not encoded:
        return None

    # Build message content: image + label pairs, then prompt
    content = []
    url_map = {}
    img_num = 0
    for i in range(len(images)):
        if i not in encoded:
            continue
        img_num += 1
        b64, media_type = encoded[i]
        url_map[img_num] = images[i]
        content.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}})
        content.append({"type": "text", "text": f"[Image {img_num}]"})

    context = build_context_block(body)
    buyer_profile = infer_buyer_profile(body)
    kb_block = f"{KNOWLEDGE_BASE}\n\n---\n" if KNOWLEDGE_BASE else ""
    profile_block = f"BUYER PROFILE: {buyer_profile}\n\n"
    context_block = f"LISTING CONTEXT:\n{context}\n\n---\n\n" if context else ""
    full_prompt = f"{kb_block}{profile_block}{context_block}{BASE_PROMPT}"
    content.append({"type": "text", "text": full_prompt})

    # Call Claude
    try:
        raw = call_claude(api_key, [{"role": "user", "content": content}], 4096)
    except Exception as e:
        logger.error(f"Claude API error [{type(e).__name__}]: {e}")
        return None

    # Parse JSON
    raw = sanitize_json(raw.strip())
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1].lstrip("json").strip() if len(parts) > 1 else raw
    start, end = raw.find("{"), raw.rfind("}") + 1
    if start != -1 and end > start:
        raw = raw[start:end]
    try:
        analysis = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e} | raw[:200]: {raw[:200]}")
        return None

    # Add image_url back to each room
    for room in analysis.get("rooms", []):
        idx = room.get("image_index", 0)
        room["image_url"] = url_map.get(idx, "")

    analysis["analyzed_at"] = datetime.now(timezone.utc).isoformat()
    analysis["backend"] = "claude-realtime"
    return analysis


# ── Offer Strategy ───────────────────────────────────────────────────────────

OFFER_STRATEGY_PROMPT = """You are a veteran Cincinnati real estate agent giving a buyer a direct offer strategy.

You have: listing details, days on market, price vs ZIP median PPSF, the AI photo analysis (condition scores, red flags), and the buyer's profile.

Rules:
- Give a specific dollar range and % below ask. Never say "it depends."
- Every WHY bullet must cite a specific data point (room score, DOM, PPSF delta, flag name).
- Use Cincinnati market knowledge to contextualize DOM (e.g., Hyde Park typically moves in 18 days).
- The tactic should say HOW to present the offer, not just what number.
- One risk: the single factor that could change this strategy.
- Keep the whole response to 120-180 words.

Respond ONLY with valid JSON, no markdown:
{
  "range_low": 685000,
  "range_high": 705000,
  "pct_below_low": 5,
  "pct_below_high": 8,
  "why_bullets": ["bullet with specific data", "..."],
  "tactic": "2-3 sentence paragraph",
  "one_risk": "one sentence",
  "confidence": "high|medium|low",
  "confidence_note": "brief note if medium or low — omit key if high"
}"""


# ── Compare ───────────────────────────────────────────────────────────────────

COMPARE_AGENT_FILE = os.path.join(AI_AGENT_DIR, "compare.md")
MAX_COMPARE_IMAGES = 8   # per home — enough to cover key rooms


def compare_listings(homes: list, api_key: str) -> dict | None:
    """Vision-based comparison of 2 homes using actual listing photos."""
    if len(homes) < 2:
        return None

    # Load compare agent prompt
    agent_prompt = ""
    if os.path.exists(COMPARE_AGENT_FILE):
        agent_prompt = open(COMPARE_AGENT_FILE, encoding="utf-8").read().strip() + "\n\n"

    # Fetch images for both homes in parallel
    def fetch_home_images(image_urls: list) -> list:
        results = {}
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(fetch_image_b64, url): i for i, url in enumerate(image_urls)}
            for future in as_completed(futures):
                i = futures[future]
                result = future.result()
                if result:
                    results[i] = result
        return [results[i] for i in sorted(results)]

    def _fmt(val, suffix=""):
        return f" | {val:,}{suffix}" if val else ""

    # Fetch images for all homes in parallel
    all_imgs = []
    with ThreadPoolExecutor(max_workers=len(homes)) as pool:
        futures = [pool.submit(fetch_home_images, (h.get("images") or [])[:MAX_COMPARE_IMAGES]) for h in homes]
        all_imgs = [f.result() for f in futures]

    if not any(all_imgs):
        logger.warning("Compare: couldn't fetch images for any home")

    # Build vision content: HOME N images labeled sequentially
    content = []
    labels = ["HOME 1", "HOME 2", "HOME 3"]
    for h_idx, imgs in enumerate(all_imgs):
        label = labels[h_idx]
        for idx, (b64, mt) in enumerate(imgs, 1):
            content.append({"type": "text",  "text": f"[{label} — Image {idx}]"})
            content.append({"type": "image", "source": {"type": "base64", "media_type": mt, "data": b64}})

    # Build text summary of homes for context
    n = len(homes)
    homes_summary = "\n".join(
        f"HOME {i+1}: {h.get('address', f'Home {i+1}')} — ${h.get('price') or 0:,} | "
        f"{h.get('beds') or '?'} bd / {h.get('baths') or '?'} ba{_fmt(h.get('sqft'), ' sqft')}"
        for i, h in enumerate(homes)
    )

    # Build JSON template with N homes in comparisons
    json_template = "{\n"
    json_template += f'  "winner": 1,  // home number (1–{n}) that wins overall based on finish, quality, and value\n'
    json_template += '  "winner_reason": "3-5 word phrase — e.g. \'sharper finishes and presence\'",\n'
    json_template += '  "overall_take": "one punchy sentence on which home looks better overall and why",\n'
    json_template += '  "comparisons": {\n'
    json_template += '    "kitchen":     "one sentence comparing the kitchens visually",\n'
    json_template += '    "bathroom":    "one sentence comparing the bathrooms",\n'
    json_template += '    "living_room": "one sentence comparing the living rooms"\n'
    json_template += '  },\n'
    json_template += '  "market_read": "one sentence on how each home is positioned relative to its price",\n'
    json_template += '  "confidence_note": "brief note if image coverage was limited — omit this key entirely if confidence is high"\n'
    json_template += "}"

    final_text = (
        agent_prompt
        + f"Images above show {n} homes. Images are labeled by home number.\n\n"
        + homes_summary
        + "\n\nFollow the agent instructions exactly. Respond ONLY with valid JSON, no markdown fences:\n"
        + json_template
    )
    content.append({"type": "text", "text": final_text})

    try:
        raw = call_claude(api_key, [{"role": "user", "content": content}], 512).strip()
    except Exception as e:
        logger.error(f"Claude compare error [{type(e).__name__}]: {e}")
        return None

    raw = sanitize_json(raw)
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1].lstrip("json").strip() if len(parts) > 1 else raw
    start, end = raw.find("{"), raw.rfind("}") + 1
    if start != -1 and end > start:
        raw = raw[start:end]
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"Compare JSON parse error: {e} | raw: {raw[:200]}")
        return None


# ── HTTP handler ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    api_key: str = ""

    def log_message(self, fmt, *args):
        logger.info(f"{self.address_string()} {fmt % args}")

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0].split("#")[0]
        if path == "/":
            path = "/index.html"
        file_path = os.path.join(DOCS_DIR, path.lstrip("/").replace("/", os.sep))
        # Prevent path traversal
        if not os.path.abspath(file_path).startswith(os.path.abspath(DOCS_DIR)):
            self.send_response(403); self.end_headers(); return
        if not os.path.isfile(file_path):
            self.send_response(404); self.end_headers(); return
        ext = os.path.splitext(file_path)[1].lower()
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".js":   "application/javascript; charset=utf-8",
            ".css":  "text/css; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".ico":  "image/x-icon",
            ".png":  "image/png",
            ".jpg":  "image/jpeg",
        }.get(ext, "application/octet-stream")
        with open(file_path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body_raw = self.rfile.read(length)
        try:
            body = json.loads(body_raw)
        except json.JSONDecodeError:
            self._json_response(400, {"error": "Invalid JSON"})
            return

        if self.path == "/analyze":
            listing_id = body.get("listing_id", "?")
            img_count  = len(body.get("images") or [])
            logger.info(f"Deep dive request: listing={listing_id}, images={img_count}")

            analysis = analyze(body, self.api_key)
            if not analysis:
                self._json_response(502, {"error": "Analysis failed — no images could be fetched or Claude returned invalid JSON"})
                return

            logger.info(f"Deep dive complete: listing={listing_id}, rooms={len(analysis.get('rooms', []))}, score={analysis.get('overall_score')}")
            self._json_response(200, analysis)

        elif self.path == "/compare":
            homes = body.get("homes") or []
            if len(homes) < 2:
                self._json_response(400, {"error": "At least 2 homes required for comparison"})
                return

            logger.info(f"Compare request: {len(homes)} homes")
            result = compare_listings(homes, self.api_key)
            if not result:
                self._json_response(502, {"error": "Comparison failed"})
                return

            logger.info(f"Compare complete")
            self._json_response(200, result)

        elif self.path == "/offer-strategy":
            listing_id    = body.get("listing_id", "?")
            analysis      = body.get("analysis") or {}
            listing       = body.get("listing") or {}
            zip_stats     = body.get("zip_stats") or {}
            buyer_profile = body.get("buyer_profile") or {}

            if not analysis.get("rooms"):
                self._json_response(400, {"error": "Deep Dive analysis required first"})
                return

            rooms_summary = ", ".join(
                f"{r.get('room_type','room')} {r.get('condition_score','?')}/10"
                for r in (analysis.get("rooms") or [])[:8]
            )
            analysis_block = (
                f"AI ANALYSIS:\n"
                f"Overall score: {analysis.get('overall_score','?')}/10\n"
                f"Rooms: {rooms_summary}\n"
                f"Red flags: {'; '.join(analysis.get('red_flags') or []) or 'none'}\n"
                f"Hidden value: {'; '.join(analysis.get('hidden_value') or []) or 'none'}\n"
            )

            zip_block = ""
            if zip_stats.get("median_ppsf"):
                this_ppsf = (listing.get("price") or 0) / max(listing.get("sqft") or 1, 1)
                delta = this_ppsf - zip_stats["median_ppsf"]
                zip_block = (
                    f"ZIP MARKET CONTEXT:\n"
                    f"ZIP median PPSF: ${zip_stats['median_ppsf']:.0f} ({zip_stats.get('peer_count', 0)} listings)\n"
                    f"This listing: ${this_ppsf:.0f}/sqft ({'+' if delta >= 0 else ''}{delta:.0f} vs median)\n"
                    f"ZIP median DOM for comparable listings (NOT this listing): {zip_stats.get('avg_dom', '?')} days\n"
                )

            context = build_context_block(listing)
            profile_str = f"Buyer profile: {json.dumps(buyer_profile)}" if buyer_profile else ""

            full_prompt = (
                f"{KNOWLEDGE_BASE}\n\n"
                f"{context}\n\n"
                f"{analysis_block}\n"
                f"{zip_block}\n"
                f"{profile_str}\n\n"
                f"---\n{OFFER_STRATEGY_PROMPT}"
            )

            try:
                raw = call_claude(self.api_key, [{"role": "user", "content": full_prompt}], 600).strip()
            except Exception as e:
                logger.error(f"Offer strategy error [{type(e).__name__}]: {e}")
                self._json_response(502, {"error": "Offer strategy generation failed"})
                return

            raw = sanitize_json(raw.strip())
            if raw.startswith("```"):
                parts = raw.split("```")
                raw = parts[1].lstrip("json").strip() if len(parts) > 1 else raw
            start, end = raw.find("{"), raw.rfind("}") + 1
            if start != -1 and end > start:
                raw = raw[start:end]
            try:
                result = json.loads(raw)
            except json.JSONDecodeError as e:
                logger.error(f"Offer strategy JSON error: {e} | raw: {raw[:200]}")
                self._json_response(502, {"error": "Invalid JSON from model"})
                return

            logger.info(f"Offer strategy complete: listing={listing_id}")
            self._json_response(200, result)

        else:
            self.send_response(404)
            self.end_headers()

    def _json_response(self, status: int, data: dict):
        payload = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(payload)


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY environment variable not set.")
        print("  export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    Handler.api_key = api_key

    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    logger.info(f"AI Deep Dive server running on http://localhost:{PORT}")
    logger.info(f"Using model: {CLAUDE_MODEL}")
    logger.info("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server stopped.")


if __name__ == "__main__":
    main()
