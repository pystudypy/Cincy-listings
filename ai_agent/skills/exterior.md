# Exterior & Outdoor Analysis Skill

Covers: backyard, patio/deck, pool, front exterior, garage, aerial/drone shots, curb appeal.

You are examining exterior photos on behalf of a home buyer. Outdoor spaces significantly impact both lifestyle and resale value. Buyers in Cincinnati pay a premium for usable outdoor entertaining space, privacy, and pools.

---

## POOL IDENTIFICATION

**In-ground pool** (emit `inground_pool`):
- Pool that is flush with or cut into the surrounding surface (decking, grass, pavers)
- Visible pool walls made of concrete/gunite or vinyl liner
- Typically surrounded by patio/decking
- HUGE value driver in Cincinnati — mention size and shape if visible

**Above-ground pool** (emit neither, note in insight):
- Pool that sits above the ground surface — walls visible from outside
- Much less desirable and does not add meaningful property value
- Note honestly: "Above-ground pool — typically not considered a value-add and may need removal"

**Hot tub / spa** (emit `hot_tub`):
- Separate freestanding or built-in spa with jets
- May be adjacent to pool or standalone on the patio/deck

---

## DECK AND PATIO IDENTIFICATION

**Deck** (emit `deck`):
- Raised structure off the back or side of the house, typically wood (cedar, pressure-treated) or composite (Trex)
- Has visible decking boards — not flush with ground level
- Note: composite decks (emit `deck` and note "composite" in insight) are maintenance-free; wood decks require annual sealing

**Patio** (emit `patio`):
- Ground-level outdoor area with concrete, stone, brick, or pavers
- Flush with grade — not elevated like a deck
- Note: large stone/paver patios with fire pit areas are a significant lifestyle feature

**Covered porch** (emit `covered_porch`):
- Roofed outdoor structure attached to the house — protects from rain and sun
- Three-season porches (enclosed with screens/windows) are very desirable in Cincinnati's climate

**Pergola** (emit `pergola`):
- Open overhead structure with beams/lattice — no solid roof
- Typically over a patio or deck; defines outdoor "room"; can have string lights

---

## OUTDOOR KITCHEN / ENTERTAINING

**Outdoor kitchen** (emit `outdoor_kitchen`):
- Built-in grill WITH counter space AND cabinetry/base — not just a freestanding gas grill
- Often includes refrigerator, sink, or pizza oven in high-end setups
- Major entertaining asset; worth $15,000–$50,000 installed

**Fire pit** (emit `fire_pit`):
- Installed fire pit (built-in stone ring, gas insert, or permanent structure)
- NOT a portable chiminea — a fixed feature of the outdoor space

---

## GARAGE IDENTIFICATION

Count the garage door openings visible:
- `three_car_garage`: 3 separate bays (door openings)
- `two_car_garage`: 2 bays — standard; still worth confirming as buyers often assume
- Single car: Note in insight; do not emit a garage tag
- `detached_garage`: Garage structure clearly separated from the main house

**EV charger** (emit `ev_charger`):
- Level 2 charging unit mounted on garage wall — typically a black or white box with cable
- Increasingly desirable as EV adoption grows

**Garage interior quality signals** (note in insight):
- Epoxy floor coating: premium touch, clean/organized feel
- Built-in cabinetry or workshop: bonus storage and utility
- High ceiling: potential for car lift installation

---

## YARD AND LOT

**Fenced yard** (emit `fenced_yard`):
- Visible fence enclosing the backyard — critical for families with children or dogs
- Note material if clear: wood privacy fence vs. aluminum/chain link

**Large lot** (emit `large_lot`):
- Lot noticeably larger than adjacent homes visible in aerial shots
- Wide side yards, long backyard depth, or aerial showing significantly more land
- In Cincinnati neighborhoods, a 0.5+ acre lot is a genuine rarity worth flagging

**Landscaped yard** (emit `landscaped_yard`):
- Clearly professionally designed: defined planting beds, mulch, specimen plants, clean edging
- Not just "has grass" — look for intent and maintenance

**Mature trees** (note in insight, no tag):
- Large shade trees on the property add value: lower cooling costs, visual appeal, privacy
- Worth mentioning if prominent in photos

---

## CURB APPEAL (front exterior)

Note in insight (no specific tags):
- Brick vs. frame construction (brick = more durable, better insulated, higher insurance appeal)
- Front porch presence: covered front porch = major lifestyle and design feature in Cincinnati
- Landscaping condition at front
- Driveway condition and width
- Visible roof condition from exterior: new shingles vs. aging/moss/sagging ridge

---

## SOLAR PANELS (emit `solar_panels`):
- Panels visible on roof surface in exterior shots
- Note approximate array size if visible; mention any remaining lease/purchase details are worth asking about

---

## INSIGHT FOCUS

1. Outdoor entertaining potential — can they host a party back here?
2. Pool: in-ground pool significantly expands buyer appeal and summer lifestyle
3. Privacy: fenced, private, or does the yard feel exposed to neighbors?
4. Garage functionality: 2-car vs. 3-car vs. tandem is a real daily-life issue
5. Lot size compared to neighboring lots visible in aerial shots
6. Any deferred exterior maintenance visible: rotting deck boards, peeling paint, overgrown landscaping
