import io
import struct
import zlib
from uuid import UUID

import pytest

from pqdif.elements import Collection, Scalar, Vector
from pqdif.errors import PqdifFormatError, UnsupportedFeatureError
from pqdif.types import Limits, PhysicalType

SIGNATURE = UUID("4a111440-e49f-11cf-9900-505144494600")
CONTAINER = UUID("89738606-f1c3-11cf-9d89-0080c72e70a3")
STYLE = UUID("8973861b-f1c3-11cf-9d89-0080c72e70a3")
ALGORITHM = UUID("8973861c-f1c3-11cf-9d89-0080c72e70a3")
VENDOR = UUID("abcdef01-2222-3333-4444-123456789abc")


def header(tag, body, next_pos=0, extra=b"", reserved=bytes(16), checksum=None):
    return (SIGNATURE.bytes_le + tag.bytes_le + struct.pack("<iiiI", 64 + len(extra),
            len(body), next_pos, zlib.adler32(body) if checksum is None else checksum)
            + reserved + extra + body)


def records(style=0, algorithm=0):
    from pqdif.physical import Record
    body = Collection(CONTAINER, [Scalar.from_value(STYLE, PhysicalType.UINT4, style),
                                 Scalar.from_value(ALGORITHM, PhysicalType.UINT4, algorithm)])
    return [Record(CONTAINER, body), Record(VENDOR, Collection(VENDOR, [
        Vector.from_text(VENDOR, "vendor payload"),
        Collection(VENDOR, [Scalar.from_value(VENDOR, PhysicalType.REAL8, 4.25)]),
    ]))]


def test_handbuilt_header_and_optional_checksum():
    from pqdif.physical import dumps_records, loads_records
    wire = header(CONTAINER, bytes(4))
    result = loads_records(wire)
    assert result[0].type_tag == CONTAINER
    assert result[0].body.elements == []
    assert dumps_records(result) == wire
    assert loads_records(header(CONTAINER, bytes(4), checksum=0))[0].body.elements == []


@pytest.mark.parametrize("compressed", [False, True])
def test_semantic_roundtrip_unknown_record_and_compression(compressed):
    from pqdif.physical import dumps_records, loads_records
    original = records(2 if compressed else 0, 1 if compressed else 0)
    wire = dumps_records(original)
    next_pos = struct.unpack_from("<i", wire, 40)[0]
    body_size = struct.unpack_from("<i", wire, 36)[0]
    assert next_pos == 64 + body_size
    assert wire[next_pos:next_pos + 16] == SIGNATURE.bytes_le
    assert loads_records(wire) == original
    assert struct.unpack_from("<i", wire, next_pos + 40)[0] == 0
    if compressed:
        assert zlib.decompress(wire[next_pos + 64:])


def test_header_extensions_reserved_zero_body_and_stream_ownership(tmp_path):
    from pqdif.physical import Record, dumps_records, read_records, write_records
    original = records() + [Record(VENDOR, None, reserved=b"R" * 16, header_extra=b"EXT!")]
    stream = io.BytesIO()
    write_records(original, stream)
    assert not stream.closed
    stream.seek(0)
    assert read_records(stream) == original
    assert not stream.closed
    path = tmp_path / "test.pqd"
    write_records(original, path)
    assert read_records(path) == original
    assert path.read_bytes() == dumps_records(original)


@pytest.mark.parametrize("style,algorithm", [(1, 1), (2, 64), (99, 1), (2, 99), (0, 1), (2, 0)])
def test_unsupported_compression_rejected(style, algorithm):
    from pqdif.codec import encode_collection
    from pqdif.physical import dumps_records, loads_records
    original = records(style, algorithm)
    with pytest.raises(UnsupportedFeatureError, match="compression"):
        dumps_records(original)
    wire = header(CONTAINER, encode_collection(original[0].body))
    with pytest.raises(UnsupportedFeatureError, match="compression"):
        loads_records(wire)


def test_corrupt_checksum_and_explicit_ignore():
    from pqdif.physical import loads_records
    wire = header(CONTAINER, bytes(4), checksum=1234)
    with pytest.raises(PqdifFormatError, match="checksum"):
        loads_records(wire)
    assert loads_records(wire, verify_checksum=False)


@pytest.mark.parametrize("position,value", [(0, 0), (32, 63), (36, -1), (40, 1), (40, 9999)])
def test_malformed_header_signature_sizes_links(position, value):
    from pqdif.physical import dumps_records, loads_records
    wire = bytearray(dumps_records(records()))
    struct.pack_into("<i", wire, position, value)
    with pytest.raises(PqdifFormatError):
        loads_records(bytes(wire))


def test_truncated_records_and_record_limits():
    from pqdif.physical import dumps_records, loads_records
    wire = dumps_records(records())
    for size in [0, 1, 20, 63, len(wire) - 1]:
        with pytest.raises(PqdifFormatError):
            loads_records(wire[:size])
    with pytest.raises(PqdifFormatError, match="file"):
        loads_records(wire, limits=Limits(max_file_bytes=50))
    with pytest.raises(PqdifFormatError, match="record"):
        loads_records(wire, limits=Limits(max_records=1))
    with pytest.raises(PqdifFormatError, match="decoded"):
        loads_records(wire, limits=Limits(max_total_decoded_bytes=70))


def test_zlib_bomb_truncation_and_trailing_stream_rejected():
    from pqdif.codec import encode_collection
    from pqdif.physical import loads_records
    container = encode_collection(records(2, 1)[0].body)
    prefix = header(CONTAINER, container, 64 + len(container))
    for compressed in [zlib.compress(bytes(5000)), zlib.compress(bytes(4))[:-1],
                       zlib.compress(bytes(4)) + b"junk", b"bad zlib"]:
        with pytest.raises(PqdifFormatError):
            loads_records(prefix + header(VENDOR, compressed), limits=Limits(max_record_bytes=256))


def test_first_record_must_be_container_and_no_duplicate_container():
    from pqdif.physical import dumps_records, loads_records
    with pytest.raises(PqdifFormatError, match="container"):
        loads_records(header(VENDOR, bytes(4)))
    with pytest.raises(ValueError, match="container"):
        dumps_records(records()[1:])
    with pytest.raises(ValueError, match="container"):
        dumps_records(records() + records()[:1])
