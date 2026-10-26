"""Stored and engineering-value series views, including sharing and expansion."""
from __future__ import annotations

import math
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from . import tags as t
from .elements import Collection, Scalar, Vector
from .errors import UnsupportedFeatureError, ValidationError
from .logical import children, integer, require
from .types import DEFAULT_LIMITS, Limits, PhysicalType, StorageMethod, Value

if TYPE_CHECKING:
    import numpy.typing as npt
    from .api import Channel

VALUE_TYPE = UUID("67f6af97-f753-11cf-9d89-0080c72e70a3")
NO_CHARACTERISTIC = UUID("a6b31adf-b451-11d1-ae17-0060083a2628")


def _scalar(root: Collection, tag: UUID, kind: PhysicalType, value: Value) -> None:
    root.replace(Scalar.from_value(tag, kind, value))


class Series:
    """A PQDIF series definition and instance with lazy engineering conversion.

    ``values`` supplied to the constructor are the stored values. For INCREMENT
    storage they are ``[rate_count, count_1, increment_1, ...]``. ``raw_values``
    always exposes that encoding; ``values`` expands it and applies enabled scaling.
    """

    def __init__(
        self, values: Iterable[Value], *, units: int = 0,
        physical_type: PhysicalType = PhysicalType.REAL8,
        value_type: UUID = VALUE_TYPE, characteristic: UUID = NO_CHARACTERISTIC,
        storage: int = StorageMethod.VALUES, scale: Value = 1, offset: Value = 0,
        share: tuple[int, int] | None = None,
    ):
        self.physical = Collection(t.ONE_SERIES_INSTANCE)
        self.definition = Collection(t.ONE_SERIES_DEFINITION, [
            Scalar.from_value(t.VALUE_TYPE_ID, PhysicalType.GUID, value_type),
            Scalar.from_value(t.QUANTITY_UNITS_ID, PhysicalType.UINT4, units),
            Scalar.from_value(t.QUANTITY_CHARACTERISTIC_ID, PhysicalType.GUID, characteristic),
            Scalar.from_value(t.STORAGE_METHOD_ID, PhysicalType.UINT4, storage),
        ])
        self._channel: Channel | None = None
        self._limits = DEFAULT_LIMITS
        if share is None:
            self.physical.elements.append(Vector.from_values(t.SERIES_VALUES, physical_type, values))
        else:
            _scalar(self.physical, t.SERIES_SHARE_CHANNEL_INDEX, PhysicalType.UINT4, share[0])
            _scalar(self.physical, t.SERIES_SHARE_SERIES_INDEX, PhysicalType.UINT4, share[1])
        if storage & StorageMethod.SCALED:
            _scalar(self.physical, t.SERIES_SCALE, physical_type, scale)
            _scalar(self.physical, t.SERIES_OFFSET, physical_type, offset)
            # Shared series inherit absent scale/offset from their target.
            if share is not None and scale == 1 and offset == 0:
                self.physical.elements = [e for e in self.physical.elements
                                          if e.tag not in (t.SERIES_SCALE, t.SERIES_OFFSET)]

    @classmethod
    def _bind(cls, physical: Collection, definition: Collection, channel: Channel,
              limits: Limits) -> Series:
        result = cls.__new__(cls)
        result.physical, result.definition = physical, definition
        result._channel, result._limits = channel, limits
        return result

    @property
    def units(self) -> int:
        return integer(self.definition, t.QUANTITY_UNITS_ID)

    @property
    def storage_method(self) -> int:
        return integer(self.definition, t.STORAGE_METHOD_ID)

    def _sharing_chain(self) -> list[Series]:
        chain = []
        seen: set[int] = set()
        current = self
        while True:
            if id(current.physical) in seen:
                raise ValidationError("cyclic series sharing")
            seen.add(id(current.physical))
            chain.append(current)
            channel_index = current.physical.get(t.SERIES_SHARE_CHANNEL_INDEX)
            series_index = current.physical.get(t.SERIES_SHARE_SERIES_INDEX)
            if channel_index is None and series_index is None:
                return chain
            if channel_index is None or series_index is None:
                raise ValidationError("incomplete series sharing reference")
            if current._channel is None or current._channel._observation is None:
                raise ValidationError("shared series must belong to an observation")
            channels = current._channel._observation.channels
            ci = integer(current.physical, t.SERIES_SHARE_CHANNEL_INDEX)
            si = integer(current.physical, t.SERIES_SHARE_SERIES_INDEX)
            if ci >= len(channels) or si >= len(channels[ci].series):
                raise ValidationError("series sharing index out of range")
            current = channels[ci].series[si]

    @property
    def stored_values(self) -> Vector:
        target = self._sharing_chain()[-1]
        return cast(Vector, require(target.physical, t.SERIES_VALUES, Vector))

    @stored_values.setter
    def stored_values(self, value: Vector) -> None:
        if self.physical.get(t.SERIES_SHARE_CHANNEL_INDEX) is not None:
            raise ValidationError("edit shared values through the referenced series")
        replacement = Vector(t.SERIES_VALUES, value.physical_type, value.raw,
                             reserved=value.reserved)
        self.physical.replace(replacement)

    @property
    def raw_values(self) -> tuple[Value, ...]:
        return self.stored_values.values

    def _scale_offset(self) -> tuple[Value, Value]:
        chain = self._sharing_chain()
        def field(tag: UUID, default: Value) -> Value:
            for series in chain:
                element = series.physical.get(tag)
                if element is not None:
                    if not isinstance(element, Scalar):
                        raise ValidationError("series scale/offset must be scalar")
                    return element.value
            return default
        return field(t.SERIES_SCALE, 1), field(t.SERIES_OFFSET, 0)

    def _transducer_ratio(self) -> float:
        if self._channel is None or self._channel._observation is None:
            return 1
        settings = self._channel._observation.settings
        if settings is None:
            return 1
        calibration = settings.body.get(t.USE_CALIBRATION)
        if isinstance(calibration, Scalar) and calibration.value:
            raise UnsupportedFeatureError("engineering conversion with calibration is not implemented")
        enabled = settings.body.get(t.USE_TRANSDUCER)
        if not isinstance(enabled, Scalar) or not enabled.value:
            return 1
        index = integer(self._channel.physical, t.CHANNEL_DEFINITION_INDEX)
        matches = [setting for setting in children(settings.body, t.CHANNEL_SETTINGS_ARRAY,
                                                   t.ONE_CHANNEL_SETTING)
                   if integer(setting, t.CHANNEL_DEFINITION_INDEX) == index]
        if len(matches) > 1:
            raise ValidationError("duplicate channel setting index")
        if not matches:
            return 1
        system = matches[0].get(t.XD_SYSTEM_SIDE_RATIO)
        monitor = matches[0].get(t.XD_MONITOR_SIDE_RATIO)
        if system is None and monitor is None:
            return 1
        if not isinstance(system, Scalar) or not isinstance(monitor, Scalar):
            raise ValidationError("transducer ratio requires system and monitor scalars")
        try:
            numerator, denominator = float(cast(float, system.value)), float(cast(float, monitor.value))
        except (ValueError, TypeError) as error:
            raise ValidationError("invalid transducer ratio") from error
        if not math.isfinite(numerator) or not math.isfinite(denominator) or denominator == 0:
            raise ValidationError("transducer ratio must be finite with nonzero monitor ratio")
        return numerator / denominator

    @property
    def values(self) -> tuple[Value, ...]:
        return self.get_values()

    def get_values(self, *, limits: Limits | None = None) -> tuple[Value, ...]:
        limits = self._limits if limits is None else limits
        storage = self.storage_method
        if storage & ~7 or not storage & (StorageMethod.VALUES | StorageMethod.INCREMENT):
            raise UnsupportedFeatureError(f"unsupported series storage method {storage}")
        ratio = self._transducer_ratio()
        vector = self.stored_values
        if vector.count > limits.max_expanded_values:
            raise ValidationError("series expansion exceeds limit")
        raw = vector.values
        values: tuple[Value, ...] = raw
        if storage & StorageMethod.INCREMENT:
            values = self._expand_increment(raw, limits.max_expanded_values)
        if storage & StorageMethod.SCALED:
            if vector.physical_type == PhysicalType.TIMESTAMP:
                raise UnsupportedFeatureError("scaled timestamps require explicit raw interpretation")
            scale, offset = self._scale_offset()
            try:
                values = tuple(cast(Any, offset) + cast(Any, v) * scale for v in values)
            except (ValueError, TypeError) as error:
                raise ValidationError("non-numeric series scaling") from error
        if ratio != 1:
            if vector.physical_type == PhysicalType.TIMESTAMP:
                return values
            try:
                values = tuple(cast(Any, value) * ratio for value in values)
            except (ValueError, TypeError) as error:
                raise ValidationError("non-numeric series transducer conversion") from error
        return values

    @staticmethod
    def _expand_increment(raw: tuple[Value, ...], limit: int) -> tuple[Value, ...]:
        def count(value: Value) -> int:
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValidationError("invalid increment count")
            result = int(value)
            if result != value:
                raise ValidationError("fractional increment count")
            return result
        if not raw:
            raise ValidationError("empty increment sequence")
        rates = count(raw[0])
        if len(raw) != 1 + rates * 2:
            raise ValidationError("increment rate count does not match vector")
        segments: list[tuple[int, float]] = []
        total = 0
        for i in range(rates):
            number = count(raw[1 + 2 * i])
            step = raw[2 + 2 * i]
            if not isinstance(step, (int, float)) or not math.isfinite(step):
                raise ValidationError("invalid increment rate")
            total += number
            if total > limit:
                raise ValidationError("increment expansion exceeds limit")
            segments.append((number, step))
        result: list[Value] = []
        start = 0.0
        for number, step in segments:
            result.extend(start + i * step for i in range(number))
            start += number * step
        return tuple(result)

    def to_numpy(self, *, engineering: bool = True) -> npt.NDArray[Any]:
        """Numeric arrays; zero-copy/read-only when conversion is unnecessary."""
        import numpy as np

        vector = self.stored_values
        if not engineering:
            return vector.to_numpy()
        if self.storage_method == StorageMethod.VALUES and self._transducer_ratio() == 1:
            return vector.to_numpy()
        result = np.asarray(self.values)
        result.flags.writeable = False
        return result
