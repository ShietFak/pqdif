"""High-level construction and live views over the complete physical file."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import cast
from uuid import UUID

from . import tags as t
from .elements import Collection, Scalar, Vector
from .errors import ValidationError
from .logical import LogicalFile, ObservationRecordView, RecordView, children, require
from .physical import Record, Source, compression_mode, dumps_records, loads_records
from .physical import read_records, write_records
from .series import Series
from .types import DEFAULT_LIMITS, Limits, PhysicalType, Timestamp

WAVEFORM = UUID("67f6af80-f753-11cf-9d89-0080c72e70a3")
MEASURED = UUID("e6b51730-f747-11cf-9d89-0080c72e70a3")


def _timestamp(value: datetime | Timestamp) -> Timestamp:
    return value if isinstance(value, Timestamp) else Timestamp.from_datetime(value)


def _text(tag: UUID, value: str) -> Vector:
    return Vector.from_text(tag, value, unicode=not value.isascii())


class Channel:
    """A channel definition and observation instance. Metadata remains editable."""

    def __init__(self, name: str, series: Iterable[Series], *, phase: int = 0,
                 quantity: int = 0, quantity_type: UUID = WAVEFORM):
        values = list(series)
        self.definition = Collection(t.ONE_CHANNEL_DEFINITION, [
            _text(t.CHANNEL_NAME, name), Scalar.from_value(t.PHASE_ID, PhysicalType.UINT4, phase),
            Scalar.from_value(t.QUANTITY_TYPE_ID, PhysicalType.GUID, quantity_type),
            Scalar.from_value(t.QUANTITY_MEASURED_ID, PhysicalType.UINT4, quantity),
            Collection(t.SERIES_DEFINITIONS, [value.definition for value in values]),
        ])
        self.physical = Collection(t.ONE_CHANNEL_INSTANCE, [
            Scalar.from_value(t.CHANNEL_DEFINITION_INDEX, PhysicalType.UINT4, 0),
            Collection(t.SERIES_INSTANCES, [value.physical for value in values]),
        ])
        self._observation: Observation | None = None
        self._limits = DEFAULT_LIMITS

    @classmethod
    def _bind(cls, physical: Collection, definition: Collection, observation: Observation,
              limits: Limits) -> Channel:
        result = cls.__new__(cls)
        result.physical, result.definition = physical, definition
        result._observation, result._limits = observation, limits
        return result

    @property
    def name(self) -> str:
        element = self.definition.get(t.CHANNEL_NAME)
        return element.text if isinstance(element, Vector) else ""

    @name.setter
    def name(self, value: str) -> None:
        self.definition.replace(_text(t.CHANNEL_NAME, value))

    @property
    def series(self) -> list[Series]:
        definitions = children(self.definition, t.SERIES_DEFINITIONS, t.ONE_SERIES_DEFINITION)
        instances = children(self.physical, t.SERIES_INSTANCES, t.ONE_SERIES_INSTANCE)
        if len(definitions) != len(instances):
            raise ValidationError("series instance count differs from definition count")
        return [Series._bind(instance, definition, self, self._limits)
                for instance, definition in zip(instances, definitions, strict=True)]


class Observation:
    """An observation bound to a source and optional monitor settings."""

    def __init__(self, name: str, start: datetime | Timestamp, channels: Iterable[Channel], *,
                 source_name: str = "pqdif", trigger: int = 0, settings: Record | None = None):
        stamp = _timestamp(start)
        channel_list = list(channels)
        if len({id(channel.physical) for channel in channel_list}) != len(channel_list):
            raise ValidationError("a channel instance cannot occur twice in an observation")
        for index, channel in enumerate(channel_list):
            channel.physical.replace(Scalar.from_value(t.CHANNEL_DEFINITION_INDEX,
                                                        PhysicalType.UINT4, index))
        source = Record(t.DATA_SOURCE, Collection(t.DATA_SOURCE, [
            Scalar.from_value(t.DATA_SOURCE_TYPE, PhysicalType.GUID, MEASURED),
            _text(t.DATA_SOURCE_NAME, source_name),
            Scalar.from_value(t.EFFECTIVE, PhysicalType.TIMESTAMP, stamp),
            Collection(t.CHANNEL_DEFINITIONS, [c.definition for c in channel_list]),
        ]))
        record = Record(t.OBSERVATION, Collection(t.OBSERVATION, [
            _text(t.OBSERVATION_NAME, name),
            Scalar.from_value(t.TIME_START, PhysicalType.TIMESTAMP, stamp),
            Scalar.from_value(t.TIME_CREATE, PhysicalType.TIMESTAMP, stamp),
            Scalar.from_value(t.TRIGGER_METHOD, PhysicalType.UINT4, trigger),
            Collection(t.CHANNEL_INSTANCES, [c.physical for c in channel_list]),
        ]))
        if settings is not None and settings.type_tag != t.MONITOR_SETTINGS:
            raise ValidationError("settings must be a monitor-settings record")
        self._view = ObservationRecordView(record, RecordView(source),
                                            RecordView(settings) if settings else None)
        self._limits = DEFAULT_LIMITS

    @classmethod
    def _bind(cls, view: ObservationRecordView, limits: Limits) -> Observation:
        result = cls.__new__(cls)
        result._view, result._limits = view, limits
        return result

    @property
    def physical(self) -> Record:
        return self._view.physical

    @property
    def source(self) -> RecordView:
        return self._view.source

    @property
    def settings(self) -> RecordView | None:
        return self._view.settings

    @property
    def name(self) -> str:
        return cast(str, self._view.value(t.OBSERVATION_NAME, ""))

    @name.setter
    def name(self, value: str) -> None:
        self._view.set_text(t.OBSERVATION_NAME, value)

    @property
    def start(self) -> Timestamp:
        scalar = cast(Scalar, require(self._view.body, t.TIME_START, Scalar))
        if scalar.physical_type != PhysicalType.TIMESTAMP:
            raise ValidationError("TimeStart must be TIMESTAMP")
        return cast(Timestamp, scalar.value)

    @start.setter
    def start(self, value: datetime | Timestamp) -> None:
        self._view.set_scalar(t.TIME_START, PhysicalType.TIMESTAMP, _timestamp(value))

    @property
    def channels(self) -> list[Channel]:
        return [Channel._bind(instance, definition, self, self._limits)
                for instance, definition in self._view.channel_pairs]


class PqdifFile:
    """A complete ordered physical sequence with high-level logical projections.

    Mutate ``records`` for extensions, or known view properties for ordinary edits.
    Container/source records and all unknown elements stay in this sequence.
    """

    def __init__(self, observations: Iterable[Observation] = (), *, compressed: bool = False,
                 filename: str = "data.pqd", created: datetime | Timestamp | None = None):
        stamp = _timestamp(created if created is not None else datetime.now(timezone.utc))
        self.records = [Record(t.CONTAINER, Collection(t.CONTAINER, [
            Vector.from_values(t.VERSION_INFO, PhysicalType.UINT4, [1, 5, 1, 0]),
            _text(t.FILE_NAME, filename), Scalar.from_value(t.CREATION, PhysicalType.TIMESTAMP, stamp),
            Scalar.from_value(t.COMPRESSION_STYLE, PhysicalType.UINT4, 2 if compressed else 0),
            Scalar.from_value(t.COMPRESSION_ALGORITHM, PhysicalType.UINT4, 1 if compressed else 0),
        ]))]
        self.limits = DEFAULT_LIMITS
        for observation in observations:
            self.records.append(observation.source.physical)
            if observation.settings is not None:
                self.records.append(observation.settings.physical)
            self.records.append(observation.physical)

    @classmethod
    def from_records(cls, records: Iterable[Record], *, limits: Limits = DEFAULT_LIMITS,
                     validate: bool = True) -> PqdifFile:
        result = cls.__new__(cls)
        result.records, result.limits = list(records), limits
        if validate:
            result.validate()
        return result

    @property
    def observations(self) -> list[Observation]:
        return [Observation._bind(view, self.limits) for view in LogicalFile(self.records).observations]

    @property
    def compressed(self) -> bool:
        if not self.records:
            raise ValidationError("file requires a container")
        return compression_mode(self.records[0])

    @compressed.setter
    def compressed(self, value: bool) -> None:
        container = LogicalFile(self.records).container
        container.set_scalar(t.COMPRESSION_STYLE, PhysicalType.UINT4, 2 if value else 0)
        container.set_scalar(t.COMPRESSION_ALGORITHM, PhysicalType.UINT4, 1 if value else 0)

    def validate(self) -> None:
        LogicalFile(self.records).validate()


def loads(data: bytes, *, limits: Limits = DEFAULT_LIMITS, verify_checksum: bool = True,
          validate: bool = True) -> PqdifFile:
    return PqdifFile.from_records(loads_records(data, limits=limits, verify_checksum=verify_checksum),
                                  limits=limits, validate=validate)


def dumps(file: PqdifFile, *, limits: Limits | None = None, validate: bool = True) -> bytes:
    if validate:
        file.validate()
    return dumps_records(file.records, limits=file.limits if limits is None else limits)


def read(source: Source, *, limits: Limits = DEFAULT_LIMITS, verify_checksum: bool = True,
         validate: bool = True) -> PqdifFile:
    return PqdifFile.from_records(read_records(source, limits=limits,
                                               verify_checksum=verify_checksum),
                                  limits=limits, validate=validate)


def write(file: PqdifFile, target: Source, *, limits: Limits | None = None,
          validate: bool = True) -> None:
    if validate:
        file.validate()
    write_records(file.records, target, limits=file.limits if limits is None else limits)
