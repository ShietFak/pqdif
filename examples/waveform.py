"""Create a compressed file using only the core package; run in a chosen output folder."""

from datetime import UTC, datetime
from pathlib import Path

from pqdif import Channel, Observation, PqdifFile, Series, read, write


def main() -> None:
    file = PqdifFile(
        [
            Observation(
                "example waveform",
                datetime(2026, 1, 2, tzinfo=UTC),
                [Channel("Va", [Series([0.25, -1.5, 3.75], units=6)], phase=1, quantity=1)],
            )
        ],
        compressed=True,
    )
    path = Path("waveform.pqd")
    write(file, path)
    assert read(path).observations[0].channels[0].series[0].values == (0.25, -1.5, 3.75)
    print(path.resolve())


if __name__ == "__main__":
    main()
