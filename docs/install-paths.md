# Installing the module: what it costs now, and what could be cheaper

Written 2026-11-20, after a flash to a board over BLE dropped twice in the same
place and the board then stopped answering at all. The question behind it: can
an end user get `BTHomeWritable` onto a device and use it without meeting the
transport at all. The answer is that the installation is already one file, and
that what hurts is not the number of modules but the three costs below, of which
only one is about size.

Every number here is measured, and says how.

## What actually goes over the air

| What is sent | Bytes | Measured by |
|---|---|---|
| `BTHomeWritable.min.js`, as espruino.com serves it | 11 956 | `curl https://www.espruino.com/modules/BTHomeWritable.min.js` |
| `BTHome.min.js`, upstream | 1 647 | likewise |
| `AESCCM.min.js`, this project's | 1 868 | likewise |
| a sketch whose `require`s pull all three | 15 471 | the sum |
| a pasteable standalone bundle (`espruino/dist/*.min.js`) | 20 535 to 26 053 | `ls -l` |
| a sketch alone, with the module already in Storage | 1 to 3 kB | `ventil.js` is 2 428 |

The module source in this repository is 57 878 bytes, the generated EspruinoDocs
copy 24 827, and espruino.com minifies that to 11 956. So the published module
is a fifth of the source: the comments that make this repository readable are
not what the user uploads.

**The transport.** Nordic UART, write without response, and therefore no flow
control in either direction. `tools/espruino_deploy.py` sends 50 bytes every
20 ms and waits 0.25 s after each 384-byte `Storage.write` statement, which is
about 52 statements and roughly 25 s for the module alone. Each of those
statements is a separate flash write at its own offset.

**What that looked like on 2026-11-20.** Two attempts on a board reporting
2v29.396, `GUNBLE`, 190 kB of free RAM, an empty Storage with 400 kB free and no
error flags, at -65 dBm. Both dropped with `Not connected` while writing the
module, at the same point. The board then advertised but refused GATT service
discovery six times running (`Unreachable`), which is the same shape as D-023's
second Windows finding. Nothing was left half written: Storage was still empty
afterwards, because a chunk that does not arrive is never committed.

## The three costs, which are not the same problem

1. **Bytes on the wire.** 13.6 kB unsealed, 15.5 kB sealed, or one 20.8 kB
   bundle. This is the cost people notice first and the one that matters least:
   it is a one-off if the module stays on the device.
2. **No flow control.** A 12 kB upload is 25 s of continuous writing with fixed
   sleeps and no acknowledgement. This is what failed, and it fails worse the
   weaker the link.
3. **The module is sent again at every iteration**, even when it already sits in
   Storage. This is the cost that actually shapes a user's day, and it is not
   ours: espruino.com's own page says of modules in flash that *"The Espruino
   Web IDE and Command-line tools will be unaware of extra modules in Storage.
   When uploading code they may attempt to find the module online and re-upload
   it, or complain that the module is not found."*

## Five ways out, with what each is worth

**A. Paste a standalone bundle.** What `docs/espruino-quickstart.md` already
tells a reader to do: one minified file of about 21 kB, nothing installed,
nothing to resolve. It works, and on a Puck.js it is near the limit (D-093:
40 960 bytes of Storage, and `OUT OF MEMORY` if the readable 60 kB version is
sent instead). Cost: the whole bundle goes again at every change.

**B. Put the module in Storage once.** `require("X")` reads a Storage file named
exactly `X`, no extension, verified on hardware in D-023, and
`tools/espruino_deploy.py` writes that layout. Then the module costs no RAM and
a sketch is 1 to 3 kB, so the fragile 12 kB upload happens once in the life of
the board. Catch, from the quotation above: a sketch sent by the Web IDE will
have its `require("BTHomeWritable")` seen by the scanner and the module fetched
and uploaded again anyway. Writing it as `require(("BTHomeWritable"))` hides it
from the scanner and is identical JavaScript, which is the trick
`build.js` in the ventilation project already uses for its bundle. That turns B
from a tool-only path into something a Web IDE user can follow.

**C. A smaller module.** Measured on the generated copy: the sealing code
(`toKey`, `seal`, `openWrite`, `counterCharacteristic`, `nonceFor`,
`loadMarks`, `saveMarks`, `macBytes`, `counterIsAhead`, `reachedMark`) is
**4 243 of 24 827 bytes, 17.1%**, and `AESCCM` is a further 1 868 on the wire.
So an unsealed build would save something under a quarter of the upload. The
minified share is not measured, because the minifier is EspruinoDocs', not ours.
Against that: a second module to keep in step with the first, which is what
rule 3 and D-084 exist to prevent. Not worth it on its own.

The cheap part of C is free and separate: `require("AESCCM")` appears twice in
the module, inside functions that only run when a bindkey is set, so it is
already lazy at runtime but not to the IDE's scanner, which fetches it for
everyone. Hiding it would save 1 868 bytes for unsealed users and break sealed
ones exactly as D-084 recorded, unless the sealed path then requires it
explicitly in the sketch. That is a trade, not a fix, which is why it is in
D-164 rather than done here.

**D. The module inside the firmware.** Espruino builds can carry JS modules, in
which case `require("BTHomeWritable")` costs nothing: no upload, no Storage, no
scanner, no version drift between a device and a bundle. This is the only option
that answers *transparent* in full, and it is not ours to take: it is a request
to @gfwilliams on espruino#8024, and it binds the module's version to a firmware
release. Worth asking precisely because the module is already published on
espruino.com, which is the step that usually precedes it.

**E. Flow control in our own uploader.** Espruino echoes what it is sent and
prints a prompt when it has finished a statement, so waiting for that prompt is
real flow control where a fixed 0.25 s sleep is a guess. Two changes, both
local to `tools/espruino_deploy.py`: wait for the prompt instead of sleeping,
and build the file in one RAM string to write it to flash once rather than 52
times, which is 52 fewer erase-and-write windows during which the radio has to
keep a link alive. On boards too small for a 12 kB string in RAM the chunked
path stays. This is the one that addresses what was actually observed.

**F. A cable, where there is one.** An MDBT42Q breakout or a nice!nano over USB
serial has flow control and no supervision timeout to lose. The Puck.js has no
USB, so this is a fallback and not an answer.

## What I would do, in order

1. **E**, because it is ours, it is small, and it fixes the failure we have in
   hand rather than a theory about it.
2. **B**, documented for Web IDE users with the `require(("X"))` note, so the
   12 kB crossing happens once per board instead of once per edit.
3. **D**, asked of Gordon on espruino#8024, as the real answer to transparency.
4. **C** only if D is refused, and then only the AESCCM half, with the sealed
   path's explicit `require` spelled out.

## Two things found on the way

- espruino.com's module page says *"Modules written to Espruino's flash memory
  can only have names that are a maximum of 8 characters long."* `BTHomeWritable`
  is fourteen, and D-023 verified it resolving from Storage on hardware, end to
  end, with a reboot. Their sentence looks stale rather than true. It is worth a
  line to them, because a user who reads it will not try B at all.
- The `Unreachable` that followed the failed uploads is the same symptom D-023
  recorded for forcing uncached service discovery on this host, and it presented
  then, as now, as a dead device.
