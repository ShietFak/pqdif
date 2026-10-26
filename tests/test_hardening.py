import io
import struct
from uuid import UUID

import pytest
from test_physical import records

from pqdif import Collection, PhysicalType, Scalar, Series, Timestamp, Vector
from pqdif.codec import decode_collection, encode_collection
from pqdif.errors import PqdifFormatError, ValidationError
from pqdif.physical import dumps_records, read_records, write_records
from pqdif.types import Limits

TAG = UUID(int=7)


def test_utf16_code_units_and_non_bmp_text_roundtrip():
    vector = Vector.from_text(TAG, "meter \U0001f600", unicode=True)
    assert vector.text == "meter \U0001f600"
    assert vector.values[-3:] == ("\ud83d", "\ude00", "\0")
    scalar = Scalar.from_value(TAG, PhysicalType.CHAR2, "\ud83d")
    assert scalar.raw == b"=\xd8"
    assert scalar.value == "\ud83d"


@pytest.mark.parametrize(
    "timestamp",
    [
        Timestamp(-1, 0),
        Timestamp(0, -1),
        Timestamp(0, 86400),
        Timestamp(0, float("nan")),
        Timestamp(0, float("inf")),
    ],
)
def test_invalid_timestamp_conversion_is_explicit(timestamp):
    with pytest.raises(ValueError, match="timestamp"):
        timestamp.to_datetime()
    with pytest.raises(ValueError, match="timestamp"):
        Scalar.from_value(TAG, PhysicalType.TIMESTAMP, timestamp)


def test_misaligned_payload_rejected():
    body = encode_collection(Collection(elements=[Vector(TAG, PhysicalType.UINT1, b"a")]))
    malformed = bytearray(body + b"\0" * 4)
    struct.pack_into("<i", malformed, 24, 33)
    with pytest.raises(PqdifFormatError, match="align"):
        decode_collection(bytes(malformed))


def test_writer_rejects_empty_linked_opaque_payload():
    from pqdif import OpaqueElement

    opaque = OpaqueElement(TAG, 99, 200, b"", relocatable=True)
    with pytest.raises(ValueError, match="empty"):
        encode_collection(Collection(elements=[opaque]))


def test_read_handles_short_reads_and_write_handles_short_writes():
    class ShortRead(io.BytesIO):
        def read(self, size=-1):
            return super().read(min(size, 3))

    class ShortWrite(io.BytesIO):
        def write(self, data):
            return super().write(data[:3])

    original = records(2, 1)
    wire = dumps_records(original)
    assert read_records(ShortRead(wire)) == original
    output = ShortWrite()
    write_records(original, output)
    assert output.getvalue() == wire


def test_invalid_logical_channel_name_does_not_silently_become_empty():
    from test_api import example

    from pqdif import tags as t

    channel = example().observations[0].channels[0]
    channel.definition.replace(Scalar.from_value(t.CHANNEL_NAME, PhysicalType.UINT4, 99))
    with pytest.raises(ValidationError, match="ChannelName"):
        _ = channel.name


def test_channel_name_edit_preserves_descriptor_reserved_byte():
    from test_api import example

    from pqdif import tags as t

    channel = example().observations[0].channels[0]
    channel.definition.get(t.CHANNEL_NAME).reserved = 42
    channel.name = "new name"
    assert channel.definition.get(t.CHANNEL_NAME).reserved == 42


def test_mutated_invalid_known_series_scale_fails_validation():
    from test_api import example

    from pqdif import tags as t

    file = example()
    series = file.observations[0].channels[0].series[0]
    series.physical.elements.append(Vector.from_text(t.SERIES_SCALE, "wrong"))
    with pytest.raises(ValidationError, match="scale|Scale"):
        file.validate()


def test_expansion_limit_applies_to_numpy_fast_path():
    series = Series([1, 2, 3], physical_type=PhysicalType.INT2)
    series._limits = Limits(max_expanded_values=2)
    with pytest.raises(ValidationError, match="expan"):
        series.to_numpy()


