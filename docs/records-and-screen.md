# Records, the first-use screen and coverage

How a licence record is identified, what the first-use screen shows, how a
receipt is matched to a record and manifest, and how consumers should ask for
an agreement. Receipt storage is described in the README
([Where receipts live](../README.md#where-receipts-live)).

## The authority and its checks

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

## Yes/no agreement screens

Consumers may show the full licence and binding conditions, name the affected
models, then ask for an explicit `yes` or `y` (default No). Pass that actual
answer to `capture_agreement`; do not manufacture an exact agreement phrase.
The legacy exact-line API remains supported. Receipts retain their existing
record, manifest, binding-text and capture-time identities. A batch consumer
may share one affirmative answer across the records actually presented in
that group, while emitting a separate receipt for each exact model manifest.
Declining or closing the screen must not call receipt creation for that group.
