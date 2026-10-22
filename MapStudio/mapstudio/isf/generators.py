"""CPU-side GENERATORS of the MadMapper ISF dialect.

A generator produces one float uniform per frame from other inputs.  Parameter values are
either literals or the *name* of an INPUT / another generator (then the value is read each
frame).  Semantics follow the Materials guide; where the guide is silent the behaviour is our
own reading and is marked as such.

Supported types: time_base, animator, multiplier, incrementer, pass_thru, damper,
transition_damper, damper_array (as a single damper), adsr, linear_filter, ease_filter, shaper.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Callable

from .header import IsfError

_QUANTISED = [1 / 64, 1 / 32, 1 / 16, 1 / 8, 1 / 4, 1 / 2, 1, 2, 4, 8, 16, 32]


@dataclass
class GeneratorContext:
    """Per-frame data shared by all generators of a material."""
    time: float = 0.0         # seconds since the material started
    dt: float = 1 / 60        # seconds since the previous frame
    bpm: float = 120.0
    values: dict[str, Any] = field(default_factory=dict)   # current input values by name (+ generator outputs)
    channels: dict[str, float] = field(default_factory=dict)  # "/custom/BPM/bpm" style channel values


class Param:
    """A generator parameter: literal or bound to a named input/generator/channel."""

    def __init__(self, raw: Any, kind: str, default: Any):
        self.kind = kind
        self.ref: str | None = None
        self.literal: Any = default
        if raw is None:
            return
        if isinstance(raw, str) and kind != "enum":
            self.ref = raw
        elif kind == "enum":
            if isinstance(raw, str):
                self.literal = raw
            else:
                raise IsfError(f"parameter should be a string")
        elif kind == "bool":
            if isinstance(raw, bool):
                self.literal = raw
            elif isinstance(raw, (int, float)):
                self.literal = raw > 0
            else:
                raise IsfError("parameter should be a boolean or a string (if the parameter should be controlled by another input/generated/channel)")
        else:
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise IsfError("parameter should be a number or a string (if the parameter should be controlled by another input/generated/channel)")
            self.literal = float(raw)

    def get(self, ctx: GeneratorContext) -> Any:
        if self.ref is None:
            return self.literal
        if self.ref.startswith("/"):
            return ctx.channels.get(self.ref, 0.0)
        v = ctx.values.get(self.ref, self.literal)
        if self.kind == "bool":
            return bool(v) if not isinstance(v, (list, tuple)) else bool(v[0])
        if self.kind == "number":
            if isinstance(v, bool):
                return 1.0 if v else 0.0
            if isinstance(v, (list, tuple)):
                return float(v[0]) if v else 0.0
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0
        return v


class Generator:
    name: str
    type_name: str = ""
    params: dict[str, tuple[str, Any]] = {}   # param -> (kind, default)

    def __init__(self, name: str, raw_params: dict[str, Any]):
        self.name = name
        self.value = 0.0
        self.p: dict[str, Param] = {}
        for key, raw in raw_params.items():
            if key not in self.params:
                raise IsfError(f"Object of type {self.type_name} has no parameter {key}")
        for key, (kind, default) in self.params.items():
            try:
                self.p[key] = Param(raw_params.get(key), kind, default)
            except IsfError as exc:
                raise IsfError(f"Error parsing generated {name}: parameter {key} {exc}") from exc

    def update(self, ctx: GeneratorContext) -> float:  # pragma: no cover - overridden
        return self.value

    def reset(self) -> None:
        self.value = 0.0


def _apply_speed_curve(speed: float, curve: float) -> float:
    if curve in (0, 1) or speed == 0:
        return speed
    return math.copysign(abs(speed) ** curve, speed)


class TimeBase(Generator):
    """`output += speed * elapsed`, with speed_curve, reverse, strob, bpm_sync and
    link_speed_to_global_bpm as described in the Materials guide."""
    type_name = "time_base"
    params = {"speed": ("number", 1.0), "reverse": ("bool", False), "speed_curve": ("number", 1.0),
              "strob": ("number", 0.0), "bpm_sync": ("bool", False), "link_speed_to_global_bpm": ("bool", False),
              "active": ("bool", True), "reset": ("bool", False)}

    def __init__(self, name: str, raw: dict[str, Any]):
        super().__init__(name, raw)
        self._accum = 0.0
        self._last_strob = -1e9

    def effective_speed(self, ctx: GeneratorContext) -> float:
        speed = _apply_speed_curve(self.p["speed"].get(ctx), self.p["speed_curve"].get(ctx))
        if self.p["reverse"].get(ctx):
            speed = -speed
        if self.p["bpm_sync"].get(ctx):
            q = min(_QUANTISED, key=lambda c: abs(c - abs(speed))) if speed != 0 else 0.0
            speed = math.copysign(q, speed) * ctx.bpm / 60.0
        elif self.p["link_speed_to_global_bpm"].get(ctx):
            speed = speed * ctx.bpm / 120.0
        return speed

    def update(self, ctx: GeneratorContext) -> float:
        if self.p["reset"].get(ctx):
            self._accum = 0.0
        if self.p["active"].get(ctx):
            self._accum += self.effective_speed(ctx) * ctx.dt
        strob = self.p["strob"].get(ctx)
        if strob > 0:
            period = strob
            if self.p["bpm_sync"].get(ctx):
                period = strob * 60.0 / max(ctx.bpm, 1e-6)
            if ctx.time - self._last_strob >= period:
                self._last_strob = ctx.time
                self.value = self._accum
        else:
            self.value = self._accum
        return self.value

    def reset(self) -> None:
        self.value = self._accum = 0.0


class Animator(TimeBase):
    """A time base whose phase is shaped: Smooth, In, Out, Linear, Cut, Noise (guide list),
    plus "Smooth In" seen in the shipped shaders (our reading: eased ramp)."""
    type_name = "animator"
    params = dict(TimeBase.params, **{"shape": ("enum", "Smooth"), "max_value": ("number", 1.0)})

    def __init__(self, name: str, raw: dict[str, Any]):
        super().__init__(name, raw)
        self._noise_seed = random.Random(hash(name) & 0xFFFF)
        self._noise_a = self._noise_seed.random()
        self._noise_b = self._noise_seed.random()
        self._noise_cycle = -1

    def update(self, ctx: GeneratorContext) -> float:
        phase_total = TimeBase.update(self, ctx)
        shape = self.p["shape"].get(ctx)
        if isinstance(shape, (int, float)) and not isinstance(shape, bool):
            shape = ["Smooth", "In", "Linear", "Cut", "Noise", "Smooth In", "Out"][int(shape) % 7]
        t = phase_total - math.floor(phase_total)
        if shape == "Smooth":
            v = 0.5 - 0.5 * math.cos(2 * math.pi * t)
        elif shape == "In":
            v = t
        elif shape == "Out":
            v = 1.0 - t
        elif shape == "Linear":
            v = 1.0 - abs(2 * t - 1)
        elif shape == "Cut":
            v = 0.0 if t < 0.5 else 1.0
        elif shape == "Smooth In":
            v = 0.5 - 0.5 * math.cos(math.pi * t)
        elif shape == "Noise":
            cycle = math.floor(phase_total)
            if cycle != self._noise_cycle:
                self._noise_cycle = cycle
                self._noise_a, self._noise_b = self._noise_b, self._noise_seed.random()
            s = t * t * (3 - 2 * t)
            v = self._noise_a + (self._noise_b - self._noise_a) * s
        else:
            v = t
        self.value = v * self.p["max_value"].get(ctx)
        return self.value


class Multiplier(Generator):
    """Product of value1..value4 (missing ones default to 1), optionally times input_value."""
    type_name = "multiplier"
    params = {"input_value": ("number", 1.0), "value1": ("number", 1.0), "value2": ("number", 1.0),
              "value3": ("number", 1.0), "value4": ("number", 1.0)}

    def update(self, ctx: GeneratorContext) -> float:
        self.value = 1.0
        for k in self.params:
            self.value *= self.p[k].get(ctx)
        return self.value


class Incrementer(Generator):
    """Counts `increment` button presses up and `decrement` down; `reset` zeroes;
    wraps at max_value when it is > 0 (our reading)."""
    type_name = "incrementer"
    params = {"increment": ("bool", False), "decrement": ("bool", False), "reset": ("bool", False),
              "max_value": ("number", 0.0), "step": ("number", 1.0)}

    def __init__(self, name: str, raw: dict[str, Any]):
        super().__init__(name, raw)
        self._prev_inc = self._prev_dec = False

    def update(self, ctx: GeneratorContext) -> float:
        inc, dec = self.p["increment"].get(ctx), self.p["decrement"].get(ctx)
        step = self.p["step"].get(ctx)
        if inc and not self._prev_inc:
            self.value += step
        if dec and not self._prev_dec:
            self.value -= step
        self._prev_inc, self._prev_dec = inc, dec
        if self.p["reset"].get(ctx):
            self.value = 0.0
        mx = self.p["max_value"].get(ctx)
        if mx > 0:
            self.value %= mx
        return self.value


class PassThru(Generator):
    type_name = "pass_thru"
    params = {"input_value": ("number", 0.0)}

    def update(self, ctx: GeneratorContext) -> float:
        self.value = self.p["input_value"].get(ctx)
        return self.value


class Damper(Generator):
    """Spring/damper follower: hardness pulls towards the input, damping bleeds velocity."""
    type_name = "damper"
    params = {"input_value": ("number", 0.0), "hardness": ("number", 0.1), "damping": ("number", 0.8)}

    def __init__(self, name: str, raw: dict[str, Any]):
        super().__init__(name, raw)
        self._vel = 0.0

    def update(self, ctx: GeneratorContext) -> float:
        target = self.p["input_value"].get(ctx)
        hardness = max(0.0, self.p["hardness"].get(ctx))
        damping = min(1.0, max(0.0, self.p["damping"].get(ctx)))
        steps = max(1, int(ctx.dt * 60))
        for _ in range(steps):
            self._vel += (target - self.value) * hardness
            self._vel *= damping
            self.value += self._vel
        return self.value


class TransitionDamper(Damper):
    type_name = "transition_damper"


class DamperArray(Damper):
    type_name = "damper_array"


class Adsr(Generator):
    """Attack / decay / release follower as described in the Materials guide.

    The guide prints the rate as `10pow(1-(0.01+attack*0.99),3) * elapsedSeconds` and states that
    0 reacts immediately while 1 "needs 10 seconds to go from 0 to 1"; the reading that matches
    both statements is `rate = 10 ** (1 - 2 * (0.01 + x * 0.99))` units per second (0.1/s at 1,
    about 9.5/s at 0)."""
    type_name = "adsr"
    params = {"input_value": ("number", 0.0), "attack": ("number", 0.0), "decay": ("number", 0.0),
              "release": ("number", 0.0)}

    def __init__(self, name: str, raw: dict[str, Any]):
        super().__init__(name, raw)
        self._decay_started: float | None = None

    @staticmethod
    def _rate(x: float) -> float:
        x = min(1.0, max(0.0, x))
        return 10.0 ** (1.0 - 2.0 * (0.01 + x * 0.99))

    def update(self, ctx: GeneratorContext) -> float:
        target = self.p["input_value"].get(ctx)
        if target > self.value:
            self._decay_started = None
            a = self.p["attack"].get(ctx)
            self.value = target if a <= 0 else min(target, self.value + self._rate(a) * ctx.dt)
        elif target < self.value:
            if self._decay_started is None:
                self._decay_started = ctx.time
            if ctx.time - self._decay_started >= self.p["decay"].get(ctx):
                r = self.p["release"].get(ctx)
                self.value = target if r <= 0 else max(target, self.value - self._rate(r) * ctx.dt)
        return self.value


class LinearFilter(Generator):
    """Linear interpolation from the current value to a new input value over `duration`."""
    type_name = "linear_filter"
    params = {"input_value": ("number", 0.0), "duration": ("number", 0.5)}

    def __init__(self, name: str, raw: dict[str, Any]):
        super().__init__(name, raw)
        self._target: float | None = None
        self._start_value = 0.0
        self._start_time = 0.0

    def _shape(self, t: float) -> float:
        return t

    def update(self, ctx: GeneratorContext) -> float:
        target = self.p["input_value"].get(ctx)
        if self._target is None:
            self._target = target
            self.value = target
            return self.value
        if target != self._target:
            self._target = target
            self._start_value = self.value
            self._start_time = ctx.time
        dur = self.p["duration"].get(ctx)
        if dur <= 0:
            self.value = target
        else:
            t = min(1.0, (ctx.time - self._start_time) / dur)
            self.value = self._start_value + (target - self._start_value) * self._shape(t)
        return self.value


class EaseFilter(LinearFilter):
    type_name = "ease_filter"
    params = dict(LinearFilter.params, type=("enum", "EaseInOut"))

    def _shape(self, t: float) -> float:
        kind = self.p["type"].literal
        if kind == "EaseIn":
            return t * t
        if kind == "EaseOut":
            return 1 - (1 - t) * (1 - t)
        return 0.5 - 0.5 * math.cos(math.pi * t)


class Shaper(Generator):
    """Maps an input through a wave shape (our reading of the undocumented `shaper`)."""
    type_name = "shaper"
    params = {"input_value": ("number", 0.0), "shape": ("enum", "Smooth"), "max_value": ("number", 1.0)}

    def update(self, ctx: GeneratorContext) -> float:
        x = self.p["input_value"].get(ctx)
        t = x - math.floor(x)
        shape = self.p["shape"].get(ctx)
        if shape == "Smooth":
            v = 0.5 - 0.5 * math.cos(2 * math.pi * t)
        elif shape == "Linear":
            v = 1.0 - abs(2 * t - 1)
        elif shape == "Cut":
            v = 0.0 if t < 0.5 else 1.0
        elif shape == "Out":
            v = 1.0 - t
        else:
            v = t
        self.value = v * self.p["max_value"].get(ctx)
        return self.value


REGISTRY: dict[str, type[Generator]] = {
    "time_base": TimeBase, "animator": Animator, "multiplier": Multiplier, "incrementer": Incrementer,
    "pass_thru": PassThru, "damper": Damper, "transition_damper": TransitionDamper, "damper_array": DamperArray,
    "adsr": Adsr, "linear_filter": LinearFilter, "ease_filter": EaseFilter, "shaper": Shaper,
}


def build_generator(spec: dict[str, Any]) -> Generator:
    cls = REGISTRY.get(spec["TYPE"])
    if cls is None:
        raise IsfError(f"Unknown generator type: {spec['TYPE']}")
    return cls(spec["NAME"], spec.get("PARAMS", {}))
