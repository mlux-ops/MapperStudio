"""Reader for MadMapper `.mad` project files.

Layout (recovered from the MadMapper 6.1.8 loader, see `../../02-project-schema.md`):

    int32 BE  magic        0x0BADBABE
    int32 BE  fileVersion  (18 for 6.1.x; < 3 is rejected by MadMapper)
    QVariantMap            Qt 6 QDataStream, big-endian, 32-bit container sizes

Nested `QByteArray` blobs (surface `positions`, `uvs`, warping grids ...) are themselves
QDataStream payloads; helpers to decode the common ones live here too.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .qvariant_stream import QVariantStreamReader, StreamError, UserType

MAD_MAGIC = 0x0BADBABE
MIN_SUPPORTED_VERSION = 3
MAX_KNOWN_VERSION = 18


class MadFileError(ValueError):
    """The file is not a readable MadMapper project."""


# --- user types registered by MadMapper -----------------------------------------------------
# Each reader receives the stream positioned right after the type name.  Layouts were recovered
# by inspecting the sample projects shipped with the demo (see `tools/mad_probe.py`).

def _read_qlist_float(r: QVariantStreamReader) -> list[float]:
    n = r.read_u32()
    return [r.read_f32() for _ in range(n)]


def _read_qlist_int(r: QVariantStreamReader) -> list[int]:
    n = r.read_u32()
    return [r.read_i32() for _ in range(n)]


def _read_qlist_double(r: QVariantStreamReader) -> list[float]:
    n = r.read_u32()
    return [r.read_f64() for _ in range(n)]


def _read_qlist_qstring(r: QVariantStreamReader) -> list[str | None]:
    n = r.read_u32()
    return [r.read_qstring() for _ in range(n)]


def _read_qlist_qpointf(r: QVariantStreamReader) -> list[tuple[float, float]]:
    return r.read_qpolygonf()


def _read_madcolor(r: QVariantStreamReader) -> dict[str, Any]:
    """`MadColor`: a QString mode followed by the colour payload.

    Modes verified against the sample projects:
      * "rgb" / "hsv": four doubles in 0..1 (components + alpha);
      * "p": a palette reference = qint32 index into `colorPalette.colors` + a double level.
    """
    mode = r.read_qstring() or "rgb"
    if mode == "p":
        index, level = r.read_i32(), r.read_f64()
        return {"space": "p", "palette_index": index, "level": level, "rgba": (1.0, 1.0, 1.0, level)}
    c = [r.read_f64() for _ in range(4)]
    if mode == "hsv":
        import colorsys
        rr, gg, bb = colorsys.hsv_to_rgb(c[0] % 1.0, c[1], c[2])
        rgba = (rr, gg, bb, c[3])
    else:
        rgba = (c[0], c[1], c[2], c[3])
    return {"space": mode, "components": c, "rgba": rgba}


def _read_filepath(r: QVariantStreamReader) -> dict[str, Any]:
    """`FilePath`: a QString path (absolute or project-relative)."""
    return {"path": r.read_qstring()}


def _read_index_float_map(r: QVariantStreamReader) -> dict[int, float]:
    """`IndexFloatMap` = QMap<int, float>: quint32 count, then (qint32 key, float value) pairs."""
    n = r.read_u32()
    return {r.read_i32(): r.read_f32() for _ in range(n)}


def _read_index_variant_map(r: QVariantStreamReader) -> dict[int, Any]:
    """`IndexVariantMap` = QMap<int, QVariant>."""
    n = r.read_u32()
    return {r.read_i32(): r.read_qvariant() for _ in range(n)}


USER_TYPE_READERS = {
    "IndexFloatMap": _read_index_float_map,
    "IndexVariantMap": _read_index_variant_map,
    "QList<float>": _read_qlist_float,
    "QList<int>": _read_qlist_int,
    "QList<double>": _read_qlist_double,
    "QList<QString>": _read_qlist_qstring,
    "QList<QPointF>": _read_qlist_qpointf,
    "MadColor": _read_madcolor,
    "FilePath": _read_filepath,
}


def read_mad_bytes(data: bytes, *, strict: bool = True) -> tuple[int, dict[str, Any]]:
    """Parse a `.mad` payload. Returns `(fileVersion, top-level map)`."""
    if len(data) < 8:
        raise MadFileError("file too small to be a MadMapper project")
    reader = QVariantStreamReader(data, user_readers=dict(USER_TYPE_READERS))
    magic = reader.read_u32()
    if magic != MAD_MAGIC:
        raise MadFileError(f"invalid header: magic 0x{magic:08X} (expected 0x0BADBABE)")
    version = reader.read_i32()
    if version < MIN_SUPPORTED_VERSION:
        raise MadFileError(f"project file version {version} is too old")
    try:
        root = reader.read_variant_map()
    except StreamError as exc:
        raise MadFileError(str(exc)) from exc
    if strict and reader.pos != len(data):
        raise MadFileError(f"{len(data) - reader.pos} trailing bytes after the project map")
    return version, root


def read_mad_file(path: str | Path, *, strict: bool = True) -> tuple[int, dict[str, Any]]:
    path = Path(path)
    if path.is_dir():  # a .madproject folder: use the .mad inside
        mads = sorted(path.glob("*.mad"))
        if not mads:
            raise MadFileError(f"no .mad file inside {path}")
        path = mads[0]
    return read_mad_bytes(path.read_bytes(), strict=strict)


# --- blob helpers ---------------------------------------------------------------------------

def decode_polygonf_blob(blob: bytes | None) -> list[tuple[float, float]]:
    """`positions` / `uvs` / mask `positions`: a serialised `QPolygonF`."""
    if not blob:
        return []
    r = QVariantStreamReader(blob)
    pts = r.read_qpolygonf()
    if r.pos != len(blob):
        raise MadFileError(f"polygon blob has {len(blob) - r.pos} trailing bytes")
    return pts


def unwrap(value: Any) -> Any:
    """Strip `UserType` wrappers recursively so the result is plain Python data."""
    if isinstance(value, UserType):
        return unwrap(value.value)
    if isinstance(value, dict):
        return {k: unwrap(v) for k, v in value.items()}
    if isinstance(value, list):
        return [unwrap(v) for v in value]
    return value
