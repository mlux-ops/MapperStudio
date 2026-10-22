"""Tests for the Surface FX loader/assembler, the FX importer keys and the OSC address tree."""
from __future__ import annotations

from pathlib import Path

import pytest

from mapstudio.isf.fx import load_fx, assemble_fx
from mapstudio.isf.header import parse_isf_source
from mapstudio.model import Project, VisualKind, Shape
from mapstudio.model.mad_import import import_mad_project
from mapstudio.osc.protocol import OscMessage
from mapstudio.osc.tree import OscTree

FACTORY_FX = Path(r"E:\Games\MadMapperDemo 6.1.8\Resources\FactorySurface2DFX")
SAMPLES = Path(r"E:\Games\MadMapperDemo 6.1.8\Resources\SampleProjects")
needs_fx = pytest.mark.skipif(not FACTORY_FX.is_dir(), reason="MadMapper FX library not installed")
needs_samples = pytest.mark.skipif(not SAMPLES.is_dir(), reason="MadMapper samples not installed")

FX_VS = "void fxVsFunc() { gl_Position = mm_ModelViewProjectionMatrix * vec4(mm_Vertex.xy, 0, 1); }"
FX_FS = '''/* a leading ordinary comment */
/*{ "INPUTS": [ { "NAME": "fx_gain", "TYPE": "float", "DEFAULT": 1.0, "MIN": 0.0, "MAX": 2.0 } ],
    "GENERATORS": [ { "NAME": "fx_time", "TYPE": "time_base", "PARAMS": { "speed": 1.0 } } ] }*/
vec4 fxColorForPixel(vec2 mm_FragNormCoord) { return FX_NORM_PIXEL(mm_FragNormCoord) * fx_gain; }'''


def test_header_after_ordinary_comment_is_found():
    doc = parse_isf_source(FX_FS)
    assert [i.name for i in doc.inputs] == ["fx_gain"]
    assert doc.generators[0]["NAME"] == "fx_time"


def test_fx_assembly_declares_interface(tmp_path: Path):
    doc = parse_isf_source(FX_FS)
    prog = assemble_fx(doc, FX_VS, doc.body, surface_kind="circle")
    for needle in ("in vec4 mm_Vertex;", "uniform mat4 mm_ModelViewProjectionMatrix;", "#define SURFACE_IS_circle 1",
                   "uniform float fx_gain = 1.0;", "uniform float fx_time = 0.0;", "fxVsFunc();"):
        assert needle in prog.vertex, needle
    for needle in ("#define FX_NORM_PIXEL(uv)", "uniform sampler2D inputImage;", "bool mm_composite(",
                   "fxColorForPixel(mm_FragNormCoord)", "#define BlendModeOver 2"):
        assert needle in prog.fragment, needle


def test_fx_folder_loader(tmp_path: Path):
    folder = tmp_path / "MyFx"
    folder.mkdir()
    (folder / "MyFx.fs").write_text(FX_FS, encoding="utf-8")
    (folder / "MyFx.vs").write_text(FX_VS, encoding="utf-8")
    fx = load_fx(folder)
    assert fx.input("fx_gain") is not None and fx.surface_kind == "quad"
    assert fx.set_value_by_label("fx_gain", 0.5) is False   # the input has no label
    fx.set_value("fx_gain", 0.5)
    assert fx.values["fx_gain"] == 0.5
    fx.tick(120.0)
    assert fx.assemble().vertex.startswith("#version 150 core")


@needs_fx
def test_every_factory_fx_assembles():
    for folder in sorted(FACTORY_FX.iterdir()):
        if folder.is_dir() and any(folder.glob("*.vs")):
            fx = load_fx(folder)
            for kind in ("quad", "triangle", "circle"):
                fx.surface_kind = kind
                fx.assemble()


@needs_samples
def test_video_example_imports_rutt_etra_fx():
    p, _ = import_mad_project(SAMPLES / "Video Example.madproject")
    for s in p.surfaces:
        assert s.fx_active and Path(s.fx_name).is_dir() and s.fx_params["__by_label__"] is True
        assert s.fx_params["Line Count"] == 27


class Host:
    def __init__(self, project: Project):
        self.project = project
        self.sel = project.surfaces[0] if project.surfaces else None
        self.vis = None
        self.changes = 0
        self.fullscreen: set[int] = set()

        class Eng:
            sources: dict = {}
            fx_renderers: dict = {}
        self.engine = Eng()

    def selected_surface(self):
        return self.sel

    def select_surface(self, s):
        self.sel = s

    def selected_visual(self):
        return self.vis

    def select_visual(self, v):
        self.vis = v

    def selected_output(self):
        return self.project.outputs[0]

    def is_output_fullscreen(self, o):
        return o.id in self.fullscreen

    def set_output_fullscreen(self, o, on):
        self.fullscreen.add(o.id) if on else self.fullscreen.discard(o.id)

    def after_osc_change(self):
        self.changes += 1


