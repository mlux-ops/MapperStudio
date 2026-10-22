"""ISF INPUT declarations (MadMapper dialect) and their validation.

The rules follow the recovered parser behaviour documented in `03-materials-isf.md`
(`FUN_1406c6980`): which keys are read, defaults, range checks, required keys per type and
the FLAGS set.  Error texts are our own but describe the same conditions.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class InputType(str, Enum):
    FLOAT = "float"
    INT = "int"
    BOOL = "bool"
    EVENT = "event"
    COLOR = "color"
    LONG = "long"
    POINT2D = "point2D"
    POINT3D = "point3D"
    POINT4D = "point4D"
    FLOAT_RANGE = "floatRange"
    IMAGE = "image"
    IMAGE_CUBE = "imageCube"
    IMAGE_3D = "image3D"
    STRING = "string"
    CURVE = "curve"
    FLOAT_VECTOR = "float_vector"
    INT_VECTOR = "int_vector"
    STRING_VECTOR = "string_vector"
    AUDIO = "audio"
    AUDIO_FFT = "audioFFT"
    MAT4 = "mat4"


_ALIASES = {"double": "float", "vec2": "point2D", "ivec2": "point2D", "usampler2D": "image",
            "polylines": "image", "array": "mat4"}

FLAG_NAMES = {"button", "button_grid", "no_alpha", "generate_as_define"}


class InputError(ValueError):
    pass


@dataclass
class IsfInput:
    name: str
    type: InputType
    label: str = ""
    description: str = ""
    default: Any = None
    min: Any = None
    max: Any = None
    values: list[Any] = field(default_factory=list)   # long: option values
    labels: list[str] = field(default_factory=list)   # long: option labels
    flags: set[str] = field(default_factory=set)
    order_index: int = -1
    meta: dict[str, Any] = field(default_factory=dict)
    interpolation: str = "linear"
    display_x_range: tuple[float, float] | None = None
    display_y_range: tuple[float, float] | None = None
    internal: bool = False
    min_filter: str = "LINEAR"
    mag_filter: str = "LINEAR"
    wrap: str = "CLAMP_TO_EDGE"

    @property
    def group(self) -> str:
        return self.label.rsplit("/", 1)[0] if "/" in self.label else ""

    @property
    def short_label(self) -> str:
        return self.label.rsplit("/", 1)[-1] if self.label else self.name

    @property
    def is_texture(self) -> bool:
        return self.type in (InputType.IMAGE, InputType.IMAGE_CUBE, InputType.IMAGE_3D)

    @property
    def is_sampler(self) -> bool:
        """Inputs exposed to GLSL as a sampler: images, audio buffers and curves (a 1-row lookup texture)."""
        return self.is_texture or self.type in (InputType.AUDIO, InputType.AUDIO_FFT, InputType.CURVE)

    @property
    def glsl_type(self) -> str:
        return {
            InputType.FLOAT: "float", InputType.INT: "int", InputType.BOOL: "bool", InputType.EVENT: "bool",
            InputType.COLOR: "vec4", InputType.LONG: "int", InputType.POINT2D: "vec2", InputType.FLOAT_RANGE: "vec2",
            InputType.POINT3D: "vec3", InputType.POINT4D: "vec4", InputType.MAT4: "mat4",
            InputType.IMAGE: "sampler2D", InputType.IMAGE_CUBE: "samplerCube", InputType.IMAGE_3D: "sampler3D",
            InputType.AUDIO: "sampler2D", InputType.AUDIO_FFT: "sampler2D", InputType.CURVE: "sampler2D",
            InputType.STRING: "", InputType.FLOAT_VECTOR: "", InputType.INT_VECTOR: "",
            InputType.STRING_VECTOR: "",
        }[self.type]

    def long_index(self, value: Any) -> int:
        """Map a `long` value (option value, label, or index) to its index."""
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            i = int(value)
            if 0 <= i < len(self.values):
                return i
        if value in self.values:
            return self.values.index(value)
        if value in self.labels:
            return self.labels.index(value)
        return self.long_index(self.default) if value is not self.default else 0

    def coerce(self, value: Any) -> Any:
        """Clamp / convert a user-supplied value into the input's domain."""
        t = self.type
        try:
            if t in (InputType.FLOAT, InputType.INT):
                v = float(value)
                if self.min is not None:
                    v = max(float(self.min), v)
                if self.max is not None:
                    v = min(float(self.max), v)
                return int(round(v)) if t == InputType.INT else v
            if t in (InputType.BOOL, InputType.EVENT):
                return _to_bool(value)
            if t == InputType.LONG:
                return self.long_index(value)
            if t == InputType.COLOR:
                c = [float(x) for x in value]
                if len(c) == 3:
                    c.append(1.0)
                if len(c) != 4:
                    raise InputError("colour needs 3 or 4 components")
                return [min(1.0, max(0.0, x)) for x in c]
            if t in (InputType.POINT2D, InputType.FLOAT_RANGE, InputType.POINT3D, InputType.POINT4D):
                n = {InputType.POINT2D: 2, InputType.FLOAT_RANGE: 2, InputType.POINT3D: 3, InputType.POINT4D: 4}[t]
                c = [float(x) for x in value]
                if len(c) != n:
                    raise InputError(f"{t.value} needs {n} components")
                if self.min is not None and self.max is not None:
                    mins = self.min if isinstance(self.min, list) else [self.min] * n
                    maxs = self.max if isinstance(self.max, list) else [self.max] * n
                    c = [min(float(hi), max(float(lo), x)) for x, lo, hi in zip(c, mins, maxs)]
                return c
        except (TypeError, ValueError) as exc:
            raise InputError(f"input {self.name}: cannot use {value!r}: {exc}") from exc
        return value


