# Native Python PQDIF design

## Intent and authority

Build an MIT-licensed, typed Python library for reading, editing, analyzing and
writing IEEE Power Quality Data Interchange Format files. Distribution and import
name preference is `pqdif`; use `pypqdif` for distribution/repository only if needed.
The user supplied the architecture, scope and authorization to settle routine
engineering decisions and execute without intermediate design approval stops.
The choices below are engineering decisions, not additional user requirements.

Full compatibility is the destination, not a claim established by self-roundtrips.
IEEE 1159.3-2025 is the current target. Public IEEE material, Gemstone source and
actual cross-implementation results determine the support matrix. Do not claim
certified/full 2025 conformance without the complete normative specification and
an independently adequate conformance corpus. Vendor quirks are deferred.

## Sources

- IEEE active edition: https://standards.ieee.org/ieee/1159.3/10437/
- Working group: https://sagroups.ieee.org/1159-3/
- Primary oracle: https://github.com/gemstone/pqdif at
  `296d859d094347420f22415b91cfe428ff87687b`.
- Historical reference: https://github.com/GridProtectionAlliance/gsf/tree/master/Source/Libraries/GSF.PQDIF
- IEEE native reference consulted for multi-rate semantics:
  https://opensource.ieee.org/pqdif/pqdifnet at
  `7cb74a0999134ad67d9e40485e4388e89db1fef1`, `pqdiflib/rec_observ.cpp`.

Gemstone's README describes 2003 support; its agreement is interoperability
evidence, not proof that every 2025 logical rule has been implemented. Derived
identifier/enum metadata retains upstream MIT notices. Do not redistribute IEEE
standards text. Record provenance and hashes for generated fixtures.

## Approaches and decisions

1. Direct C# class port: easy API comparison, but carries .NET conventions and
   may silently discard unknown tags when projecting objects.
2. Independent physical tree plus logical views and a Python facade (selected):
   preserves arbitrary tags and exact value bytes while allowing NumPy views;
   requires explicit validation and links between the layers.
3. Wrap .NET: rejected by the native-runtime requirement.

Python >=3.11; standard library binary codec; NumPy optional extra for array
conversion; setuptools PEP 517 packaging; pytest, Hypothesis, Ruff and mypy for
development. No .NET imports, subprocesses or runtime dependencies in `src/pqdif`.

## Layer 1: physical codec

`types.py` defines all PQDIF physical types, element kinds, compression enums and
timestamp representation. `elements.py` provides ordered collections, scalars,
vectors and opaque elements. Scalars/vectors retain raw little-endian value bytes
so NaN payloads, boolean bit patterns, unknown identifiers and duplicate tags
survive. Values decode on demand. Timestamp stores days since 1900-01-01 and
binary64 seconds, with explicit UTC datetime conversion rather than rounding the
underlying representation. Strings are CHAR1 ASCII or CHAR2 UTF-16LE vectors;
decoding does not alter raw bytes.

`codec.py` reads/writes collection bodies: int32 element count, ordered 28-byte
descriptors (GUID, kind, physical type, embedded flag, reserved byte, 8-byte inline
value or absolute body link and allocation size). Out-of-line payloads are aligned
to four bytes. GUIDs use Windows/.NET little-endian field order. Small scalars
(<8 bytes) are embedded by default; readers accept supported inline sizes <=8.
Collections may nest; duplicate tags and order remain significant. Unknown
descriptor kinds/types are retained as opaque payloads if safely bounded. Opaque
payloads with unknown internal pointers cannot be relocated safely: reject their
rewrite unless embedded or explicitly marked relocatable by the caller. Unknown
tags with known physical encodings are fully editable and rewritable.

`physical.py` handles 64-byte headers, signature, type GUID, sizes, absolute next
record links, reserved bytes/header extensions and Adler-32 over stored body bytes.
It follows the record chain, rejects cycles/backward/overlapping/out-of-range
links, and preserves unknown record types. Blank/zero-body records are supported.
The first container is always uncompressed; its compression tags govern subsequent
records. Write none or record-level zlib. Reject deprecated total-file/PKZIP and
unknown combinations explicitly; never guess a decompressor. Recompute offsets,
checksums and padding on write; byte identity is not promised.

