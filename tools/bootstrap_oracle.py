"""Build the test-only Gemstone oracle, optionally regenerate deterministic fixtures.

Usage: python tools/bootstrap_oracle.py [--fixtures] [--dotnet PATH]
Requires a .NET 9 SDK and network access to GitHub/NuGet on the first run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN = "296d859d094347420f22415b91cfe428ff87687b"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", action="store_true")
    parser.add_argument("--dotnet")
    args = parser.parse_args()
    portable = ROOT / "work/tools/dotnet" / ("dotnet.exe" if os.name == "nt" else "dotnet")
    dotnet = (
        args.dotnet or os.environ.get("PQDIF_DOTNET") or shutil.which("dotnet") or str(portable)
    )
    if not Path(dotnet).exists():
        raise SystemExit("Install a .NET 9 SDK, or pass --dotnet PATH")
    source = ROOT / "work/reference/gemstone-pqdif"
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "https://github.com/gemstone/pqdif.git", str(source)], check=True
        )
        subprocess.run(["git", "-C", str(source), "checkout", "--detach", PIN], check=True)
    actual = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    if actual != PIN:
        raise SystemExit(f"Expected pinned Gemstone {PIN}, found {actual}; checkout left untouched")
    environment = dict(
        os.environ,
        DOTNET_CLI_HOME=str(ROOT / "work/dotnet-home"),
        NUGET_PACKAGES=str(ROOT / "work/nuget"),
        DOTNET_NOLOGO="1",
        DOTNET_CLI_TELEMETRY_OPTOUT="1",
    )
    project = ROOT / "tests/interop/oracle/Oracle.csproj"
    upstream = source / "src/Gemstone.PQDIF/Gemstone.PQDIF.csproj"
    output = ROOT / "work/oracle"
    subprocess.run(
        [
            dotnet,
            "build",
            str(project),
            "-c",
            "Release",
            "-o",
            str(output),
            "-p:GemstoneProject=" + str(upstream),
            "-p:TargetFrameworks=net9.0",
            "--nologo",
        ],
        env=environment,
        check=True,
    )
    if args.fixtures:
        fixtures = ROOT / "tests/interop/fixtures"
        fixtures.mkdir(parents=True, exist_ok=True)
        hashes = {}
        for mode in ("none", "zlib"):
            path = fixtures / f"gemstone-{mode}.pqd"
            result = subprocess.run(
                [dotnet, str(output / "Oracle.dll"), "generate", str(path), mode],
                capture_output=True,
                text=True,
                env=environment,
                check=True,
            )
            canonical = json.loads(result.stdout)
            (path.with_suffix(".json")).write_text(
                json.dumps(canonical, indent=2) + "\n", encoding="utf-8"
            )
            hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        provenance = {
            "generator": "tests/interop/oracle/Program.cs",
            "repository": "https://github.com/gemstone/pqdif",
            "commit": PIN,
            "sdk": subprocess.check_output(
                [dotnet, "--version"], env=environment, text=True
            ).strip(),
            "files": hashes,
        }
        (fixtures / "provenance.json").write_text(
            json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
        )
        print("Generated independent Gemstone fixtures with hashes")


if __name__ == "__main__":
    main()
