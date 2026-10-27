# Upstream, unmodified

`BTHome.js` and `BTHome.min.js` are Espruino's own BTHome module, fetched
unmodified on 2026-10-26 from <https://www.espruino.com/modules/BTHome.js> and
<https://www.espruino.com/modules/BTHome.min.js>. Espruino and its modules are
MPL-2.0; the copyright is Gordon Williams's.

**Do not edit them, and do not import them from the module or the integration.**
`espruino/BTHomeWritable.js` requires `BTHome` by name, which is rule 3 of
CLAUDE.md: wrap, do not fork. These copies exist for one reason.

## The reason: a "standalone" bundle was not standalone

`tools/build_espruino_bundle.py` inlines `BTHomeWritable.js` and leaves
`require("BTHome")` in place, because the Web IDE resolves it at upload time
and `tools/espruino_upload.py` relies on the module already being on the board.
On 2026-10-26 the Puck's storage was erased before a reflash, and the sketch
stopped working at boot:

    Uncaught Error: entry 1 ("light") cannot be encoded
    (Module "BTHome" not found); declare it with id and length

The module had been sitting in that board's Storage since some earlier session,
unrecorded and depended upon. Every bench board is in the same position, so
**lamp, lamp2 and lamp3 will each fail this way the first time their storage is
cleared**, and the failure names a declaration problem rather than a missing
module, which is worse.

`tools/build_power_variants.py` therefore inlines this copy into the Storage
images of docs/measurements.md §23: an image that boots from `.bootcde` has no
Web IDE to resolve anything and no network, so it has to carry everything. The
inlining is the bundler's own flat pattern, `var exports = {}` before and a
name bound after, with no closure around it.

**And BTHome was not the only one.** The image with BTHome inlined booted and
died on `require("AESCCM")` behind it, which is this project's own module and
had been living in that same storage. Finding them one boot at a time is not a
method, so `leftover_requires` now fails the build on any `require()` the
firmware does not answer: the list of what it does answer is `BUILTINS`, which
is `process.env.MODULES` on the board under test. A boot failure names the
operation it was in the middle of, not the module it lacked, which is why the
build is the place to catch this.

Keeping a byte-identical copy rather than a rewrite is what makes it checkable:

    curl -s https://www.espruino.com/modules/BTHome.min.js | diff - BTHome.min.js
