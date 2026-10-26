"""Ordered lossless element model. Raw value bytes are the source of truth."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeAlias
from uuid import UUID

from .errors import UnsupportedFeatureError, ValidationError
from .types import EMPTY_TAG, NUMPY_DTYPES, PhysicalType, Value, pack_value, unpack_value

if TYPE_CHECKING:
    import numpy.typing as npt


@dataclass
class Scalar:
    tag: UUID
    physical_type: PhysicalType
    raw: bytes
    reserved: int = field(default=0, kw_only=True)

    def __post_init__(self) -> None:
        self.raw = bytes(self.raw)
        if len(self.raw) != self.physical_type.size:
            raise ValueError("scalar length does not match physical type")

    @classmethod
    def from_value(cls, tag: UUID, physical_type: PhysicalType, value: Value) -> Scalar:
        return cls(tag, physical_type, pack_value(physical_type, value))

    @property
    def value(self) -> Value:
        return unpack_value(self.physical_type, self.raw)

    @value.setter
    def value(self, value: Value) -> None:
        self.raw = pack_value(self.physical_type, value)


@dataclass
class Vector:
    tag: UUID
    physical_type: PhysicalType
    raw: bytes
    reserved: int = field(default=0, kw_only=True)

    def __post_init__(self) -> None:
        self.raw = bytes(self.raw)
        if len(self.raw) % self.physical_type.size:
            raise ValueError("vector length does not match physical type")

    @classmethod
    def from_values(cls, tag: UUID, physical_type: PhysicalType, values: Iterable[Value]) -> Vector:
        return cls(tag, physical_type, b"".join(pack_value(physical_type, v) for v in values))

    @classmethod
    def from_text(cls, tag: UUID, text: str, *, unicode: bool = False) -> Vector:
        kind = PhysicalType.CHAR2 if unicode else PhysicalType.CHAR1
        return cls(tag, kind, (text + "\0").encode("utf-16-le" if unicode else "ascii"))

    @property
    def count(self) -> int:
        return len(self.raw) // self.physical_type.size

    @property
    def values(self) -> tuple[Value, ...]:
        size = self.physical_type.size
        return tuple(
            unpack_value(self.physical_type, self.raw[i : i + size])
            for i in range(0, len(self.raw), size)
        )

    @property
    def text(self) -> str:
        if self.physical_type not in (PhysicalType.CHAR1, PhysicalType.CHAR2):
            raise ValueError("text requires a character vector")
        encoding = "ascii" if self.physical_type == PhysicalType.CHAR1 else "utf-16-le"
        return self.raw.decode(encoding).rstrip("\0")

    def to_numpy(self) -> npt.NDArray[Any]:
        """Read-only zero-copy numeric array; boolean arrays reflect truth semantics."""
        import numpy as np

        if self.physical_type not in NUMPY_DTYPES:
            raise UnsupportedFeatureError("NumPy view requires a numeric physical type")
        result = np.frombuffer(self.raw, dtype=NUMPY_DTYPES[self.physical_type])
        if self.physical_type in (
            PhysicalType.BOOLEAN1,
            PhysicalType.BOOLEAN2,
            PhysicalType.BOOLEAN4,
        ):
            result = result.astype(np.bool_)
            result.flags.writeable = False
        return result


@dataclass
class Collection:
    tag: UUID = EMPTY_TAG
    elements: list[Element] = field(default_factory=list)
    reserved: int = field(default=0, kw_only=True)
    physical_type: int = field(default=0, kw_only=True)

    def all(self, tag: UUID) -> list[Element]:
        return [element for element in self.elements if element.tag == tag]

    def get(self, tag: UUID) -> Element | None:
        matches = self.all(tag)
        if len(matches) > 1:
            raise ValidationError(f"duplicate singleton tag {tag}")
        return matches[0] if matches else None

    def replace(self, element: Element) -> None:
        """Replace a known field, keeping the first occurrence's position."""
        positions = [i for i, value in enumerate(self.elements) if value.tag == element.tag]
        if not positions:
            self.elements.append(element)
            return
        self.elements[positions[0]] = element
        for index in reversed(positions[1:]):
            del self.elements[index]


@dataclass
class OpaqueElement:
    """Unknown physical encoding; out-of-line rewriting requires explicit opt-in.

    The caller may set relocatable=True only when the payload contains no absolute
    links into its original record body. Unknown *tags* do not need this escape hatch.
    """

    tag: UUID
    element_type: int
    physical_type: int
    raw: bytes
    embedded: bool = False
    relocatable: bool = False
    reserved: int = 0


Element: TypeAlias = Scalar | Vector | Collection | OpaqueElement
