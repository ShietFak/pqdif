"""Bounded PQDIF collection-body codec; links are absolute within a record body."""
from __future__ import annotations

import struct
from uuid import UUID

from .elements import Collection, Element, OpaqueElement, Scalar, Vector
from .errors import PqdifFormatError, UnsupportedFeatureError
from .types import DEFAULT_LIMITS, EMPTY_TAG, Limits, PhysicalType

_I32 = struct.Struct("<i")
_LINK = struct.Struct("<ii")


def decode_collection(
    data: bytes, *, tag: UUID = EMPTY_TAG, limits: Limits = DEFAULT_LIMITS,
) -> Collection:
    """Decode a bounded record body, retaining unknown tags and raw value bytes."""
    if len(data) > limits.max_record_bytes:
        raise PqdifFormatError("record body exceeds limit", 0)
    remaining = limits.max_elements

    def check(start: int, size: int, end: int) -> None:
        if start < 0 or size < 0 or start + size > end:
            raise PqdifFormatError("truncated or out-of-bounds payload", start)

    def collection(start: int, end: int, depth: int, collection_tag: UUID) -> Collection:
        nonlocal remaining
        if depth > limits.max_depth:
            raise PqdifFormatError("collection depth exceeds limit", start)
        check(start, 4, end)
        count = _I32.unpack_from(data, start)[0]
        if count < 0 or count > remaining:
            raise PqdifFormatError("invalid element count or element limit exceeded", start)
        remaining -= count
        table_end = start + 4 + count * 28
        check(start, table_end - start, end)
        result = Collection(collection_tag)
        allocations: list[tuple[int, int]] = []
        for index in range(count):
            pos = start + 4 + index * 28
            element_tag = UUID(bytes_le=data[pos:pos + 16])
            kind, physical, embedded, reserved = data[pos + 16:pos + 20]
            if embedded not in (0, 1):
                raise PqdifFormatError("invalid embedded flag", pos + 18)
            payload = pos + 20
            payload_end = payload + 8
            if not embedded:
                payload, allocated = _LINK.unpack_from(data, payload)
                if payload < table_end:
                    raise PqdifFormatError("link overlaps collection table or creates cycle", pos + 20)
                check(payload, allocated, end)
                if allocated <= 0:
                    raise PqdifFormatError("empty linked allocation", pos + 24)
                payload_end = payload + allocated
                allocations.append((payload, payload_end))
            try:
                physical_type = PhysicalType(physical)
            except ValueError:
                physical_type = None

            element: Element
            if kind == 1:
                if embedded:
                    raise PqdifFormatError("collection cannot be embedded", pos)
                element = collection(payload, payload_end, depth + 1, element_tag)
                element.physical_type = physical
                element.reserved = reserved
            elif kind in (2, 3) and physical_type is not None:
                size = physical_type.size
                if kind == 2:
                    if embedded and size > 8:
                        raise PqdifFormatError("scalar too large for inline value", pos)
                    check(payload, size, payload_end)
                    element = Scalar(element_tag, physical_type, data[payload:payload + size],
                                     reserved=reserved)
                else:
                    if embedded:
                        raise PqdifFormatError("vector cannot be embedded", pos)
                    check(payload, 4, payload_end)
                    values = _I32.unpack_from(data, payload)[0]
                    if values < 0 or values > limits.max_vector_values:
                        raise PqdifFormatError("invalid vector count or vector limit exceeded", payload)
                    check(payload + 4, values * size, payload_end)
                    element = Vector(element_tag, physical_type,
                                     data[payload + 4:payload + 4 + values * size], reserved=reserved)
            else:
                element = OpaqueElement(element_tag, kind, physical,
                                        data[payload:payload_end], bool(embedded), reserved=reserved)
            result.elements.append(element)

        # Sorting avoids quadratic interval checks on large descriptor tables.
        allocations.sort()
        for previous, current in zip(allocations, allocations[1:]):
            if current[0] < previous[1]:
                raise PqdifFormatError("overlapping element allocations", current[0])
        return result

    return collection(0, len(data), 0, tag)


def encode_collection(root: Collection, *, limits: Limits = DEFAULT_LIMITS) -> bytes:
    """Encode a canonical body; known values keep their exact bytes and ordering."""
    ancestors: set[int] = set()
    remaining = limits.max_elements

    def collection(value: Collection, base: int, depth: int) -> bytes:
        nonlocal remaining
        if id(value) in ancestors:
            raise ValueError("cyclic collection tree")
        if depth > limits.max_depth:
            raise ValueError("collection depth exceeds limit")
        count = len(value.elements)
        remaining -= count
        if remaining < 0:
            raise ValueError("element limit exceeded")
        table_size = 4 + 28 * count
        if base + table_size > limits.max_record_bytes:
            raise ValueError("record body exceeds limit")
        ancestors.add(id(value))
        descriptors = bytearray(_I32.pack(count))
        payloads: list[bytes] = []
        cursor = base + table_size
        for element in value.elements:
            embedded = False
            if isinstance(element, Collection):
                kind, physical = 1, element.physical_type
                payload = collection(element, cursor, depth + 1)
            elif isinstance(element, Scalar):
                kind, physical = 2, int(element.physical_type)
                if len(element.raw) != element.physical_type.size:
                    raise ValueError("scalar length does not match physical type")
                embedded = element.physical_type.size < 8
                payload = element.raw
            elif isinstance(element, Vector):
                kind, physical = 3, int(element.physical_type)
                if len(element.raw) % element.physical_type.size:
                    raise ValueError("vector length does not match physical type")
                if element.count > limits.max_vector_values:
                    raise ValueError("vector limit exceeded")
                payload = _I32.pack(element.count) + element.raw
            else:
                kind, physical = element.element_type, element.physical_type
                embedded = element.embedded
                if not embedded and not element.relocatable:
                    raise UnsupportedFeatureError("opaque payload is unsafe to relocate")
                if embedded and len(element.raw) != 8:
                    raise ValueError("opaque embedded payload must contain eight bytes")
                payload = element.raw
            descriptors += element.tag.bytes_le + bytes([kind, physical, int(embedded),
                                                          element.reserved])
            if embedded:
                descriptors += payload.ljust(8, b"\0")
            else:
                size = (len(payload) + 3) // 4 * 4
                if cursor + size > limits.max_record_bytes:
                    raise ValueError("record body exceeds limit")
                descriptors += _LINK.pack(cursor, size)
                payloads.append(payload.ljust(size, b"\0"))
                cursor += size
        ancestors.remove(id(value))
        return bytes(descriptors) + b"".join(payloads)

    return collection(root, 0, 0)
