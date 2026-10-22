"""Tests for the OSC codec and the address tree."""
from __future__ import annotations

import pytest

from mapstudio.osc.protocol import decode_packet, encode_message, encode_bundle, OscMessage, OscBundle, OscError


def test_message_roundtrip_all_types():
    pkt = encode_message("/surfaces/2/opacity", [0.5, 3, "hi", True, False, None, b"\x01\x02\x03"])
    m = decode_packet(pkt)
    assert isinstance(m, OscMessage)
    assert m.address == "/surfaces/2/opacity"
    assert m.args[0] == pytest.approx(0.5) and m.args[1] == 3 and m.args[2] == "hi"
    assert m.args[3] is True and m.args[4] is False and m.args[5] is None and m.args[6] == b"\x01\x02\x03"
    assert len(pkt) % 4 == 0


def test_bundle_roundtrip():
    b = encode_bundle([encode_message("/a", [1]), encode_message("/b", [2.0])])
    out = decode_packet(b)
    assert isinstance(out, OscBundle) and [e.address for e in out.elements] == ["/a", "/b"]


def test_message_without_typetags():
    assert decode_packet(b"/x\0\0").args == []


@pytest.mark.parametrize("bad", [b"x\0\0\0", b"/a\0\0,q\0\0", b"/a\0\0,i\0\0\x00", b"#bundle\0\0"])
def test_malformed_packets_raise(bad: bytes):
    with pytest.raises(OscError):
        decode_packet(bad)
