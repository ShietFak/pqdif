"""PQDIF wire types; all values use little-endian encoding."""
from __future__ import annotations

import struct
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import IntEnum, IntFlag
from typing import TypeAlias, cast
from uuid import UUID


class ElementType(IntEnum):
    COLLECTION = 1
    SCALAR = 2
    VECTOR = 3


class PhysicalType(IntEnum):
    BOOLEAN1 = 1
    BOOLEAN2 = 2
    BOOLEAN4 = 3
    CHAR1 = 10
    CHAR2 = 11
    INT1 = 20
    INT2 = 21
    INT4 = 22
    UINT1 = 30
    UINT2 = 31
    UINT4 = 32
    REAL4 = 40
    REAL8 = 41
    COMPLEX8 = 42
    COMPLEX16 = 43
    TIMESTAMP = 50
    GUID = 60

    @property
    def size(self) -> int:
        return struct.calcsize("<" + _FORMATS[self])


class CompressionStyle(IntEnum):
    NONE = 0
    TOTAL_FILE = 1
    RECORD = 2


class CompressionAlgorithm(IntEnum):
    NONE = 0
    ZLIB = 1
    PKZIP = 64


class StorageMethod(IntFlag):
    VALUES = 1
    SCALED = 2
    INCREMENT = 4


@dataclass(frozen=True)
class Limits:
    """Resource ceilings; raise explicit errors rather than allocating past them."""

    max_file_bytes: int = 512 * 1024 * 1024
    max_record_bytes: int = 64 * 1024 * 1024
    max_total_decoded_bytes: int = 512 * 1024 * 1024
    max_elements: int = 1_000_000
    max_vector_values: int = 8_000_000
    max_records: int = 100_000
    max_depth: int = 64
    max_expanded_values: int = 8_000_000

    def __post_init__(self) -> None:
        if any(value <= 0 for value in vars(self).values()):
            raise ValueError("limits must be positive")


DEFAULT_LIMITS = Limits()
EMPTY_TAG = UUID(int=0)
EPOCH = datetime(1900, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Timestamp:
    """Exact PQDIF day/seconds representation; datetime conversion rounds to microseconds."""

    days: int
    seconds: float

    def to_datetime(self) -> datetime:
        return EPOCH + timedelta(days=self.days, seconds=self.seconds)

    @classmethod
    def from_datetime(cls, value: datetime) -> Timestamp:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp requires a timezone-aware datetime")
        delta = value.astimezone(timezone.utc) - EPOCH
        if delta.days < 0:
            raise ValueError("PQDIF timestamps cannot precede 1900-01-01")
        return cls(delta.days, delta.seconds + delta.microseconds / 1_000_000)


Value: TypeAlias = bool | int | float | complex | str | UUID | Timestamp

_FORMATS: dict[PhysicalType, str] = {
    PhysicalType.BOOLEAN1: "B", PhysicalType.BOOLEAN2: "H", PhysicalType.BOOLEAN4: "I",
    PhysicalType.CHAR1: "c", PhysicalType.CHAR2: "2s",
    PhysicalType.INT1: "b", PhysicalType.INT2: "h", PhysicalType.INT4: "i",
    PhysicalType.UINT1: "B", PhysicalType.UINT2: "H", PhysicalType.UINT4: "I",
    PhysicalType.REAL4: "f", PhysicalType.REAL8: "d",
    PhysicalType.COMPLEX8: "ff", PhysicalType.COMPLEX16: "dd",
    PhysicalType.TIMESTAMP: "Id", PhysicalType.GUID: "16s",
}

NUMPY_DTYPES: dict[PhysicalType, str] = {
    PhysicalType.BOOLEAN1: "u1", PhysicalType.BOOLEAN2: "<u2", PhysicalType.BOOLEAN4: "<u4",
    PhysicalType.INT1: "i1", PhysicalType.INT2: "<i2", PhysicalType.INT4: "<i4",
    PhysicalType.UINT1: "u1", PhysicalType.UINT2: "<u2", PhysicalType.UINT4: "<u4",
    PhysicalType.REAL4: "<f4", PhysicalType.REAL8: "<f8",
    PhysicalType.COMPLEX8: "<c8", PhysicalType.COMPLEX16: "<c16",
}


def pack_value(physical_type: PhysicalType, value: Value) -> bytes:
    args: tuple[object, ...] = (value,)
    if physical_type == PhysicalType.GUID:
        if not isinstance(value, UUID):
            raise ValueError("GUID requires UUID")
        args = (value.bytes_le,)
    elif physical_type == PhysicalType.TIMESTAMP:
        if not isinstance(value, Timestamp):
            raise ValueError("TIMESTAMP requires Timestamp")
        args = (value.days, value.seconds)
    elif physical_type in (PhysicalType.COMPLEX8, PhysicalType.COMPLEX16):
        number = complex(cast("complex", value))
        args = (number.real, number.imag)
    elif physical_type in (PhysicalType.CHAR1, PhysicalType.CHAR2):
        if not isinstance(value, str) or len(value) != 1:
            raise ValueError("character requires one character")
        raw = value.encode("ascii" if physical_type == PhysicalType.CHAR1 else "utf-16-le")
        if len(raw) != physical_type.size:
            raise ValueError("character does not fit physical type")
        args = (raw,)
    elif physical_type in (PhysicalType.BOOLEAN1, PhysicalType.BOOLEAN2, PhysicalType.BOOLEAN4):
        args = (int(bool(value)),)
    try:
        return struct.pack("<" + _FORMATS[physical_type], *args)
    except (struct.error, OverflowError, TypeError) as error:
        raise ValueError(f"value does not fit {physical_type.name}: {value!r}") from error


def unpack_value(physical_type: PhysicalType, raw: bytes) -> Value:
    values = struct.unpack("<" + _FORMATS[physical_type], raw)
    if physical_type == PhysicalType.GUID:
        return UUID(bytes_le=raw)
    if physical_type == PhysicalType.TIMESTAMP:
        return Timestamp(values[0], values[1])
    if physical_type in (PhysicalType.COMPLEX8, PhysicalType.COMPLEX16):
        return complex(*values)
    if physical_type in (PhysicalType.CHAR1, PhysicalType.CHAR2):
        return raw.decode("ascii" if physical_type == PhysicalType.CHAR1 else "utf-16-le")
    if physical_type in (PhysicalType.BOOLEAN1, PhysicalType.BOOLEAN2, PhysicalType.BOOLEAN4):
        return bool(values[0])
    return cast(Value, values[0])
