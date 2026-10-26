import io
from datetime import UTC, datetime
from uuid import UUID

import numpy as np
import pytest

from pqdif import tags as t
from pqdif.elements import Collection, Scalar, Vector
from pqdif.errors import UnsupportedFeatureError, ValidationError
from pqdif.types import Limits, PhysicalType, StorageMethod, Timestamp

START = datetime(2026, 1, 2, 3, 4, 5, 123456, UTC)
VENDOR = UUID("ffffffff-1111-2222-3333-444444444444")


def example(compressed=False):
    from pqdif import Channel, Observation, PqdifFile, Series

    return PqdifFile(
        [
            Observation(
                "waveform",
                START,
                [
                    Channel(
                        "Va",
                        [
                            Series(
                                np.array([1, -2, 3], dtype=np.int16),
                                units=6,
                                physical_type=PhysicalType.INT2,
                            )
                        ],
                        phase=1,
                        quantity=1,
                    )
                ],
            )
        ],
        compressed=compressed,
        created=START,
    )


@pytest.mark.parametrize("compressed", [False, True])
def test_build_write_read_numeric_file_and_required_fields(compressed, tmp_path):
    from pqdif import dumps, loads, read, write

    file = example(compressed)
    wire = dumps(file)
    result = loads(wire)
    result.validate()
    observation = result.observations[0]
    assert observation.name == "waveform"
    assert observation.start == Timestamp.from_datetime(START)
    assert observation.channels[0].name == "Va"
    series = observation.channels[0].series[0]
    assert series.units == 6
    assert series.values == (1, -2, 3)
    assert series.to_numpy().dtype.str == "<i2"
    assert not series.to_numpy().flags.writeable
    assert result.compressed == compressed
    path = tmp_path / "example.pqd"
    write(result, path)
    assert read(path).records == result.records
    stream = io.BytesIO()
    write(result, stream)
    assert not stream.closed
    stream.seek(0)
    assert read(stream).records == result.records


def test_read_edit_write_preserves_unknown_everywhere():
    from pqdif import dumps, loads

    file = example()
    observation = file.observations[0]
    channel = observation.channels[0]
    series = channel.series[0]
    roots = [
        file.records[0].body,
        observation.physical.body,
        channel.definition,
        channel.physical,
        series.definition,
        series.physical,
    ]
    for root in roots:
        root.elements += [
            Vector(VENDOR, PhysicalType.REAL4, bytes.fromhex("0100c07f")),
            Collection(VENDOR, [Scalar.from_value(VENDOR, PhysicalType.UINT4, 99)]),
        ]
    result = loads(dumps(file))
    observation = result.observations[0]
    observation.name = "edited"
    observation.channels[0].name = "Voltage A"
    series = observation.channels[0].series[0]
    series.stored_values = Vector.from_values(t.SERIES_VALUES, PhysicalType.INT2, [7, 8])
    result = loads(dumps(result))
    observation = result.observations[0]
    channel = observation.channels[0]
    series = channel.series[0]
    assert observation.name == "edited"
    assert channel.name == "Voltage A"
    assert series.values == (7, 8)
    for root in [
        result.records[0].body,
        observation.physical.body,
        channel.definition,
        channel.physical,
        series.definition,
        series.physical,
    ]:
        assert root.all(VENDOR)[0].raw.hex() == "0100c07f"
        assert root.all(VENDOR)[1].elements[0].value == 99


def test_scale_offset_and_multirate_increment_expansion_and_limit():
    from pqdif import Series

    series = Series(
        [1, 2, 3],
        physical_type=PhysicalType.INT2,
        storage=StorageMethod.VALUES | StorageMethod.SCALED,
        scale=2,
        offset=-1,
    )
    assert series.raw_values == (1, 2, 3)
    assert series.values == (1, 3, 5)
    np.testing.assert_array_equal(series.to_numpy(), [1, 3, 5])
    series = Series(
        [2, 3, 0.5, 2, 1.0],
        storage=StorageMethod.INCREMENT | StorageMethod.SCALED,
        scale=2,
        offset=10,
    )
    assert series.values == (10.0, 11.0, 12.0, 13.0, 15.0)
    with pytest.raises(ValidationError, match="expan"):
        series.get_values(limits=Limits(max_expanded_values=4))


