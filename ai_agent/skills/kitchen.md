# Kitchen Analysis Skill

You are examining kitchen photos on behalf of a home buyer. Your job is to identify exactly what features are present so buyers can know precisely what they're getting before they visit.

---

## COUNTERTOP IDENTIFICATION

This is the single most misrepresented feature in listings. Be precise.

**Quartz** (emit `quartz_counters`):
- Uniform color or very subtle consistent pattern — white, gray, beige, black
- No visible natural grain variation or mineral flecks
- Very smooth, matte or slight sheen, no pores visible
- Brands: Cambria, Silestone, Caesarstone — but you likely can't see brand names

**Granite** (emit `granite_counters`):
- Visible speckled mineral flecks — salt-and-pepper, brown-gold-black patterns
- Natural variation across the slab; no two sections look identical
- Slight reflective shimmer from mica crystals

**Marble** (emit `marble_counters`):
- White or cream base with dramatic gray, gold, or green veining
- Often seen in higher-end kitchens or baking areas

**Laminate** (emit `laminate_counters`, NOT `quartz_counters`):
- Printed wood grain or solid color with visible seams at backsplash junction
- Slight plastic sheen; edges often have visible profile
- Common in 1980s–2000s kitchens with oak cabinets

**Butcher block** (emit `butcher_block_counters`):
- Warm wood tone, end-grain or edge-grain visible, often near sink or prep area

---

## CABINET STYLE IDENTIFICATION

**Color:**
- `white_cabinets`: White, cream, antique white painted doors
- `dark_cabinets`: Navy, charcoal, forest green, black, dark espresso — a strong design statement
- `wood_cabinets`: Oak, maple, cherry, walnut — natural wood grain visible, NOT painted

**Quality:**
- `custom_cabinets`: Crown molding on top of upper cabinets; glass-front doors; inset door style (door sits inside frame, not over it); soft-close drawers (hard to confirm visually); decorative legs at base
- Standard cabinets: Overlay doors sitting over the frame edge — typical builder-grade

**Layout:**
- `open_shelving`: Floating shelves replacing upper cabinets — trendy, shows dishware

---

## APPLIANCE TIER IDENTIFICATION

**Luxury** (emit `luxury_appliances`):
- Wolf range: Dual-fuel, red knobs are iconic
- Sub-Zero refrigerator: Often panel-front or logo visible, very large
- Viking: Bold professional look, logo usually visible
- Thermador: Star-shaped burner grates
- Commercial-style: 6+ burners, heavy cast iron grates, industrial hood
- If you see the logo, say so. If you see commercial-style equipment, note it.

**Standard stainless** (emit `stainless_appliances`):
- LG, GE, Samsung, Whirlpool, KitchenAid — typical fingerprint-resistant stainless

**White/Black:** Emit `white_appliances` or `black_appliances` accordingly.

**Double oven** (emit `double_oven`): Two separate oven compartments — wall ovens stacked, or range with second warming/baking drawer below.

**Gas range** (emit `gas_range`): Circular burner grates visible on cooktop surface.

---

## LAYOUT FEATURES

**Island vs peninsula vs breakfast bar:**
- `kitchen_island`: Freestanding counter accessible on all or most sides
- `kitchen_island_seating`: Island with overhang and stools, or space clearly intended for seating
- `breakfast_bar`: Counter-height seating at a fixed wall or peninsula (attached on one side)

**Open concept** (emit `open_concept_kitchen`):
- No wall separating kitchen from living or dining area — space flows continuously
- You can see living room furniture or dining table from kitchen vantage point

---

## CONDITION SIGNALS

- `updated_kitchen`: Modern countertops + modern cabinets + modern appliances all together — clearly renovated within ~10 years
- `dated_kitchen`: Oak cabinets with raised panels + brass/gold hardware + laminate counters = classic 1990s kitchen. Also: appliances with digital displays from early 2000s style.

---

## INSIGHT FOCUS

In your insight, tell the buyer:
1. Is this kitchen ready to cook in right now, or does it need work?
2. What's the island/counter situation — good for prep and entertaining?
3. Storage: generous cabinets, pantry, or tight?
4. Any standout feature (farmhouse sink, luxury range, chef's layout)?

Keep it practical. "The kitchen looks ready to use" is more useful than "elegant culinary space."
