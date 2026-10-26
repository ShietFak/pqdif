"""File/record framing and current PQDIF record-level zlib compression."""
from __future__ import annotations

import io
import os
import struct
import zlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import BinaryIO, TypeAlias
from uuid import UUID

from .codec import decode_collection, encode_collection
from .elements import Collection, Scalar
from .errors import PqdifFormatError, UnsupportedFeatureError, ValidationError
from .types import DEFAULT_LIMITS, EMPTY_TAG, Limits, PhysicalType

SIGNATURE = UUID("4a111440-e49f-11cf-9900-505144494600")
CONTAINER_TAG = UUID("89738606-f1c3-11cf-9d89-0080c72e70a3")
COMPRESSION_STYLE_TAG = UUID("8973861b-f1c3-11cf-9d89-0080c72e70a3")
COMPRESSION_ALGORITHM_TAG = UUID("8973861c-f1c3-11cf-9d89-0080c72e70a3")
_HEADER = struct.Struct("<16s16siiiI16s")
Source: TypeAlias = str | os.PathLike[str] | BinaryIO


@dataclass
class Record:
    type_tag: UUID
    body: Collection | None = None
    reserved: bytes = bytes(16)
    header_extra: bytes = b""
    offset: int = field(default=0, compare=False)
    checksum: int = field(default=0, compare=False)

    def __post_init__(self) -> None:
        if self.body is not None and self.body.tag == EMPTY_TAG:
            self.body.tag = self.type_tag
        if len(self.reserved) != 16:
            raise ValueError("record reserved field must be sixteen bytes")


def compression_mode(container: Record) -> bool:
    """Return whether records are zlib-compressed; reject unknown declarations."""
    def number(tag: UUID) -> int:
        element = container.body.get(tag) if container.body else None
        if element is None:
            return 0
        if not isinstance(element, Scalar) or element.physical_type != PhysicalType.UINT4:
            raise ValidationError("compression declaration must be UINT4 scalar")
        return int(element.value)  # type: ignore[arg-type]

    mode = (number(COMPRESSION_STYLE_TAG), number(COMPRESSION_ALGORITHM_TAG))
    if mode == (0, 0):
        return False
    if mode == (2, 1):
        return True
    raise UnsupportedFeatureError(f"unsupported compression style/algorithm {mode}")


def _inflate(data: bytes, limit: int, offset: int) -> bytes:
    decompressor = zlib.decompressobj()
    try:
        result = decompressor.decompress(data, limit + 1)
    except zlib.error as error:
        raise PqdifFormatError(f"invalid zlib stream: {error}", offset) from error
    if len(result) > limit or decompressor.unconsumed_tail:
        raise PqdifFormatError("decoded record exceeds limit", offset)
    if not decompressor.eof or decompressor.unused_data:
        raise PqdifFormatError("truncated zlib stream or trailing compressed data", offset)
    return result


def loads_records(
    data: bytes, *, limits: Limits = DEFAULT_LIMITS, verify_checksum: bool = True,
) -> list[Record]:
    """Parse the linked record chain from an in-memory file.

    Nonzero checksums are interpreted as Adler-32, as emitted by Gemstone.
    Set verify_checksum=False explicitly for a different external checksum scheme.
    """
    if len(data) > limits.max_file_bytes:
        raise PqdifFormatError("file exceeds size limit", 0)
    records: list[Record] = []
    offset = 0
    compressed = False
    total_decoded = 0
    while True:
        if len(records) >= limits.max_records:
            raise PqdifFormatError("record count exceeds limit", offset)
        if offset + _HEADER.size > len(data):
            raise PqdifFormatError("truncated record header", offset)
        signature, tag, header_size, body_size, next_pos, checksum, reserved = (
            _HEADER.unpack_from(data, offset))
        if signature != SIGNATURE.bytes_le:
            raise PqdifFormatError("invalid PQDIF record signature", offset)
        if header_size < 64 or header_size > limits.max_record_bytes:
            raise PqdifFormatError("invalid header size", offset + 32)
        if body_size < 0 or body_size > limits.max_record_bytes:
            raise PqdifFormatError("invalid record body size", offset + 36)
        end = offset + header_size + body_size
        if end > len(data):
            raise PqdifFormatError("truncated record body", offset + header_size)
        type_tag = UUID(bytes_le=tag)
        if not records and type_tag != CONTAINER_TAG:
            raise PqdifFormatError("first record must be container", offset)
        if records and type_tag == CONTAINER_TAG:
            raise PqdifFormatError("duplicate container record", offset)
        if next_pos != 0 and (next_pos < end or next_pos >= len(data)):
            raise PqdifFormatError("invalid next record link or record cycle", offset + 40)
        stored = data[offset + header_size:end]
        if verify_checksum and checksum and zlib.adler32(stored) != checksum:
            raise PqdifFormatError("record checksum mismatch", offset + 44)
        body_bytes = (_inflate(stored, min(limits.max_record_bytes,
                                         limits.max_total_decoded_bytes - total_decoded),
                               offset + header_size)
                      if compressed and stored else stored)
        total_decoded += len(body_bytes)
        if total_decoded > limits.max_total_decoded_bytes:
            raise PqdifFormatError("total decoded bytes exceed limit", offset)
        try:
            body = decode_collection(body_bytes, tag=type_tag, limits=limits) if body_bytes else None
        except PqdifFormatError as error:
            raise PqdifFormatError(f"record body: {error}", offset + header_size) from error
        record = Record(type_tag, body, reserved, data[offset + 64:offset + header_size],
                        offset, checksum)
        records.append(record)
        if len(records) == 1:
            try:
                compressed = compression_mode(record)
            except ValidationError as error:
                raise PqdifFormatError(str(error), offset) from error
        if next_pos == 0:
            if end != len(data):
                raise PqdifFormatError("trailing bytes after terminal record", end)
            return records
        offset = next_pos