@pytest.mark.parametrize(
    "values",
    [[-1], [1, 3], [1, -1, 1], [1, 1.5, 1], [2, 3, 1], [1, float("inf"), 1], [float("nan"), 2, 1]],
)
def test_invalid_increment_encoding_rejected(values):
    from pqdif import Series

    with pytest.raises(ValidationError, match="increment"):
        _ = Series(values, storage=StorageMethod.INCREMENT).values


def test_series_sharing_and_cycle_index_detection():
    from pqdif import Channel, Observation, PqdifFile, Series, dumps, loads

    a = Series([1, 2, 3], storage=StorageMethod.VALUES | StorageMethod.SCALED, scale=2, offset=1)
    b = Series([], storage=StorageMethod.VALUES | StorageMethod.SCALED, share=(0, 0))
    file = PqdifFile([Observation("shared", START, [Channel("a", [a]), Channel("b", [b])])])
    result = loads(dumps(file))
    assert result.observations[0].channels[1].series[0].values == (3.0, 5.0, 7.0)
    a = result.observations[0].channels[0].series[0]
    a.physical.elements += [
        Scalar.from_value(t.SERIES_SHARE_CHANNEL_INDEX, PhysicalType.UINT4, 1),
        Scalar.from_value(t.SERIES_SHARE_SERIES_INDEX, PhysicalType.UINT4, 0),
    ]
    with pytest.raises(ValidationError, match="cycl"):
        _ = a.values
    with pytest.raises(ValidationError, match="cycl"):
        dumps(result)
    a.physical.get(t.SERIES_SHARE_CHANNEL_INDEX).value = 99
    with pytest.raises(ValidationError, match="index"):
        _ = a.values


def test_multiple_observations_sources_and_settings_preserved():
    from test_logical import settings

    from pqdif import Channel, Observation, PqdifFile, Series, dumps, loads

    a = Observation("a", START, [Channel("a", [Series([1.0])])], settings=settings())
    b = Observation("b", START, [Channel("b", [Series([2.0])])])
    result = loads(dumps(PqdifFile([a, b])))
    assert [o.name for o in result.observations] == ["a", "b"]
    assert result.observations[0].settings is not None
    assert result.observations[1].settings is None


def test_transducer_ratio_and_explicit_unsupported_calibration():
    from test_logical import settings

    from pqdif import Channel, Observation, PqdifFile, Series

    record = settings()
    record.body.get(t.USE_TRANSDUCER).value = True
    setting = record.body.get(t.CHANNEL_SETTINGS_ARRAY).elements[0]
    setting.elements += [
        Scalar.from_value(t.XD_SYSTEM_SIDE_RATIO, PhysicalType.REAL8, 100),
        Scalar.from_value(t.XD_MONITOR_SIDE_RATIO, PhysicalType.REAL8, 5),
    ]
    file = PqdifFile(
        [Observation("xd", START, [Channel("v", [Series([1.0, 2.0])])], settings=record)]
    )
    series = file.observations[0].channels[0].series[0]
    assert series.values == (20.0, 40.0)
    setting.get(t.XD_MONITOR_SIDE_RATIO).value = 0
    with pytest.raises(ValidationError, match="ratio"):
        _ = series.values
    record.body.get(t.USE_CALIBRATION).value = True
    with pytest.raises(UnsupportedFeatureError, match="calibration"):
        _ = series.values
    assert series.raw_values == (1.0, 2.0)


def test_unknown_storage_preserved_and_not_silently_interpreted():
    from pqdif import Series

    series = Series([1.0], storage=128)
    assert series.raw_values == (1.0,)
    with pytest.raises(UnsupportedFeatureError, match="storage"):
        _ = series.values
