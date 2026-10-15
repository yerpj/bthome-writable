/* bthome-writable — one device offering every platform the integration has.
 *
 * A switch, a number, a text and two buttons on a single device, which is what
 * a receiver's device page looks like when a device declares more than one
 * kind of entry. Written for a screenshot, and useful for a bench: it exercises
 * four codecs — binary, number, text, event — in one advertising packet.
 *
 * Every entry has a `get` as well as a `set`, so each characteristic is
 * readable, the device advertises BTHome's settings revision (0x65), and Home
 * Assistant shows the value the device holds rather than the value it last
 * sent (PROTOCOL.md §3.1). A switch then appears as a toggle instead of the
 * two push buttons Home Assistant uses for an assumed state.
 *
 * That is legitimate here because something other than a receiver can change
 * these values: this board has no button, so the console does it. Call
 * toggle(), target(22.5) or message("hello") and the device bumps the revision
 * for receivers to read again (§3.2).
 *
 * Install with:
 *   python -m tools.espruino_deploy --address <mac> \
 *       --app espruino/examples/all-platforms.js
 */

/* exported toggle, target, message */

var bw = require("BTHomeWritable");

var state = { on: false, target: 21, text: "ready" };

function apply() {
  // nice!nano and Puck.js both define LED1; a board without it still runs.
  if (typeof LED1 !== "undefined") digitalWrite(LED1, state.on);
}

function toggle() {
  state.on = !state.on;
  apply();
  bw.changed();
}

function target(degrees) {
  state.target = degrees;
  bw.changed();
}

function message(text) {
  state.text = text;
  bw.changed();
}

bw.setup({
  advertise: [
    // A plain sensor beside the controls, which is the point of the whole
    // thing: writable entries live on the same device card as what it
    // measures. `E.getBattery()` is a Puck.js and Bangle.js function, so this
    // reads the supply voltage instead, which every nRF52 board has.
    { type: "voltage", interval: 300000, get: function () { return NRF.getBattery(); } },
    {
      type: "light",
      get: function () { return state.on; },
      set: function (v) {
        state.on = v;
        apply();
      },
    },
    {
      type: "temperature",
      get: function () { return state.target; },
      set: function (v) {
        state.target = v;
      },
    },
    {
      type: "text",
      get: function () { return state.text; },
      set: function (v) {
        state.text = v;
      },
    },
    // A dimmer is an event, and the encoder cannot reach it by name: an event
    // entry is declared by its id and length (0x3C, event code + step count).
    // Home Assistant offers it as two buttons, rotate left and rotate right,
    // and a press sends one step. Its value is the last event seen, which is
    // what a button has instead of a resting state.
    {
      id: 0x3c,
      length: 2,
      get: function () { return [0, 0]; },
      set: function (v) {
        // length 2, so the module hands over both bytes: [event, steps].
        var event = v[0];
        var steps = v[1];
        state.target += (event === 1 ? 1 : -1) * steps;
        console.log("dimmer", event, steps, "-> target", state.target);
      },
    },
  ],
  interval: 1000,
  // Five objects and the declaration come to 14 bytes of service data, and a
  // nice!nano advertising its own name has room for 5 to 7 (D-046). The name
  // is the cheaper thing to drop: a receiver finds the device by its BTHome
  // service data anyway, and Home Assistant lets you rename it.
  showName: false,
  onError: function (error) {
    console.log("write rejected:", error.code, error.message);
  },
});

apply();
console.log("advertising as", NRF.getAddress());
console.log("writable entries:", bw.plan().entryIds);
