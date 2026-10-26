# Native PQDIF Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking. The user authorized uninterrupted engineering decisions and execution.

**Goal:** Deliver an installable native Python PQDIF reader/writer with layered APIs and independently verified interoperability.

**Architecture:** Ordered raw physical trees preserve data; context-aware logical views validate associations; high-level objects provide analysis and construction. Gemstone runs only as a test oracle.

**Tech Stack:** Python >=3.11, stdlib struct/uuid/zlib/dataclasses, optional NumPy, setuptools, pytest/Hypothesis, mypy/Ruff, portable .NET 9 test oracle.

**Spec:** `docs/superpowers/specs/2026-10-26-pqdif-design.md`

## Global Constraints

- MIT; `import pqdif`; prefer `pqdif` repository/distribution.
- No .NET runtime dependency in the Python library.
- Both reading/writing; none and record-level zlib compression.
- Semantic equivalence with preservation of raw unknown-tag values and order.
- IEEE 1159.3-2025 is the target; document gaps without claiming certification.
- Every implementation task requires observed RED then GREEN before commit.

## Review Focus

- Hostile counts, links and decompression expansion: reject before expensive allocation.
- Unknown opaque payloads with internal pointers: preserve reading, refuse unsafe relocation.
- Shared and increment-encoded series: bounded expansion, detect cycles and bad indexes.
- Multiple data sources/settings: reset context on source changes; do not lose intervening records.
- Read/edit/write of known metadata: preserve unknown nested data and raw numeric encodings.

## File map

`src/pqdif/{types,elements,codec,physical,tags,logical,api}.py` implement the layers.
`src/pqdif/data/` holds pinned upstream metadata, `py.typed` marks typing.
`tests/test_{elements,codec,physical,logical,api,properties}.py` prove native behavior.
`tests/interop/` holds live oracle tests, C# CLI and committed binary fixtures.
`tools/` contains reproducible metadata/oracle bootstrap utilities.
`docs/{compatibility,architecture,development}.md` record public contracts.
`docs/superpowers/execution.md` records decisions, RED/GREEN and review results.

### Task 1: Typed physical values and packaging

**Files:** `pyproject.toml`, `src/pqdif/{__init__,types,elements,errors}.py`, `tests/test_elements.py`, license/notices.
**Produces:** `PhysicalType`, `ElementType`, `Timestamp`, `Limits`; `Scalar(tag,type,raw)`, `Vector(tag,type,raw)`, `Collection(tag,elements)`, `OpaqueElement`; `PqdifFormatError`, `UnsupportedFeatureError`, `ValidationError`.

- [x] Write parameterized tests for all 17 types, timestamp precision, GUID order, CHAR1/2, invalid lengths, duplicate tags, exact NaN bytes and read-only NumPy views.
- [x] Run `python -m pytest tests/test_elements.py -q`; observe missing API failures.
- [x] Implement raw-byte models and explicit pack/unpack/conversion helpers; configure package and optional extras.
- [x] Run element tests; commit typed physical model.

### Task 2: Collection codec

**Files:** `src/pqdif/codec.py`, `tests/test_codec.py`.
**Consumes:** Task 1 models/limits/errors.
**Produces:** `encode_collection(root: Collection, *, limits: Limits = ...) -> bytes`; `decode_collection(data: bytes, *, tag: UUID = ..., limits: Limits = ...) -> Collection`.

- [x] Test hand-built embedded and linked descriptors, nested absolute links, four-byte padding, unknown-tag semantics, opaque relocation refusal, out-of-bounds/cyclic links and count/depth limits.
- [x] Run codec tests and observe RED.
- [x] Implement bounded traversal and canonical writer with cycle detection; preserve descriptor reserved data.
- [x] Run elements+codec tests; commit codec.

### Task 3: Records and compression

**Files:** `src/pqdif/physical.py`, `tests/test_physical.py`.
**Produces:** `Record(type_tag, body, ...)`, `read_records(source, *, limits, verify_checksum) -> list[Record]`, `write_records(records, target, *, limits) -> None`; in-memory `loads_records`/`dumps_records`.

