# Feature Taxonomy — Structured Tags for Vision Analysis

This is the **master list of exact tag strings** that the vision agent emits into `listing["features"]`.
Use ONLY these strings — no variations, no synonyms, no free-form text.
Tags are grouped by room. Emit only tags where you have clear visual evidence.

---

## KITCHEN

| Tag | Emit when you see |
|-----|-------------------|
| `kitchen_island` | A freestanding counter/island in the center or off-center of the kitchen |
| `kitchen_island_seating` | Island or peninsula with bar stools, overhang, or counter-height seating |
| `quartz_counters` | Solid-color or subtle-pattern countertops (white, gray, beige) with no visible grain — engineered stone look |
| `granite_counters` | Speckled stone countertops with visible mineral grain/flecks — usually darker |
| `marble_counters` | White or cream countertops with distinctive gray/gold veining |
| `butcher_block_counters` | Warm wood-tone countertops (end grain or edge grain) |
| `laminate_counters` | Printed pattern countertops, visible seams at backsplash, plastic-feel edges — do NOT emit `quartz_counters` if you see this |
| `white_cabinets` | White, off-white, or cream painted cabinet doors |
| `dark_cabinets` | Navy, charcoal, forest green, espresso, or black cabinet doors |
| `wood_cabinets` | Natural wood tone (oak, maple, cherry, walnut) — not painted |
| `custom_cabinets` | Crown molding on top of upper cabinets, glass-front doors, inset doors, or dovetail drawer boxes visible |
| `open_shelving` | Floating shelves replacing some or all upper cabinets |
| `stainless_appliances` | Stainless steel finish on refrigerator, oven, dishwasher, or range |
| `black_appliances` | Matte or glossy black finish appliances |
| `white_appliances` | White or bisque finish appliances |
| `luxury_appliances` | Brand logos or style of Wolf, Sub-Zero, Viking, Thermador, Miele, Bosch (panel-ready), La Cornue, AGA visible; or commercial-style 6-burner range |
| `double_oven` | Two oven compartments stacked or side-by-side wall ovens |
| `gas_range` | Gas burners visible on cooktop or range |
| `farmhouse_sink` | Apron-front (exposed front panel) sink |
| `tile_backsplash` | Decorative tile behind the cooktop or counters (any style) |
| `subway_tile_backsplash` | Classic rectangular white or light-colored subway tile in a grid or offset pattern |
| `pendant_lights_kitchen` | Hanging pendant lights above island or peninsula |
| `under_cabinet_lighting` | LED strip or puck lights mounted under upper cabinets |
| `open_concept_kitchen` | Kitchen visually open to living or dining area (no wall separating them) |
| `breakfast_bar` | Counter-height seating at a peninsula or wall counter (not a full island) |
| `pantry` | Separate pantry door visible, or large floor-to-ceiling pantry cabinet |
| `updated_kitchen` | Clearly renovated within ~10 years — modern counters, hardware, and appliances together |
| `dated_kitchen` | Original 1980s–2000s laminate counters, old-style appliances, or oak cabinets with brass hardware |

---

## BATHROOM

| Tag | Emit when you see |
|-----|-------------------|
| `walk_in_shower` | Walk-in shower with no tub, or shower clearly separate from tub |
| `frameless_glass_shower` | Shower enclosure with no metal frame (clear glass panels, minimal hardware) |
| `soaking_tub` | Deep freestanding or drop-in tub clearly larger than a standard tub |
| `clawfoot_tub` | Vintage tub on decorative feet |
| `double_vanity` | Two separate sinks in the same vanity / two sink basins side by side |
| `floating_vanity` | Vanity cabinet mounted to wall with visible floor underneath |
| `vessel_sink` | Bowl-shaped sink sitting on top of the counter |
| `marble_tile_bath` | White or cream tile with veining — marble or high-quality marble-look porcelain |
| `rain_shower_head` | Oversized ceiling-mounted or wall-mounted wide showerhead |
| `updated_bathroom` | Clearly renovated — modern tile, frameless glass, new vanity |
| `dated_bathroom` | Pink/peach/avocado tile, cultured marble vanity tops, original fixtures |
| `spa_bathroom` | Master bath that combines multiple luxury elements: soaking tub + walk-in shower + double vanity + premium tile |

---

## LIVING SPACES (Living Room, Dining Room, Family Room, Great Room)

