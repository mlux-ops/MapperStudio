"""OSC 1.0 packet codec (messages and bundles), written from the published specification.

Supported type tags: i (int32), f (float32), s (string), b (blob), h (int64), d (float64),
T/F (true/false), N (nil), I (impulse), t (timetag).  Unknown tags raise `OscError` so that a
malformed packet from the network can never crash the receiver.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any

BUNDLE_HEADER = b"#bundle\0"
IMMEDIATELY = 1


class OscError(ValueError):
    pass


@dataclass
class OscMessage:
    address: str
    args: list[Any] = field(default_factory=list)


@dataclass
class OscBundle:
    timetag: int
    elements: list["OscMessage | OscBundle"] = field(default_factory=list)


def _pad(n: int) -> int:
    return (4 - n % 4) % 4


def _read_string(data: bytes, pos: int) -> tuple[str, int]:
    end = data.find(b"\0", pos)
    if end < 0:
        raise OscError("unterminated string")
    s = data[pos:end].decode("utf-8", errors="replace")
    end += 1
    return s, end + _pad(end)


def _read_blob(data: bytes, pos: int) -> tuple[bytes, int]:
    if pos + 4 > len(data):
        raise OscError("truncated blob size")
    n = struct.unpack(">i", data[pos:pos + 4])[0]
    if n < 0 or pos + 4 + n > len(data):
        raise OscError("bad blob size")
    start = pos + 4
    end = start + n
    return data[start:end], end + _pad(n)


def decode_message(data: bytes) -> OscMessage:
    address, pos = _read_string(data, 0)
    if not address.startswith("/"):
        raise OscError(f"address must start with '/': {address!r}")
    if pos >= len(data):
        return OscMessage(address, [])
    tags, pos = _read_string(data, pos)
    if not tags.startswith(","):
        raise OscError("type tag string must start with ','")
    args: list[Any] = []
    for tag in tags[1:]:
        if tag == "i":
            args.append(struct.unpack(">i", _take(data, pos, 4))[0]); pos += 4
        elif tag == "f":
            args.append(struct.unpack(">f", _take(data, pos, 4))[0]); pos += 4
        elif tag == "s" or tag == "S":
            s, pos = _read_string(data, pos); args.append(s)
        elif tag == "b":
            b, pos = _read_blob(data, pos); args.append(b)
        elif tag == "h":
            args.append(struct.unpack(">q", _take(data, pos, 8))[0]); pos += 8
        elif tag == "d":
            args.append(struct.unpack(">d", _take(data, pos, 8))[0]); pos += 8
        elif tag == "t":
            args.append(struct.unpack(">Q", _take(data, pos, 8))[0]); pos += 8
        elif tag == "c":
            args.append(chr(struct.unpack(">I", _take(data, pos, 4))[0])); pos += 4
        elif tag == "T":
            args.append(True)
        elif tag == "F":
            args.append(False)
        elif tag == "N":
            args.append(None)
        elif tag == "I":
            args.append(Ellipsis)
        else:
            raise OscError(f"unsupported type tag {tag!r}")
    return OscMessage(address, args)


def _take(data: bytes, pos: int, n: int) -> bytes:
    if pos + n > len(data):
        raise OscError("truncated argument")
    return data[pos:pos + n]


def decode_packet(data: bytes) -> OscMessage | OscBundle:
    if data.startswith(BUNDLE_HEADER):
        if len(data) < 16:
            raise OscError("truncated bundle")
        timetag = struct.unpack(">Q", data[8:16])[0]
        pos = 16
        elements: list[OscMessage | OscBundle] = []
        while pos < len(data):
            size = struct.unpack(">i", _take(data, pos, 4))[0]
            pos += 4
            if size < 0 or pos + size > len(data):
                raise OscError("bad bundle element size")
            elements.append(decode_packet(data[pos:pos + size]))
            pos += size
        return OscBundle(timetag, elements)
    return decode_message(data)


def _write_string(s: str) -> bytes:
    b = s.encode("utf-8") + b"\0"
    return b + b"\0" * _pad(len(b))


def encode_message(address: str, args: list[Any] | tuple[Any, ...] = ()) -> bytes:
    tags = ","
    body = b""
    for a in args:
        if isinstance(a, bool):
            tags += "T" if a else "F"
        elif isinstance(a, int):
            tags += "i"; body += struct.pack(">i", max(-2**31, min(2**31 - 1, a)))
        elif isinstance(a, float):
            tags += "f"; body += struct.pack(">f", a)
        elif isinstance(a, str):
            tags += "s"; body += _write_string(a)
        elif isinstance(a, (bytes, bytearray)):
            tags += "b"; body += struct.pack(">i", len(a)) + bytes(a) + b"\0" * _pad(len(a))
        elif a is None:
            tags += "N"
        else:
            raise OscError(f"cannot encode argument of type {type(a).__name__}")
    return _write_string(address) + _write_string(tags) + body


def encode_bundle(messages: list[bytes], timetag: int = IMMEDIATELY) -> bytes:
    out = BUNDLE_HEADER + struct.pack(">Q", timetag)
    for m in messages:
        out += struct.pack(">i", len(m)) + m
    return out
