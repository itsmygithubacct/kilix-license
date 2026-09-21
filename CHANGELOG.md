# Changelog

All notable changes to `kilix-license` are recorded here.

## Unreleased

- The EnCodec first-use screen shows the licence-history note itself
  instead of OD-AR's builder-facing sentence describing it. The note is a
  vendored text under `data/texts/`, quoting the 2022 CC BY-NC and 2023
  MIT README statements and, as the adjacent repository that does state a
  licence for model weights separately, audiocraft's two README lines -
  byte for byte from the upstream licence history the L-ENC-R2 evidence
  packet pins. `ADVISORY_TEXTS` binds it to both EnCodec records; a stale
  or malformed entry, and a missing or altered note, are refused.
  Advisories stay outside the record digest (OD-AQ), so both EnCodec
  record digests and every receipt's coverage are unchanged.
- An advisory note's "quoted from" headers are now checked against what it
  is declared to quote. `ADVISORY_TEXT_SOURCES` is the one declaration of
  each note's sources, digests and line numbers; the generator parses the
  note's own headers and refuses a disagreement, and the suite re-derives
  every quoted line from the source file pinned under
  `tests/data/note-sources/` and compares bytes. A quoted licence sentence
  that drifts from its source, or a header that claims a slice it does not
  quote, now fails.
- `make check OFFLINE=1` names, in the tree, what a sandboxed gate
  needs: `uv build` resolves the PEP 517 build backend over the network
  and uv.lock does not pin it, so without the flag a gate run with no
  network fails on name resolution rather than on a defect. The default
  is unchanged.
- Licence texts carry a generated document identity, `licence_text_id`,
  outside the record digest (every record digest is unchanged), so a
  licence text revised through a sibling record is marked changed. Receipts
  record it as context; receipts written before it resolve it through the
  record index.
- The receipt scan and `require` share one hardened reader: stat before
  open, `O_NONBLOCK | O_NOCTTY`, a regular-file `fstat` before any read, and
  a read budget of 1 MiB + 1 byte. A FIFO or device named like a receipt no
  longer hangs `require`; it is refused with `CoverageRefused`. Tests now
  measure the bytes read from a raced device, the bounded read of an entry
  whose size lies, and that a swapped-in terminal never becomes the
  controlling terminal.
- SR-4 changed-text detection in the public API: `render_screen` now
  takes the receipt store (keyword `receipts`, required) and marks each
  bound text changed since an earlier acceptance; `changed_texts` and
  `scan_receipts` expose the detection. Binding conditions carry a
  generated `text_id` (outside the record digest), so the marker holds
  across sibling records and binding renames. Unusable receipt files are
  skipped for the marker, never fatal; coverage is unchanged.
- Receipts record statement and component-exception digests and binding
  text identities as context (OD-AQ, additive); older receipts still
  read and cover.
- The generator's `--check` writes nothing and fails on a missing quote
  text; the determinations pin file must hold exactly one pin; the
  card-only licence texts and the repository LICENSE are pinned by digest.
- Generated licence records for the three OD-AY kilix-pdf-conversion engine
  models (granite-docling-258m, documentfigureclassifier-v2.5,
  granite-vision-4.1-4b) from determinations R3; every record now cites the
  R3 sha256. The Datalab/Surya models, the marker font, N3 and N4 get no
  record.
- Generated licence records from the pinned determinations R2 JSON
  (each record cites that sha256; the generator refuses a hand-edited
  record).
- Established the local-only repository identity with MIT licensing
  (LIC3 re-confirms the licence file).
- Pinned Python 3.12.8 and uv 0.12.5 for the empty runtime dependency
  closure.
- Added a hermetic harness: fixture records, FakeStore in a temp dir,
  and a guard that refuses the live receipt store.
- Added a tracked-tree weight guard (suffix, magic, catalog-digest list).
- Added the licence-record schema, verbatim screen, agreement capture,
  and digest-bound atomic receipts.
- Added binding-scoped covers() and require(); catalogue-digest binding
  is refused.
- Record digest omits advisory, statement, and non-exception component
  hashes (OD-AQ); covers() requires the expected manifest.
- Agreements carry the record and binding digests shown; accept receipts
  require the typed line.
- Live-store guard resolves dir_fd via /proc/self/fd and wraps truncate,
  chmod, utime, and rmdir.
- OpenFst magic is d6 fd b2 7e and .fst is a weight suffix.
- Receipt writes use a unique temp name and remove stale temps under the
  store lock so a retry after crash succeeds.
- LOCAL_ONLY remote checks allow a clone-created origin.