| Tag | Emit when you see |
|-----|-------------------|
| `fireplace` | Any fireplace (gas, wood, or electric) |
| `gas_fireplace` | Linear rectangular firebox, no ash door, clean front — modern gas insert |
| `wood_burning_fireplace` | Traditional brick surround, raised hearth, visible ash door or log grate |
| `built_ins` | Built-in shelving, bookcases, or cabinetry flanking fireplace or lining a wall |
| `coffered_ceiling` | Grid pattern of recessed rectangular panels in ceiling |
| `tray_ceiling` | Ceiling with one or more stepped recessed sections (box shape, often with molding) |
| `vaulted_ceiling` | Cathedral or angled ceiling that follows the roofline — not flat |
| `crown_molding` | Decorative molding trim at the ceiling-wall junction |
| `wainscoting` | Wood paneling covering the lower portion of walls |
| `hardwood_floors` | Solid or engineered wood plank floors — visible grain, wood tone, board lines |
| `luxury_vinyl_floors` | Modern LVP flooring — uniform planks with wood look but uniform sheen |
| `tile_floors` | Ceramic, porcelain, or stone tile on the main living floor |
| `open_floor_plan` | Living, dining, and/or kitchen share one continuous open space |
| `high_ceilings` | Ceilings visually above 9 feet — furniture appears small relative to ceiling height |
| `recessed_lighting` | Can lights (pot lights) embedded flush in the ceiling |
| `natural_light` | Multiple large windows or floor-to-ceiling windows flooding the space with light |
| `home_office` | Dedicated room with a desk setup as primary use |
| `home_theater` | Dedicated media room with projector, large screen, or theater-style seating |
| `wet_bar` | Bar area with counter, cabinetry, and a sink — not just a wine rack |
| `sunroom` | Glass-enclosed room addition with windows on 3+ sides |

---

## BEDROOM

| Tag | Emit when you see |
|-----|-------------------|
| `walk_in_closet` | Door to a separate closet room visible, or walk-in closet interior shown |
| `custom_closet` | Built-out closet system with shelves, drawers, hanging rods, and organizational features |
| `en_suite_bathroom` | Bathroom door visible inside the bedroom, or bathroom clearly attached |
| `tray_ceiling_bedroom` | Tray ceiling in a bedroom |
| `vaulted_ceiling_bedroom` | Vaulted ceiling in a bedroom |

---

## EXTERIOR & OUTDOOR

| Tag | Emit when you see |
|-----|-------------------|
| `inground_pool` | In-ground swimming pool (flush with surrounding surface) |
| `hot_tub` | Hot tub or spa separate from or integrated with pool |
| `deck` | Raised wood or composite deck off the back of the house |
| `patio` | Ground-level concrete, stone, or paver outdoor area |
| `covered_porch` | Roofed outdoor porch or covered patio |
| `pergola` | Open-roof structure with beams (no solid roof) over outdoor area |
| `outdoor_kitchen` | Outdoor grill with built-in counter, sink, or cabinetry — more than just a portable grill |
| `fire_pit` | Built-in or installed fire pit in yard |
| `fenced_yard` | Visible fence enclosing the backyard |
| `landscaped_yard` | Clearly professionally landscaped with plantings, mulched beds, defined edging |
| `large_lot` | Lot noticeably larger than typical — wide setbacks, long backyard, or aerial shows large parcel |
| `three_car_garage` | Garage with 3 or more door bays |
| `two_car_garage` | Garage with exactly 2 door bays |
| `detached_garage` | Garage structure separate from the main house |
| `ev_charger` | EV charging unit mounted on wall visible in garage |
| `solar_panels` | Solar panels visible on roof in exterior shots |

---

## BASEMENT & OTHER

| Tag | Emit when you see |
|-----|-------------------|
| `finished_basement` | Basement with drywall, flooring, lighting, and finished ceiling — usable living space |
| `walkout_basement` | Basement with door or large glass opening leading directly to exterior grade |
| `in_law_suite` | Separate living area with kitchen/kitchenette and bathroom — self-contained unit |
| `sauna` | Sauna room with wood paneling and bench |
| `home_gym` | Room dedicated to exercise equipment |
| `wine_cellar` | Dedicated wine storage room or built-in wine wall |
| `laundry_room` | Dedicated laundry room (not just a laundry closet) with folding counter or cabinetry |
| `mudroom` | Entry room with built-in cubbies, bench, hooks, or lockers for shoes/coats |

---

## CONDITION (emit exactly one per listing based on overall impression)

| Tag | Emit when |
|-----|-----------|
| `move_in_ready` | Kitchen and bathrooms already updated; no visible deferred maintenance; buyer can move in without spending money |
| `needs_cosmetic_update` | Good structure and systems but dated finishes — paint, carpet, fixtures need updating; < $30K work |
| `fixer_upper` | Significant visible deferred maintenance, outdated systems, or major renovation needed; > $30K work |
| `new_construction_feel` | Looks brand new or built within 3–5 years — everything fresh |
| `historic_character` | Pre-1940 home with preserved original details: plaster walls, original hardwood, ornate millwork, period trim |
