# Brand assets

Home Assistant shows an icon for every integration, and this one has none.
Gordon noticed while testing: *"does bthome-writable have an icon?"*

## What is here

| File | What it is |
|---|---|
| `bthome-icon-reference.png` | **BTHome's own icon**, kept for reference. Their mark, not ours: it is here so that whatever we draw sits beside it convincingly, and for no other purpose. It must never be committed as this integration's icon, and nothing points at it. |
| `bthome-writable-icon2.png` | The proposal as drawn. |
| `bthome-writable-icon2.svg` | The same, recovered as geometry rather than traced — seven circular arcs with round caps, so radius, span, weight and spacing are editable numbers. 91.8 % pixel overlap with the drawing; the difference is a one-pixel fringe of antialiasing. |
| `proposed-icon-256.png`, `proposed-icon-512.png` | Rendered from the SVG, transparent. These become `icon.png` and `icon@2x.png` if the proposal is adopted. |
| `icon-proposal.html`, `icon-proposal.png` | The sheet for the discussion: the two marks side by side, and both at the sizes Home Assistant actually draws them. |

## The idea, so it is not lost

BTHome's four arcs are kept exactly as they are — the advertising is still the
essential thing. A second set faces back, and its largest arc is dropped, so it
is visibly the lesser of the two: that is the writing this extension adds.

The two groups turning away from each other is not only the meaning. It is also
what keeps them legible at 24 px, because convex meeting convex is the widest
gap two arc groups can have. The wordmark is gone for the same practical
reason — at that size it is a smudge — and for a better one: without it the
icon stops presenting itself as BTHome.

**It is a proposal.** The mark it extends belongs to the BTHome project, so the
last word on it does too.

## Rendering

```
chrome --headless --disable-gpu --hide-scrollbars --default-background-color=00000000 \
       --screenshot=proposed-icon-256.png --window-size=256,256 \
       file:///path/to/bthome-writable-icon2.svg
```

Add `--force-device-scale-factor=2` for the 512. The proposal sheet is
`--window-size=640,566` against `icon-proposal.html`, with the scale factor and
without the transparent background.

## Where the files have to end up

Two destinations, and the first does not remove the need for the second.

**`custom_components/bthome_writable/brand/icon.png`** — HACS looks here first.
Its validation action names this exact path and falls back to checking
`home-assistant/brands` when the directory is absent, which is why the `brands`
check is currently ignored in CI (D-085). A real icon here is what makes that
ignore removable.

**A pull request to [`home-assistant/brands`](https://github.com/home-assistant/brands)**,
under `custom_integrations/bthome_writable/`. This is what makes the icon appear
in Home Assistant itself rather than only in HACS, and it needs someone else to
merge it, so it is worth starting early. It is also hard to undo: changing a
merged icon is another pull request, and installations cache the old one. Hence
showing it on the discussion first.

## Specification

A copy of the brands repository's requirements; check them again before
submitting, because they are theirs to change.

| | |
|---|---|
| `icon.png` | 256×256, PNG with transparency, square, the subject filling it |
| `icon@2x.png` | 512×512, the same image |
| `logo.png` | optional, landscape, may carry a wordmark; falls back to the icon |
