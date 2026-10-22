"""Readers for MadMapper's binary `.mad` project format (a Qt QDataStream QVariantMap)."""
from .qvariant_stream import QVariantStreamReader, StreamError, UserType
from .madproject import read_mad_file, read_mad_bytes, decode_polygonf_blob, unwrap, MadFileError

__all__ = [
    "QVariantStreamReader", "StreamError", "UserType",
    "read_mad_file", "read_mad_bytes", "decode_polygonf_blob", "unwrap", "MadFileError",
]
