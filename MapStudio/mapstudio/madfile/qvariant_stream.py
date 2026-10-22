"""Pure-Python reader for the Qt 6 `QDataStream` serialisation of `QVariant` values.

MadMapper writes its project as a `QVariantMap` with the default (big-endian, Qt 6.0-6.6) stream
settings: container sizes are 32-bit, strings are UTF-16BE prefixed with their byte length, and
every value is wrapped as `quint32 typeId, qint8 isNull, [const char* typeName when user type],
payload`.  Only the types that occur in `.mad` files (plus the common Qt value types) are
implemented; an unknown type raises `StreamError` with the offset so the layout can be
recovered and added.

The layouts follow the public Qt documentation of each `operator<<`:
    https://doc.qt.io/qt-6/datastreamformat.html
"""
from __future__ import annotations

import colorsys
import struct
from dataclasses import dataclass, field
from typing import Any, Callable

# Qt 6 QMetaType ids (qmetatype.h).
T_BOOL, T_INT, T_UINT, T_LONGLONG, T_ULONGLONG, T_DOUBLE, T_QCHAR = 1, 2, 3, 4, 5, 6, 7
T_VARIANTMAP, T_VARIANTLIST, T_QSTRING, T_QSTRINGLIST, T_QBYTEARRAY, T_QBITARRAY = 8, 9, 10, 11, 12, 13
T_QDATE, T_QTIME, T_QDATETIME, T_QURL, T_QLOCALE = 14, 15, 16, 17, 18
T_QRECT, T_QRECTF, T_QSIZE, T_QSIZEF, T_QLINE, T_QLINEF, T_QPOINT, T_QPOINTF = 19, 20, 21, 22, 23, 24, 25, 26
T_VARIANTHASH, T_QUUID, T_LONG, T_SHORT, T_CHAR, T_ULONG, T_USHORT, T_UCHAR = 28, 30, 32, 33, 34, 35, 36, 37
T_FLOAT, T_SCHAR, T_QVARIANT, T_VOID, T_QJSONDOCUMENT, T_QBYTEARRAYLIST = 38, 40, 41, 43, 48, 49
T_QCOLOR, T_QIMAGE, T_QPOLYGON = 0x1003, 0x1006, 0x1007
T_QTRANSFORM, T_QMATRIX4X4, T_QVECTOR2D, T_QVECTOR3D, T_QVECTOR4D, T_QQUATERNION, T_QPOLYGONF = (
    0x1010, 0x1011, 0x1012, 0x1013, 0x1014, 0x1015, 0x1016)
T_USER = 0x10000

NULL_LENGTH = 0xFFFFFFFF


class StreamError(ValueError):
    """Raised when the stream does not match the expected layout."""


@dataclass
class UserType:
    """A value of a user-registered meta type (e.g. MadMapper's `MadColor`)."""
    type_name: str
    value: Any


@dataclass
class QColorValue:
    """A `QColor` as streamed: spec (1 rgb, 2 hsv, 3 cmyk, 4 hsl, 5 extended rgb) and 16-bit components."""
    spec: int
    alpha: int
    c1: int
    c2: int
    c3: int
    c4: int = 0

    def to_rgba_floats(self) -> tuple[float, float, float, float]:
        """RGBA in 0..1. HSV/HSL/CMYK are converted the way QColor::toRgb() would."""
        a = self.alpha / 65535.0
        if self.spec in (1, 5):
            return self.c1 / 65535.0, self.c2 / 65535.0, self.c3 / 65535.0, a
        if self.spec == 2:  # hsv: hue is stored x100 in 0..35999
            h = (self.c1 / 100.0) / 360.0 if self.c1 != 0xFFFF else 0.0
            r, g, b = colorsys.hsv_to_rgb(h, self.c2 / 65535.0, self.c3 / 65535.0)
            return r, g, b, a
        if self.spec == 4:
            h = (self.c1 / 100.0) / 360.0 if self.c1 != 0xFFFF else 0.0
            r, g, b = colorsys.hls_to_rgb(h, self.c3 / 65535.0, self.c2 / 65535.0)
            return r, g, b, a
        if self.spec == 3:
            c, m, y, k = (v / 65535.0 for v in (self.c1, self.c2, self.c3, self.c4))
            return (1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k), a
        return 0.0, 0.0, 0.0, a


@dataclass
class QImageValue:
    """An embedded image; `data` is the PNG byte stream Qt wrote."""
    format: int
    data: bytes


