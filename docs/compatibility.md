# Compatibility and evidence

## Target and present release

The primary target is the active [IEEE 1159.3-2025 edition](https://standards.ieee.org/ieee/1159.3/10437/),
published July 22, 2025. The [working group](https://sagroups.ieee.org/1159-3/)
also identifies the 2019 corrigendum and current revision work.

This is an initial alpha, not a declaration of complete/certified 2025 conformance.
The full current normative text and a broad independent conformance corpus have
not been available for exhaustive verification. Agreement with Gemstone establishes
interoperability for tested files, not compliance with every rule of a newer edition.

| Area | Implemented and tested | Limit or qualification |
| --- | --- | --- |
| Physical types | All 17 types as scalars/vectors | CHAR2 scalar values are UTF-16 code units |
| Collections | Ordered nesting, duplicates, embedded/linked values | Configurable depth/count bounds; unsafe overlap rejected |
| Headers | Signature, 64-byte base, extra bytes, reserved bytes, next links | Signed 32-bit addressing; finite complete files |
| Checksums | Adler-32 over stored bodies; zero means unspecified | Other checksum algorithms require explicit `verify_checksum=False` |
| Compression | Read/write record-level zlib; uncompressed container | Deprecated total-file and PKZIP, and unknown combinations rejected |
| Logical records | Container, source, settings, observation, definition/instance links | Known required fields and selected structural rules; not exhaustive normative validation |
| Extensions | Unknown GUID tags and record types retained | Unknown physical encodings may not be safely relocatable |
| Numeric conversion | Explicit values, scale/offset, increment expansion, sharing, transducer ratio | Calibration and scaled timestamps raise explicitly; raw representation remains accessible |
| NumPy | Numeric dtype mapping; read-only views for untransformed series | Optional extra; complex supported; timestamp/GUID/character vectors have no numeric array view |
| File I/O | Paths, binary streams, memory; partial reads/writes | Reads buffer the bounded complete file; no asynchronous/live network streaming API |
| Legacy/vendor quirks | Raw preservation where structurally safe | No permissive repair mode or vendor-specific workarounds |

## Preservation

The physical tree retains exact scalar/vector bytes, including NaN payloads,
noncanonical true booleans and timestamp fractions, plus GUIDs, element order,
duplicate extension tags, descriptor reserved bytes and record header extensions.
Logical views update individual known fields, retaining unrelated metadata.

Original allocation padding, inline unused bytes, record gaps, checksum values,
compression images and placement are not promised to be reproduced. Writers
recompute them. A zero-body record remains a zero-body record. A dictionary keyed
by GUID would lose duplicate elements; this implementation deliberately uses lists.

An unknown tag with a recognized physical type is fully portable. An unknown
physical kind/type is returned as `OpaqueElement`. Embedded opaque values can be
rewritten. Out-of-line opaque bytes may contain unknown absolute body pointers;
rewriting raises `UnsupportedFeatureError` unless the caller sets
`relocatable=True` after determining that relocation is safe. This opt-in is never
made automatically.

## Independent interoperability

The test-only oracle builds the actual Gemstone.PQDIF project from:

- Repository: https://github.com/gemstone/pqdif
- Commit: `296d859d094347420f22415b91cfe428ff87687b`
- Assembly version: `1.0.185`
- Initial fixture generator SDK: .NET `9.0.320`
- Fixture hashes: `tests/interop/fixtures/provenance.json`

The corpus includes all physical scalar/vector types, raw special floating-point
patterns, nested vendor GUIDs, explicit/scaled/increment series and none/zlib
compression. Tests compare canonical raw trees, all numeric engineering series,
Python -> Gemstone parsing/rewriting, Gemstone -> Python parsing/rewriting, and
deterministic regeneration. Normal tests require committed fixtures. Required
live-oracle mode fails if its tooling is absent.

## Multi-rate increment discrepancy

Input `[3, 2, 1, 2, 10, 2, 100]` encodes three segments of two points with increments
1, 10 and 100. Python expands this to `[0, 1, 2, 12, 22, 122]`: emit the current
coordinate, then advance by the current segment's increment. This agrees with
`CPQDIF_R_Observation::_GenerateSeriesData` in the IEEE project's native reference:

- [IEEE PQDIFNet source](https://opensource.ieee.org/pqdif/pqdifnet)
- Commit: `7cb74a0999134ad67d9e40485e4388e89db1fef1`
- File: `pqdiflib/rec_observ.cpp`, `_GenerateSeriesData`

Gemstone's `SeriesInstance.GetOriginalValues` assigns the next origin using only
the immediately previous segment, giving `[0, 1, 2, 12, 20, 120]` here. The IEEE
repository's C# validator has another boundary convention. The library follows the
native reference's cumulative convention, documents the disagreement, and tests
that raw multi-rate files still interchange losslessly. This source comparison is
not a substitute for verifying the current normative clause.

## Remaining conformance work

Before declaring full 2025 compatibility: audit all normative clauses and identifier
updates, obtain diverse independently produced files, expand context-sensitive
validation beyond the presently tested rules, verify calibration and timestamp
conversion semantics, and test additional architectures and device vendors.
Deprecated compression and vendor recovery remain separate compatibility work.
