# Development and verification

## Python environment

```sh
python -m venv .venv
# Activate it using your platform's normal command.
python -m pip install -e '.[dev]'
python -m pytest
python -m ruff check src tests tools examples
python -m ruff format --check src tests tools examples
python -m mypy src/pqdif
python -m build
python -m twine check dist/*
```

Use TDD for behavior changes: add a focused failing test, observe the intended
failure, implement, then run it and the affected suite. Tests include independently
specified wire values, malformed cases and Hypothesis-generated raw trees/mutations.
Do not use self-roundtrips as the only evidence of interoperability.

## Live Gemstone oracle

Install a .NET 9 SDK for development only. The first bootstrap needs GitHub/NuGet
network access; all downloaded reference/tooling files remain under ignored `work/`.

```sh
python tools/bootstrap_oracle.py
# POSIX
PQDIF_REQUIRE_ORACLE=1 python -m pytest
# PowerShell
$env:PQDIF_REQUIRE_ORACLE = '1'
python -m pytest
```

Use `--dotnet /absolute/path/to/dotnet` or `PQDIF_DOTNET` to select a portable SDK.
The script clones/checks out a pinned Gemstone commit. If an existing checkout has
a different commit, it stops without changing that checkout. It builds the actual
upstream project via `ProjectReference`, not a reimplementation of Gemstone's codec.
The test adapter is `tests/interop/oracle/Program.cs`.

Normal native tests always run the committed independently generated fixtures.
Live tests skip if not bootstrapped, unless `PQDIF_REQUIRE_ORACLE=1`, which makes
missing tooling an error. CI runs that mandatory live mode separately.

To deliberately regenerate fixtures:

```sh
python tools/bootstrap_oracle.py --fixtures
```

Review binary/JSON/provenance changes together. The corpus has a fixed UTC creation
time and compares deterministic generation. `provenance.json` records source commit,
SDK and fixture hashes. `packages.lock.json` records the oracle's NuGet closure.

To regenerate identifier metadata after checking out its pinned reference:

```sh
python tools/generate_metadata.py
python -m ruff format src/pqdif/_tag_constants.py
```

Metadata provenance hashes the Git blob, independent of checkout line endings.
Do not upgrade the source pin without reviewing identifier changes and rerunning
the oracle. Consult `docs/compatibility.md` for the multi-rate conversion difference.

## Release criteria

Run the complete native and required-oracle suite, lint/format/type checks, build
wheel/sdist, validate metadata, install the wheel in a clean environment without
NumPy/.NET, and exercise a compressed create/read/write cycle. Run optional NumPy
checks separately. Review support claims against actual evidence. Create a source
release only with deliberate versioning; publishing to PyPI is a separate action.
