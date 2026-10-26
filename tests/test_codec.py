import struct
from uuid import UUID

import pytest

from pqdif.elements import Collection, OpaqueElement, Scalar, Vector
from pqdif.errors import PqdifFormatError, UnsupportedFeatureError
from pqdif.types import Limits, PhysicalType

TAG = UUID("11223344-5566-7788-9900-aabbccddeeff")


def descriptor(kind, physical, embedded, payload, reserved=0):
    return TAG.bytes_le + bytes([kind, physical, embedded, reserved]) + payload


def test_decode_handbuilt_embedded_scalar():
    from pqdif.codec import decode_collection

    wire = struct.pack("<i", 1) + descriptor(2, 22, 1, struct.pack("<i", -123) + b"\0" * 4, 7)
    result = decode_collection(wire)
    assert result.elements[0].value == -123
    assert result.elements[0].reserved == 7


def test_writer_matches_independent_vector_layout_and_padding():
    from pqdif.codec import decode_collection, encode_collection

    wire = (
        struct.pack("<i", 1)
        + descriptor(3, 30, 0, struct.pack("<ii", 32, 8))
        + struct.pack("<i", 3)
        + b"abc\0"
    )
    root = Collection(elements=[Vector(TAG, PhysicalType.UINT1, b"abc")])
    assert encode_collection(root) == wire
    assert decode_collection(wire).elements == root.elements


def test_nested_absolute_links_duplicates_and_guid_scalar():
    from pqdif.codec import decode_collection, encode_collection

    root = Collection(
        elements=[
            Collection(
                TAG,
                [
                    Scalar.from_value(TAG, PhysicalType.GUID, TAG),
                    Scalar.from_value(TAG, PhysicalType.REAL8, 1.25),
                    Vector.from_values(TAG, PhysicalType.COMPLEX16, [1 + 2j, 3 - 4j]),
                    Collection(TAG),
                ],
            )
        ]
    )
    wire = encode_collection(root)
    assert struct.unpack_from("<ii", wire, 24) == (32, len(wire) - 32)
    assert struct.unpack_from("<i", wire, 32 + 24)[0] == 32 + 4 + 4 * 28
    decoded = decode_collection(wire)
    assert decoded.elements == root.elements
    assert encode_collection(decoded) == wire


def test_unknown_embedded_and_out_of_line_are_preserved_but_relocation_guarded():
    from pqdif.codec import decode_collection, encode_collection

    wire = struct.pack("<i", 1) + descriptor(99, 200, 1, b"vendor!?", 9)
    root = decode_collection(wire)
    opaque = root.elements[0]
    assert isinstance(opaque, OpaqueElement)
    assert opaque.raw == b"vendor!?"
    assert encode_collection(root) == wire
    wire = struct.pack("<i", 1) + descriptor(3, 200, 0, struct.pack("<ii", 32, 8)) + b"vendor!?"
    root = decode_collection(wire)
    assert root.elements[0].raw == b"vendor!?"
    with pytest.raises(UnsupportedFeatureError, match="relocat"):
        encode_collection(root)
    root.elements[0].relocatable = True
    assert encode_collection(root) == wire


@pytest.mark.parametrize(
    "wire",
    [
        b"",
        b"\0",
        struct.pack("<i", -1),
        struct.pack("<i", 100000),
        struct.pack("<i", 1) + descriptor(3, 30, 0, struct.pack("<ii", -1, 4)),
        struct.pack("<i", 1) + descriptor(3, 30, 0, struct.pack("<ii", 400, 4)),
        struct.pack("<i", 1) + descriptor(1, 0, 0, struct.pack("<ii", 0, 32)),
        struct.pack("<i", 1)
        + descriptor(3, 30, 0, struct.pack("<ii", 32, 8))
        + struct.pack("<i", -1)
        + b"\0" * 4,
        struct.pack("<i", 1)
        + descriptor(3, 30, 0, struct.pack("<ii", 32, 8))
        + struct.pack("<i", 9)
        + b"\0" * 4,
        struct.pack("<i", 1) + descriptor(2, 60, 1, b"\0" * 8),
        struct.pack("<i", 1) + descriptor(3, 30, 1, b"\0" * 8),
        struct.pack("<i", 1) + descriptor(2, 30, 2, b"\0" * 8),
    ],
)
def test_malformed_body_rejected_with_offset(wire):
    from pqdif.codec import decode_collection

    with pytest.raises(PqdifFormatError, match="byte"):
        decode_collection(wire)


def test_depth_element_vector_and_write_cycle_limits():
    from pqdif.codec import decode_collection, encode_collection

    root = Collection(elements=[Collection(TAG, [Collection(TAG)])])
    wire = encode_collection(root)
    with pytest.raises(PqdifFormatError, match="depth"):
        decode_collection(wire, limits=Limits(max_depth=1))
    with pytest.raises(PqdifFormatError, match="element"):
        decode_collection(wire, limits=Limits(max_elements=1))
    vector = encode_collection(Collection(elements=[Vector(TAG, PhysicalType.UINT1, b"abc")]))
    with pytest.raises(PqdifFormatError, match="vector"):
        decode_collection(vector, limits=Limits(max_vector_values=2))
    with pytest.raises(ValueError, match="depth"):
        encode_collection(root, limits=Limits(max_depth=1))
    root.elements.append(root)
    with pytest.raises(ValueError, match="cycl"):
        encode_collection(root)
