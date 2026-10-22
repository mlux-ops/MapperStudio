"""MapStudio: an educational projection-mapping application modelled on MadMapper.

Package layout:
    madfile/    pure-Python reader for Qt QDataStream / QVariant streams and MadMapper .mad projects
    model/      the project model (surfaces, outputs, media) and its JSON persistence
    isf/        ISF header parsing, shader assembly and CPU-side generators
    render/     OpenGL renderer (quads, corner-pin warping, materials, outputs)
    ui/         Qt widgets (main window, input/output views, inspector, media panel)
"""
__version__ = "0.1.0"
