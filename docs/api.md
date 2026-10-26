# API contracts

## High-level objects

- `PqdifFile(observations=(), compressed=False, filename="data.pqd", created=None)`
  creates required container metadata and emits each supplied observation with its
  source/settings. `records` is the authoritative ordered, mutable physical sequence.
- `Observation(name, start, channels, source_name="pqdif", trigger=0, settings=None)`
  accepts an aware datetime or exact `Timestamp`. It owns copies of supplied channel
  templates so reuse cannot corrupt earlier observations. Settings must be a physical
  monitor-settings `Record`. Read objects retain live source/settings bindings.
- `Channel(name, series, phase=0, quantity=0, quantity_type=WAVEFORM)` creates a
  definition and instance. `name` edits the definition; `.definition` and `.physical`
  expose their complete trees. Missing optional channel names read as empty strings;
  malformed known names raise `ValidationError`.
- `Series(values, units=0, physical_type=REAL8, value_type=VAL,
  characteristic=NONE, storage=VALUES, scale=None, offset=None, share=None)` accepts
  stored values and metadata. Choose an explicit physical type for integer/complex
  data; default REAL8 intentionally avoids platform-dependent dtype inference.

View lists (`observations`, `channels`, `series`) are newly constructed projections.
Changing a property updates its physical tree; appending/removing from a returned
list does not change the file. Construct observations before creating a file, or
edit the physical collection lists to add/remove structure and validate afterward.

`Series.raw_values` is the stored vector decoded without engineering transforms.
`Series.stored_values` exposes its `Vector` (and can replace an unshared vector).
`Series.values` expands/decodes under file limits; `get_values(limits=...)` overrides
the expansion budget for that call. Scaling is `offset + raw * scale`. Numeric
operand checks precede multiplication. Shared vectors inherit missing scale/offset;
explicit identity values override inheritance. Cyclic/invalid references raise.

Increment vectors contain `[rate_count, point_count_1, increment_1, ...]`. Counts
must be nonnegative integers and output counts must fit the configured limit before
allocation. Segment coordinates accumulate; see the documented reference disagreement.
Unknown storage flags are preserved physically and raise on engineering conversion.
Enabled calibration and scaled timestamps similarly require explicit raw access.

`Series.to_numpy(engineering=True)` returns a read-only numeric array. It uses a
zero-copy view when no conversion is needed, and a new array for transformed data.
`engineering=False` exposes stored numeric values without scaling/expansion/calibration.
PQDIF boolean widths decode to NumPy booleans while raw bytes retain their width.

## I/O

`read(path_or_binary_stream, *, limits=Limits(), verify_checksum=True, validate=True)`
and `loads(bytes, ...)` return `PqdifFile`. `write(file, target, *, limits=None,
validate=True)` and `dumps(file, ...)` serialize it. Writer limits default to the
file's retained reader limits. Caller streams stay open; paths are opened/closed by
the library. Stream addresses describe the standalone image starting at the
supplied current position. Writing validates/serializes before opening/truncating a
path; writing to a caller stream uses its write semantics without truncating it.

`validate=False` bypasses supported logical rules, not physical safety checks. Use
`pqdif.physical.read_records`, `write_records`, `loads_records`, `dumps_records` for
incomplete documents, future records, unknown physical encodings, or exact sequence
work. Those operations still enforce supported compression, bounds and safe relocation.

## Physical values

`Scalar(tag, physical_type, raw)` and `Vector(tag, physical_type, raw)` validate raw
lengths. `Scalar.from_value(...)` and `Vector.from_values(...)` encode typed values.
`Vector.from_text(tag, text, unicode=False)` writes a terminated character vector;
`.text` decodes without changing bytes, stripping terminal NULs. CHAR2 `.values`
returns individual UTF-16 code units; `.text` combines surrogate pairs.

`Collection(tag=UUID(int=0), elements=[])` stores ordered elements. `.all(tag)`
returns every match. `.get(tag)` returns zero/one element and rejects ambiguous
duplicates. `.replace(element)` replaces a known field at its original first
position. `decode_collection`/`encode_collection` operate on an entire record body;
links use offsets relative to that body, not to a nested collection.

`Timestamp(days, seconds)` keeps the exact uint32 day/binary64 seconds fields.
`.validate()` checks wire-domain bounds. `.to_datetime()` rounds only the returned
datetime to microseconds and explicitly rejects dates outside Python's range.
`.from_datetime()` requires a timezone and converts to UTC. Raw timestamp bytes can
still be preserved without interpretation, including malformed extension content.

## Identifiers

`from pqdif import tags` exposes constants such as `tags.OBSERVATION`, `tags.TIME_START`
and `tags.SERIES_VALUES`. `tags.BY_ID`, `tags.BY_NAME`, `tags.IDENTIFIERS` and
`tags.PROVENANCE` expose the pinned registry. For example:

```python
from pqdif import tags
volts = int(tags.IDENTIFIERS["tagQuantityUnitsID"]["Volts"]["value"])
assert volts == 6
```

The registry is a reference snapshot, not an allowlist: unknown GUIDs/codes remain
valid extensions. Logical views are in `pqdif.logical`; `LogicalFile(records)`
captures per-observation source/settings context and `.validate()` checks supported
known fields and links.

## Limits and errors

Default `Limits`: file 512 MiB; stored/decoded body 64 MiB; aggregate decoded bodies
512 MiB; one million elements per body; eight million values per vector; 100,000
records; nesting depth 64; eight million expanded values per series. Input is
buffered within the file limit. Bounds should be chosen for the workload.

- `PqdifFormatError`: malformed physical bytes, with `.offset` and byte context.
- `ValidationError`: known logical ambiguity, wrong fields, links or unsafe conversion.
- `UnsupportedFeatureError`: unsupported compression or semantics/opaque relocation.
- `PqdifError`: common base.
- `ValueError`: invalid caller-created values/trees or writer limits.

Adler-32 is checked over stored (compressed when applicable) body bytes. Zero
header checksums are unspecified. An explicit `verify_checksum=False` permits
external checksum conventions without claiming those checksums were validated.
