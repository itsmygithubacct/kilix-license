"""One receipt store root, for the writer and for the reader (V-ACC F7).

V-ACC-VERIFY F7, demonstrated rather than argued: kilix-content's real
first-use flow rendered the licence, took the typed agreement and filed a
receipt; the kilix-voice weights gate then refused, because the two sides had
each chosen a receipt store root and the choices differed. Nothing in the
symptom points at the cause -- the user sees a gate telling them to accept a
licence they have just accepted.

OD-AJ makes this authority the one place such a fact is decided, so the root is
decided here: :func:`kilix_license.paths.receipt_store_root`, and
:meth:`ReceiptStore.shared`, which no caller passes a path to.

The last test here is the verifier's ``interop.py`` adapted to this repository.
It keeps its shape -- a producing process files a receipt, a separate consuming
process looks for it, and a control arm files at a root the writer chose -- with
an in-repository producer in place of kilix-content's flow, because this suite
must be green in a fresh clone with no other repository present. The
cross-repository run against kilix-content is in LIC6-IMPL.md.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from kilix_license.errors import ReceiptStoreRootRefused
from kilix_license.paths import (
    RECEIPT_STORE_ENV,
    RECEIPT_STORE_LEAF,
    STACK_HOME_ENV,
    check_receipt_store_root,
    live_store_root,
    receipt_store_root,
    stack_home,
)
from kilix_license.store import ReceiptStore

ROOT = Path(__file__).resolve().parents[1]

# The producer: renders nothing, but does exactly what a first-use flow does at
# the receipt -- capture the agreement, mint the receipt, file it -- and never
# names a directory. It is run as a separate interpreter so "the writer" and
# "the reader" are two processes that share only this authority, which is the
# arrangement V-ACC F7 broke.
_WRITER = """
import json, sys
import kilix_license as KL

records = KL.RecordIndex(KL.load_determined_records())
record = records.by_id(sys.argv[1])
store = KL.ReceiptStore.shared() if sys.argv[2] == "shared" else KL.ReceiptStore(sys.argv[2])
typed = KL.typed_agreement_line(record) if record.expected_decision == "accept" else None
agreement = KL.capture_agreement(record, typed)
receipt = KL.receipt_from_agreement(
    record, agreement,
    manifest_digest=sys.argv[3], release_digest="0" * 64, catalogue_digest="1" * 64)
path = store.write(receipt)
print(json.dumps({"root": str(store.root), "path": str(path),
                  "record_digest": record.digest,
                  "acceptance": receipt.acceptance.to_jsonable()}))
"""

# The consumer: the shape of the kilix-voice gate. It also names no directory.
_READER = """
import json, sys
import kilix_license as KL

records = KL.RecordIndex(KL.load_determined_records())
record = records.by_id(sys.argv[1])
store = KL.ReceiptStore.shared()
ref = KL.AssetRef(id=sys.argv[1], record_digest=record.digest, manifest_digest=sys.argv[2])
try:
    receipt = KL.require(ref, records=records, store=store)
except KL.CoverageRefused as error:
    print(json.dumps({"outcome": "REFUSED", "field": error.field,
                      "root": str(store.root)}))
else:
    print(json.dumps({"outcome": "COVERED", "root": str(store.root),
                      "record_digest": receipt.record_digest}))
