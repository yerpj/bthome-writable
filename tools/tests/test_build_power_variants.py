"""One image a recording, and the constants in it are the recording.

The images of §23 are what the board actually runs under the meter, so the
substitution that makes them is worth a test of its own: a constant that
silently failed to take would be a recording of the wrong arm, and nothing
downstream could tell.
"""

from __future__ import annotations

import pytest

from tools.build_power_variants import (
    BUILTINS,
    FLAGS,
    INLINE,
    VARIANTS,
    leftover_requires,
    preamble,
    resolve,
    rewrite,
)


def test_a_constant_is_replaced_exactly_once() -> None:
    source = "var ADV_INTERVAL = 2000;\nvar SWEEP = null;\nvar SWEEP_MS = 180000;\n"
    out = rewrite(source, {"SWEEP": "[100, 200]", "SWEEP_MS": "120000"})
    assert "var SWEEP = [100, 200];" in out
    assert "var SWEEP_MS = 120000;" in out
    assert "var ADV_INTERVAL = 2000;" in out


def test_a_constant_that_is_not_there_is_an_error() -> None:
    """Silence here would mean recording an arm nobody selected."""
    with pytest.raises(SystemExit, match="matched 0 declarations"):
        rewrite("var SWEEP = null;\n", {"MARK": "null"})


def test_the_name_of_a_constant_is_not_a_prefix_of_another() -> None:
    source = "var SWEEP = null;\nvar SWEEP_MS = 180000;\n"
    out = rewrite(source, {"SWEEP": "[100]"})
    assert "var SWEEP_MS = 180000;" in out


def test_every_recording_of_section_23_has_an_image() -> None:
    assert set(VARIANTS) == {
        "power-sweep",
        "power-commands",
        "power-commands-pinned",
    }
    # The marker channel is not available on this bench, so no image asks for
    # one: the steps and the commands are read out of the current itself.
    assert all(arm["MARK"] == "null" for arm in VARIANTS.values())
    assert VARIANTS["power-commands-pinned"]["CONNECTION_INTERVAL"] == "7.5"
    assert VARIANTS["power-commands"]["CONNECTION_INTERVAL"] == "null"
    assert VARIANTS["power-sweep"]["SWEEP_MS"] == "120000"


def test_an_image_tokenises_before_it_parses_anything_else() -> None:
    """A Puck.js has no room for 23 kB of function source text."""
    assert FLAGS.startswith("E.setFlags({pretokenise")


def test_a_module_the_firmware_does_not_have_fails_the_build() -> None:
    """The check that was missing. The first image inlined BTHome, shipped,
    booted, and died on AESCCM behind it; a board booting from .bootcde
    reports the symptom it reached rather than the module it lacked."""
    assert leftover_requires('var a = require("AESCCM");') == ["AESCCM"]
    assert leftover_requires('require("Zlib");require("AESCCM")') == [
        "AESCCM",
        "Zlib",
    ]


def test_the_firmware_s_own_modules_are_not_leftovers() -> None:
    body = 'require("Storage").read("x");require("crypto").AES'
    assert leftover_requires(body) == []
    assert "Storage" in BUILTINS and "crypto" in BUILTINS


def test_resolving_points_every_require_at_its_binding() -> None:
    body = 'var b = require("BTHome");var c = require("AESCCM").encrypt;'
    out = resolve("test", body)
    assert out == "var b = BTHomeUpstream;var c = AESCCMInlined.encrypt;"
    assert leftover_requires(out) == []


def test_an_inlined_module_nobody_requires_is_an_error() -> None:
    """Dead weight in an image with 274 JsVars to spare, and more likely a
    rename that silently stopped resolving."""
    with pytest.raises(SystemExit, match="nothing requires BTHome"):
        resolve("test", 'require("AESCCM")')


def test_the_preamble_binds_before_anything_uses_it() -> None:
    text = preamble()
    assert text.startswith(FLAGS)
    for _name, _path, bound, _strip in INLINE:
        assert f"var {bound} = exports;" in text
    # One fresh exports per module, each closed off by its own binding.
    assert text.count("var exports = {};") == len(INLINE)
    assert leftover_requires(text) == []