def _to_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v > 0
    if isinstance(v, str):
        if v.lower() in ("true", "1"):
            return True
        if v.lower() in ("false", "0", ""):
            return False
    raise InputError(f"bool attribute default value is invalid: {v!r}")


def _num(v: Any, what: str, name: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise InputError(f"Error in ISF INPUT {name}: {what} must be a number")
    return float(v)


def _numlist(v: Any, n: int, what: str, name: str, tname: str) -> list[float]:
    if not isinstance(v, list) or len(v) != n or any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in v):
        words = {2: "two", 3: "three", 4: "four"}[n]
        raise InputError(f"Error in ISF INPUT {name}: {tname} {what} value must have {words} values")
    return [float(x) for x in v]


def parse_input(item: dict[str, Any]) -> IsfInput:
    name = item.get("NAME")
    if not isinstance(name, str) or not name:
        raise InputError("ISF INPUT without a NAME")
    if not name.replace("_", "a").isalnum() or name[0].isdigit():
        raise InputError(f"ISF INPUT {name!r} is not a valid GLSL identifier")
    tname = item.get("TYPE")
    if not isinstance(tname, str) or not tname:
        raise InputError(f"TYPE not defined for ISF INPUT {name}")
    tname = _ALIASES.get(tname, tname)
    try:
        itype = InputType(tname)
    except ValueError as exc:
        raise InputError(f"Error in ISF input {name}: Unhandled ISF input type \"{tname}\"") from exc

    label = item.get("Label") or item.get("LABEL") or ""
    if not isinstance(label, str):
        label = str(label)
    if label.startswith("/") or label.endswith("/") or "//" in label:
        raise InputError(f"Error in ISF INPUT {name}: invalid label {label!r}")
    flags_raw = item.get("FLAGS", [])
    if isinstance(flags_raw, str):
        flags_raw = [f.strip() for f in flags_raw.split(",") if f.strip()]
    if not isinstance(flags_raw, list) or any(not isinstance(f, str) for f in flags_raw):
        raise InputError(f"Error in ISF INPUT {name}: FLAGS should be an array of strings")
    flags = {f for f in flags_raw if f in FLAG_NAMES}

    inp = IsfInput(name, itype, label, str(item.get("DESCRIPTION", "") or ""), flags=flags,
                   order_index=int(item.get("ORDER_INDEX", -1)) if isinstance(item.get("ORDER_INDEX"), int) else -1,
                   meta=item.get("META") if isinstance(item.get("META"), dict) else {},
                   internal=bool(item.get("MM_INTERNAL", False)))
    inp.min_filter = str(item.get("GL_TEXTURE_MIN_FILTER", "LINEAR"))
    inp.mag_filter = str(item.get("GL_TEXTURE_MAG_FILTER", "LINEAR"))
    inp.wrap = str(item.get("GL_TEXTURE_WRAP", "CLAMP_TO_EDGE"))
    d, mn, mx = item.get("DEFAULT"), item.get("MIN"), item.get("MAX")

    if itype in (InputType.FLOAT, InputType.INT):
        lo = -3.4e38 if itype == InputType.FLOAT else -2147483648
        hi = 3.4e38 if itype == InputType.FLOAT else 2147483647
        inp.default = _num(d, "DEFAULT", name) if d is not None else 0.0
        inp.min = _num(mn, "MIN", name) if mn is not None else lo
        inp.max = _num(mx, "MAX", name) if mx is not None else hi
        if not (inp.min <= inp.default <= inp.max):
            raise InputError(f"Error in ISF INPUT {name}: default value is not in range MIN-MAX")
        if itype == InputType.INT:
            inp.default, inp.min, inp.max = int(inp.default), int(inp.min), int(inp.max)
    elif itype in (InputType.BOOL, InputType.EVENT):
        inp.default = _to_bool(d) if (d is not None and itype == InputType.BOOL) else False
    elif itype == InputType.COLOR:
        if not isinstance(d, list) or len(d) not in (3, 4) or any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in d):
            raise InputError(f"Error in ISF INPUT {name}: default value for a color input must be an array of 3 or 4 value (rgb or rgba)")
        inp.default = [float(x) for x in d] + ([1.0] if len(d) == 3 else [])
    elif itype == InputType.LONG:
        values = item.get("VALUES")
        if not isinstance(values, list) or not values:
            raise InputError(f"Error in ISF Header INPUT {name}: VALUES array is missing")
        if any(not isinstance(v, (str, int, float)) or isinstance(v, bool) for v in values):
            raise InputError(f"Error in ISF Header INPUT {name}: VALUES entry of \"long\" input is invalid")
        labels = item.get("LABELS", values)
        if not isinstance(labels, list) or len(labels) != len(values):
            raise InputError(f"Error in ISF Header INPUT {name}: VALUES and LABELS arrays must have same size")
        inp.values = list(values)
        inp.labels = [str(x) for x in labels]
        if d is None or not isinstance(d, (str, int, float)) or isinstance(d, bool):
            raise InputError(f"Error in ISF INPUT {name} default value of \"long\" input is undefined or invalid")
        if d in values:
            inp.default = values.index(d)
        elif d in inp.labels:
            inp.default = inp.labels.index(d)
        elif isinstance(d, (int, float)) and 0 <= int(d) < len(values):
            inp.default = int(d)
        else:
            raise InputError(f"Error in ISF INPUT {name} default value of \"long\" input is undefined or invalid")
    elif itype in (InputType.POINT2D, InputType.POINT3D, InputType.POINT4D, InputType.FLOAT_RANGE):
        n = {InputType.POINT2D: 2, InputType.FLOAT_RANGE: 2, InputType.POINT3D: 3, InputType.POINT4D: 4}[itype]
        inp.default = _numlist(d, n, "default", name, itype.value) if d is not None else [0.0] * n
        if itype == InputType.FLOAT_RANGE:
            inp.min = _num(mn, "MIN", name) if mn is not None else 0.0
            inp.max = _num(mx, "MAX", name) if mx is not None else 1.0
            if any(not (inp.min <= x <= inp.max) for x in inp.default):
                raise InputError(f"Error in ISF INPUT {name}: default value is not in range MIN-MAX")
        else:
            if (mn is None) != (mx is None):
                raise InputError(f"Error in ISF INPUT {name}: if {itype.value} has MIN or MAX, it must have both")
            if mn is not None:
                inp.min = _numlist(mn, n, "MIN", name, itype.value) if isinstance(mn, list) else [_num(mn, "MIN", name)] * n
                inp.max = _numlist(mx, n, "MAX", name, itype.value) if isinstance(mx, list) else [_num(mx, "MAX", name)] * n
    elif itype == InputType.CURVE:
        inp.default = [float(x) for x in d] if isinstance(d, list) else []
        for key, attr in (("DISPLAY_X_RANGE", "display_x_range"), ("DISPLAY_Y_RANGE", "display_y_range")):
            r = item.get(key)
            if r is not None:
                if not isinstance(r, list) or len(r) != 2:
                    raise InputError(f"Error in ISF INPUT {name}: curve {key} value must have two values")
                if r[0] > r[1]:
                    raise InputError(f"Error in ISF INPUT {name}: curve {key} is invalid (min>max)")
                setattr(inp, attr, (float(r[0]), float(r[1])))
        interp = item.get("INTERPOLATION", "linear")
        if interp not in ("none", "linear", "hermite", "catmull_rom"):
            raise InputError(f"Error in ISF INPUT {name}: invalid INTERPOLATION {interp!r}")
        inp.interpolation = interp
    elif itype in (InputType.STRING,):
        inp.default = str(d) if d is not None else ""
    elif itype in (InputType.STRING_VECTOR, InputType.FLOAT_VECTOR, InputType.INT_VECTOR):
        inp.default = list(d) if isinstance(d, list) else []
    elif itype in (InputType.IMAGE, InputType.IMAGE_CUBE, InputType.IMAGE_3D, InputType.AUDIO, InputType.AUDIO_FFT, InputType.MAT4):
        inp.default = str(d) if isinstance(d, str) else None
    return inp
