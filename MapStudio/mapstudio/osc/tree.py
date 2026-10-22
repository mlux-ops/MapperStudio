"""The OSC address tree: maps MadMapper-style addresses onto the MapStudio project.

Address families follow the MadMapper v4 OSC guide where MapStudio has the feature
(`/surfaces/<sel>/opacity`, `/medias/<sel>/assign`, `/outputs/<sel>/show_test_pattern`,
`/master/master_level`, `/custom/BPM/bpm`); v6-style additions (`soft_edge/*`, `fx/*`) use the
same naming rules (lower case, hyphens and spaces to underscores).

`<sel>` is `selected`, a numeric id, or the object's name (spaces may be written as `_`).
A message without arguments is a query: the current value is sent back to the sender.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from ..model import Project, QuadSurface, Output, Visual, VisualKind, BlendMode
from .protocol import OscMessage


@dataclass
class OscEntry:
    pattern: str
    kind: str          # f (0..1 float), b (bool), i (int), s (string), n (no argument), v (value)
    doc: str


ADDRESS_DOC: list[OscEntry] = [
    OscEntry("/surfaces/<sel>/opacity", "f", "0..1"),
    OscEntry("/surfaces/<sel>/visible", "b", ""),
    OscEntry("/surfaces/<sel>/locked", "b", ""),
    OscEntry("/surfaces/<sel>/color/red|green|blue", "f", "0..1"),
    OscEntry("/surfaces/<sel>/color/rgba", "v", "r g b a"),
    OscEntry("/surfaces/<sel>/blend_mode", "i", "0 ignore alpha, 1 add, 2 over, 3 premultiplied, 4 multiply, 5 subtract"),
    OscEntry("/surfaces/<sel>/output/x|y", "f", "stage units (centre)"),
    OscEntry("/surfaces/<sel>/output/handles/<n>/x|y", "f", "stage units, corner n (0 BL, 1 BR, 2 TR, 3 TL)"),
    OscEntry("/surfaces/<sel>/input/x|y", "f", "0..1 (input rectangle centre)"),
    OscEntry("/surfaces/<sel>/input/scale", "f", "0..10 (input rectangle size, 1 = whole media)"),
    OscEntry("/surfaces/<sel>/input/flip", "s", "No, X, Y, XY"),
    OscEntry("/surfaces/<sel>/visual/number", "i", "index in the media list"),
    OscEntry("/surfaces/<sel>/visual/name", "s", "media name"),
    OscEntry("/surfaces/<sel>/soft_edge/active", "b", ""),
    OscEntry("/surfaces/<sel>/soft_edge/left|right|top|bottom", "f", "0..1"),
    OscEntry("/surfaces/<sel>/fx_active", "b", ""),
    OscEntry("/surfaces/<sel>/fx/<param>", "v", "FX parameter by label or input name"),
    OscEntry("/surfaces/<sel>/mask/inverted", "b", ""),
    OscEntry("/surfaces/<sel>/mask/feather", "f", "0..0.25"),
    OscEntry("/medias/select", "i", "index in the media list"),
    OscEntry("/medias/next | /medias/previous", "n", ""),
    OscEntry("/medias/<sel>/select", "b", ""),
    OscEntry("/medias/<sel>/assign", "n", "assign to the selected surface"),
    OscEntry("/medias/<sel>/assign_to_all_surfaces", "n", ""),
    OscEntry("/medias/<sel>/restart", "n", "materials: restart time"),
    OscEntry("/medias/<sel>/play_forward | pause | loop", "b", "movies"),
    OscEntry("/medias/<sel>/play_speed", "f", "0..4"),
    OscEntry("/medias/<sel>/<param>", "v", "material parameter by label or input name"),
    OscEntry("/outputs/<sel>/enabled", "b", ""),
    OscEntry("/outputs/<sel>/show_test_pattern", "b", ""),
    OscEntry("/outputs/<sel>/fullscreen", "b", ""),
    OscEntry("/master/master_level", "f", "0..1"),
    OscEntry("/master/bpm | /custom/BPM/bpm", "f", "20..400"),
    OscEntry("/application/view/fullscreen", "b", "all outputs"),
]


class OscTree:
    """Dispatches OSC messages to a host object exposing the project and UI hooks.

    The host must provide: `project`, `selected_surface()`, `select_surface(s)`, `select_visual(v)`,
    `set_output_fullscreen(o, bool)`, `after_osc_change()` (refresh views) and `reply(address, args)`.
    """

    def __init__(self, host: Any):
        self.host = host

    # ---- public ----
    def dispatch(self, msg: OscMessage, reply: Callable[[str, list], None] | None = None) -> bool:
        parts = [p for p in msg.address.split("/") if p]
        if not parts:
            return False
        args = list(msg.args)
        query = len(args) == 0
        handled = False
        value = None
        try:
            if parts[0] == "surfaces":
                handled, value = self._surfaces(parts[1:], args, query)
            elif parts[0] in ("medias", "media"):
                handled, value = self._medias(parts[1:], args, query)
            elif parts[0] == "outputs":
                handled, value = self._outputs(parts[1:], args, query)
            elif parts[0] == "master":
                handled, value = self._master(parts[1:], args, query)
            elif parts[0] == "custom" and parts[1:3] == ["BPM", "bpm"]:
                handled, value = self._master(["bpm"], args, query)
            elif parts[0] == "application":
                handled, value = self._application(parts[1:], args, query)
        except (IndexError, ValueError, TypeError) as exc:
            raise ValueError(f"bad arguments for {msg.address}: {exc}") from exc
        if handled:
            if query and reply is not None and value is not None:
                reply(msg.address, value if isinstance(value, list) else [value])
            elif not query:
                self.host.after_osc_change()
        return handled

    @staticmethod
    def documentation() -> list[OscEntry]:
        return list(ADDRESS_DOC)

    # ---- resolution helpers ----
    @staticmethod
    def _norm(name: str) -> str:
        return re.sub(r"[\s\-]+", "_", name.strip()).lower()

    def _find(self, items: list, sel: str, selected: Any):
        if sel == "selected":
            return selected
        if sel.isdigit():
            for it in items:
                if it.id == int(sel):
                    return it
        key = self._norm(sel)
        for it in items:
            if it.name == sel or self._norm(it.name) == key:
                return it
        return None

    # ---- families ----
    def _surfaces(self, parts: list[str], args: list, query: bool) -> tuple[bool, Any]:
        p: Project = self.host.project
        if not parts:
            return False, None
        s: QuadSurface | None = self._find(p.surfaces, parts[0], self.host.selected_surface())
        if s is None:
            return False, None
        rest = parts[1:]
        if not rest:
            return False, None
        key = rest[0]
        if key == "opacity":
            if query:
                return True, float(s.opacity)
            s.opacity = _unit(args[0])
        elif key == "visible":
            if query:
                return True, s.visible
            s.visible = _bool(args[0])
        elif key == "locked":
            if query:
                return True, s.locked
            s.locked = _bool(args[0])
        elif key == "select":
            if query:
                return True, s is self.host.selected_surface()
            if _bool(args[0]):
                self.host.select_surface(s)
        elif key == "color" and len(rest) >= 2:
            ch = rest[1]
            r, g, b = s.color
            if ch == "rgba":
                if query:
                    return True, [r, g, b, float(s.opacity)]
                vals = [_unit(a) for a in args[:4]]
                s.color = (vals[0], vals[1], vals[2])
                if len(vals) == 4:
                    s.opacity = vals[3]
            else:
                idx = {"red": 0, "green": 1, "blue": 2}.get(ch)
                if idx is None:
                    return False, None
                if query:
                    return True, float(s.color[idx])
                c = list(s.color)
                c[idx] = _unit(args[0])
                s.color = (c[0], c[1], c[2])
        elif key == "blend_mode":
            if query:
                return True, int(s.blend_mode)
            s.blend_mode = BlendMode(max(0, min(8, int(args[0]))))
        elif key == "output" and len(rest) >= 2:
            sub = rest[1]
            cx, cy = s.centre()
            if sub in ("x", "y"):
                if query:
                    return True, float(cx if sub == "x" else cy)
                v = float(args[0])
                s.move(v - cx if sub == "x" else 0.0, v - cy if sub == "y" else 0.0)
            elif sub == "handles" and len(rest) >= 4:
                n = int(rest[2])
                if not (0 <= n < len(s.corners)):
                    return False, None
                axis = 0 if rest[3] == "x" else 1
                if query:
                    return True, float(s.corners[n][axis])
                c = list(s.corners[n])
                c[axis] = float(args[0])
                s.corners[n] = (c[0], c[1])
                if s.warp_points:
                    s.warp_points = []
                    s.warp_cols = s.warp_rows = 0
            else:
                return False, None
        elif key == "input" and len(rest) >= 2:
            sub = rest[1]
            us = [u for u, _ in s.uv_corners]
            vs = [v for _, v in s.uv_corners]
            ucx, ucy = (min(us) + max(us)) / 2, (min(vs) + max(vs)) / 2
            w, h = max(us) - min(us), max(vs) - min(vs)
            if sub in ("x", "y"):
                if query:
                    return True, float(ucx if sub == "x" else ucy)
                v = float(args[0])
                dx = v - ucx if sub == "x" else 0.0
                dy = v - ucy if sub == "y" else 0.0
                s.uv_corners = [(u + dx, vv + dy) for u, vv in s.uv_corners]
            elif sub == "scale":
                if query:
                    return True, float(max(w, h))
                sc = max(1e-3, float(args[0]))
                hw, hh = sc / 2, sc / 2
                s.uv_corners = [(ucx - hw, ucy - hh), (ucx + hw, ucy - hh), (ucx + hw, ucy + hh), (ucx - hw, ucy + hh)][:len(s.uv_corners)]
            elif sub == "flip":
                if query:
                    return True, {(False, False): "No", (True, False): "X", (False, True): "Y", (True, True): "XY"}[(s.flip_h, s.flip_v)]
                mode = str(args[0]).upper() if isinstance(args[0], str) else {0: "NO", 1: "X", 2: "Y", 3: "XY"}.get(int(args[0]), "NO")
                s.flip_h, s.flip_v = "X" in mode, "Y" in mode
            else:
                return False, None
        elif key == "visual" and len(rest) >= 2:
            sub = rest[1]
            if sub == "number":
                if query:
                    ids = [v.id for v in p.visuals]
                    return True, ids.index(s.visual_id) if s.visual_id in ids else -1
                n = int(args[0])
                if 0 <= n < len(p.visuals):
                    s.visual_id = p.visuals[n].id
            elif sub == "name":
                if query:
                    v = p.visual(s.visual_id)
                    return True, v.name if v else ""
                v = self._find(p.visuals, str(args[0]), None)
                if v is not None:
                    s.visual_id = v.id
            else:
                return False, None
        elif key == "soft_edge" and len(rest) >= 2:
            sub = rest[1]
            se = s.soft_edge
            if sub == "active":
                if query:
                    return True, se.active
                se.active = _bool(args[0])
            elif sub in ("left", "right", "top", "bottom"):
                if query:
                    return True, float(getattr(se, sub))
                setattr(se, sub, _unit(args[0]))
            else:
                return False, None
        elif key == "fx_active":
            if query:
                return True, s.fx_active
            s.fx_active = _bool(args[0])
        elif key == "fx" and len(rest) >= 2:
            pname = "/".join(rest[1:])
            fx = self.host.engine.fx_renderers.get(s.id) if s.fx_active else None
            mat = fx.material if fx is not None else None
            inp = None
            if mat is not None:
                inp = mat.input(pname) or mat.input_by_label(pname) or next(
                    (i for i in mat.inputs if self._norm(i.label) == self._norm(pname) or self._norm(i.name) == self._norm(pname)), None)
            if inp is None:
                return False, None
            if query:
                return True, _osc_value(mat.values.get(inp.name))
            mat.set_value(inp.name, _coerce_for(inp, args))
            s.fx_params[inp.name] = mat.values[inp.name]
        elif key == "mask" and len(rest) >= 2:
            if rest[1] == "inverted":
                if query:
                    return True, s.mask_inverted
                s.mask_inverted = _bool(args[0])
            elif rest[1] == "feather":
                if query:
                    return True, float(s.mask_feather)
                s.mask_feather = max(0.0, min(0.25, float(args[0])))
            else:
                return False, None
        else:
            return False, None
        return True, None

    def _medias(self, parts: list[str], args: list, query: bool) -> tuple[bool, Any]:
        p: Project = self.host.project
        if not parts:
            return False, None
        if parts[0] == "select" and len(parts) == 1:
            if query:
                v = self.host.selected_visual()
                return True, [x.id for x in p.visuals].index(v.id) if v and v in p.visuals else -1
            n = int(args[0])
            if 0 <= n < len(p.visuals):
                self.host.select_visual(p.visuals[n])
            return True, None
        if parts[0] in ("next", "previous") and len(parts) == 1:
            if not p.visuals:
                return True, None
            cur = self.host.selected_visual()
            idx = p.visuals.index(cur) if cur in p.visuals else -1
            idx = (idx + (1 if parts[0] == "next" else -1)) % len(p.visuals)
            self.host.select_visual(p.visuals[idx])
            return True, None
        v: Visual | None = self._find(p.visuals, parts[0], self.host.selected_visual())
        if v is None or len(parts) < 2:
            return False, None
        key = parts[1]
        if key == "select":
            if query:
                return True, v is self.host.selected_visual()
            if _bool(args[0]):
                self.host.select_visual(v)
            return True, None
        if key == "assign":
            s = self.host.selected_surface()
            if s is not None:
                s.visual_id = v.id
            return True, None
        if key == "assign_to_all_surfaces":
            for s in p.surfaces:
                s.visual_id = v.id
            return True, None
        src = self.host.engine.sources.get(v.id)
        if key == "restart":
            mat = getattr(src, "material", None)
            if mat is not None:
                mat.restart()
            return True, None
        if v.kind == VisualKind.MOVIE and key in ("play_forward", "pause", "loop", "play_speed"):
            player = getattr(src, "player", None)
            if key == "loop":
                if query:
                    return True, v.loop
                v.loop = _bool(args[0])
                if src is not None:
                    src.apply_attributes()
            elif key == "play_speed":
                if query:
                    return True, float(v.speed)
                v.speed = max(0.0, min(4.0, float(args[0])))
                if src is not None:
                    src.apply_attributes()
            elif player is not None:
                if query:
                    return True, player.isPlaying() if key == "play_forward" else not player.isPlaying()
                on = _bool(args[0])
                if key == "play_forward":
                    player.play() if on else player.pause()
                else:
                    player.pause() if on else player.play()
            return True, None
        mat = getattr(src, "material", None)
        if mat is not None:
            pname = "/".join(parts[1:])
            inp = mat.input(pname) or mat.input_by_label(pname) or next(
                (i for i in mat.inputs if self._norm(i.label) == self._norm(pname) or self._norm(i.name) == self._norm(pname)), None)
            if inp is not None:
                if query:
                    return True, _osc_value(mat.values.get(inp.name))
                src.set_parameter(inp.name, _coerce_for(inp, args))
                return True, None
        if v.kind == VisualKind.SOLID and key == "color":
            if query:
                return True, list(v.attributes.get("color", [1, 1, 1, 1]))
            v.attributes["color"] = [_unit(a) for a in args[:4]] + [1.0] * max(0, 4 - len(args))
            if src is not None:
                src.apply_attributes()
            return True, None
        return False, None

    def _outputs(self, parts: list[str], args: list, query: bool) -> tuple[bool, Any]:
        p: Project = self.host.project
        if len(parts) < 2:
            return False, None
        o: Output | None = self._find(p.outputs, parts[0], self.host.selected_output())
        if o is None:
            return False, None
        key = parts[1]
        if key == "enabled":
            if query:
                return True, o.active
            o.active = _bool(args[0])
        elif key == "show_test_pattern":
            if query:
                return True, o.test_pattern
            o.test_pattern = _bool(args[0])
        elif key == "fullscreen":
            if query:
                return True, self.host.is_output_fullscreen(o)
            self.host.set_output_fullscreen(o, _bool(args[0]))
        elif key in ("x", "y"):
            if query:
                return True, float(o.centre[0] if key == "x" else o.centre[1])
            v = float(args[0])
            o.centre = (v, o.centre[1]) if key == "x" else (o.centre[0], v)
        else:
            return False, None
        return True, None

    def _master(self, parts: list[str], args: list, query: bool) -> tuple[bool, Any]:
        p: Project = self.host.project
        if not parts:
            return False, None
        key = parts[0]
        if key in ("master_level", "master_video_level"):
            if query:
                return True, float(p.master_level)
            p.master_level = _unit(args[0])
        elif key == "bpm":
            if query:
                return True, float(p.bpm)
            p.bpm = max(20.0, min(400.0, float(args[0])))
        else:
            return False, None
        return True, None

    def _application(self, parts: list[str], args: list, query: bool) -> tuple[bool, Any]:
        if parts[:2] == ["view", "fullscreen"]:
            if query:
                return True, any(self.host.is_output_fullscreen(o) for o in self.host.project.outputs)
            on = _bool(args[0])
            for o in self.host.project.outputs:
                if not o.is_buffer:
                    self.host.set_output_fullscreen(o, on)
            return True, None
        return False, None


# ---- value helpers ------------------------------------------------------------------------------

def _bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v > 0
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "on", "yes")
    return bool(v)


def _unit(v: Any) -> float:
    return max(0.0, min(1.0, float(v)))


def _osc_value(v: Any) -> Any:
    if isinstance(v, (list, tuple)):
        return [float(x) for x in v]
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float, str)):
        return v
    return str(v)


def _coerce_for(inp, args: list) -> Any:
    from ..isf.inputs import InputType
    t = inp.type
    if t in (InputType.COLOR, InputType.POINT2D, InputType.POINT3D, InputType.POINT4D, InputType.FLOAT_RANGE):
        return [float(a) for a in args]
    if t in (InputType.BOOL, InputType.EVENT):
        return _bool(args[0])
    if t == InputType.LONG:
        return args[0]
    if t == InputType.INT:
        return int(float(args[0]))
    return float(args[0]) if not isinstance(args[0], str) else args[0]