Configurable `Limits` bound input size, stored/uncompressed record sizes, total
decoded bytes, element count, vector count, records and nesting depth. Validate
lengths before allocation, bound zlib expansion, reject truncated/trailing zlib
streams, and include byte offsets in `PqdifFormatError`. Nonzero checksum mismatch
is an error by default; an explicit ignore option supports externally checksummed
files without claiming to validate a different algorithm. Arbitrary reserved and
header-extension bytes are retained.

## Layer 2: logical records

`tags.py` exposes a complete provenance-pinned Gemstone identifier registry rather
than an invented subset. `logical.py` binds container, data-source, monitor-setting
and observation records to their physical trees; active source/settings state is
captured for each observation. A new data source clears old settings. Preserve
unrecognized records in the original sequence. Known logical getters/setters
operate on existing trees and change only named fields. Validation separates
physical safety from required logical fields and linkage checks. Required-field
metadata is context-sensitive; nested rules are not treated as globally required.
Unknown tags/enums are allowed. Structural ambiguity (duplicate singleton tags,
bad definition indexes, mismatched series counts, invalid sharing) raises explicit
validation errors rather than truncating data through zip-like behavior.

## Layer 3: Python API

`read(path_or_binary_stream) -> PqdifFile` and `write(file, path_or_binary_stream)`
own paths they open and leave caller streams open. `loads(bytes)`/`dumps(file)`
serve memory use. A `PqdifFile` holds the complete record sequence and offers
`observations`; observations expose `Channel` objects and channels expose `Series`.
New files can be built from `Observation(name, start, channels)` containing
`Channel(name, series, ...)` and `Series(values, units, ...)`. Builder creates
required data-source/channel/series definitions and observation instances with
explicit defaults, supports several observations/sources and monitor records, and
validates before writing.

Read objects are live views of their physical trees; writing a read file preserves
unknown metadata at all levels, including when a known property is changed.
Series expose raw stored values separately from engineering values. Support
explicit values, scale/offset, increment expansion, series sharing with cycle and
index checks, and transducer ratios when enabled by settings. Do not silently
apply calibration not yet modeled: expose it and raise if conversion would be
misleading. Configurable expansion limits also cover increment-compressed arrays.
NumPy integration uses explicit dtype mappings (no platform-native int assumptions)
and read-only views for unscaled numeric data. Raw timestamp precision is retained.

## Testing and acceptance

Use TDD per task: write tests, observe intended RED, implement, observe GREEN;
record evidence in a committed execution log. Tests include all physical types,
inline/out-of-line scalars, vectors, nesting, duplicate and unknown tags, reserved
bytes, opaque safety, checksum and linked records, compressed/uncompressed,
malformed pointers/counts/headers, decompression limits, semantic roundtrips,
multiple sources/settings, sharing/scale/increment behavior and NumPy.

A separate C# CLI under `tests/interop/oracle` builds against pinned Gemstone.
It generates fixtures and canonical JSON trees using raw values, rewrites Python
output and verifies logical interpretation. Python tests exercise Gemstone ->
Python and Python -> Gemstone for compressed and uncompressed files and compare
canonical trees. Commit deterministic generated fixtures with provenance so normal
tests need no SDK/network. CI must also run the live oracle in a separate job;
oracle-required mode fails rather than silently skipping absent tooling.

Release verification includes full tests, type/lint checks, wheel/sdist build,
clean installed-wheel smoke test, independent review and fixes. Create a public
GitHub repository in the authenticated personal account if absent; do not overwrite
an existing unrelated repository or publish to PyPI. Document support gaps and
reproducible oracle commands. Production-quality engineering is required; full
standards conformance remains an evidence-based milestone.
