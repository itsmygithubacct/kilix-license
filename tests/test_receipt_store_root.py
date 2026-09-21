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
    STACK_HOME_DIRS,
    STACK_HOME_ENV,
    check_receipt_store_root,
    is_under_live_store,
    live_store_root,
    live_store_roots,
    nss_home,
    receipt_store_root,
    stack_home,
    user_home,
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

    def test_with_no_stack_home_the_root_follows_the_stacks_own_home(self) -> None:
        # LIC6-VERIFY F1. With $GPU_TERMINAL_HOME unset the root must compose
        # what every OTHER component composes: $HOME/.local/gpu_terminal plus
        # the leaf. It used to compose the NSS passwd home's, which ignores
        # $HOME, so in any environment where the two differ -- a sandbox, a
        # service unit, `su` without `-l` -- the writer filed a receipt at one
        # root and the reader refused at another. The literals are typed here
        # deliberately: they are the stack's convention, not this module's
        # preference, and moving either must fail in this repository.
        #
        # No store is constructed in this arm: it resolves under the invoking
        # user's own home, which this suite never writes to (tests/__init__).
        self.assertEqual(STACK_HOME_DIRS, (".local", "gpu_terminal"))
        environment = {k: v for k, v in os.environ.items()
                       if k not in (STACK_HOME_ENV, RECEIPT_STORE_ENV)}
        with mock.patch.dict(os.environ, environment, clear=True):
            expected = Path(os.path.expanduser("~")) / ".local" / "gpu_terminal"
            self.assertEqual(stack_home(), expected)
            self.assertEqual(stack_home(), user_home().joinpath(*STACK_HOME_DIRS))
            self.assertEqual(
                receipt_store_root(), expected / RECEIPT_STORE_LEAF
            )

    def test_the_fallback_is_what_every_other_component_composes(self) -> None:
        # The claim LIC6-VERIFY F1 falsified, re-stated as a test rather than
        # as prose: with $GPU_TERMINAL_HOME unset, this authority's root and
        # voicelib.licensing.receipt_store_root() are the same string.
        # voicelib is not importable here, so its two lines are reproduced --
        # os.path.join(os.path.expanduser("~"), ".local", "gpu_terminal") and
        # os.path.join(that, "license-receipts") -- against an $HOME that is
        # NOT the passwd home, which is the only case that ever differed.
        elsewhere = self.scratch / "sandbox-home"
        elsewhere.mkdir()
        environment = {k: v for k, v in os.environ.items()
                       if k not in (STACK_HOME_ENV, RECEIPT_STORE_ENV)}
        environment["HOME"] = str(elsewhere)
        with mock.patch.dict(os.environ, environment, clear=True):
            self.assertNotEqual(str(elsewhere), str(nss_home()))
            voicelib_home = os.path.join(
                os.path.expanduser("~"), ".local", "gpu_terminal"
            )
            voicelib_root = os.path.join(voicelib_home, "license-receipts")
            self.assertEqual(str(stack_home()), voicelib_home)
            self.assertEqual(str(receipt_store_root()), voicelib_root)
            # and it is NOT the passwd home's, which is what it used to be
            self.assertNotEqual(
                str(receipt_store_root()),
                str(nss_home() / ".local" / "gpu_terminal" / "license-receipts"),
            )

    def test_the_live_store_guard_still_reads_the_passwd_home(self) -> None:
        # Mutant v5's lesson: nss_home() also backs the live-store guard, so
        # the root fix had to SPLIT the two, not move both. The guard must
        # keep reading the passwd home, because the suite redirects $HOME into
        # a scratch directory -- a $HOME-based guard would stop guarding the
        # real store exactly while the suite runs.
        self.assertEqual(live_store_root(), nss_home().joinpath(*STACK_HOME_DIRS))
        home = user_home()
        if str(home) != str(nss_home()):
            # This is the `make test` case: $HOME is redirected.
            self.assertFalse(
                str(live_store_root()).startswith(str(home) + os.sep),
                f"the live-store guard followed $HOME ({home}) instead of the "
                "passwd home; it would no longer guard the real store",
            )
        # Nothing the guard used to refuse became allowed: both spellings are
        # refused, so broadening the receipt root narrowed no protection.
        for root in live_store_roots():
            with self.subTest(root=str(root)):
                self.assertTrue(is_under_live_store(str(root)))
                self.assertTrue(is_under_live_store(str(root / "license-receipts")))
        self.assertIn(live_store_root(), live_store_roots())
        self.assertIn(user_home().joinpath(*STACK_HOME_DIRS), live_store_roots())

    def test_a_wrong_root_with_the_right_leaf_is_refused(self) -> None:
        # LIC6-VERIFY F5, mutant v1: check_receipt_store_root compared only the
        # basename and the suite never noticed, because every wrong root the
        # suite built had a different leaf (`content-chosen-root`,
        # `writer-chosen-root`, `deployment-chosen`). The wrong root that
        # actually occurs is F1's shape -- a DIFFERENT stack home with the SAME
        # leaf -- and it is a public-API call (KL.check_receipt_store_root) a
        # consumer uses to validate its own configured path.
        agreed_home = self.scratch / "agreed-home"
        other_home = self.scratch / "other-home"
        near_miss = other_home / RECEIPT_STORE_LEAF
        with mock.patch.dict(
            os.environ, {STACK_HOME_ENV: str(agreed_home)}, clear=False
        ):
            os.environ.pop(RECEIPT_STORE_ENV, None)
            agreed = agreed_home / RECEIPT_STORE_LEAF
            self.assertEqual(receipt_store_root(), agreed)
            self.assertEqual(near_miss.name, agreed.name)
            self.assertNotEqual(str(near_miss), str(agreed))
            for call in (check_receipt_store_root, ReceiptStore.shared):
                with self.subTest(call=call.__name__):
                    with self.assertRaises(ReceiptStoreRootRefused) as caught:
                        call(near_miss)
                    message = str(caught.exception)
                    # both FULL paths, not just the leaf they share
                    self.assertIn(str(near_miss), message)
                    self.assertIn(str(agreed), message)
            self.assertFalse(near_miss.exists())

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
        # V-ACC-VERIFY F6 as OD-BC settled it: the receipt the writer filed
        # says when it was captured and whether there was a terminal, and
        # names nobody -- no account, no uid. The literal set is asserted, so
        # an identity field reappearing fails here.
        self.assertEqual(
            set(written["acceptance"]), {"capture_mode", "captured_at"}
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
