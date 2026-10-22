"""ISF (Interactive Shader Format) support in the MadMapper dialect.

* `header`      - extract and parse the leading `/*{ ... }*/` JSON block
* `inputs`      - typed INPUT declarations with validation
* `generators`  - CPU-side GENERATORS (time_base, animator, damper, ...)
* `assembly`    - build the final GLSL vertex/fragment sources (preamble, macros, main())
* `material`    - `Material`: a loaded material folder tying the above together
"""
from .header import IsfError, parse_isf_source, split_header
from .inputs import IsfInput, InputType
from .generators import Generator, GeneratorContext, build_generator
from .material import Material, load_material, MaterialSource

__all__ = [
    "IsfError", "parse_isf_source", "split_header", "IsfInput", "InputType",
    "Generator", "GeneratorContext", "build_generator",
    "Material", "load_material", "MaterialSource",
]
