"""Generative tests use raw bit patterns, independent of Python numeric equality."""

import struct
from uuid import UUID

from hypothesis import given, settings
from hypothesis import strategies as st

from pqdif import Collection, PhysicalType, Record, Scalar, Vector
from pqdif.codec import decode_collection, encode_collection
from pqdif.errors import PqdifError
from pqdif.physical import CONTAINER_TAG, dumps_records, loads_records

tags = st.uuids()
kinds = st.sampled_from(list(PhysicalType))


@st.composite
def leaves(draw):
    tag, kind = draw(tags), draw(kinds)
    if draw(st.booleans()):
        return Scalar(
            tag,
            kind,
            draw(st.binary(min_size=kind.size, max_size=kind.size)),
            reserved=draw(st.integers(0, 255)),
        )
    count = draw(st.integers(0, 6))
    return Vector(
        tag,
        kind,
        draw(st.binary(min_size=count * kind.size, max_size=count * kind.size)),
        reserved=draw(st.integers(0, 255)),
    )


trees = st.recursive(
    leaves(),
    lambda children: st.builds(
        Collection, tags, st.lists(children, max_size=5), reserved=st.integers(0, 255)
    ),
    max_leaves=30,
)


@given(st.lists(trees, max_size=6))
@settings(max_examples=250, deadline=None)
def test_arbitrary_raw_tree_roundtrip_preserves_bit_patterns(elements):
    root = Collection(elements=elements)
    encoded = encode_collection(root)
    result = decode_collection(encoded)
    assert result == root
    assert encode_collection(result) == encoded


@given(st.lists(trees, max_size=6))
@settings(max_examples=150, deadline=None)
def test_linked_records_roundtrip_preserves_raw_tree(elements):
    root = Collection(CONTAINER_TAG)
    vendor = UUID("ffffffff-1111-2222-3333-444444444444")
    records = [Record(CONTAINER_TAG, root), Record(vendor, Collection(vendor, elements))]
    assert loads_records(dumps_records(records)) == records


@given(st.binary(max_size=256))
@settings(max_examples=1500, deadline=None)
def test_random_collection_bytes_are_rejected_or_parse_without_internal_errors(data):
    try:
        decode_collection(data)
    except PqdifError:
        pass


@given(st.binary(max_size=512))
@settings(max_examples=1000, deadline=None)
def test_random_file_bytes_are_rejected_or_parse_without_internal_errors(data):
    try:
        loads_records(data)
    except PqdifError:
        pass


@given(st.integers(0, 35), st.binary(min_size=4, max_size=4))
@settings(max_examples=300, deadline=None)
def test_mutated_valid_descriptor_never_leaks_internal_exceptions(offset, mutation):
    element = Vector.from_values(UUID(int=1), PhysicalType.UINT4, [1, 2, 3])
    body = bytearray(encode_collection(Collection(elements=[element])))
    body[offset : offset + 4] = mutation
    try:
        decode_collection(bytes(body))
    except PqdifError:
        pass


def test_negative_and_extreme_declared_counts_fail_before_allocation():
    for count in [-(2**31), -1, 2**31 - 1]:
        try:
            decode_collection(struct.pack("<i", count))
        except PqdifError:
            continue
        raise AssertionError("unsafe count accepted")
