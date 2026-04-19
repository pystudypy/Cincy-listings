# Bathroom Analysis Skill

You are examining bathroom photos on behalf of a home buyer. Bathrooms are one of the top factors in buying decisions and renovation cost. Be specific about what you see.

---

## SHOWER IDENTIFICATION

**Walk-in shower** (emit `walk_in_shower`):
- Shower stall with no tub — just shower entry, floor drain, showerhead(s)
- Could be in a corner or a full wet room
- If the room has BOTH a walk-in shower AND a soaking tub, emit both

**Tub-shower combo** (do NOT emit `walk_in_shower`):
- Standard tub with a showerhead above it and curtain rod or sliding doors
- Very common in secondary bathrooms; buyers wanting a dedicated shower note this as a limitation

**Frameless glass** (emit `frameless_glass_shower`):
- Clear glass panels with no metal frame around the perimeter
- Only hardware visible is hinges and handle
- Looks expensive and airy — easy to see the tile work inside

**Framed glass** (do NOT emit `frameless_glass_shower`):
- Silver or chrome metal frame around all edges of the glass
- Older style — common in 1990s–2000s renovations

**Rain shower head** (emit `rain_shower_head`):
- Oversized showerhead — ceiling-mounted (completely flat on ceiling) or wall-mounted arm extending outward with a wide face
- Much larger than a standard round showerhead

---

## TUB IDENTIFICATION

**Soaking tub** (emit `soaking_tub`):
- Freestanding tub (standing on its own, not built into a deck) — modern or traditional
- OR a clearly deep drop-in tub larger than standard (usually in a tiled deck surround)
- Deep enough to actually soak in — not a standard bathtub

**Clawfoot tub** (emit `clawfoot_tub`):
- Vintage-style tub on four decorative feet — usually cast iron
- Often in historic homes; a desirable character feature

---

## VANITY IDENTIFICATION

**Double vanity** (emit `double_vanity`):
- Two separate sinks in the same counter/vanity run
- Or two separate vanity units side by side
- Key feature for master bathrooms shared by a couple

**Floating vanity** (emit `floating_vanity`):
- Cabinet mounted to the wall with visible floor space underneath
- Modern look; easier to clean

**Vessel sink** (emit `vessel_sink`):
- Bowl-shaped sink sitting ON TOP of the counter (not recessed into it)
- Dramatic look; requires taller faucet

---

## TILE IDENTIFICATION

**Marble tile** (emit `marble_tile_bath`):
- White/cream tile with gray or gold veining — can be real marble or very high-quality porcelain lookalike
- Common in spa-style master baths

**Subway tile**: Standard rectangular tile in a grid or offset pattern — very common, neutral. Do NOT emit a special tag for this unless it's in the kitchen context.

**Dated tile** (context for `dated_bathroom`):
- Peach, avocado green, harvest gold, or pink tile = 1950s–1970s original
- Small square floor mosaic tiles = pre-1980 typical
- Cultured marble (swirled cream/tan vanity tops and tub surrounds) = 1980s–1990s

---

## OVERALL BATHROOM RATING

**Spa bathroom** (emit `spa_bathroom`):
- Master bath combining at LEAST three luxury elements:
  - Soaking tub (standalone/freestanding)
  - Large walk-in shower with frameless glass
  - Double vanity
  - Premium tile (marble or stone)
  - Heated floors (usually mentioned in description, hard to see visually)
- The overall feel is a high-end hotel or spa

**Updated bathroom** (emit `updated_bathroom`):
- Modern tile, updated vanity, new fixtures — clearly renovated
- Everything looks cohesive and intentional

**Dated bathroom** (emit `dated_bathroom`):
- Original builder-grade from 1980s–2000s: single-sink vanity with cultured marble top, standard tub-shower combo, basic tile
- OR pink/avocado/harvest gold original tile

---

## RED FLAGS (note in insight even if not a taxonomy tag)

- Caulk gaps at tub/wall junction: water intrusion pathway — mention specifically
- Grout cracking in shower surround: water behind the wall — serious
- Mold visible on ceiling or around shower: ventilation problem
- No ventilation fan visible: moisture buildup issue, leads to mold
- Toilet rocking or gap at base: wax ring failure, possible subfloor damage

---

## INSIGHT FOCUS

1. Is the master bath a selling point or just functional?
2. Does the shower/tub situation match what most buyers want? (Many buyers now prefer walk-in shower over tub)
3. Any spa-level features that justify the price?
4. Any red flags visible?
