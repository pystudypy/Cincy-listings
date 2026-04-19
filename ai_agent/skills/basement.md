# Basement & Utility Analysis Skill

Covers: basement (finished and unfinished), utility room, laundry, bonus spaces (gym, wine cellar, in-law suite, mudroom).

Basements are the most frequently misrepresented space in listings AND the most common source of serious problems. Treat every basement photo with extra scrutiny.

---

## FINISHED VS. UNFINISHED

**Finished basement** (emit `finished_basement`):
- All four of these must be present: drywall walls, ceiling (drywall, drop tile, or exposed beams FINISHED), flooring (carpet, LVP, tile — not bare concrete), and proper lighting
- Usable living space — could serve as family room, home office, guest suite, etc.
- A single finished room surrounded by unfinished space: note specifically ("partial finish")

**Walkout basement** (emit `walkout_basement`):
- Exterior door or large glass slider/windows at grade level visible in basement photos
- Basement walks out directly to the yard — not below grade on that side
- Major value add: natural light, easy access, easier to finish

**Unfinished** (no tag):
- Bare concrete floor and/or block/poured concrete walls
- Utility equipment visible without drywall surround
- Note in insight: ceiling height matters. 7'+ = good finishing potential. Under 6'8" = limited.

---

## RED FLAGS — PRIORITIZE THESE (reference knowledge.md)

**Efflorescence** (white or gray powdery deposits on concrete walls):
- Proof of water migrating through the foundation — not cosmetic
- Flag immediately: "White mineral deposits on basement walls indicate active water migration through the foundation — this needs professional waterproofing evaluation before closing"

**Fresh paint on basement walls** (suspicious):
- A very common seller tactic: paint over water stains right before listing
- Flag if you see isolated patchy paint on walls that don't otherwise look freshly painted throughout: "Isolated fresh paint patches on basement walls are a classic pre-listing cover-up for water staining — ask the seller directly about water intrusion history"

**Dark staining at corners or floor-wall junction**:
- Water intrusion evidence — flag it

**Horizontal wall cracks**:
- Structural failure signal — most serious type of basement crack
- Flag immediately with cost context: "$15,000–$50,000+ to remediate, potentially a deal-killer"

**Stair-step cracks in block walls**:
- Foundation movement — serious; needs structural engineer evaluation

---

## UTILITY SYSTEMS (when visible)

These generate no tags but go in the insight — buyers need to know:

**HVAC / Furnace:**
- Note visible brand and age if label is readable
- Old-style cabinet design (pre-2000): budget $8,000–$15,000 for replacement within 5 years
- Rust, soot marks, or very old sheet metal ductwork: flag

**Water heater:**
- Date sticker is often on the side — read it if visible
- Beyond 10–12 years: budget $800–$1,500 for replacement soon
- Rust at base or around connections: flag

**Electrical panel:**
- Note if visible: fuse box (round glass fuses) = pre-1960, possible insurance issue
- Burn marks or rust on panel: flag
- Note if it appears to be 200-amp service (good) vs. older 100-amp

**Sump pump:**
- Presence is normal and expected in Cincinnati
- ABSENCE of a sump pump in a below-grade basement that shows any moisture signs: note it

---

## SPECIAL SPACES

**In-law suite** (emit `in_law_suite`):
- A self-contained living area with: sleeping area + kitchen/kitchenette + bathroom, all within a separate unit
- May have its own entrance or be accessible from the main house
- A major value-add for multigenerational families and investors
- Do NOT emit for just a "finished basement with a full bath" — needs kitchen/kitchenette too

**Home gym** (emit `home_gym`):
- Dedicated room with exercise equipment as its primary purpose
- Rubber flooring, mirrors, or equipment visible

**Wine cellar** (emit `wine_cellar`):
- Dedicated wine storage: built-in wine racks, climate control unit, or brick/stone aesthetic
- A wine wall in the main living area does not count

**Sauna** (emit `sauna`):
- Wood-paneled room with benches visible — cannot mistake for another room type

**Laundry room** (emit `laundry_room`):
- Dedicated room for laundry — not just a hallway closet
- Has counter space, cabinetry, sink, or folding area
- Upper-floor laundry room: worth calling out specifically as a buyer convenience

**Mudroom** (emit `mudroom`):
- Entry room (typically from garage or back door) with built-in storage: cubbies, hooks, bench, lockers
- The built-ins must be present — not just a room where you put boots

---

## INSIGHT FOCUS

1. Lead with any red flags immediately — efflorescence, cracks, suspicious fresh paint
2. What's the finishing level and what's the potential? ("Currently unfinished but has 8-foot ceilings and 1,200 sqft — strong candidate for finishing with a $40,000–$60,000 budget")
3. Utility system ages if visible
4. Any special spaces that add meaningful value (gym, wine cellar, in-law suite)
5. Walkout access — major lifestyle feature if present
