"""Tests for the pure-Python QVariant stream reader and the .mad project reader."""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

from mapstudio.madfile import read_mad_bytes, read_mad_file, decode_polygonf_blob, unwrap, MadFileError
from mapstudio.madfile.qvariant_stream import QVariantStreamReader, StreamError, UserType

SAMPLES = Path(r"E:\Games\MadMapperDemo 6.1.8\Resources\SampleProjects")
SAMPLE_NAMES = [
    "Video Example", "SoftEdge Blending 2 Outputs Example", "SoftEdge Blending 4 Outputs Example",
    "DMX LED Bar Example", "DMX LED Bar Lines Example", "Laser Example",
]
needs_samples = pytest.mark.skipif(not SAMPLES.is_dir(), reason="MadMapper demo samples not installed")


def qstring(s: str) -> bytes:
    b = s.encode("utf-16-be")
    return struct.pack(">I", len(b)) + b


def variant_double(v: float) -> bytes:
    return struct.pack(">IB", 6, 0) + struct.pack(">d", v)


def variant_int(v: int) -> bytes:
    return struct.pack(">IB", 2, 0) + struct.pack(">i", v)


def test_reads_qt4_wire_format_map():
    body = struct.pack(">I", 2) + qstring("a") + variant_double(1.5) + qstring("b") + variant_int(-7)
    r = QVariantStreamReader(body)
    assert r.read_variant_map() == {"a": 1.5, "b": -7}
    assert r.pos == len(body)


def test_float_type_is_streamed_as_double_by_default():
    body = struct.pack(">I", 1) + qstring("f") + struct.pack(">IB", 135, 0) + struct.pack(">d", 60.0)
    assert QVariantStreamReader(body).read_variant_map() == {"f": 60.0}


def test_invalid_variant_carries_null_string_marker_in_qt4_streams():
    body = struct.pack(">I", 1) + qstring("x") + struct.pack(">IB", 0, 1) + struct.pack(">I", 0xFFFFFFFF)
    assert QVariantStreamReader(body).read_variant_map() == {"x": None}


def test_user_type_without_reader_raises_with_offset():
    body = struct.pack(">I", 1) + qstring("u") + struct.pack(">IB", 127, 0) + struct.pack(">I", 4) + b"Foo\0"
    with pytest.raises(StreamError, match="Foo"):
        QVariantStreamReader(body).read_variant_map()


def test_madcolor_rgb_and_palette_modes():
    from mapstudio.madfile.madproject import USER_TYPE_READERS
    rgb = qstring("rgb") + struct.pack(">dddd", 0.5, 0.25, 1.0, 1.0)
    r = QVariantStreamReader(rgb, user_readers=USER_TYPE_READERS)
    assert USER_TYPE_READERS["MadColor"](r)["rgba"] == (0.5, 0.25, 1.0, 1.0)
    pal = qstring("p") + struct.pack(">id", 2, 0.75)
    r = QVariantStreamReader(pal, user_readers=USER_TYPE_READERS)
    out = USER_TYPE_READERS["MadColor"](r)
    assert out["palette_index"] == 2 and out["level"] == 0.75


def test_bad_magic_is_rejected():
    with pytest.raises(MadFileError, match="magic"):
        read_mad_bytes(b"\x00\x00\x00\x00" + struct.pack(">i", 18) + struct.pack(">I", 0))


def test_old_version_is_rejected():
    with pytest.raises(MadFileError, match="too old"):
        read_mad_bytes(struct.pack(">I", 0x0BADBABE) + struct.pack(">i", 2) + struct.pack(">I", 0))


def test_polygon_blob_roundtrip():
    blob = struct.pack(">I", 2) + struct.pack(">dd", 1.0, 2.0) + struct.pack(">dd", 3.0, 4.0)
    assert decode_polygonf_blob(blob) == [(1.0, 2.0), (3.0, 4.0)]
    with pytest.raises(MadFileError):
        decode_polygonf_blob(blob + b"\0")


@needs_samples
@pytest.mark.parametrize("name", SAMPLE_NAMES)
def test_all_sample_projects_parse_completely(name: str):
    version, root = read_mad_file(SAMPLES / f"{name}.madproject")
    assert version in (18, 19)
    assert "surfaces" in root and "outputs" in root and "visuals" in root
    plain = unwrap(root)
    assert not any(isinstance(v, UserType) for v in plain.values())


@needs_samples
def test_video_example_quads_decode():
    _, root = read_mad_file(SAMPLES / "Video Example.madproject")
    root = unwrap(root)
    quads = [s for s in root["surfaces"] if s["type"] == "quad"]
    assert [q["name"] for q in quads] == ["Quad-2", "Quad-1"]
    corners = decode_polygonf_blob(quads[0]["positions"])
    assert len(corners) == 4
    assert quads[0]["customSettings"]["FX/Name"] == "Rutt Etra"
    assert root["outputs"]["outputs"][0]["stageSize"] == (6.3999999999999995, 3.6)