- [x] Test independent 64-byte headers, record links, all compression declarations, checksum errors, zlib corruption/expansion, truncation, reserved/extensions, unknown records, blank bodies, caller stream lifetime.
- [x] Run physical tests and observe RED.
- [x] Implement bounded record codec and container-driven compression; reject unsupported modes before interpreting compressed data.
- [x] Run full native tests; commit physical reader/writer.

### Task 4: Registry and logical associations

**Files:** `src/pqdif/{tags,logical}.py`, `src/pqdif/data/`, `tools/generate_metadata.py`, `tests/test_logical.py`.
**Produces:** `tags` constants/registry, `LogicalFile(records)` with `container`, context-bound observations, source/settings and `validate()`.

- [x] Test provenance-pinned registry entries; required fields, duplicate singleton ambiguity, source/settings reset, multiple sources, unknown enums/records, bad channel indexes/counts.
- [x] Run logical tests and observe RED.
- [x] Generate metadata with upstream attribution; implement tree views and context validation, preserving original sequence.
- [x] Run native suite; commit registry/logical layer.

### Task 5: High-level construction and analysis

**Files:** `src/pqdif/api.py`, public exports, `tests/test_api.py`.
**Produces:** `PqdifFile`, `Observation`, `Channel`, `Series`, `read`, `write`, `loads`, `dumps`.

- [x] Test creation with required definitions; several observations; edit-known/preserve-unknown at every level; numeric dtype mapping; scales/offsets; increment and shared series; cycle/index/expansion guards; transducer behavior and unsupported calibration.
- [x] Run API tests and observe RED.
- [x] Implement construction and live views; bound engineering-value expansion; keep raw values accessible; provide NumPy conversion.
- [x] Run all native tests; commit high-level API.

### Task 6: Independent Gemstone interoperability

**Files:** `tests/interop/oracle/{Oracle.csproj,Program.cs}`, fixtures/provenance, `tests/interop/test_gemstone.py`, `tools/bootstrap_oracle.py`.
**Consumes:** Complete native API; pinned Gemstone source outside runtime package.
**Produces:** deterministic generate/inspect/rewrite commands and canonical physical JSON.

- [x] Write cross-implementation tests that require independent raw-tree equality in both directions for none/zlib and logical numeric interpretation, all physical types and unknown nested metadata.
- [x] Run required-oracle tests and observe RED before writing CLI.
- [x] Build a CLI against the actual pinned Gemstone library, generate checked-in fixtures and canonical JSON; implement bootstrap with source pin/hash.
- [x] Run live tests in both directions; record commands/provenance; commit fixtures/harness.

### Task 7: Hardening, review and public documentation

**Files:** property tests, README/examples, docs, CI workflows, contribution/security guidance.

- [x] Add Hypothesis semantic-tree roundtrips and malformed-input tests, targeting limits and parser error consistency; observe RED for new missing behavior and fix via TDD.
- [x] Run pytest, Ruff, mypy; build wheel/sdist and test a clean installed wheel including metadata and optional NumPy.
- [x] Independently review the complete branch against the spec; regression tests before fixes; rerun all checks.
- [x] Document support matrix, public APIs, bounded reading, compression and precision/opaque limits, provenance and fixture regeneration; commit.

### Task 8: Repository and deliverables

**Files:** Git remote, final execution log; output wheel/sdist and brief report.

- [ ] Check authenticated account and name availability; create public `pqdif` repository if absent, falling back to `pypqdif` only if necessary. Never overwrite unrelated work.
- [ ] Push reviewed feature branch and open a reviewable PR with requirements/testing/support limitations; attach PR to chat.
- [ ] Verify remote repository/PR, final test counts, clean status and install artifacts. No PyPI publication.

## Completion contract

Plan steps are complete only with recorded observed outcomes. If an external
permission or normative reference blocks an item, describe the specific remaining
item accurately; do not relabel a skipped oracle test as passing conformance.

## Plan self-review

All three layer interfaces match their consuming tasks. Compression belongs to
physical records; logical validation does not prevent low-level preservation.
Each Review Focus item is owned by Tasks 2, 3, 4 or 5 with an explicit test.
The design builder check reported “nothing important left”. User authorization
to execute supersedes routine approval handoffs in the workflow skills.
