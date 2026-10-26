# Contributing

See [development instructions](docs/development.md) for setup and verification.

Keep the binary codec, logical rules and high-level conversions separate. Preserve
unknown data and raw value bytes by default. Reproduce behavior with a failing
test before implementation. Include independently produced fixtures or reference
evidence for compatibility changes, and retain their license/provenance.

Report malformed-input bugs with a minimized synthetic reproducer. Do not attach
confidential power-system data. New features should include type annotations,
bounded resource behavior and support-matrix updates. Contributions are MIT licensed.
