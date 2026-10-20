/* The code printed on the tutorial page has to run.
 *
 * `espruinodocs/tutorials/BTHome Light Switch.md` is a page somebody will
 * copy out of a browser into the Web IDE, and the thing it promises -- that
 * the board prints `writable entries: [ 30 ]` and that a write lights the LED
 * -- is a claim like any other. A page is also the easiest thing in this
 * repository to leave behind: its code is not imported by anything, so nothing
 * else notices when the module moves under it (D-089 is the same lesson, about
 * a comment that described an upstream module as it had been months earlier).
 *
 * This lifts the JS block straight out of the page and runs it against the
 * real module. It has its own small fake board rather than bundle.test.js's,
 * because that one runs built standalone bundles out of dist/ and the page is
 * not an example -- what has to be checked here is the text as published.
 */
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const PAGE = path.join(
  __dirname,
  "..",
  "espruinodocs",
  "tutorials",
  "BTHome Light Switch.md"
);
const SERVICE = "2FAA0000-3B0B-4B1A-9E2A-B4C2952E62F2";

function codeBlocks(markdown) {
  return [...markdown.matchAll(/```JS\n([\s\S]*?)```/g)].map((m) => m[1]);
}

/* Enough board to run a sketch: the pins it writes, the radio it advertises
 * on, and the upstream BTHome module's encoding for the two objects this page
 * uses. The real module is loaded; only the world around it is pretend. */
function board() {
  const pins = {};
  const advertised = [];
  const printed = [];
  let services = null;

  /* Collected rather than run. The module arms its next read with a real
   * setTimeout and every wake arms the next one (D-109), so a test that let
   * them run would keep Node's event loop alive for ever. */
  const timers = [];
  const context = {
    console: { log: (...parts) => printed.push(parts.join(" ")) },
    getTime: () => Date.now() / 1000,
    setTimeout: (fn, ms) => timers.push({ fn, ms }),
    clearTimeout: (handle) => {
      if (handle !== undefined) timers[handle - 1] = { cancelled: true };
    },
    digitalWrite: (pin, value) => {
      pins[pin] = value;
    },
    LED1: "LED1",
    E: { getBattery: () => 97 },
    NRF: {
      on() {},
      getAddress: () => "c8:80:32:ad:f7:b9",
      setAdvertising: (data) => advertised.push(data[0xfcd2]),
      setServices: (given) => {
        services = given;
      },
      updateServices() {},
    },
  };
  context.global = context;
  vm.createContext(context);

  const loaded = {};
  context.require = (name) => {
    if (loaded[name]) return loaded[name];
    if (name === "BTHomeWritable") {
      const source = fs.readFileSync(
        path.join(__dirname, "..", "BTHomeWritable.js"),
        "utf8"
      );
      const factory = vm.runInContext(
        "(function(module, exports, require){" + source + "\nreturn exports;})",
        context
      );
      const holder = { exports: {} };
      return (loaded[name] = factory(holder, holder.exports, context.require));
    }
    if (name === "BTHome") {
      return (loaded[name] = {
        packetId: 0,
        getAdvertisement(devices) {
          const device = devices[0];
          const object =
            device.type === "battery"
              ? [0x01, Math.round(device.v)]
              : [0x1e, device.v ? 1 : 0];
          return { 0xfcd2: [0x40, 0x00, 0x01].concat(object) };
        },
      });
    }
    throw new Error("unexpected require(" + name + ")");
  };

  return { context, pins, advertised, printed, timers, services: () => services };
}

test("the tutorial page still has a code block to check", () => {
  const blocks = codeBlocks(fs.readFileSync(PAGE, "utf8"));
  assert.ok(blocks.length >= 1, "no ```JS block on the page");
});

test("the tutorial's sketch sets up and advertises what the page says", () => {
  const device = board();
  const [sketch] = codeBlocks(fs.readFileSync(PAGE, "utf8"));
  vm.runInContext(sketch, device.context, { filename: "tutorial.js" });

  assert.equal(device.advertised.length, 1, "one advertisement at setup");
  const packet = device.advertised[0];
  assert.equal(packet[0], 0x40, "BTHome v2, unencrypted");
  assert.ok(
    packet.includes(0xff),
    "the declaration is what makes the entry writable"
  );
  /* The page tells the reader to expect exactly this line, and 30 is 0x1E --
   * BTHome's light object. If the module ever renumbers it, the page is wrong
   * and so is this. */
  assert.ok(
    device.printed.some((line) => line === "writable entries: 30"),
    `expected "writable entries: 30", got ${JSON.stringify(device.printed)}`
  );
});

test("the tutorial's sketch lights the LED when a central writes to it", () => {
  const device = board();
  const [sketch] = codeBlocks(fs.readFileSync(PAGE, "utf8"));
  vm.runInContext(sketch, device.context, { filename: "tutorial.js" });

  const service = device.services()[SERVICE];
  const uuids = Object.keys(service);
  assert.equal(uuids.length, 1, "one writable entry, one characteristic");
  assert.equal(uuids[0], "2FAA0001-3B0B-4B1A-9E2A-B4C2952E62F2");

  // `apply()` runs inside the write, so the pin moves without any timer.
  service[uuids[0]].onWrite({ data: [0x1e, 0x01] });
  assert.equal(device.pins.LED1, true, "a write of 1E 01 lights LED1");
  service[uuids[0]].onWrite({ data: [0x1e, 0x00] });
  assert.equal(device.pins.LED1, false, "and 1E 00 puts it out");
});
