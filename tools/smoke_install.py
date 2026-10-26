"""Verify the installed wheel in an isolated interpreter (use Python -I)."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-only", action="store_true")
    args = parser.parse_args()
    if args.core_only:
        assert importlib.util.find_spec("numpy") is None, "core smoke environment contains NumPy"

    import pqdif
    from pqdif import Channel, Observation, PqdifFile, Series, dumps, loads

    assert Path(pqdif.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
    file = PqdifFile(
        [
            Observation(
                "installed wheel",
                datetime(2026, 1, 2, tzinfo=UTC),
                [Channel("Va", [Series([0.25, -1.5, 3.75], units=6)])],
            )
        ],
        compressed=True,
    )
    result = loads(dumps(file))
    assert result.observations[0].channels[0].series[0].values == (0.25, -1.5, 3.75)
    assert len(pqdif.tags.BY_NAME) == 137
    assert pqdif.tags.PROVENANCE["commit"] == "296d859d094347420f22415b91cfe428ff87687b"
    if not args.core_only:
        assert result.observations[0].channels[0].series[0].to_numpy().tolist() == [
            0.25,
            -1.5,
            3.75,
        ]
    print(f"Installed wheel smoke passed: {pqdif.__version__}, core-only={args.core_only}")


if __name__ == "__main__":
    main()
