# Bolt spacing was wrong for this capture

BOLT SPACING WRONG IN APP: this capture was taken with the app's bolt spacing at the default 20 cm; the wall's real spacing is 25 cm (corrected in the app from the capture after 2026-11-18_174142_ac2132d6). Every cm in saves.json (legs cm, margin_cm, wall_length_cm) is therefore 1.25x too short. Grid units, tiers, angles and bolts are unaffected. Use cm = units x 25; see NOTE_bolt_spacing.md.

| save | from | to | units | app cm (at 20) | corrected cm (at 25) | tier |
|---|---|---|---|---|---|---|
| 1 | 3 | 4 | 3.192 | 63.8 | 79.8 | A |
| 1 | wall length | | | 213.1 | 266.4 | |
