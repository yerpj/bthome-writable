"""Borrow the integration's wire-format code without dragging Home Assistant in.

`custom_components/bthome_writable/protocol.py` is deliberately free of Home
Assistant imports — it is the wire format and nothing else — but the package's
`__init__.py` is not, so an ordinary `from custom_components... import protocol`
executes that first and fails on any machine without Home Assistant installed.
The host tools run in a venv that has no reason to carry it.

Copying the parsing into `tools/` instead would leave two implementations of
`PROTOCOL.md` to drift apart, which is the one thing this project must not do.
So the package is bound under another name whose `__path__` points at the same
directory: the relative `from .const import ...` still resolves, and the real
`__init__.py` is never run.

    from tools.ha_protocol import parse_declaration, split_objects
"""

from __future__ import annotations

import importlib
from pathlib import Path
import sys
import types

_PACKAGE = "_bthome_writable_wire"
_ROOT = Path(__file__).resolve().parent.parent
_SOURCE = _ROOT / "custom_components" / "bthome_writable"

if _PACKAGE not in sys.modules:
    _shim = types.ModuleType(_PACKAGE)
    _shim.__path__ = [str(_SOURCE)]
    sys.modules[_PACKAGE] = _shim

_protocol = importlib.import_module(f"{_PACKAGE}.protocol")

Declaration = _protocol.Declaration
ProtocolError = _protocol.ProtocolError
WritableObject = _protocol.WritableObject
compose_write = _protocol.compose_write
no_op_value = _protocol.no_op_value
parse_declaration = _protocol.parse_declaration
split_objects = _protocol.split_objects
