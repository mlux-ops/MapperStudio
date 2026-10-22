"""Tests for the ISF header parser, input validation, generators and shader assembly."""
from __future__ import annotations

from pathlib import Path

import pytest

from mapstudio.isf import parse_isf_source, IsfError, load_material
from mapstudio.isf.assembly import assemble_material, resolve_includes
from mapstudio.isf.generators import GeneratorContext, build_generator, TimeBase, Animator, Adsr, LinearFilter
from mapstudio.isf.inputs import InputError, InputType

MATERIALS = Path(r"E:\Games\MadMapperDemo 6.1.8\Resources\Materials")
needs_library = pytest.mark.skipif(not MATERIALS.is_dir(), reason="MadMapper demo materials not installed")

HEADER = '''/*{
    "DESCRIPTION": "test",
    "INPUTS": [
        { "NAME": "speed", "LABEL": "Motion/Speed", "TYPE": "float", "MIN": 0.0, "MAX": 2.0, "DEFAULT": 1. },
        { "NAME": "reverse", "TYPE": "bool", "DEFAULT": false, "FLAGS": "button" },
        { "NAME": "col", "TYPE": "color", "DEFAULT": [1.0, 0.5, 0.25] },
        { "NAME": "shape", "TYPE": "long", "VALUES": ["A", "B"], "LABELS": ["Alpha", "Beta"], "DEFAULT": "B", "FLAGS": "generate_as_define" },
        { "NAME": "pos", "TYPE": "point2D", "DEFAULT": [.5, 0.5], "MIN": [0, 0], "MAX": [1, 1] },
    ],
    "GENERATORS": [
        { "NAME": "t", "TYPE": "time_base", "PARAMS": { "speed": "speed", "reverse": "reverse", "speed_curve": 2 } }
    ]
}*/
vec4 materialColorForPixel(vec2 uv) { return vec4(uv, t, 1.0); }
'''


def test_header_tolerates_trailing_commas_and_bare_dots():
    doc = parse_isf_source(HEADER)
    assert [i.name for i in doc.inputs] == ["speed", "reverse", "col", "shape", "pos"]
    assert doc.input("speed").default == 1.0 and doc.input("speed").group == "Motion"
    assert doc.input("col").default == [1.0, 0.5, 0.25, 1.0]
    assert doc.input("shape").default == 1 and doc.input("shape").labels == ["Alpha", "Beta"]
    assert doc.input("pos").default == [0.5, 0.5]
    assert doc.generators[0]["TYPE"] == "time_base"


def test_assembly_contains_uniforms_defines_and_main():
    doc = parse_isf_source(HEADER)
    prog = assemble_material(doc, doc.body)
    frag = prog.fragment
    assert frag.startswith("#version 150 core")
    assert "#define shape_IS_B 1" in frag
    assert "uniform float speed = 1.0;" in frag
    assert "uniform vec4 col = vec4(1.0,0.5,0.25,1.0);" in frag
    assert "uniform float t = 0.0;" in frag
    assert "FragColor = materialColorForPixel(isf_FragNormCoord);" in frag
    assert prog.uses_time is False


@pytest.mark.parametrize("bad, message", [
    ('{"INPUTS": [{"NAME": "x"}]}', "TYPE not defined"),
    ('{"INPUTS": [{"NAME": "x", "TYPE": "float", "MIN": 0, "MAX": 1, "DEFAULT": 2}]}', "not in range"),
    ('{"INPUTS": [{"NAME": "x", "TYPE": "color"}]}', "color input must be an array"),
    ('{"INPUTS": [{"NAME": "x", "TYPE": "long", "DEFAULT": "a"}]}', "VALUES array is missing"),
    ('{"INPUTS": [{"NAME": "x", "TYPE": "point2D", "MIN": [0, 0]}]}', "must have both"),
    ('{"INPUTS": [{"NAME": "x", "TYPE": "wibble"}]}', "Unhandled ISF input type"),
    ('{"INPUTS": [{"NAME": "x", "TYPE": "float", "FLAGS": [1]}]}', "FLAGS should be an array of strings"),
])
def test_input_validation_errors(bad: str, message: str):
    with pytest.raises((IsfError, InputError), match=message):
        parse_isf_source("/*" + bad + "*/\nvoid f(){}")