def _project() -> Project:
    p = Project()
    p.add_output("Projector 1")
    tc = p.add_visual(VisualKind.TEST_CARD, "Test Card")
    q = p.add_quad(name="Quad-1")
    q.visual_id = tc.id
    p.add_visual(VisualKind.SOLID, "Solid Color", color=[1, 1, 1, 1])
    return p


def test_osc_surface_addresses():
    p = _project()
    host = Host(p)
    tree = OscTree(host)
    q = p.surfaces[0]
    assert tree.dispatch(OscMessage("/surfaces/selected/opacity", [0.25]))
    assert q.opacity == 0.25
    assert tree.dispatch(OscMessage(f"/surfaces/{q.id}/visible", [0]))
    assert q.visible is False
    assert tree.dispatch(OscMessage("/surfaces/Quad_1/color/red", [0.5]))
    assert q.color[0] == 0.5
    assert tree.dispatch(OscMessage("/surfaces/Quad-1/blend_mode", [1]))
    assert int(q.blend_mode) == 1
    assert tree.dispatch(OscMessage("/surfaces/selected/output/handles/0/x", [-3.0]))
    assert q.corners[0][0] == -3.0
    assert tree.dispatch(OscMessage("/surfaces/selected/soft_edge/left", [0.4]))
    assert q.soft_edge.left == 0.4
    assert tree.dispatch(OscMessage("/surfaces/selected/visual/number", [1]))
    assert q.visual_id == p.visuals[1].id
    assert tree.dispatch(OscMessage("/surfaces/selected/visual/name", ["Test Card"]))
    assert q.visual_id == p.visuals[0].id
    assert not tree.dispatch(OscMessage("/surfaces/selected/nonsense", [1]))
    assert host.changes == 8


def test_osc_queries_reply_with_current_value():
    p = _project()
    tree = OscTree(Host(p))
    replies = []
    assert tree.dispatch(OscMessage("/surfaces/selected/opacity", []), lambda a, args: replies.append((a, args)))
    assert replies == [("/surfaces/selected/opacity", [1.0])]
    assert tree.dispatch(OscMessage("/master/bpm", []), lambda a, args: replies.append((a, args)))
    assert replies[-1] == ("/master/bpm", [120.0])


def test_osc_media_output_master():
    p = _project()
    host = Host(p)
    tree = OscTree(host)
    assert tree.dispatch(OscMessage("/medias/select", [1])) and host.vis is p.visuals[1]
    assert tree.dispatch(OscMessage("/medias/next", [])) and host.vis is p.visuals[0]
    assert tree.dispatch(OscMessage("/medias/Solid_Color/assign", [])) and p.surfaces[0].visual_id == p.visuals[1].id
    assert tree.dispatch(OscMessage("/outputs/Projector_1/show_test_pattern", [True])) and p.outputs[0].test_pattern
    assert tree.dispatch(OscMessage("/outputs/selected/fullscreen", [1])) and p.outputs[0].id in host.fullscreen
    assert tree.dispatch(OscMessage("/application/view/fullscreen", [0])) and not host.fullscreen
    assert tree.dispatch(OscMessage("/master/master_level", [0.5])) and p.master_level == 0.5
    assert tree.dispatch(OscMessage("/custom/BPM/bpm", [90.0])) and p.bpm == 90.0
    with pytest.raises(ValueError):
        tree.dispatch(OscMessage("/surfaces/selected/opacity", ["x"]))


def test_osc_server_udp_roundtrip():
    import socket
    from PyQt6.QtCore import QCoreApplication, QEventLoop
    from mapstudio.osc.server import OscServer
    from mapstudio.osc.protocol import encode_message, decode_packet
    app = QCoreApplication.instance() or QCoreApplication([])
    got = []
    server = OscServer(lambda msg, host, port: got.append((msg.address, list(msg.args), host, port)))
    port = 0
    for candidate in range(18010, 18030):
        if server.start(candidate):
            port = candidate
            break
    assert port, "no free UDP port"
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client.bind(("127.0.0.1", 0))
    client.settimeout(2.0)
    client.sendto(encode_message("/surfaces/selected/opacity", [0.5]), ("127.0.0.1", port))
    client.sendto(b"garbage" + bytes(2), ("127.0.0.1", port))
    for _ in range(50):
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        if got:
            break
    assert got and got[0][0] == "/surfaces/selected/opacity" and got[0][1][0] == pytest.approx(0.5)
    server.send("/reply", [1], "127.0.0.1", client.getsockname()[1])
    data, _ = client.recvfrom(1024)
    assert decode_packet(data).address == "/reply"
    server.stop()
    client.close()
