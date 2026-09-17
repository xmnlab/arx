# Logical types and schemas

Arx's data model is Arrow-native. It does not introduce an `arrow` namespace or
require `import arrow` in Arx source.

## Implemented foundation

ASTx exposes immutable `LogicalType`, `LogicalParameter`, `SchemaField`, and
`Schema` descriptors in `astx.schema` and at the package root. Descriptors cover
all 45 modeled logical families: primitive and null types; string/binary,
large-offset and view types; fixed-size binary; dates, times, timestamps,
durations and intervals; decimal32/64/128/256; recursive lists, structs, maps,
unions, dictionaries, run-end encoding, and opaque extensions.

These are **schema descriptors**, not evidence that every corresponding Arx
value, builder, operator, or kernel can execute. `ScalarType`, `ArrayType`,
`ChunkedArrayType`, `RecordBatchType`, `TableType`, `StreamType`, `SchemaType`,
and `FieldType` are modeled, but their new native value paths remain pending.
Declarations using these modeled-only types are rejected by IRx analysis rather
than reaching an unsupported LLVM representation. Existing DataFrame, Series,
tensor, and primitive runtime behavior is unchanged.

IRx provides:

- `irx.analysis.schema`: validation and canonicalization, with logical field
  paths on `SchemaError` and no invented source spans.
- `irx.analysis.schema_types`: resolved C Data formats and storage widths.
  Scalar mappings live in the shared builtin primitive metadata module, without
  introducing analyzer import cycles. Boolean storage is one bit, not one byte.
  Existing primitive builders remain limited to their previously implemented
  types.
- `irx.analysis.schema_conversions`: `EXACT`, `LOSSLESS`, `EXPLICIT`, and
  `INCOMPATIBLE` classifications. Classification is not an executable cast.
- `irx.schema_interop`: host-side `schema_to_pyarrow` and `schema_from_pyarrow`
  APIs. These use the Arrow C Data schema contract, not Python execution of
  compiled Arx operations.

For example, this **Python host API** constructs a schema descriptor:

```python
from astx import LogicalKind, LogicalType, Schema, SchemaField
from irx.schema_interop import schema_from_pyarrow, schema_to_pyarrow

schema = Schema((
    SchemaField("count", LogicalType(LogicalKind.INT64), nullable=True),
), metadata=((b"producer", b"arx"),))
assert schema_from_pyarrow(schema_to_pyarrow(schema)) == schema
```

## Identity and validation

Fields retain their order and independent nullability. Field and schema metadata
retain binary keys and values, including NUL and non-UTF-8 bytes. Metadata key
ordering is canonicalized; duplicate keys and duplicate sibling field names are
rejected. Names must be valid UTF-8 without NUL. Empty schemas are distinct from
unknown runtime schemas.

Validation checks decimal precision limits (9/18/38/76 digits) and signed 32-bit
scale, time units, fixed sizes, union code uniqueness and range, integer
dictionary indices, nonnullable map keys, and signed run-end index widths. Named
timezones use the host's IANA database via `zoneinfo`; signed `HH:MM` offsets
and naive timestamps are also accepted. Nesting is bounded at 64 levels.
Extension names and serialized bytes are retained, not interpreted as permission
to execute unregistered extension kernels.

Arrow's C Data importer normalizes some synthetic children. To prevent silent
loss, descriptor validation requires:

- maps: `entries`, `key`, and `value` names, with no `entries` metadata;
- dictionaries: bare nonnullable `indices` and `values` type children;
- extensions: one bare nonnullable `storage` child;
- run-end encoding: bare `run_ends` and nullable `values` children, no direct
  nested run-end value type.

User field or schema metadata must not contain reserved extension keys; use an
explicit extension descriptor instead. These restrictions are deliberate
diagnostics, not silently dropped metadata.

Implicit compatibility requires whole-domain representability. Integer
narrowing, unsafe signedness changes, inexact integer-to-float conversions,
nullability removal, temporal rescaling, dictionary changes, and metadata
changes require explicit conversion. Unrelated structural shapes and changes to
opaque extension identity are incompatible.

## Native schema boundary

`irx_arrow_schema_import_copy` now imports recursive **field descriptors** using
Arrow C++. It clones the C struct tree before import, without invoking producer
release callbacks or consuming producer children. Metadata and names are copied
into owned Arrow fields. Exported schemas remain valid after the runtime handle
is released. A schema can be represented as a struct-root field descriptor; the
existing ABI does not yet distinguish a field handle from a schema handle.

The legacy primitive `schema_type_id` query is unchanged: nonprimitive types
return `UNKNOWN` and must be inspected through their exported recursive schema.
No Arrow C++ object layout is embedded in LLVM and no ABI symbol or ABI version
has been changed. The `array` runtime feature contract is now 1.1.0, so
consumers can query for recursive schema support while 1.0 consumers remain
compatible.

Tests cover every logical family through descriptors, PyArrow C Data, IPC schema
serialization, and the native schema copy/retain/export/release path. They also
cover binary metadata, producer-first destruction, allocation-entry failure,
invalid outputs, and the restrictions above. The sanitizer harness additionally
exercises recursive schema lifetime.

## Remaining milestone work

M3 is **partial**, not complete. Source syntax, focused expression nodes,
semantic sidecars consumed by lowering, native type/field descriptor handles,
and end-to-end construction/inspection/projection/conversion remain pending.
Container value support and kernels must not be inferred from descriptor tests.
M2 also retains open leak-detection, post-mutation allocation-failure, and
aggregate lifecycle tasks; see `PLAN.md`.
