"""Independent GPA Gemstone oracle. Ordinary runs use committed oracle fixtures.

Set PQDIF_REQUIRE_ORACLE=1 for a mandatory live run; it fails if not bootstrapped.
"""

import hashlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from pqdif import Channel, Observation, PhysicalType, PqdifFile, Series, dumps, loads
from pqdif.elements import Collection, Scalar, Vector

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures"
ORACLE = ROOT / "work/oracle/Oracle.dll"
VENDOR = UUID("a1111111-2222-3333-4444-555555555555")


def canonical_element(element):
    if isinstance(element, Collection):
        return {
            "tag": str(element.tag),
            "kind": 1,
            "type": element.physical_type,
            "children": [canonical_element(e) for e in element.elements],
        }
    return {
        "tag": str(element.tag),
        "kind": 2 if isinstance(element, Scalar) else 3,
        "type": int(element.physical_type),
        "raw": element.raw.hex(),
    }


def canonical_file(file):
    return [
        {"tag": str(record.type_tag), "body": canonical_element(record.body)}
        for record in file.records
    ]


@pytest.fixture(scope="session")
def oracle():
    portable = ROOT / "work/tools/dotnet" / ("dotnet.exe" if os.name == "nt" else "dotnet")
    dotnet = os.environ.get("PQDIF_DOTNET") or shutil.which("dotnet") or str(portable)
    if not ORACLE.exists() or not Path(dotnet).exists():
        if os.environ.get("PQDIF_REQUIRE_ORACLE") == "1":
            pytest.fail("Gemstone oracle missing: run tools/bootstrap_oracle.py")
        pytest.skip("live oracle not bootstrapped; committed Gemstone fixtures still tested")

    def run(*args):
        result = subprocess.run(
            [dotnet, str(ORACLE), *map(str, args)],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        return json.loads(result.stdout)

    return run


@pytest.mark.parametrize("name", ["gemstone-none", "gemstone-zlib"])
def test_committed_gemstone_fixtures_match_oracle_canonical_and_semantic_roundtrip(name):
    path = FIXTURES / (name + ".pqd")
    assert path.exists(), "Gemstone-generated fixture must be committed"
    wire = path.read_bytes()
    file = loads(wire)
    expected = json.loads((FIXTURES / (name + ".json")).read_text("utf-8"))
    assert canonical_file(file) == expected["records"]
    assert file.observations[0].channels[0].series[0].values == tuple(expected["values"])
    assert [
        [[list(series.values) for series in channel.series] for channel in obs.channels]
        for obs in file.observations
    ] == expected["seriesValues"]
    assert canonical_file(loads(dumps(file))) == expected["records"]
    provenance = json.loads((FIXTURES / "provenance.json").read_text("utf-8"))
    assert hashlib.sha256(wire).hexdigest() == provenance["files"][path.name]


@pytest.mark.interop
@pytest.mark.parametrize("compressed", [False, True])
def test_python_to_gemstone_reads_and_rewrites_equivalent_tree(oracle, compressed, tmp_path):
    file = PqdifFile(
        [
            Observation(
                "python event",
                datetime(2026, 1, 2, tzinfo=UTC),
                [
                    Channel(
                        "voltage",
                        [Series([1, -2, 3], physical_type=PhysicalType.INT2, units=6)],
                        phase=1,
                        quantity=1,
                    )
                ],
            )
        ],
        compressed=compressed,
    )
    file.records[0].body.elements.append(
        Collection(
            VENDOR,
            [
                Scalar(VENDOR, PhysicalType.REAL4, bytes.fromhex("0100c07f")),
                Vector.from_text(VENDOR, "unknown vendor payload"),
            ],
        )
    )
    path, rewritten = tmp_path / "python.pqd", tmp_path / "gemstone-rewrite.pqd"
    path.write_bytes(dumps(file))
    result = oracle("inspect", path)
    assert result["records"] == canonical_file(file)
    assert result["values"] == [1, -2, 3]
    assert result["seriesValues"] == [[[[1, -2, 3]]]]
    assert result["missingTags"] == []
    assert oracle("rewrite", path, rewritten)["records"] == canonical_file(file)
    assert canonical_file(loads(rewritten.read_bytes())) == canonical_file(file)


@pytest.mark.interop
@pytest.mark.parametrize("compressed", [False, True])
def test_gemstone_to_python_live_generation_then_rewrite(oracle, compressed, tmp_path):
    path, rewritten = tmp_path / "oracle.pqd", tmp_path / "python-rewrite.pqd"
    result = oracle("generate", path, "zlib" if compressed else "none")
    file = loads(path.read_bytes())
    assert canonical_file(file) == result["records"]
    assert [
        [[list(series.values) for series in channel.series] for channel in obs.channels]
        for obs in file.observations
    ] == result["seriesValues"]
    rewritten.write_bytes(dumps(file))
    assert oracle("inspect", rewritten) == result


@pytest.mark.interop
def test_fixture_regeneration_is_deterministic(oracle, tmp_path):
    for mode in ("none", "zlib"):
        path = tmp_path / (mode + ".pqd")
        oracle("generate", path, mode)
        assert path.read_bytes() == (FIXTURES / ("gemstone-" + mode + ".pqd")).read_bytes()


@pytest.mark.interop
def test_three_rate_increment_documents_gemstone_disagreement(oracle, tmp_path):
    from pqdif import StorageMethod

    # IEEE native pqdiflib/rec_observ.cpp emits a point then adds its segment's rate.
    series = Series([3, 2, 1, 2, 10, 2, 100], storage=StorageMethod.INCREMENT, units=2)
    file = PqdifFile(
        [Observation("three rates", datetime(2026, 1, 2, tzinfo=UTC), [Channel("time", [series])])]
    )
    path = tmp_path / "three-rates.pqd"
    path.write_bytes(dumps(file))
    assert file.observations[0].channels[0].series[0].values == (0, 1, 2, 12, 22, 122)
    result = oracle("inspect", path)
    assert result["records"] == canonical_file(file)
    assert result["seriesValues"] == [[[[0, 1, 2, 12, 20, 120]]]]
