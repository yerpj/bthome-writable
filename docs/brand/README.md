# Brand assets

Home Assistant shows an icon for every integration, and this one has none.
Gordon noticed while testing: *"does bthome-writable have an icon?"*

## What is here

`bthome-icon-reference.png` — **BTHome's own icon**, 256×256, saved for
reference. It is their mark, not ours: it is here so that whatever we draw sits
beside it convincingly, and for no other purpose. It must never be committed as
this integration's icon, and nothing in the repository points at it.

The two belong side by side on one device card, so the resemblance that matters
is of family, not of copy: a reader should see at a glance that one extends the
other, and never mistake which is which.

## What is needed, and where it goes

Two destinations, and the first does not remove the need for the second.

**`custom_components/bthome_writable/brand/icon.png`** — HACS looks here first.
Its validation action names this exact path, and falls back to checking
`home-assistant/brands` when the directory is absent, which is why the `brands`
check is currently ignored in CI (D-085). Putting a real icon here is what makes
that ignore removable.

**A pull request to [`home-assistant/brands`](https://github.com/home-assistant/brands)**,
under `custom_integrations/bthome_writable/`. This is what makes the icon appear
in Home Assistant itself rather than only in HACS, and it is the one that needs
someone else to merge it, so it is worth starting early.

## Specification

Taken from the brands repository's own requirements; check them again before
submitting, because they are theirs to change and this is a copy.

| | |
|---|---|
| `icon.png` | 256×256, PNG with transparency, the subject square within it |
| `icon@2x.png` | 512×512, same image |
| `logo.png` | optional, wider mark; falls back to the icon when absent |

Trimmed of empty margin, so the glyph fills the square — the reference beside
it is a good test of whether the weight matches.
