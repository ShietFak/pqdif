"""Context-aware logical views; these never replace the underlying physical tree."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from . import tags as t
from .elements import Collection, Element, Scalar, Vector
from .errors import ValidationError
from .physical import Record, compression_mode
from .types import PhysicalType as P
from .types import Value


def require(root: Collection, tag: UUID, expected: type[Element] | None = None) -> Element:
    element = root.get(tag)
    name = t.BY_ID[tag].name if tag in t.BY_ID else str(tag)
    if element is None:
        raise ValidationError(f"missing {name}")
    if expected is not None and not isinstance(element, expected):
        raise ValidationError(f"{name} must be {expected.__name__}")
    return element


def children(root: Collection, group: UUID, item: UUID) -> list[Collection]:
    collection = cast(Collection, require(root, group, Collection))
    values = collection.all(item)
    if any(not isinstance(value, Collection) for value in values):
        raise ValidationError(f"expected collection children in {group}")
    return cast(list[Collection], values)


def integer(root: Collection, tag: UUID) -> int:
    element = cast(Scalar, require(root, tag, Scalar))
    if element.physical_type != P.UINT4:
        raise ValidationError(f"{t.BY_ID[tag].name} must be UINT4")
    return cast(int, element.value)


def _fields(root: Collection, scalars: dict[UUID, P], vectors: dict[UUID, P]) -> None:
    for tag, kind in scalars.items():
        element = cast(Scalar, require(root, tag, Scalar))
        if element.physical_type != kind:
            raise ValidationError(f"{t.BY_ID[tag].name} must be {kind.name}")
    for tag, kind in vectors.items():
        vector = cast(Vector, require(root, tag, Vector))
        if vector.physical_type != kind and not (kind == P.CHAR1 and vector.physical_type == P.CHAR2):
            raise ValidationError(f"{t.BY_ID[tag].name} has invalid physical type")


@dataclass
class RecordView:
    physical: Record

    @property
    def body(self) -> Collection:
        if self.physical.body is None:
            raise ValidationError(f"logical record {self.physical.type_tag} has no body")
        return self.physical.body

    def value(self, tag: UUID, default: Value | None = None) -> Value | tuple[Value, ...] | None:
        element = self.body.get(tag)
        if element is None:
            return default
        if isinstance(element, Scalar):
            return element.value
        if isinstance(element, Vector):
            return element.text if element.physical_type in (P.CHAR1, P.CHAR2) else element.values
        raise ValidationError(f"{tag} is not a scalar/vector")

    def set_text(self, tag: UUID, value: str) -> None:
        previous = self.body.get(tag)
        unicode = (isinstance(previous, Vector) and previous.physical_type == P.CHAR2
                   or not value.isascii())
        replacement = Vector.from_text(tag, value, unicode=unicode)
        if previous is not None:
            replacement.reserved = previous.reserved
        self.body.replace(replacement)

    def set_scalar(self, tag: UUID, kind: P, value: Value) -> None:
        previous = self.body.get(tag)
        replacement = Scalar.from_value(tag, kind, value)
        if previous is not None:
            replacement.reserved = previous.reserved
        self.body.replace(replacement)


@dataclass
class ObservationRecordView(RecordView):
    source: RecordView
    settings: RecordView | None

    @property
    def channel_pairs(self) -> list[tuple[Collection, Collection]]:
        definitions = children(self.source.body, t.CHANNEL_DEFINITIONS, t.ONE_CHANNEL_DEFINITION)
        instances = children(self.body, t.CHANNEL_INSTANCES, t.ONE_CHANNEL_INSTANCE)
        pairs = []
        for instance in instances:
            index = integer(instance, t.CHANNEL_DEFINITION_INDEX)
            if index >= len(definitions):
                raise ValidationError("channel definition index out of range")
            pairs.append((instance, definitions[index]))
        return pairs

    def validate_instances(self) -> None:
        pairs = self.channel_pairs
        if not pairs:
            raise ValidationError("observation requires channel instances")
        nodes: dict[tuple[int, int], Collection] = {}
        references: dict[tuple[int, int], tuple[int, int]] = {}
        for ci, (instance, definition) in enumerate(pairs):
            definitions = children(definition, t.SERIES_DEFINITIONS, t.ONE_SERIES_DEFINITION)
            instances = children(instance, t.SERIES_INSTANCES, t.ONE_SERIES_INSTANCE)
            if len(instances) != len(definitions):
                raise ValidationError("series instance count differs from definition count")
            for si, series in enumerate(instances):
                nodes[ci, si] = series
                channel = series.get(t.SERIES_SHARE_CHANNEL_INDEX)
                shared = series.get(t.SERIES_SHARE_SERIES_INDEX)
                if (channel is None) != (shared is None):
                    raise ValidationError("incomplete series sharing reference")
                if channel is not None:
                    references[ci, si] = (integer(series, t.SERIES_SHARE_CHANNEL_INDEX),
                                          integer(series, t.SERIES_SHARE_SERIES_INDEX))
                else:
                    require(series, t.SERIES_VALUES, Vector)
        resolved: set[tuple[int, int]] = set()
        for node in nodes:
            path: set[tuple[int, int]] = set()
            current = node
            while current in references and current not in resolved:
                if current in path:
                    raise ValidationError("cyclic series sharing")
                path.add(current)
                current = references[current]
                if current not in nodes:
                    raise ValidationError("series sharing index out of range")
            resolved.update(path)


class LogicalFile:
    """Complete sequence with observation/source/settings bindings."""

    def __init__(self, records: Iterable[Record]):
        self.records = list(records)
        if not self.records or self.records[0].type_tag != t.CONTAINER:
            raise ValidationError("first record must be container")
        self.container = RecordView(self.records[0])
        self.sources: list[RecordView] = []
        self.observations: list[ObservationRecordView] = []
        source: RecordView | None = None
        settings: RecordView | None = None
        for record in self.records[1:]:
            if record.type_tag == t.CONTAINER:
                raise ValidationError("duplicate container record")
            if record.type_tag == t.DATA_SOURCE:
                source, settings = RecordView(record), None
                self.sources.append(source)
            elif record.type_tag == t.MONITOR_SETTINGS:
                if source is None:
                    raise ValidationError("monitor settings require a data source")
                settings = RecordView(record)
            elif record.type_tag == t.OBSERVATION:
                if source is None:
                    raise ValidationError("observation requires a data source")
                self.observations.append(ObservationRecordView(record, source, settings))

    def validate(self) -> None:
        compression_mode(self.container.physical)
        _fields(self.container.body, {t.CREATION: P.TIMESTAMP},
                {t.VERSION_INFO: P.UINT4, t.FILE_NAME: P.CHAR1})
        version = cast(Vector, require(self.container.body, t.VERSION_INFO, Vector))
        if version.count != 4:
            raise ValidationError("VersionInfo must contain four values")
        for source in self.sources:
            _fields(source.body, {t.DATA_SOURCE_TYPE: P.GUID, t.EFFECTIVE: P.TIMESTAMP},
                    {t.DATA_SOURCE_NAME: P.CHAR1})
            definitions = children(source.body, t.CHANNEL_DEFINITIONS, t.ONE_CHANNEL_DEFINITION)
            if not definitions:
                raise ValidationError("data source requires channel definitions")
            for channel in definitions:
                _fields(channel, {t.PHASE_ID: P.UINT4, t.QUANTITY_TYPE_ID: P.GUID,
                                  t.QUANTITY_MEASURED_ID: P.UINT4}, {})
                series = children(channel, t.SERIES_DEFINITIONS, t.ONE_SERIES_DEFINITION)
                if not series:
                    raise ValidationError("channel requires series definitions")
                for definition in series:
                    _fields(definition, {t.VALUE_TYPE_ID: P.GUID, t.QUANTITY_UNITS_ID: P.UINT4,
                                        t.QUANTITY_CHARACTERISTIC_ID: P.GUID,
                                        t.STORAGE_METHOD_ID: P.UINT4}, {})
        active_source: RecordView | None = None
        for record in self.records:
            if record.type_tag == t.DATA_SOURCE:
                active_source = RecordView(record)
            if record.type_tag == t.MONITOR_SETTINGS:
                root = RecordView(record).body
                _fields(root, {t.EFFECTIVE: P.TIMESTAMP, t.TIME_INSTALLED: P.TIMESTAMP,
                               t.USE_CALIBRATION: P.BOOLEAN4, t.USE_TRANSDUCER: P.BOOLEAN4}, {})
                settings = children(root, t.CHANNEL_SETTINGS_ARRAY, t.ONE_CHANNEL_SETTING)
                assert active_source is not None
                count = len(children(active_source.body, t.CHANNEL_DEFINITIONS, t.ONE_CHANNEL_DEFINITION))
                indexes = [integer(setting, t.CHANNEL_DEFINITION_INDEX) for setting in settings]
                if any(index >= count for index in indexes) or len(set(indexes)) != len(indexes):
                    raise ValidationError("invalid/duplicate channel setting index")
        for observation in self.observations:
            _fields(observation.body, {t.TIME_CREATE: P.TIMESTAMP, t.TIME_START: P.TIMESTAMP,
                                       t.TRIGGER_METHOD: P.UINT4}, {t.OBSERVATION_NAME: P.CHAR1})
            observation.validate_instances()
