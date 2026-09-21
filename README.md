# kilix-license

Licence: MIT (OD-AV). LIC3 re-confirms the LICENSE file; remote creation is RC-13.

`kilix-license` is the single licence authority for Kilix (OD-AJ). It
owns licence records stored by text digest, the verbatim first-use
screen, agreement capture, digest-bound receipts, and binding-scoped
`covers` / `require`.

The public coverage check is `covers(record, receipt, *, manifest_digest)`.
The expected manifest is part of the binding (OD-AI); the two-argument
form is refused. OD-AI's record digest names this licence record, not an
asset/v3 record. Advisories, statements, and component entries without
exception text are context (OD-AQ) and are omitted from that digest.

The screen is `render_screen(record, texts, *, receipts, records=None)`.
It marks every bound text that is "changed since your last acceptance"
(SR-4): the licence text, a component exception, or a binding condition
whose text identity an earlier accept receipt accepted with other bytes.
`receipts` (the `ReceiptStore`) is required, so no consumer can render a
screen without the marker; the two-argument form is refused. The same
detection is `changed_texts(record, receipts, *, records=None)`, and
`scan_receipts(store)` lists the receipt files it used and skipped. A
binding condition's identity is its generated `text_id`, and a licence
text's identity is its record's generated `licence_text_id`. Both are keyed
by the document, not by record or binding id, so they hold across sibling
records (both Bonsai Image variants, both EnCodec checkpoints) and a
renamed binding or entry. The generator refuses an identity table that
gives two texts one identity or one text two identities. The marker never
grants coverage: `covers` and `require` do not read it. A receipt file that
cannot be parsed, or has an unknown schema, is skipped for the marker,
never fatal.

The scan and `require` read receipt files the same way. Each entry is
stat'ed before it is opened, so a FIFO, device or directory is never
opened. The open is `O_NONBLOCK | O_NOCTTY`, and the descriptor must be a
regular file of at most 1 MiB before one byte is read. Reads stop at
1 MiB + 1 byte whatever the file's size claims. An entry named like a
receipt that fails this is not a receipt: `require` refuses with
`CoverageRefused` and never waits on it.

Most bound and context texts are the determinations JSON's own quoted
spans. One is not: the EnCodec `encodec-licence-history-note` advisory. The
determinations quote there is OD-AR's builder-facing description of the
screen, so `ADVISORY_TEXTS` binds the note itself instead - a text vendored
under `data/texts/` whose quoted lines are copied byte for byte from the
upstream licence history the L-ENC-R2 evidence packet pins. The generator
refuses a table entry no determinations quote uses, an entry that is not a
sha256, and a note that is missing or does not match its digest. An advisory
is not bound (OD-AQ), so the EnCodec record digests and every receipt's
coverage are unchanged by it.

The note tells the user that every line under a "quoted from" header is its
named source's bytes, so that promise is checked rather than asserted.
`ADVISORY_TEXT_SOURCES` declares, for each note, which file it quotes, that
file's sha256 and the exact lines taken; `parse_quoted_blocks` reads the
same three facts back out of the note's own headers, and the generator
refuses a note whose headers disagree with the declaration, including a
header that names one slice while quoting another. Each named source file is
pinned under `tests/data/note-sources/<sha256>`, and the suite re-derives
every quoted line from it and compares bytes, using the line numbers the
note itself claims. Adding or dropping a quoted block is a change to that
one table: nothing else names the note's sources.

Receipts written from LIC4 on also record, as context that is not bound
(OD-AQ), the statement and component-exception digests shown on the screen
and each binding's text identity; from LIC4-FIX on they also record the
licence text identity. Receipts without those keys, as written before LIC4
or LIC4-FIX, are still read and still cover; their identities are resolved
through the record their licence id names (pass `records=`).

This `0.1.0` LIC2 state generates licence records from the checked
determinations JSON (never retyped). The repository licence file is MIT
(OD-AV). LIC3 re-confirms that LICENSE file; the GitHub remote remains
RC-13.

## Publication status

The repository is **local-only**. It has no remote and is not authorised
for a push or for GitHub repository creation. See `PUBLICATION.md`.

Runtime code uses the Python standard library only.

## Development

The development environment is frozen to Python 3.12.8 and uv 0.12.5.

```sh
uv sync --frozen --python 3.12.8
make check
```

`make check` syncs the frozen environment, runs the test suite, and
builds installable artifacts. Inside a network sandbox run it as
`make check OFFLINE=1`: `uv build` otherwise resolves the PEP 517 build
backend over the network, which uv.lock does not pin, and the gate fails
with a name-resolution error rather than a defect.