# Qt 4 wire ids (used when the stream version is < Qt_5_0 = 13), mapped to the Qt 6 ids above.
# QDataStream version 12 (Qt_4_8) is what MadMapper uses for projects and blobs.
QT4_TO_QT6_IDS: dict[int, int] = {
    **{i: i for i in range(0, 30)},          # core value types kept their ids
    64 + 0: 0x1000, 65: 0x1001, 66: 0x1002, 67: T_QCOLOR, 68: 0x1004, 69: 0x1005, 70: T_QIMAGE,
    71: T_QPOLYGON, 72: 0x1008, 73: 0x1009, 74: 0x100a, 76: 0x100b, 77: 0x100c, 78: 0x100d,
    79: 0x100e, 81: T_QTRANSFORM, 82: T_QMATRIX4X4, 83: T_QVECTOR2D, 84: T_QVECTOR3D,
    85: T_QVECTOR4D, 86: T_QQUATERNION, 87: T_QPOLYGONF,
    127: T_USER,
    # Qt 5 core ids 31..55 were shifted by +97 when written with a Qt 4 stream version.
    **{97 + i: i for i in range(31, 56)},
}
QT5_TO_QT6_IDS: dict[int, int] = {
    **{i: i for i in range(0, 64)},
    **{64 + i: 0x1000 + i for i in range(0, 24)},
    1024: T_USER,
}
STREAM_QT_5_0, STREAM_QT_6_0 = 13, 20


