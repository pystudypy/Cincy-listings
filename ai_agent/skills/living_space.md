# Living Space Analysis Skill

Covers: living room, dining room, family room, great room, den, bonus room.

You are examining these spaces on behalf of a home buyer to identify features that affect both lifestyle and resale value. Focus on structural details (ceiling, floors, built-ins) and character features (fireplace, architectural details) — these are what buyers actually pay for.

---

## FIREPLACE IDENTIFICATION

**Gas fireplace** (emit `gas_fireplace` AND `fireplace`):
- Modern linear rectangle firebox with no visible ash or grate
- Clean glass front, often with crystals/pebbles rather than logs, or contemporary log set
- Mounted in drywall or stone surround — no raised hearth common
- Gas key valve on the wall nearby (small round knob)

**Wood-burning fireplace** (emit `wood_burning_fireplace` AND `fireplace`):
- Traditional brick surround and/or raised brick hearth
- Ash door or damper handle visible
- Iron grate or andirons inside the firebox
- Often a wooden mantel with classical detailing

**Electric fireplace** (emit `fireplace` only, note "electric" in insight):
- Wall-mounted unit that looks like a TV; flame effect behind glass; no chimney or surround beyond the unit itself
- Much less desirable than gas or wood — note this honestly

---

## CEILING IDENTIFICATION

**Coffered ceiling** (emit `coffered_ceiling`):
- Grid of recessed rectangular panels in the ceiling
- Creates a waffle or grid pattern — each box is a distinct recessed section
- High-end feature; adds visual weight and formality

**Tray ceiling** (emit `tray_ceiling`):
- Ceiling with a raised center section creating a stepped "tray" effect — usually one step up, sometimes with crown molding at the step
- Often has accent lighting inside the recess or crown molding detail
- Common in dining rooms and master bedrooms in 2000s–2010s construction

**Vaulted/cathedral ceiling** (emit `vaulted_ceiling`):
- Ceiling follows the roofline angle — rises to a peak or slopes
- Dramatically higher than a standard 8–9 ft flat ceiling
- Creates sense of spaciousness — do NOT emit for just "high ceilings" (flat but tall)

**High ceilings** (emit `high_ceilings`):
- Flat ceiling that appears above 9 feet — furniture looks proportionally smaller
- Windows are taller than standard; you can often see the room height clearly

Do NOT emit multiple ceiling tags for the same room — pick the most specific one.

---

## FLOOR MATERIAL IDENTIFICATION

**Hardwood floors** (emit `hardwood_floors`):
- Visible wood planks with natural grain variation, warm tones (oak, walnut, cherry, maple)
- Board seams visible, slight sheen but not plastic-bright
- Real wood has subtle color variation plank-to-plank

**Luxury vinyl plank** (emit `luxury_vinyl_floors`):
- Modern plank flooring with uniform woodgrain PRINT — each plank looks nearly identical
- Brighter, more uniform sheen than real wood
- Often in bathrooms and basements where real wood wouldn't go

**Tile floors** (emit `tile_floors`):
- Ceramic, porcelain, or stone — visible grout lines in a grid pattern
- Common in kitchens, entryways, and Florida rooms

Carpet: do not emit a tag, but note condition in insight if relevant.

---

## ARCHITECTURAL DETAILS

**Built-ins** (emit `built_ins`):
- Built-in shelving, bookcases, or cabinetry that is part of the wall — not freestanding furniture
- Classic flanking a fireplace, in a library, or in a hallway
- Adds significant visual value and storage — worth noting explicitly

**Crown molding** (emit `crown_molding`):
- Decorative trim where the wall meets the ceiling — curved or stepped profile
- Quality signal in older and traditional homes
- Do NOT emit if you only see very thin flat trim — that's standard base/door trim

**Wainscoting** (emit `wainscoting`):
- Wood paneling covering the lower portion of walls (usually bottom 36–42 inches)
- Often white painted with a chair rail molding on top
- Classic detail in formal dining rooms and entryways

---

## OTHER FEATURES

**Open floor plan** (emit `open_floor_plan`):
- Kitchen, dining, and living areas share one continuous space — no walls between them
- Very common in post-2000 homes; most buyers expect it

**Natural light** (emit `natural_light`):
- Rooms with multiple large windows, floor-to-ceiling windows, or skylights flooding the space
- Photos show bright, evenly lit rooms without much artificial light needed
- Only emit when it's genuinely a standout feature — not just "has windows"

**Recessed lighting** (emit `recessed_lighting`):
- Can lights (round flush fixtures) in the ceiling — standard in renovated and newer homes

**Wet bar** (emit `wet_bar`):
- Bar area with counter, cabinetry, and a SINK — not just a wine rack or beverage fridge alone
- Common in basements, bonus rooms, and entertainment spaces

**Home theater** (emit `home_theater`):
- Dedicated room with projector + screen, or very large TV (85"+) with theater-style seating
- Acoustical panels on walls are a giveaway

**Sunroom** (emit `sunroom`):
- Glass-enclosed room addition — windows on 3 or more sides
- Often off the back of the house, used as a transitional indoor/outdoor space

---

## INSIGHT FOCUS

1. What's the vibe — formal traditional, open modern, cozy, eclectic?
2. What's the standout architectural feature (fireplace, built-ins, coffered ceiling)?
3. Does the layout work for how most families actually live? (open plan = easier for entertaining/watching kids)
4. Natural light situation — does it feel airy or closed in?
5. Floor condition and material — a hardwood floor refinish returns nearly full cost; carpet signals likely replacement cost
