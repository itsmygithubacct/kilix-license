# Advisory notes

An advisory note is a text this authority shows on a first-use screen that
is not itself a licence. This page covers how its quoted lines are tied to
their sources and how its authored lines are pinned.

## What a note may say

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

The note's own lines - its preamble and each block's three header lines -
are the only text in it that upstream did not write, and they may not say
what a licence is. `states_a_licence` looks for a licence identifier or the
language of permission and relicensing, and the generator refuses a note
with such a line outside a quoted block. This is the rule the note exists
for: licence statements on a first-use screen come from upstream's bytes,
never from us. An authored line may still introduce, attribute and cite,
which is where the orientation on a quoted block comes from.

Each declared source also carries a second, independent witness where one
exists: the evidence packet's own record of the file, vendored beside it
under `tests/data/note-sources/packet-records/<source sha256>.json`. The
suite checks the declared digest and each quoted line against that record,
and checks that the record's own packet digest is the one the note shows
the user. That is a partial close, not a full one: the packet records no
copy of the audiocraft lines, so block 2 has one witness, and both
witnesses are in this tree. `tools/verify_note_sources.py --packets DIR`
re-derives both from the evidence packets themselves when they are to
hand; it takes the directory as an argument and no path is committed.

## Checking an advisory note against the evidence packets

An advisory note's quoted source is pinned twice inside this tree - the
source file under `tests/data/note-sources/`, and the evidence packet's own
record of it beside it - so both can be forged together by one seat willing
to make the edits agree. Only the packets themselves settle it, and they
are not in this repository:

```sh
make notes PACKETS=<directory holding the licence-evidence-* packets>
```

**A release gate runs that, and it must be run before an advisory note's
digest is re-pinned anywhere downstream.** `make check` reaches it through
`notes-guarded`, which runs it whenever `PACKETS` is set and prints a
`notes: SKIPPED` block naming what was not checked when it is not - so a
gate that omits the second witness says so rather than passing quietly.

## Changing what this authority says on a consent screen

An advisory note has two kinds of line. Lines under a `quoted from` header
are re-derived from their named source byte for byte. Every other line -
the preamble, and each block's three header lines - is **authored**, and is
**pinned, not screened**: it must appear byte for byte in
`ADVISORY_NOTE_AUTHORED` in `src/kilix_license/generate.py`, keyed by the
note's sha256. Screening authored prose for licence vocabulary could not
work, because a false sentence can be written in plain English; the
constraint is equality with a declaration, so a new or altered authored
sentence is refused whatever it says.

The declaration is itself pinned, by a digest typed beside it in
`ADVISORY_NOTE_AUTHORED_PIN`. Without that, the declaration could be made to
derive from the note file - and then the note would be compared with itself,
the suite would stay green, and a new sentence would reach a consent screen
with nothing in the diff to read. The pin is typed and never computed, and
the suite requires the declaration to be a literal in the source, so a
computed declaration is refused rather than satisfied.

To change it deliberately, in one place:

1. edit the note under `src/kilix_license/data/texts/` and rename it to its
   new sha256;
2. copy its authored lines - in note order, blank lines omitted - into
   `ADVISORY_NOTE_AUTHORED` under the new digest, and put the declaration's
   own sha256 in `ADVISORY_NOTE_AUTHORED_PIN` beside it **and** in
   `AUTHORED_PIN` in `tests/test_records.py`, the suite's independently
   typed copy of the same figure (every refusal prints the value);
3. point `ADVISORY_TEXTS` and `ADVISORY_TEXT_SOURCES` at the new digest;
4. run `make regenerate`, which **writes** the records - `make records` is
   `--check` and refuses until they are written;
5. `git add -A`, because three tests read the committed tree and the renamed
   note is a new path, then run `make check`.

The generator's refusals state those five steps, including the two an editor
meets first: the digest mismatch before the rename, and the missing file just
after it. Widening a detector is not an alternative: a sentence absent from
that declaration never reaches a user.

