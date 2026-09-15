# Figures

For the espruino#8013 discussion and anything else that needs to show the
mechanism rather than describe it.

| File | What it shows |
| --- | --- |
| `round-trip.png` | The four steps, with real bench bytes: advertising carrying the `0xFF` declaration, discovery, the write, the refreshed advertising that confirms it. |
| `latency.png` | Click → action → confirmation, measured on one Raspberry Pi with no ESPHome proxy: 10.7 s baseline down to 1.7 s. |

Each `.png` is rendered from the `.html` beside it, so the numbers stay
editable and the figure stays reproducible:

```
chrome --headless --disable-gpu --hide-scrollbars \
       --force-device-scale-factor=2 \
       --screenshot=round-trip.png --window-size=1080,560 \
       file:///path/to/round-trip.html
```

The byte strings in `round-trip.png` are copied from the bench, not composed:
`40 00 f0 01 64 1e 01 1e 01 1e 01 ff 1c` is a Puck.js advertising three lights
on one object ID, and `ff 1c` is the declaration -- bitmask `0b00011100`,
naming positions 2, 3 and 4. The latency figures come from the T3.2 runs
recorded in `spec/decisions.md`.
