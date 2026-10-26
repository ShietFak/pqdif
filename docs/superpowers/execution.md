# Execution record — 2026-10-26-native-pqdif

Plan: `docs/superpowers/plans/2026-10-26-native-pqdif.md`
Spec: `docs/superpowers/specs/2026-10-26-pqdif-design.md`

## Setup

- Workspace verified separate from Gridsentinel; no preexisting implementation.
- Initialized a new Git repository; implementation on `feat/native-pqdif`.
- Ruling: reuse the dedicated empty workspace, without a second worktree — no
  existing project changes to isolate and the user requested this assigned folder.
- Ruling: execute inline; fresh independent design and final code reviews follow
  the Superpowers workflow. No parallel implementers are needed.
- Ruling: user explicitly authorized design decisions and continued execution;
  do not reintroduce routine approval handoffs from generic skill instructions.
- Design builder check: independent reviewer found “nothing important left”.
- Reference pinned at Gemstone `296d859d094347420f22415b91cfe428ff87687b`.
- Pre-flight: Task 1 models feed Tasks 2–5; Task 2 body codec feeds Task 3;
  Task 3 records feed Task 4 context and Task 5 I/O; Task 4 views feed Task 5;
  Task 6 compares actual native output. No conflicting interfaces found.
- Portable .NET SDK installed in ignored `work/tools/dotnet`, test-only.

## Task evidence

To be appended after each observed RED/GREEN cycle.

### Task 1: complete
RED: 22 tests failed because pqdif was absent. GREEN: 22 passed (Python 3.12). Independent scalar hex expectations, raw precision and NumPy checks passed.

### Task 2: complete
RED: 17 codec tests failed because the codec was absent. GREEN: 39 total tests passed. Independent descriptor bytes, nested links, opaque relocation guard and malformed limits verified.

### Task 3: complete
RED: 19 physical-file tests failed on absent record API. GREEN: 58 native tests passed, including compressed/uncompressed records, Adler-32, header extensions, stream ownership, truncation and bounded inflate.

### Task 4: complete
RED: six logical/registry tests failed on missing interfaces. GREEN: 64 native tests passed. Generated 137 tags and 483 identifiers with source SHA-256; context resets, required fields, index/count and sharing-cycle validation passed.

### Task 5: complete
RED: 15 high-level cases failed on missing public API. GREEN: 79 native tests passed. Live tree edits preserved unknown nested raw values. Added Series in series.py to keep conversion/sharing separate from file construction. Multi-rate increments accumulate segment origins; no calibration conversion is silently guessed.

### Task 6: complete
RED: committed fixtures absent and required live oracle failed setup (2 failed, 5 errors). Built actual pinned Gemstone project with portable .NET 9.0.320 (zero warnings/errors), generated deterministic fixtures with SHA-256 provenance. GREEN: 86 tests passed with PQDIF_REQUIRE_ORACLE=1, including both implementations reading and rewriting each other's none/zlib files. Registry metadata present in install. GitHub repository created at https://github.com/ShietFak/pqdif (empty, not yet pushed).

### Task 7: complete

- Added Hypothesis raw-bit tree/file roundtrips and arbitrary/mutated malformed inputs.
- RED: hardening run exposed 13 failures in UTF-16 code-unit handling, timestamps,
  alignment, empty opaque output, known-property behavior, NumPy limits and validation.
- Independent review reproduced allocation amplification (13.2 MB peak from 71 KB
  input). RED spy regression observed two payload copies before overlap rejection.
  Fixed by preflighting all sibling allocations before any payload copy.
- Independent review reproduced three further cases; RED tests confirmed channel
  reuse mutated earlier observations, explicit identity scaling was lost, and
  character scaling could repeat strings. Fixed owned channel copies, None defaults
  for inheritance, and numeric operands checked before arithmetic.
- RED sharing-chain regression observed 198 full list builds for a 100-node chain.
  Per-traversal context/series caches make each channel list build once.
- Expanded oracle comparison to all numeric series; observed seven RED missing
  canonical fields before extending the actual C# adapter and regenerating JSON.
- Ruling: follow IEEE native reference cumulative multi-rate expansion. Gemstone
  resets segment origins; IEEE C# validator uses another transition convention.
  Added a live test documenting the discrepancy and raw interchange preservation.
  Full current normative verification remains an explicit conformance milestone.
- RED registry provenance test exposed checkout-line-ending-dependent hashing;
  generator now hashes the pinned Git blob. Metadata and test are GREEN.
- GREEN: 112 tests with mandatory live oracle, Ruff/format and strict mypy checks.
- Final fresh independent reviewer found no critical/important defects and
  independently reran 40 high-level/logical/hardening cases successfully.
- Built wheel and sdist successfully; Twine metadata checks passed. Installed wheel
  under Python -I in two fresh environments: core-only with NumPy absent, and with
  NumPy available; compressed construction/reading and registry packaging passed.
- Added cross-platform Python 3.11–3.14 CI, required Gemstone job, clean-wheel job,
  license/provenance, API/architecture/support/development docs and example.
- Ruling: initial version is 0.1.0a1. Engineering checks and interoperability pass;
  do not market an alpha as established exhaustive IEEE 2025 conformance.

### Task 8: complete

- Public repository `ShietFak/pqdif` created using the configured Git credential.
- Ruling: push the implementation as a reviewable PR against the initial design
  branch `main`, per the saved plan. User authorization covers repository setup and
  continued implementation; do not add a routine finishing-menu approval stop.
- No PyPI publication is requested or performed.
- Implementation pushed to `feat/native-pqdif`; initial design pushed to `main`.
- PR https://github.com/ShietFak/pqdif/pull/1 created and attached to this chat.
- Remote repository visibility/branches and PR head verified. Local Git status was
  clean after the implementation commit. Install artifacts retained in `outputs/`.
- GitHub CI is running the full Python 3.11–3.14 Windows/Linux matrix, required live
  Gemstone oracle, package checks and core-only wheel installation. Its current
  results remain visible on the PR; local release evidence above is complete.