def test_invalid_timestamp_in_required_logical_field_rejected():
    from test_api import example

    from pqdif import tags as t

    file = example()
    file.records[0].body.replace(
        Scalar(t.CREATION, PhysicalType.TIMESTAMP, struct.pack("<Id", 45000, float("nan")))
    )
    with pytest.raises(ValidationError, match="timestamp"):
        file.validate()


def test_overlapping_allocations_rejected_before_any_value_copy(monkeypatch):
    import pqdif.codec as codec

    body = bytearray(
        encode_collection(
            Collection(
                elements=[
                    Vector(TAG, PhysicalType.UINT1, b"abc"),
                    Vector(TAG, PhysicalType.UINT1, b"xyz"),
                ]
            )
        )
    )
    struct.pack_into("<i", body, 52, 60)
    copies = []
    real_vector = codec.Vector

    def tracked_copy(*args, **kwargs):
        copies.append(args)
        return real_vector(*args, **kwargs)

    monkeypatch.setattr(codec, "Vector", tracked_copy)
    with pytest.raises(PqdifFormatError, match="overlap"):
        codec.decode_collection(bytes(body))
    assert copies == [], "validate allocation overlap before copying attacker-controlled payloads"


def test_reusing_channel_in_another_observation_does_not_mutate_prior_observation():
    from test_api import START

    from pqdif import Channel, Observation, PqdifFile

    a = Channel("a", [Series([1.0])])
    b = Channel("b", [Series([2.0])])
    first = Observation("first", START, [a])
    second = Observation("second", START, [b, a])
    file = PqdifFile([first, second])
    file.validate()
    assert file.observations[0].channels[0].name == "a"
    assert file.observations[0].channels[0].series[0].values == (1.0,)
    assert [c.name for c in file.observations[1].channels] == ["b", "a"]


def test_explicit_identity_scale_on_shared_series_overrides_inherited_scale():
    from test_api import START

    from pqdif import Channel, Observation, PqdifFile, StorageMethod

    original = Series([1.0], storage=3, scale=2, offset=1)
    identity = Series([], storage=3, share=(0, 0), scale=1, offset=0)
    inherited = Series([], storage=StorageMethod.VALUES | StorageMethod.SCALED, share=(0, 0))
    file = PqdifFile(
        [
            Observation(
                "shared",
                START,
                [Channel("a", [original]), Channel("b", [identity]), Channel("c", [inherited])],
            )
        ]
    )
    assert file.observations[0].channels[1].series[0].values == (1.0,)
    assert file.observations[0].channels[2].series[0].values == (3.0,)


def test_non_numeric_scaling_rejected_before_string_multiplication():
    from pqdif import tags as t

    series = Series(["a"], physical_type=PhysicalType.CHAR1)
    series.definition.get(t.STORAGE_METHOD_ID).value = 3
    series.physical.elements += [
        Scalar.from_value(t.SERIES_SCALE, PhysicalType.INT4, 1000),
        Scalar.from_value(t.SERIES_OFFSET, PhysicalType.CHAR1, "b"),
    ]
    with pytest.raises(ValidationError, match="numeric"):
        _ = series.values


def test_long_sharing_chain_builds_each_channel_series_list_once(monkeypatch):
    from test_api import START

    from pqdif import Channel, Observation, PqdifFile

    series = [Series([], share=(0, index + 1)) for index in range(99)] + [Series([42.0])]
    file = PqdifFile([Observation("chain", START, [Channel("one", series)])])
    view = file.observations[0].channels[0].series[0]
    original = Channel.series.fget
    calls = []

    def tracked(channel):
        calls.append(channel)
        return original(channel)

    monkeypatch.setattr(Channel, "series", property(tracked))
    assert view.values == (42.0,)
    assert len(calls) <= 2, "series sharing traversal must not repeatedly rebuild entire lists"