@dataclass
class QVariantStreamReader:
    data: bytes
    pos: int = 0
    # Hooks for user-registered types: name -> reader(self) -> value.
    user_readers: dict[str, Callable[["QVariantStreamReader"], Any]] = field(default_factory=dict)
    version: int = 12  # QDataStream::Qt_4_8, MadMapper's choice
    single_precision: bool = False  # QDataStream::FloatingPointPrecision (default: doubles)

    # ---- primitives -------------------------------------------------------------------------
    def _take(self, n: int) -> bytes:
        if n < 0 or self.pos + n > len(self.data):
            raise StreamError(f"unexpected end of stream at offset {self.pos} (wanted {n} bytes)")
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def _unpack(self, fmt: str) -> Any:
        return struct.unpack(fmt, self._take(struct.calcsize(fmt)))[0]

    def read_u8(self) -> int:
        return self._unpack(">B")

    def read_i8(self) -> int:
        return self._unpack(">b")

    def read_u16(self) -> int:
        return self._unpack(">H")

    def read_i16(self) -> int:
        return self._unpack(">h")

    def read_u32(self) -> int:
        return self._unpack(">I")

    def read_i32(self) -> int:
        return self._unpack(">i")

    def read_u64(self) -> int:
        return self._unpack(">Q")

    def read_i64(self) -> int:
        return self._unpack(">q")

    def read_f32(self) -> float:
        """A C++ `float`. QDataStream writes floats as doubles unless single precision was
        requested (`setFloatingPointPrecision`); MadMapper leaves the default, so 8 bytes."""
        return self._unpack(">f") if self.single_precision else self._unpack(">d")

    def read_f64(self) -> float:
        return self._unpack(">d")

    def read_bool(self) -> bool:
        return self.read_u8() != 0

    def read_qstring(self) -> str | None:
        n = self.read_u32()
        if n == NULL_LENGTH:
            return None
        if n % 2:
            raise StreamError(f"odd QString byte length {n} at offset {self.pos - 4}")
        return self._take(n).decode("utf-16-be")

    def read_qbytearray(self) -> bytes | None:
        n = self.read_u32()
        if n == NULL_LENGTH:
            return None
        return self._take(n)

    def read_cstring(self) -> str | None:
        """`QDataStream << const char*`: quint32 length including the NUL, then the bytes."""
        n = self.read_u32()
        if n == 0:
            return None
        raw = self._take(n)
        return raw.rstrip(b"\0").decode("latin-1")

    # ---- compound Qt types -----------------------------------------------------------------
    def read_qpointf(self) -> tuple[float, float]:
        return self.read_f64(), self.read_f64()

    def read_qpoint(self) -> tuple[int, int]:
        return self.read_i32(), self.read_i32()

    def read_qsizef(self) -> tuple[float, float]:
        return self.read_f64(), self.read_f64()

    def read_qsize(self) -> tuple[int, int]:
        return self.read_i32(), self.read_i32()

    def read_qrect(self) -> tuple[int, int, int, int]:
        """Returns (x, y, width, height); Qt streams left, top, right, bottom."""
        x1, y1, x2, y2 = (self.read_i32() for _ in range(4))
        return x1, y1, x2 - x1 + 1, y2 - y1 + 1

    def read_qrectf(self) -> tuple[float, float, float, float]:
        x, y, w, h = (self.read_f64() for _ in range(4))
        return x, y, w, h

    def read_qpolygonf(self) -> list[tuple[float, float]]:
        n = self.read_u32()
        return [self.read_qpointf() for _ in range(n)]

    def read_qpolygon(self) -> list[tuple[int, int]]:
        n = self.read_u32()
        return [self.read_qpoint() for _ in range(n)]

    def read_qcolor(self) -> QColorValue:
        spec = self.read_i8()
        if spec == 5:  # ExtendedRgb: four floats
            a, r, g, b = (self.read_f32() for _ in range(4))

            def clamp(v: float) -> int:
                return max(0, min(65535, int(round(v * 65535))))

            return QColorValue(5, clamp(a), clamp(r), clamp(g), clamp(b))
        alpha, c1, c2, c3, c4 = (self.read_u16() for _ in range(5))
        return QColorValue(spec, alpha, c1, c2, c3, c4)

    def read_qimage(self) -> QImageValue | None:
        """Qt streams a qint32 (0 = null image; 1 or a format id otherwise) then the image saved as PNG."""
        fmt = self.read_i32()
        if fmt in (-1, 0):
            return None
        start = self.pos
        sig = self._take(8)
        if sig != b"\x89PNG\r\n\x1a\n":
            raise StreamError(f"embedded QImage at offset {start} is not PNG")
        while True:  # walk chunks to IEND
            length = self.read_u32()
            ctype = self._take(4)
            self._take(length + 4)  # data + crc
            if ctype == b"IEND":
                break
        return QImageValue(fmt, self.data[start:self.pos])

    def read_qdate(self) -> int:
        """Julian day: quint32 before Qt_5_0, qint64 after."""
        return self.read_u32() if self.version < STREAM_QT_5_0 else self.read_i64()

    def read_qtime(self) -> int:
        return self.read_u32()  # milliseconds since midnight

    def read_qdatetime(self) -> dict[str, Any]:
        jd, ms = self.read_qdate(), self.read_u32()
        spec = self.read_i8()
        extra: Any = None
        if self.version >= 15:  # Qt_5_2 added offset / zone payloads
            if spec == 2:  # OffsetFromUTC
                extra = self.read_i32()
            elif spec == 3:  # TimeZone
                extra = self.read_qbytearray()
        return {"julian_day": jd, "msecs": ms, "spec": spec, "extra": extra}

    def read_quuid(self) -> str:
        l, w1, w2 = self.read_u32(), self.read_u16(), self.read_u16()
        b = self._take(8)
        return f"{l:08x}-{w1:04x}-{w2:04x}-{b[:2].hex()}-{b[2:].hex()}"

    def read_qstringlist(self) -> list[str | None]:
        n = self.read_u32()
        return [self.read_qstring() for _ in range(n)]

    def read_qbytearraylist(self) -> list[bytes | None]:
        n = self.read_u32()
        return [self.read_qbytearray() for _ in range(n)]

    def read_variant_list(self) -> list[Any]:
        n = self.read_u32()
        return [self.read_qvariant() for _ in range(n)]

    def read_variant_map(self) -> dict[str, Any]:
        n = self.read_u32()
        out: dict[str, Any] = {}
        for _ in range(n):
            key = self.read_qstring()
            out[key if key is not None else ""] = self.read_qvariant()
        return out

    def read_qlocale(self) -> str | None:
        return self.read_qstring()  # Qt streams the BCP47 name

    def sub_reader(self, blob: bytes) -> "QVariantStreamReader":
        """A reader over a nested QByteArray payload with the same stream settings."""
        return QVariantStreamReader(blob, 0, self.user_readers, self.version, self.single_precision)

    def read_floats(self, n: int) -> tuple[float, ...]:
        return tuple(self.read_f32() for _ in range(n))

    # ---- QVariant dispatch -----------------------------------------------------------------
    def read_qvariant(self) -> Any:
        start = self.pos
        wire_id = self.read_u32()
        if self.version < STREAM_QT_5_0:
            type_id = QT4_TO_QT6_IDS.get(wire_id, -1)
        elif self.version < STREAM_QT_6_0:
            type_id = QT5_TO_QT6_IDS.get(wire_id, -1)
        else:
            type_id = wire_id
        if type_id == -1:
            raise StreamError(f"unknown wire type id {wire_id} for stream version {self.version} at offset {start}")
        is_null = self.read_i8()
        type_name: str | None = None
        if type_id == T_USER:
            type_name = self.read_cstring()
        if type_id in (T_VOID, 0):
            if self.version < STREAM_QT_5_0 and type_id == 0:
                self.read_qstring()  # Qt 4 streams carry a null QString after an invalid QVariant
            return None
        try:
            if type_name is not None:
                reader = self.user_readers.get(type_name)
                if reader is None:
                    raise StreamError(
                        f"no reader for user type {type_name!r} at offset {start}; "
                        f"next bytes: {self.data[self.pos:self.pos + 48].hex()}")
                return UserType(type_name, reader(self))
            fn = _BUILTIN.get(type_id)
            if fn is None:
                raise StreamError(f"unsupported QVariant type id {type_id} (0x{type_id:x}) at offset {start}")
            value = fn(self)
        except struct.error as exc:
            raise StreamError(f"truncated value of type {type_id} at offset {start}: {exc}") from exc
        if is_null and isinstance(value, (int, float, str, bytes)) and not value:
            return None
        return value


