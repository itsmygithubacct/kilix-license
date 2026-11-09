# kilix-license

The licence authority for Kilix: licence records stored by text digest, the
verbatim first-use screen, agreement capture, digest-bound receipts and the
coverage check that every model install must pass.

Pinned in Plebian-OS 0.2.3 as `KILIX_LICENSE_REF` in `releases/0.2.3.env`,
where the image build reads its records and texts to produce the release's
model-compliance carrier. On an installed system it runs as the copy that
[kilix-content](https://github.com/itsmygithubacct/kilix-content#readme)
vendors under `third_party/kilix-license`, inside Kilix.

## What it does

- Generates `kilix.license.record/v1` licence records from checked
  determination JSON files under `src/kilix_license/data/`; licence texts are
  copied byte for byte into `data/texts/`, named by their SHA-256, and never
  retyped.
- Renders the first-use screen a user sees before a model is installed, with
  every stored text printed byte-identical and a marker on any bound text that
  changed since an earlier acceptance.
- Captures an agreement: an explicit `yes` or `y` for a licence with binding or
  restrictive terms (`affirmative`), none for an `informational` one whose
  terms are shown and recorded.
- Writes receipts to one shared store and answers whether a receipt covers an
  exact licence record and model manifest (`covers`, `require`).
- Records a standard-licence distribution policy for installs that need no
  typed answer, without claiming human consent.

Runtime code uses the Python standard library only.

## Quick start

```python
from pathlib import Path
from kilix_license import (AssetRef, ReceiptStore, capture_agreement, load_determined_records,
                           load_determined_texts, receipt_from_agreement, render_screen, require)

records = load_determined_records()               # every packaged licence record
record = records.by_id(record_id)            # a record id from data/*records/
texts = load_determined_texts(Path(scratch) / "texts")   # copies the texts into a TextStore
store = ReceiptStore.shared()                     # $GPU_TERMINAL_HOME/license-receipts
screen = render_screen(record, texts, receipts=store, records=records)   # bytes to show
agreement = capture_agreement(record, "yes")      # the user's answer, after the screen
store.write(receipt_from_agreement(record, agreement, manifest_digest=manifest,
                                   release_digest=release, catalogue_digest=catalogue))
require(AssetRef(id=asset_id, record_digest=record.digest, manifest_digest=manifest),
        records=records, store=store)             # raises CoverageRefused when not covered
```

In practice a consumer does not call these directly: kilix-content's
first-use flow (`kilix models install <asset>` in Kilix) and the Kilix model
wizard (`kilix wizard`) drive them.

## Usage

| Call | What it does |
|---|---|
| `load_determined_records()` / `load_determined_texts(dir)` | The packaged records (a `RecordIndex`) and their texts |
| `render_screen(record, texts, *, receipts, records=None)` | The verbatim first-use screen, with changed-text markers |
| `changed_texts(record, receipts, *, records=None)`, `scan_receipts(store)` | Which bound texts changed since an earlier acceptance, and which receipt files were read or skipped |
| `capture_agreement(record, typed_text)` | Agreement for one record; refuses a missing or wrong answer |
| `capture_standard_policy(record)` | Policy authorization for a standard licence with no extra terms |
| `receipt_from_agreement(record, agreement, *, manifest_digest, ...)` | A receipt bound to the record and the exact manifest |
| `ReceiptStore.shared()`, `receipt_store_root()` | The single receipt store and its root |
| `covers(record, receipt, *, manifest_digest)`, `require(asset, *, records, store)` | Coverage: is there a receipt for this record and manifest |

| Make target | What it does |
|---|---|
| `make check` | Sync the frozen environment, run the tests, build and install the wheel, run the advisory-note check when `PACKETS` is set |
| `make records` | Fail unless the committed records equal the generator's output |
| `make regenerate` | Write the records from the determinations |
| `make notes PACKETS=DIR` | Check advisory-note sources against the evidence packets |

## How it works

```
determinations-*.json ──generate──> data/*records/*.json + data/texts/<sha256>
                                            │
consumer (kilix-content, kilix wizard) ─────┤
   render_screen ──> user answers ──> capture_agreement ──> receipt_from_agreement
                                            │
                     ReceiptStore.shared()  ▼  $GPU_TERMINAL_HOME/license-receipts
                                            │
   installer ──> require(record digest, manifest digest) ──> install or refuse
```

A record's digest covers its licence text, bound conditions and component
exceptions; advisories, statements and component entries without exception
text are context and stay out of it. A receipt binds that record digest to
the exact manifest digest of the model it was captured for, so a changed
licence text or a changed model needs a new receipt. The screen, coverage
and receipt-file rules are in [docs/records-and-screen.md](docs/records-and-screen.md),
and the rules for advisory notes shown on a screen are in
[docs/advisory-notes.md](docs/advisory-notes.md).

## Where receipts live

There is one receipt store root, and this authority names it (OD-AJ):
`receipt_store_root()`, which is `$GPU_TERMINAL_HOME/license-receipts` and
is overridden outright by `$KILIX_LICENSE_RECEIPTS`. Producers and
consumers reach it as `ReceiptStore.shared()`, which takes no path; a
caller that hands in a path gets it checked, and anything but the agreed
root raises `ReceiptStoreRootRefused` naming both. `ReceiptStore(root)` is
unchanged and still opens any directory, for fixtures and inspection.

With `$GPU_TERMINAL_HOME` unset the root is **`$HOME/.local/gpu_terminal/license-receipts`**.
That is the composition the rest of the stack already performs -
`voicelib.paths.gpu_terminal_home()` is `os.path.expanduser("~")`, and
`kilix/bootstrap.sh`, `kilix/build.sh` and `pleb/lib/common.sh` all read
`GPU_TERMINAL_HOME="${GPU_TERMINAL_HOME:-$HOME/.local/gpu_terminal}"` - so
the writer and the reader compose the same path with the variable set and
with it unset. It read the NSS passwd home (`pw_dir`) before, which ignores
`$HOME`; wherever the two differ - a sandbox, a service unit, `su` without
`-l` - consent was filed at one root while the gate refused at another,
which is exactly the symptom below. The suite's own live-store guard still
reads `pw_dir`, deliberately and for a different reason: the suite
redirects `$HOME` into a scratch directory, so a `$HOME`-based guard would
stop guarding the real store at the one moment it has to work. Both
spellings are refused by that guard.

This exists because the two sides each used to choose: an acceptance filed
by one component was invisible to another, and the symptom was a gate
refusing a licence the user had just accepted. A consumer that composes its
own path, or adds its own override variable, re-opens that.

Receipts written from LIC4 on also record, as context that is not bound
(OD-AQ), the statement and component-exception digests shown on the screen
and each binding's text identity; from LIC4-FIX on they also record the
licence text identity. Receipts without those keys, as written before LIC4
or LIC4-FIX, are still read and still cover; their identities are resolved
through the record their licence id names (pass `records=`).

From LIC6 a receipt also records an `acceptance` block, again as context
that is not bound. OD-BC settled its shape: exactly two fields, and no
identity. `captured_at` is the capturing machine's own UTC clock at
capture; `capture_mode` is `interactive-tty` when that process had a
terminal on both standard input and standard output, `no-tty` otherwise.
**No account name and no uid is recorded**, so nothing in a receipt
distinguishes two users of one machine - the accepted outcome of OD-BC,
not an oversight. A receipt carrying an identity field is refused, not
ignored.

### What a receipt proves, and what it does not

OD-BC: record, do not bind, in 0.2.2. A receipt is an unsigned JSON file in
the user's own store. It records that this authority captured an agreement
against a particular licence record and manifest, at a stated moment, with
or without a terminal.

**It does not prove that a human accepted anything. It does not say which
human. It does not prove that the recorded time is the real time.** Nothing
signs it, so a producer that wants to fabricate one can. Read the block as
the place to look when asking where a receipt came from, never as consent.

What it does buy: a receipt minted by a build step, an image build or an
unattended provisioning script records `no-tty`, because there is no
terminal there, and that is mechanically distinguishable from one minted at
a console - by inspection, and by
`require(..., captured_at_a_terminal=True)`. OD-BC keeps that lever
**available and off**; the default is unchanged and every earlier receipt
still covers.

### Distribution policy and receipts

Images and model bundles never carry user receipts. Standard licences can be
handled during installation by `capture_standard_policy(record)`, using the
complete determined record and exact model manifest. This writes a local
`standard-license-policy-v1` statement digest in the existing receipt
context, with no typed answer or claim of human consent. Capture mode still
records the actual terminal state. This preserves older receipt readers;
the policy statement distinguishes automated authorization. Original licence texts, notices and modification statements must
remain available beside the installed model.

Unknown licences, extra binding terms and unreviewed component exceptions
still require explicit agreement. The legacy component field also carries
ordinary licence notices: the reviewed Needle 3 MIT runtime notice is allowed
only at its exact digest. A changed notice requires renewed review.

Interactive-terminal-only consumers continue to reject policy receipts.
Existing interactive and noninteractive receipts remain readable.

If a build needs to attest something about licences, that attestation is a
**distinct schema** and never a `kilix.license.receipt/v1` (OD-BC, settling
OQ-C4).

### Compatibility

Receipts written before LIC6 carry no `acceptance` block, read exactly as
before, and cover exactly as before; they are refused only by a caller that
has opted into `captured_at_a_terminal=True`. Receipts written from LIC6 on
are **refused by pre-LIC6 readers**, which reject an unknown context key -
a fail-closed break, so every consumer pinning this authority must re-pin
before anything writes a LIC6 receipt.

This `0.1.0` LIC2 state generates licence records from the checked
determinations JSON (never retyped). The repository licence file is MIT
(OD-AV). LIC3 re-confirms that LICENSE file; the GitHub remote remains
RC-13.

## Publication status

Published as `itsmygithubacct/kilix-license`; the disposition is recorded in
[PUBLICATION.md](PUBLICATION.md). Release pins name exact commits of this
repository.

## Development


The development environment is frozen to Python 3.12.8 and uv 0.12.5.

```sh
uv sync --frozen --python 3.12.8
make check
```

`make check` syncs the frozen environment, runs the test suite, builds
installable artifacts, and reaches the advisory-note source check. Inside a
network sandbox run it as `make check OFFLINE=1`: `uv build` otherwise
resolves the PEP 517 build backend over the network, which uv.lock does not
pin, and the gate fails with a name-resolution error rather than a defect.

### Changing this file

This file's prose is pinned by digest in `tests/test_identity.py`
(whitespace-normalised, so re-wrapping is free and any change to a word is
not). OD-BC's shipping rule is a rule nothing here can enforce except by
being read, and such a rule is reversed just as easily by adding a sentence
elsewhere in the document as by editing the sentence itself - so the
document is constrained rather than screened for the wording of an
exception, which is the same choice the authored-note prose forced. Edit
the prose and update `README_NORMALISED_SHA256`; the failure prints the
value to put there.


## Documentation

| Document | Contents |
|---|---|
| [docs/records-and-screen.md](docs/records-and-screen.md) | Coverage, the first-use screen and its changed-text marker, how receipt files are read, yes/no agreement screens |
| [docs/advisory-notes.md](docs/advisory-notes.md) | Advisory notes: quoted sources, second witnesses, and how to change authored lines |
| [docs/history.md](docs/history.md) | Earlier publication statements from this README |
| [PUBLICATION.md](PUBLICATION.md) | Publication disposition |
| [CHANGELOG.md](CHANGELOG.md) | Record and behaviour changes |

## Related repositories

- [kilix-content](https://github.com/itsmygithubacct/kilix-content#readme):
  vendors this authority and runs the first-use flow for every catalog model.
- [kilix](https://github.com/itsmygithubacct/kilix#readme): `kilix models`
  and the model wizard present the screens this authority renders.
- [plebian-os](https://github.com/itsmygithubacct/plebian-os#readme): pins
  this repository and builds the release's model-compliance carrier from it.

## Part of Plebian-OS

kilix-license is one of the repositories behind
[Plebian-OS](https://github.com/itsmygithubacct/plebian-os#readme), a Debian
install whose desktop is [Kilix](https://github.com/itsmygithubacct/kilix#readme)
running the [Kilix 95](https://github.com/itsmygithubacct/kilix-95#readme)
desktop through [Pleb](https://github.com/itsmygithubacct/pleb#readme).
It is pinned in the release environment for the image's model-compliance
carrier and reaches users as the copy vendored inside kilix-content. The map
of every repository and how it ships is on the
[components page](https://github.com/itsmygithubacct/plebian-os/blob/main/docs/components.md).

## License

Licence: MIT (OD-AV). LIC3 re-confirms the LICENSE file; remote creation is RC-13.

See [LICENSE](LICENSE).
