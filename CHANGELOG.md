# Changelog

All notable changes to `kilix-license` are recorded here.

## Unreleased

- Authored advisory-note prose is **pinned, not screened**. A note's own
  lines - its preamble and each block's three header lines - were checked
  by a detector that looked for licence identifiers and the language of
  permission, and a false sentence phrased outside that vocabulary walked
  past it onto a first-use consent screen with the whole suite green:
  "Meta later allowed everyone to reuse the encodec weights freely", on a
  screen whose binding condition is CC BY-NC 4.0, printed beneath it. No
  addition to the vocabulary closes that class. The authored text must now
  equal, byte for byte, the lines declared in `ADVISORY_NOTE_AUTHORED`, so
  a new or altered authored sentence is refused whatever its wording, and
  the generator refuses a note whose authored prose is undeclared. The
  declaration is the one place a future editor changes; the refusal states
  the four steps, and `README.md` records them. The quoted blocks are
  unchanged and still re-derived from their named source, so text appended
  after the last block is still caught there.
- With `$GPU_TERMINAL_HOME` unset the receipt store root is now
  `$HOME/.local/gpu_terminal/license-receipts`, which is what `voicelib`,
  `kilix/bootstrap.sh`, `kilix/build.sh` and `pleb/lib/common.sh` all
  compose. It read the NSS passwd home before, which ignores `$HOME`: in a
  sandbox or a service unit where the two differ, the real first-use flow
  filed a receipt at one root while the real weights gate refused at
  another, and told the user to accept a licence they had just accepted.
  The suite's live-store guard still reads the passwd home, deliberately -
  the suite redirects `$HOME`, so a `$HOME`-based guard would stop guarding
  the real store while the suite runs - and it now refuses both spellings.
- A receipt whose `acceptance.captured_at` or `acceptance.capture_mode` is
  not a string is refused as a `ReceiptShapeError` naming the field,
  instead of raising `TypeError` out of a regex; a consumer that catches
  the refusal no longer sees a traceback from one malformed file in the
  store. `captured_at` with a trailing newline is refused too.
- The shipping rule is bound by its sentences and its location rather than
  by eight substrings: reversing it in place, moving it to an appendix and
  adding a third acceptable outcome each left every substring intact. The
  honest statement of what a receipt proves is now pinned in
  `Acceptance`'s docstring as well as in `README.md`, where a caller meets
  it. The rule itself is enforceable only by being read, and it appears
  nowhere outside this repository: enforcement where images are built is
  owed to those repositories, not provided here.
- `make check` reaches `tools/verify_note_sources.py`. It is the only check
  that settles an advisory note's quoted source against the evidence
  packets rather than against two pins inside this tree, and no gate ran
  it. `make notes PACKETS=<dir>` runs it; `make check` runs it whenever
  `PACKETS` is set and prints what was not checked when it is not.
- There is one receipt store root and this authority names it:
  `receipt_store_root()` is `$GPU_TERMINAL_HOME/license-receipts`,
  overridden by `$KILIX_LICENSE_RECEIPTS`, and `ReceiptStore.shared()`
  opens it without a caller naming a path. A caller that does name one and
  gets it wrong is refused at that point, with both paths in the message,
  instead of producing a gate that refuses an acceptance the user gave.
  A writer process and a reader process, each naming no path, are checked
  against each other in the suite, with the diverging arm as a control.
- A receipt records an `acceptance` block as context that is not bound
  (OD-AQ, shaped by OD-BC): exactly `captured_at` and `capture_mode`
  (`interactive-tty` or `no-tty`), both observed by this authority when the
  agreement is captured. **No account name and no uid is recorded**, so
  nothing in a receipt distinguishes two users of one machine; a receipt
  carrying an identity field is refused, not ignored. A receipt does not
  prove that a human accepted, which human, or that its time is real - it
  is unsigned. Minting without a recorded capture is refused, so the block
  cannot be skipped. `require(..., captured_at_a_terminal=True)` lets a
  caller demand the weakest form of it; OD-BC keeps it available and off,
  the default is unchanged, and every earlier receipt still covers exactly
  as before. Receipts written from here on are refused by readers older
  than this change, which reject an unknown context key: re-pin consumers
  first.
- The rule OD-BC pairs with that, in `README.md` where a reader meets it: a
  receipt is never shipped, vendored or provisioned; shipping one is not an
  acceptable remedy for a refusing gate; the acceptable outcomes are
  acceptance at first use, or no weights. A build-time attestation is a
  distinct schema, never a `kilix.license.receipt/v1` (settling OQ-C4).
- No line an advisory note wrote itself may state a licence. The note's
  preamble and each block's attribution header were checked by nothing, so
  a fabricated "relicensed to Apache-2.0; commercial use is permitted"
  could ship on the accept screen with the suite green while every quoted
  line was still verbatim. The generator now refuses a note whose authored
  lines carry a licence identifier or the language of permission, and the
  suite proves the detector is live against the upstream wording itself.
- The audiocraft block's attribution header says why an adjacent
  repository is on an EnCodec screen and that "this repository" in the
  lines below is audiocraft. The note moves; both EnCodec record **files**
  move with it; no record digest moves.
- Each declared note source carries the evidence packet's own record of it,
  vendored under `tests/data/note-sources/packet-records/`, as a second
  witness for the declared digest and for every quoted line the packet
  records. `tools/verify_note_sources.py --packets DIR` re-derives both
  from the packets when they are to hand.
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