def dumps_records(records: Iterable[Record], *, limits: Limits = DEFAULT_LIMITS) -> bytes:
    """Serialize records, recomputing links, allocation sizes and stored-body checksums."""
    iterator = iter(records)
    first = next(iterator, None)
    if first is None or first.type_tag != CONTAINER_TAG:
        raise ValueError("first record must be container")
    compressed = compression_mode(first)
    chunks: list[bytes] = []
    position = 0
    total_decoded = 0
    current = first
    count = 0
    while True:
        following = next(iterator, None)
        count += 1
        if count > limits.max_records:
            raise ValueError("record count exceeds limit")
        if count > 1 and current.type_tag == CONTAINER_TAG:
            raise ValueError("duplicate container record")
        if len(current.reserved) != 16:
            raise ValueError("record reserved field must be sixteen bytes")
        body = encode_collection(current.body, limits=limits) if current.body is not None else b""
        total_decoded += len(body)
        if total_decoded > limits.max_total_decoded_bytes:
            raise ValueError("total decoded bytes exceed limit")
        stored = zlib.compress(body) if compressed and count > 1 and body else body
        if len(stored) > limits.max_record_bytes:
            raise ValueError("stored record exceeds limit")
        header_size = 64 + len(current.header_extra)
        if header_size > limits.max_record_bytes:
            raise ValueError("record header exceeds limit")
        end = position + header_size + len(stored)
        if end > min(limits.max_file_bytes, 2**31 - 1):
            raise ValueError("file exceeds size limit or signed record address range")
        header = _HEADER.pack(SIGNATURE.bytes_le, current.type_tag.bytes_le, header_size,
                              len(stored), end if following else 0,
                              zlib.adler32(stored), current.reserved)
        chunks.append(header + current.header_extra + stored)
        if following is None:
            return b"".join(chunks)
        current, position = following, end


def read_records(
    source: Source, *, limits: Limits = DEFAULT_LIMITS, verify_checksum: bool = True,
) -> list[Record]:
    """Read from a path or current stream position; leave supplied streams open."""
    if isinstance(source, (str, os.PathLike)):
        with open(source, "rb") as stream:
            return read_records(stream, limits=limits, verify_checksum=verify_checksum)
    data = bytearray()
    while True:
        chunk = source.read(min(65536, limits.max_file_bytes + 1 - len(data)))
        if not chunk:
            break
        data += chunk
        if len(data) > limits.max_file_bytes:
            raise PqdifFormatError("file exceeds size limit", 0)
    return loads_records(bytes(data), limits=limits, verify_checksum=verify_checksum)


def write_records(
    records: Iterable[Record], target: Source, *, limits: Limits = DEFAULT_LIMITS,
) -> None:
    """Write a standalone file image at the current position; leave supplied streams open."""
    data = dumps_records(records, limits=limits)
    if isinstance(target, (str, os.PathLike)):
        with open(target, "wb") as stream:
            _write_all(stream, data)
    else:
        _write_all(target, data)


def _write_all(stream: BinaryIO, data: bytes) -> None:
    remaining = memoryview(data)
    while remaining:
        count = stream.write(remaining)
        if count is None or count <= 0:
            raise io.BlockingIOError("binary stream made no write progress")
        remaining = remaining[count:]
