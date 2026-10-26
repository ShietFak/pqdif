from uuid import UUID

import pytest

from pqdif.elements import Collection, Scalar, Vector
from pqdif.errors import ValidationError
from pqdif.physical import Record
from pqdif.types import PhysicalType as P
from pqdif.types import Timestamp

VENDOR = UUID("a1111111-2222-3333-4444-555555555555")


def scalar(tag, kind, value):
    return Scalar.from_value(tag, kind, value)


def valid_records():
    from pqdif import tags as t
    stamp = Timestamp(45000, 120.5)
    series = Collection(t.ONE_SERIES_DEFINITION, [
        scalar(t.VALUE_TYPE_ID, P.GUID, VENDOR), scalar(t.QUANTITY_UNITS_ID, P.UINT4, 6),
        scalar(t.QUANTITY_CHARACTERISTIC_ID, P.GUID, VENDOR),
        scalar(t.STORAGE_METHOD_ID, P.UINT4, 1),
    ])
    channel = Collection(t.ONE_CHANNEL_DEFINITION, [
        Vector.from_text(t.CHANNEL_NAME, "Va"), scalar(t.PHASE_ID, P.UINT4, 1),
        scalar(t.QUANTITY_TYPE_ID, P.GUID, VENDOR), scalar(t.QUANTITY_MEASURED_ID, P.UINT4, 1),
        Collection(t.SERIES_DEFINITIONS, [series]),
    ])
    return [
        Record(t.CONTAINER, Collection(t.CONTAINER, [
            Vector.from_values(t.VERSION_INFO, P.UINT4, [1, 5, 1, 0]),
            Vector.from_text(t.FILE_NAME, "example.pqd"), scalar(t.CREATION, P.TIMESTAMP, stamp)])),
        Record(t.DATA_SOURCE, Collection(t.DATA_SOURCE, [
            scalar(t.DATA_SOURCE_TYPE, P.GUID, VENDOR), Vector.from_text(t.DATA_SOURCE_NAME, "meter"),
            scalar(t.EFFECTIVE, P.TIMESTAMP, stamp), Collection(t.CHANNEL_DEFINITIONS, [channel])])),
        Record(t.OBSERVATION, Collection(t.OBSERVATION, [
            Vector.from_text(t.OBSERVATION_NAME, "event"), scalar(t.TIME_CREATE, P.TIMESTAMP, stamp),
            scalar(t.TIME_START, P.TIMESTAMP, stamp), scalar(t.TRIGGER_METHOD, P.UINT4, 0),
            Collection(t.CHANNEL_INSTANCES, [Collection(t.ONE_CHANNEL_INSTANCE, [
                scalar(t.CHANNEL_DEFINITION_INDEX, P.UINT4, 0),
                Collection(t.SERIES_INSTANCES, [Collection(t.ONE_SERIES_INSTANCE, [
                    Vector.from_values(t.SERIES_VALUES, P.REAL8, [1.0, 2.0, 3.0])])])])])])),
    ]


def settings():
    from pqdif import tags as t
    stamp = Timestamp(45000, 0)
    return Record(t.MONITOR_SETTINGS, Collection(t.MONITOR_SETTINGS, [
        scalar(t.EFFECTIVE, P.TIMESTAMP, stamp), scalar(t.TIME_INSTALLED, P.TIMESTAMP, stamp),
        scalar(t.USE_CALIBRATION, P.BOOLEAN4, False), scalar(t.USE_TRANSDUCER, P.BOOLEAN4, False),
        Collection(t.CHANNEL_SETTINGS_ARRAY, [Collection(t.ONE_CHANNEL_SETTING, [
            scalar(t.CHANNEL_DEFINITION_INDEX, P.UINT4, 0)])])]))


def test_pinned_registry_contains_all_tags_and_identifiers():
    from pqdif import tags
    assert len(tags.BY_NAME) == 137
    assert tags.VERSION_INFO == UUID("89738607-f1c3-11cf-9d89-0080c72e70a3")
    assert tags.BY_NAME["SeriesValuesTag"].id == tags.SERIES_VALUES
    assert tags.IDENTIFIERS["tagQuantityUnitsID"]["Volts"]["value"] == "6"
    assert tags.PROVENANCE["commit"] == "296d859d094347420f22415b91cfe428ff87687b"


def test_valid_context_and_unknown_tags_records_enums_preserved():
    from pqdif import tags as t
    from pqdif.logical import LogicalFile
    records = valid_records()
    records.insert(2, Record(VENDOR, Collection(VENDOR)))
    records[1].body.elements.append(scalar(VENDOR, P.UINT4, 123))
    file = LogicalFile(records)
    file.validate()
    assert file.records == records
    assert len(file.observations) == 1
    observation = file.observations[0]
    assert observation.source.physical is records[1]
    assert observation.settings is None
    assert observation.value(t.OBSERVATION_NAME) == "event"
    observation.set_text(t.OBSERVATION_NAME, "edited")
    assert records[-1].body.get(t.OBSERVATION_NAME).text == "edited"
    assert records[1].body.get(VENDOR).value == 123


def test_source_change_resets_settings_and_bindings_are_snapshot_context():
    from copy import deepcopy
    from pqdif.logical import LogicalFile
    a, b, observation = valid_records()
    monitor = settings()
    second_source = deepcopy(b)
    file = LogicalFile([a, b, monitor, observation, second_source, deepcopy(observation)])
    file.validate()
    first, second = file.observations
    assert first.settings.physical is monitor
    assert second.settings is None
    assert second.source.physical is second_source


def test_required_fields_and_duplicate_singletons_rejected():
    from pqdif import tags as t
    from pqdif.logical import LogicalFile
    records = valid_records()
    records[0].body.elements.pop()
    with pytest.raises(ValidationError, match="Creation"):
        LogicalFile(records).validate()
    records = valid_records()
    records[-1].body.elements.append(Vector.from_text(t.OBSERVATION_NAME, "ambiguous"))
    with pytest.raises(ValidationError, match="duplicate"):
        LogicalFile(records).validate()


def test_observation_requires_source_bad_index_and_series_count_rejected():
    from pqdif import tags as t
    from pqdif.logical import LogicalFile
    records = valid_records()
    with pytest.raises(ValidationError, match="source"):
        LogicalFile([records[0], records[-1]])
    instance = records[-1].body.get(t.CHANNEL_INSTANCES).elements[0]
    instance.get(t.CHANNEL_DEFINITION_INDEX).value = 9
    with pytest.raises(ValidationError, match="index"):
        LogicalFile(records).validate()
    instance.get(t.CHANNEL_DEFINITION_INDEX).value = 0
    instance.get(t.SERIES_INSTANCES).elements.clear()
    with pytest.raises(ValidationError, match="series"):
        LogicalFile(records).validate()


def test_sharing_cycle_and_incomplete_reference_rejected():
    from pqdif import tags as t
    from pqdif.logical import LogicalFile
    records = valid_records()
    instance = records[-1].body.get(t.CHANNEL_INSTANCES).elements[0]
    series = instance.get(t.SERIES_INSTANCES).elements[0]
    series.elements.append(scalar(t.SERIES_SHARE_CHANNEL_INDEX, P.UINT4, 0))
    with pytest.raises(ValidationError, match="shar"):
        LogicalFile(records).validate()
    series.elements.append(scalar(t.SERIES_SHARE_SERIES_INDEX, P.UINT4, 0))
    with pytest.raises(ValidationError, match="cycl"):
        LogicalFile(records).validate()