"""

RECORD_ID = "small-en-us"
MANIFEST = "9" * 64


class ReceiptStoreRootTests(unittest.TestCase):
    """Where receipts go, decided once."""

    def setUp(self) -> None:
        self.scratch = Path(tempfile.mkdtemp(prefix="kilix-license-receipt-root-"))

    def _env(self, home: Path, *, override: str | None = None) -> dict[str, str]:
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(ROOT / "src"), str(ROOT / "tests" / "support")]
        )
        env[STACK_HOME_ENV] = str(home)
        env["TMPDIR"] = str(self.scratch / "tmp")
        os.makedirs(env["TMPDIR"], exist_ok=True)
        env.pop(RECEIPT_STORE_ENV, None)
        if override is not None:
            env[RECEIPT_STORE_ENV] = override
        return env

    def _run(self, program: str, *args: str, env: dict[str, str]) -> dict:
        result = subprocess.run(
            [sys.executable, "-c", program, *args],
            capture_output=True, text=True, env=env, check=False, timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_the_default_root_is_the_stack_home_plus_one_leaf(self) -> None:
        # Derived, not typed: the composition every consumer must stop doing
        # for itself is asserted here once, so a change to the base or the leaf
        # fails in this repository instead of in a user's bug report. This is
        # byte for byte what voicelib.licensing.receipt_store_root() composes
        # today, so the wrapper it becomes is a thin one.
        home = self.scratch / "stack-home"
        # The literal, deliberately. RECEIPT_STORE_LEAF would agree with any
        # value it was given; what has to hold is the value every consumer
        # already composes for itself, so that moving it fails here and is
        # recognised as a stack-wide change rather than a rename.
        self.assertEqual(RECEIPT_STORE_LEAF, "license-receipts")
        self.assertEqual(STACK_HOME_ENV, "GPU_TERMINAL_HOME")
        self.assertEqual(RECEIPT_STORE_ENV, "KILIX_LICENSE_RECEIPTS")
        with mock.patch.dict(os.environ, {STACK_HOME_ENV: str(home)}, clear=False):
            os.environ.pop(RECEIPT_STORE_ENV, None)
            self.assertEqual(stack_home(), home)
            self.assertEqual(receipt_store_root(), home / "license-receipts")
            self.assertEqual(receipt_store_root(), home / RECEIPT_STORE_LEAF)

    def test_with_no_stack_home_the_root_follows_the_nss_home(self) -> None:
        # No store is constructed here: this arm resolves to the invoking
        # user's real store, which this suite never touches (tests/__init__).
        environment = {k: v for k, v in os.environ.items()
                       if k not in (STACK_HOME_ENV, RECEIPT_STORE_ENV)}
        with mock.patch.dict(os.environ, environment, clear=True):
            self.assertEqual(stack_home(), live_store_root())
            self.assertEqual(
                receipt_store_root(), live_store_root() / RECEIPT_STORE_LEAF
            )

    def test_the_override_moves_the_root_for_every_caller_at_once(self) -> None:
        elsewhere = self.scratch / "deployment-chosen"
        with mock.patch.dict(
            os.environ,
            {STACK_HOME_ENV: str(self.scratch / "stack-home"),
             RECEIPT_STORE_ENV: str(elsewhere)},
            clear=False,
        ):
            self.assertEqual(receipt_store_root(), elsewhere)
            store = ReceiptStore.shared()
            self.assertEqual(store.root, elsewhere)
            # and a caller that hands in the same path is accepted
            self.assertEqual(ReceiptStore.shared(elsewhere).root, elsewhere)

    def test_a_relative_root_is_refused_rather_than_resolved_somewhere(self) -> None:
        for variable in (STACK_HOME_ENV, RECEIPT_STORE_ENV):
            with self.subTest(variable=variable):
                with mock.patch.dict(
                    os.environ, {variable: "relative/receipts"}, clear=False
                ):
                    with self.assertRaises(ReceiptStoreRootRefused) as caught:
                        receipt_store_root()
                    self.assertIn(variable, str(caught.exception))

    def test_a_root_the_caller_chose_is_refused_and_says_where_to_look(self) -> None:
        # The F7 shape, refused at the moment it is made instead of at the
        # gate, one process and one licence screen later.
        home = self.scratch / "stack-home"
        chosen = self.scratch / "content-chosen-root"
        with mock.patch.dict(os.environ, {STACK_HOME_ENV: str(home)}, clear=False):
            os.environ.pop(RECEIPT_STORE_ENV, None)
            with self.assertRaises(ReceiptStoreRootRefused) as caught:
                ReceiptStore.shared(chosen)
            message = str(caught.exception)
            for expected in (str(chosen), str(home / RECEIPT_STORE_LEAF),
                             RECEIPT_STORE_ENV, STACK_HOME_ENV):
                self.assertIn(expected, message)
            with self.assertRaises(ReceiptStoreRootRefused):
                check_receipt_store_root(chosen)
            # Nothing was created at the root the caller wanted.
            self.assertFalse(chosen.exists())
            # ReceiptStore itself is unchanged: a fixture store still works.
            self.assertEqual(ReceiptStore(chosen).root, chosen)

    def test_a_writer_and_a_reader_that_never_name_a_path_agree(self) -> None:
        # The verifier's interop.py, adapted. Two processes, two roles, no
        # path spelled by either: the writer files, the reader requires, and
        # the same receipt is found. If this authority ever hands the two
        # sides different answers, this fails.
        home = self.scratch / "agree"
        env = self._env(home)
        written = self._run(_WRITER, RECORD_ID, "shared", MANIFEST, env=env)
        self.assertEqual(written["root"], str(home / RECEIPT_STORE_LEAF))
        self.assertTrue(Path(written["path"]).is_file())
        read = self._run(_READER, RECORD_ID, MANIFEST, env=env)
        self.assertEqual(read["outcome"], "COVERED", read)
        self.assertEqual(read["root"], written["root"])
        self.assertEqual(read["record_digest"], written["record_digest"])
        # V-ACC-VERIFY F6: the receipt the writer filed says when it was
        # captured, as whom, and whether there was a terminal.
        self.assertEqual(
            set(written["acceptance"]),
            {"capture_mode", "captured_at", "captured_by_account", "captured_by_uid"},
        )
        self.assertEqual(written["acceptance"]["capture_mode"], "no-tty")

    def test_a_writer_that_picks_its_own_root_leaves_the_reader_refusing(self) -> None:
        # I.4 in the verifier's run, and the whole of F7: the acceptance
        # succeeded, the receipt exists, and the gate still says no.
        home = self.scratch / "disagree"
        chosen = self.scratch / "writer-chosen-root"
        env = self._env(home)
        written = self._run(_WRITER, RECORD_ID, str(chosen), MANIFEST, env=env)
        self.assertEqual(written["root"], str(chosen))
        self.assertTrue(Path(written["path"]).is_file())
        read = self._run(_READER, RECORD_ID, MANIFEST, env=env)
        self.assertEqual(read["outcome"], "REFUSED", read)
        self.assertEqual(read["field"], "receipt")
        self.assertNotEqual(read["root"], written["root"])
        # And that writer, had it asked for the shared store by name, would
        # have been told so at the point of the mistake.
        with mock.patch.dict(os.environ, {STACK_HOME_ENV: str(home)}, clear=False):
            os.environ.pop(RECEIPT_STORE_ENV, None)
            with self.assertRaises(ReceiptStoreRootRefused):
                ReceiptStore.shared(chosen)

    def test_the_override_keeps_writer_and_reader_together(self) -> None:
        home = self.scratch / "override-home"
        elsewhere = self.scratch / "override-root"
        env = self._env(home, override=str(elsewhere))
        written = self._run(_WRITER, RECORD_ID, "shared", MANIFEST, env=env)
        self.assertEqual(written["root"], str(elsewhere))
        read = self._run(_READER, RECORD_ID, MANIFEST, env=env)
        self.assertEqual(read["outcome"], "COVERED", read)
        self.assertEqual(read["root"], str(elsewhere))


if __name__ == "__main__":
    unittest.main()
