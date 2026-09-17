# Figures

For the espruino#8013 discussion and anything else that needs to show the
mechanism rather than describe it.

| File | What it shows |
| --- | --- |
| `round-trip.png` | The four steps, with real bench bytes: advertising carrying the `0xFF` declaration, discovery, the write to one entry's characteristic, the acknowledgement. |
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
`40 00 f0 01 64 ff 1e 1e 1e` is a Puck.js running `three-lights.js`, where
`ff 1e 1e 1e` is the declaration -- three `light` entries, served on
characteristics `2FAA0001` to `2FAA0003`. None of their values are on the air.
The latency figures come from the T3.2 runs and from D-049, both recorded in
`spec/decisions.md`.