def test_unknown_generator_type_and_parameter():
    with pytest.raises(IsfError, match="Unknown generator type"):
        build_generator({"NAME": "g", "TYPE": "nope", "PARAMS": {}})
    with pytest.raises(IsfError, match="has no parameter"):
        build_generator({"NAME": "g", "TYPE": "time_base", "PARAMS": {"bogus": 1}})


def test_time_base_integrates_speed_with_curve_and_reverse():
    g = TimeBase("t", {"speed": "speed", "reverse": "reverse", "speed_curve": 2})
    ctx = GeneratorContext(dt=0.5, values={"speed": 2.0, "reverse": False})
    assert g.update(ctx) == pytest.approx(2.0)      # speed^2 * dt = 4 * 0.5
    ctx.values["reverse"] = True
    assert g.update(ctx) == pytest.approx(0.0)


def test_time_base_bpm_sync_quantises_to_powers_of_two():
    g = TimeBase("t", {"speed": 0.3, "bpm_sync": True})
    ctx = GeneratorContext(dt=1.0, bpm=120.0)
    assert g.update(ctx) == pytest.approx(0.25 * 2.0)   # 0.3 -> 1/4 beat, 120 bpm = 2 beats/s


def test_animator_shapes():
    for shape, expect in (("In", 0.25), ("Cut", 0.0), ("Linear", 0.5), ("Smooth", 0.5)):
        g = Animator("a", {"speed": 1.0, "shape": shape})
        g.update(GeneratorContext(dt=0.25))
        assert g.value == pytest.approx(expect, abs=1e-6), shape


def test_adsr_attack_zero_jumps_and_release_decays():
    g = Adsr("e", {"input_value": "x", "attack": 0.0, "release": 0.5, "decay": 0.0})
    ctx = GeneratorContext(dt=0.1, time=0.0, values={"x": 1.0})
    assert g.update(ctx) == 1.0
    ctx.values["x"] = 0.0
    ctx.time = 0.1
    v = g.update(ctx)
    assert 0.0 < v < 1.0                       # release 0.5 -> about 0.98 units per second
    assert v == pytest.approx(1.0 - 10 ** (1 - 2 * (0.01 + 0.5 * 0.99)) * 0.1)


def test_linear_filter_reaches_target_after_duration():
    g = LinearFilter("l", {"input_value": "x", "duration": 1.0})
    ctx = GeneratorContext(dt=0.1, time=0.0, values={"x": 0.0})
    g.update(ctx)
    ctx.values["x"] = 1.0
    ctx.time = 0.0
    g.update(ctx)
    ctx.time = 0.5
    assert g.update(ctx) == pytest.approx(0.5)
    ctx.time = 2.0
    assert g.update(ctx) == pytest.approx(1.0)


def test_include_resolution_and_errors(tmp_path: Path):
    inc = tmp_path / "lib.glsl"
    inc.write_text("float lib() { return 1.0; }", encoding="utf-8")
    out = resolve_includes('#include "lib.glsl"\nvoid main(){}', [tmp_path])
    assert "float lib()" in out
    with pytest.raises(IsfError, match="not found"):
        resolve_includes('#include "missing.glsl"', [tmp_path])
    with pytest.raises(IsfError, match="Incomplete"):
        resolve_includes("#include lib.glsl", [tmp_path])
    assert "MAPSTUDIO_MADNOISE_GLSL" in resolve_includes('#include "MadNoise.glsl"', [])


@needs_library
def test_every_shipped_material_parses_and_assembles():
    failures = []
    for folder in sorted(p for p in MATERIALS.iterdir() if p.is_dir() and any(p.glob("*.fs"))):
        try:
            m = load_material(folder)
            m.assemble()
            m.tick(120.0)
        except (IsfError, InputError) as exc:
            failures.append(f"{folder.name}: {exc}")
    assert not failures, "\n".join(failures)


@needs_library
def test_material_values_by_label_and_defines():
    m = load_material(MATERIALS / "Fill")
    assert m.set_value_by_label("Auto Move/Shape", "Noise")
    assert m.values["mat_automoveshape"] == m.input("mat_automoveshape").values.index("Noise")
    assert m.defines() == {"mat_automoveshape": m.values["mat_automoveshape"]}
    prog = m.assemble()
    assert "#define mat_automoveshape_IS_Noise 1" in prog.fragment