_BUILTIN: dict[int, Callable[[QVariantStreamReader], Any]] = {
    T_BOOL: QVariantStreamReader.read_bool,
    T_INT: QVariantStreamReader.read_i32,
    T_UINT: QVariantStreamReader.read_u32,
    T_LONGLONG: QVariantStreamReader.read_i64,
    T_ULONGLONG: QVariantStreamReader.read_u64,
    T_DOUBLE: QVariantStreamReader.read_f64,
    T_FLOAT: QVariantStreamReader.read_f32,
    T_QCHAR: QVariantStreamReader.read_u16,
    T_LONG: QVariantStreamReader.read_i64,
    T_ULONG: QVariantStreamReader.read_u64,
    T_SHORT: QVariantStreamReader.read_i16,
    T_USHORT: QVariantStreamReader.read_u16,
    T_CHAR: QVariantStreamReader.read_i8,
    T_SCHAR: QVariantStreamReader.read_i8,
    T_UCHAR: QVariantStreamReader.read_u8,
    T_VARIANTMAP: QVariantStreamReader.read_variant_map,
    T_VARIANTHASH: QVariantStreamReader.read_variant_map,
    T_VARIANTLIST: QVariantStreamReader.read_variant_list,
    T_QSTRING: QVariantStreamReader.read_qstring,
    T_QSTRINGLIST: QVariantStreamReader.read_qstringlist,
    T_QBYTEARRAY: QVariantStreamReader.read_qbytearray,
    T_QBYTEARRAYLIST: QVariantStreamReader.read_qbytearraylist,
    T_QDATE: QVariantStreamReader.read_qdate,
    T_QTIME: QVariantStreamReader.read_qtime,
    T_QDATETIME: QVariantStreamReader.read_qdatetime,
    T_QURL: QVariantStreamReader.read_qbytearray,
    T_QLOCALE: QVariantStreamReader.read_qlocale,
    T_QRECT: QVariantStreamReader.read_qrect,
    T_QRECTF: QVariantStreamReader.read_qrectf,
    T_QSIZE: QVariantStreamReader.read_qsize,
    T_QSIZEF: QVariantStreamReader.read_qsizef,
    T_QLINE: lambda r: (r.read_qpoint(), r.read_qpoint()),
    T_QLINEF: lambda r: (r.read_qpointf(), r.read_qpointf()),
    T_QPOINT: QVariantStreamReader.read_qpoint,
    T_QPOINTF: QVariantStreamReader.read_qpointf,
    T_QUUID: QVariantStreamReader.read_quuid,
    T_QVARIANT: QVariantStreamReader.read_qvariant,
    T_QJSONDOCUMENT: QVariantStreamReader.read_qbytearray,
    T_QCOLOR: QVariantStreamReader.read_qcolor,
    T_QIMAGE: QVariantStreamReader.read_qimage,
    0x1001: QVariantStreamReader.read_qimage,   # QPixmap is streamed as its QImage
    T_QPOLYGON: QVariantStreamReader.read_qpolygon,
    T_QPOLYGONF: QVariantStreamReader.read_qpolygonf,
    T_QVECTOR2D: lambda r: r.read_floats(2),
    T_QVECTOR3D: lambda r: r.read_floats(3),
    T_QVECTOR4D: lambda r: r.read_floats(4),
    T_QQUATERNION: lambda r: r.read_floats(4),   # scalar, x, y, z
    T_QMATRIX4X4: lambda r: r.read_floats(16),   # row-major
    T_QTRANSFORM: lambda r: tuple(r.read_f64() for _ in range(9)),
}
