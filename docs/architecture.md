# Architecture

The physical representation is authoritative. Upper layers are views or builders;
they do not project a file into a smaller schema and discard the rest.

```text
read/write, PqdifFile, Observation, Channel, Series      api.py, series.py
                         |
context/required fields, source/settings, logical links logical.py, tags.py
                         |
record framing, compression, checksums                  physical.py
                         |
ordered collection descriptors and absolute body links codec.py
                         |
raw scalar/vector/opaque bytes, wire types, limits      elements.py, types.py
```

Each record begins with the fixed PQDIF signature and 64-byte base header. Its body
is a root collection with 28-byte descriptors. Numeric fields and GUID fields use
the PQDIF little-endian representation. Small scalar values embed in descriptors;
other values link to four-byte-aligned allocations relative to the record body.
The writer computes canonical placements and Adler-32; the container declares
compression for subsequent records.

Descriptor bounds/alignment/overlap are preflighted before copying any payload.
This prevents repeated links from multiplying allocations before a later error.
Nested allocation scopes, count/depth limits, decompression output bounds and
record-chain checks make malformed input explicit rather than partially recovering.
Reader-created objects keep exact numeric raw bytes. Known timestamps only become
Python datetimes on explicit conversion.

Logical parsing tracks active source/settings. New sources reset prior settings;
each observation gets the context that applied at its position. Unknown records
stay in the physical sequence. Invalid indexes/counts are rejected instead of
truncating definitions and instances through `zip`.

Series resolve references lazily with cycle detection and per-traversal lookup
caches. Counts are checked before increment expansion. NumPy remains an optional
local import; the unscaled numeric path references immutable raw bytes.

Gemstone is never imported, invoked, bundled or restored by runtime package code.
It lives only in the test harness, pinned to a source commit. Canonical raw JSON
provides an independent comparison separate from Python's own writer/reader.
