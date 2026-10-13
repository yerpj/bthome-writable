# The parser change to offer `bthome-ble`

A pull request to [`Bluetooth-Devices/bthome-ble`](https://github.com/Bluetooth-Devices/bthome-ble),
to go with the object-ID request on `bthome.io`. Both 2026-04 assignments were
filed that way — `0x65` linked parser PR #352, `0x3B` linked its own — so an ID
request without the code that reads it leaves the work to the maintainer.

**What it does: teaches the parser that `0xFF` is length-prefixed, so it can
skip it instead of stopping.** Today a receiver meeting an unknown object ID
cannot know its length, so it abandons the rest of the packet
(`parser.py`, the `break` under `if obj_meas_type not in MEAS_TYPES`). That is
the whole reason the declaration has to be the last object; with this change,
the rule becomes a courtesy rather than a requirement, and anything placed
after it survives.

It also exposes what it read, as `device.writable_entries`, so a receiver that
wants the declaration does not have to re-parse the advertisement itself.

## It follows an existing pattern exactly

`0xF0`, `0xF1` and `0xF2` — the device-info objects added in 3.24.0 — are
objects that are *parsed for their meaning rather than turned into a sensor*.
They are declared with `meas_format=None` and a `data_format` of their own, and
handled in a short branch that sets device state and `continue`s. This change
is the same shape, with one addition: the declaration is length-prefixed, like
`string` and `raw`, so its format name joins that list.

Nothing else is touched. No existing object changes meaning, and a device that
never sends `0xFF` parses exactly as before.

## The change

### `src/bthome_ble/const.py`

Add one entry to `MEAS_TYPES`, after `0xF2`:

```python
    0xFF: MeasTypes(
        meas_format=None,
        data_format="writable_entries",
    ),
```

### `src/bthome_ble/parser.py`

**1.** In `__init__`, beside `device_type_id`:

```python
        # Object IDs the device accepts writes for (object 0xFF), in entry
        # order. None when the device has never sent a declaration.
        self.writable_entries: tuple[int, ...] | None = None
```

**2.** In the object-splitting loop, let the format carry a length byte:

```python
-                    if obj_data_format in ["raw", "string", "command"]:
+                    if obj_data_format in [
+                        "raw",
+                        "string",
+                        "command",
+                        "writable_entries",
+                    ]:
```

**3.** In the value loop, beside the device-info branches:

```python
            if meas["data format"] == "writable_entries":
                self.writable_entries = tuple(meas["measurement data"])
                result = True
                continue
```

That is the whole of it: one table entry, one list membership, one branch.

## The tests to add, in `tests/test_parser_v2.py`

Written to the shape of `test_bthome_device_type_id`.

```python
def test_bthome_writable_entries() -> None:
    """Object 0xFF lists the object IDs a device accepts writes for."""
    # adv_info + FF 01 1E  (one entry, accepting 0x1E "light")
    data_string = b"\x40\xff\x01\x1e"
    advertisement = bytes_to_service_info(
        data_string, local_name="TEST DEVICE", address="A4:C1:38:8D:18:B2"
    )

    device = BTHomeBluetoothDeviceData()
    device.update(advertisement)

    assert device.writable_entries == (0x1E,)


def test_bthome_writable_entries_does_not_stop_the_parser() -> None:
    """The reason for this object having a length: what follows it survives.

    Before, an unknown ID ended parsing, because its length is unknown. A
    device had to put its declaration last and hope. Here the battery reading
    comes after it and must still arrive.
    """
    # adv_info + FF 02 1E 53 (two entries) + 01 61 (battery 97 %)
    data_string = b"\x40\xff\x02\x1e\x53\x01\x61"
    advertisement = bytes_to_service_info(
        data_string, local_name="TEST DEVICE", address="A4:C1:38:8D:18:B2"
    )

    device = BTHomeBluetoothDeviceData()
    result = device.update(advertisement)

    assert device.writable_entries == (0x1E, 0x53)
    assert result.entity_values[
        DeviceKey(key="battery", device_id=None)
    ].native_value == 97


def test_bthome_writable_entries_truncated() -> None:
    """A length byte that promises more than the packet holds is dropped,
    not guessed at."""
    # adv_info + FF 04 1E  (claims four entries, carries one)
    data_string = b"\x40\xff\x04\x1e"
    advertisement = bytes_to_service_info(
        data_string, local_name="TEST DEVICE", address="A4:C1:38:8D:18:B2"
    )

    device = BTHomeBluetoothDeviceData()
    device.update(advertisement)

    assert device.writable_entries is None
```

And a fourth, which is the one a maintainer actually cares about:

```python
def test_a_device_that_never_declares_is_untouched() -> None:
    """The change must be invisible to everyone else."""
    # adv_info + temperature 25.00 + humidity 50.55
    data_string = b"@Ä	¿"
    advertisement = bytes_to_service_info(
        data_string, local_name="TEST DEVICE", address="A4:C1:38:8D:18:B2"
    )

    device = BTHomeBluetoothDeviceData()
    result = device.update(advertisement)

    assert device.writable_entries is None
    assert result.entity_values[
        DeviceKey(key="temperature", device_id=None)
    ].native_value == 25.0
```

The truncated case needs no new code: the loop's existing
`if payload_length < next_obj_start` check already refuses an object that
promises more than the packet holds. The test is there so the behaviour is
pinned rather than assumed.

## This was applied and run before being offered

Against `bthome-ble` 3.24.0, which is what `pyproject.toml` says upstream is
today. The change was made to a copy of the installed library and tested with
**their own suite**, not only ours:

```
tests/test_parser_v2.py   118 passed      (their file, unmodified)
the four tests above        4 passed
                          122 passed in 0.32s
```

Their suite passing unmodified is the claim worth making in the pull request:
no existing object changes behaviour.

One honest note on the reviewer's likely first question — *why a tuple of raw
object IDs rather than something richer?* Because the parser cannot know more
without inventing semantics. Entry *k* is the *k*-th ID in the list, and what
a receiver does with that is the receiver's business; `bthome-ble` reads
advertising.

## What to say when asked "why does a parser need this?"

Three answers, in the order they tend to be asked:

1. **It unblocks the packet.** Not the declaration's own value — the objects
   after it. Today they are lost for every receiver.
2. **It is already deployed.** Devices advertising this exist on three benches
   and in two people's homes; the library skipping it knowingly is what lets
   them stop placing it last and hoping.
3. **It costs one table entry.** No existing object changes, and a device that
   never sends `0xFF` is parsed byte-for-byte as before.

## What this change is *not*

It does not implement writing. Nothing here opens a connection or sends
anything: `bthome-ble` is a parser, and the declaration is advertising data
like any other object. The GATT side lives in the receiver — see
`spec/PROTOCOL.md` §4 — and is not being proposed here.
