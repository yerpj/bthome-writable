"""The BTHome Writable integration.

Downlink companion to the core BTHome integration: devices declare writable
objects in their advertising, this integration writes new values back over a
short GATT connection. See spec/PROTOCOL.md.
"""

from __future__ import annotations

__all__ = ["DOMAIN"]

from .const import DOMAIN
