from datetime import UTC, datetime
from importlib.util import find_spec
from uuid import UUID

import pytest

TAG = UUID("11223344-5566-7788-9900-aabbccddeeff")


def test_public_package_exists():
    assert find_spec("pqdif") is not None


@pytest.mark.parametrize(
    "name,value,hex_value",
    [
        ("BOOLEAN1", True, "01"),
        ("BOOLEAN2", False, "0000"),
        ("BOOLEAN4", True, "01000000"),
        ("CHAR1", "A", "41"),
        ("CHAR2", "\u03a9", "a903"),
        ("INT1", -2, "fe"),
        ("INT2", -2, "feff"),
        ("INT4", -2, "feffffff"),
        ("UINT1", 255, "ff"),
        ("UINT2", 65535, "ffff"),
        ("UINT4", 4294967295, "ffffffff"),
        ("REAL4", 1.5, "0000c03f"),
        ("REAL8", 1.5, "000000000000f83f"),
        ("COMPLEX8", complex(1, -2), "0000803f000000c0"),
        ("COMPLEX16", complex(1, -2), "000000000000f03f00000000000000c0"),
        ("GUID", TAG, "44332211665588779900aabbccddeeff"),
    ],
)
def test_scalar_independent_wire_values(name, value, hex_value):
    from pqdif.elements import Scalar
    from pqdif.types import PhysicalType

    scalar = Scalar.from_value(TAG, PhysicalType[name], value)
    assert scalar.raw.hex() == hex_value
    assert scalar.value == value
    scalar.value = value
    assert scalar.raw.hex() == hex_value


def test_timestamp_retains_binary64_precision_and_converts_utc():
    from pqdif.elements import Scalar
    from pqdif.types import PhysicalType, Timestamp

    timestamp = Timestamp(2, 0.123456789)
    scalar = Scalar.from_value(TAG, PhysicalType.TIMESTAMP, timestamp)
    assert scalar.raw.hex() == "020000005f633937dd9abf3f"
    assert scalar.value == timestamp
    assert timestamp.to_datetime() == datetime(1900, 1, 3, 0, 0, 0, 123457, UTC)
    assert Timestamp.from_datetime(datetime(1900, 1, 3, tzinfo=UTC)).days == 2
    with pytest.raises(ValueError, match="timezone"):
        Timestamp.from_datetime(datetime(2020, 1, 1))


def test_raw_nan_and_noncanonical_boolean_preserved():
    from pqdif.elements import Scalar
    from pqdif.types import PhysicalType

    scalar = Scalar(TAG, PhysicalType.REAL4, bytes.fromhex("0100c07f"))
    assert scalar.value != scalar.value
    assert scalar.raw.hex() == "0100c07f"
    scalar = Scalar(TAG, PhysicalType.BOOLEAN4, b"\xff" * 4)
    assert scalar.value is True
    assert scalar.raw == b"\xff" * 4


def test_vectors_strings_and_numpy_readonly():
    from pqdif.elements import Vector
    from pqdif.types import PhysicalType

    assert Vector.from_text(TAG, "meter").raw == b"meter\x00"
    assert Vector.from_text(TAG, "\u03a9", unicode=True).text == "\u03a9"
    vector = Vector.from_values(TAG, PhysicalType.INT2, [-1, 2, 300])
    assert vector.values == (-1, 2, 300)
    array = vector.to_numpy()
    assert array.dtype.str == "<i2"
    assert array.tolist() == [-1, 2, 300]
    assert not array.flags.writeable
    assert Vector.from_values(TAG, PhysicalType.REAL8, []).count == 0


def test_invalid_raw_sizes_and_scalar_range():
    from pqdif.elements import Scalar, Vector
    from pqdif.types import PhysicalType

    with pytest.raises(ValueError):
        Scalar(TAG, PhysicalType.REAL8, b"1234")
    with pytest.raises(ValueError):
        Vector(TAG, PhysicalType.INT2, b"1")
    with pytest.raises(ValueError):
        Scalar.from_value(TAG, PhysicalType.UINT1, 256)


def test_collection_preserves_duplicate_tags_and_replace_position():
    from pqdif.elements import Collection, Scalar
    from pqdif.errors import ValidationError
    from pqdif.types import PhysicalType

    a = Scalar.from_value(TAG, PhysicalType.INT4, 1)
    b = Scalar.from_value(TAG, PhysicalType.INT4, 2)
    c = Collection(elements=[a, b])
    assert c.all(TAG) == [a, b]
    with pytest.raises(ValidationError, match="duplicate"):
        c.get(TAG)
    c.replace(Scalar.from_value(TAG, PhysicalType.INT4, 3))
    assert len(c.elements) == 1
    assert c.get(TAG).value == 3
