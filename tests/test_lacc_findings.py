"""LIC-ACC R1 findings as tests (seat 6f850afe), adapted to pass on this head."""
from dataclasses import replace
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

from kilix_license.agreement import Agreement, capture_agreement, typed_agreement_line
from kilix_license.coverage import covers
from kilix_license.errors import AgreementRequired, AtomicWriteCrashed, CoverageRefused, LiveStoreForbidden
from kilix_license.paths import live_store_root
from kilix_license.receipts import receipt_from_agreement
from kilix_license.records import Advisory, BindingCondition
from kilix_license.store import ReceiptStore
from fixtures import FIXTURE_CATALOGUE, FIXTURE_MANIFEST, FIXTURE_RELEASE, build_fixtures
from live_store_guard import live_root
from weight_scan import scan_tree

ROOT = Path(__file__).resolve().parents[1]


def _receipt(fx, record, agreement):
    return receipt_from_agreement(
        record,
        agreement,
        manifest_digest=FIXTURE_MANIFEST,
        release_digest=FIXTURE_RELEASE,
        catalogue_digest=FIXTURE_CATALOGUE,
    )


class LaccFindings(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="lacc-findings-"))
        self.fx = build_fixtures(self.root)
        self.agreement = capture_agreement(
            self.fx.pocket, typed_agreement_line(self.fx.pocket)
        )
        self.receipt = _receipt(self.fx, self.fx.pocket, self.agreement)

    def test_F1_changed_advisory_text_keeps_coverage(self):
        digest = self.fx.texts.put(self.fx.advisory + b"Revised.\n", label="advisory-v2")
        revised = replace(self.fx.pocket, advisories=(Advisory("research-use", digest),))
        self.assertEqual(revised.digest, self.fx.pocket.digest)
        self.assertTrue(
            covers(revised, self.receipt, manifest_digest=FIXTURE_MANIFEST)
        )

    def test_F2a_agreement_captured_for_other_binding_text_is_refused(self):
        digest = self.fx.texts.put(
            self.fx.pocket_prohibited + b" Changed.", label="binding-v2"
        )
        changed = replace(
            self.fx.pocket,
            binding_conditions=(BindingCondition("pocket-prohibited-use", digest, True),),
        )
        with self.assertRaises(AgreementRequired):
            _receipt(self.fx, changed, self.agreement)

    def test_F2b_accept_receipt_requires_the_typed_line(self):
        forged = Agreement(self.fx.pocket.id, ("pocket-prohibited-use",), "accept", None)
        with self.assertRaises(AgreementRequired):
            _receipt(self.fx, self.fx.pocket, forged)

    def test_F3_openfst_header_is_detected(self):
        tree = Path(tempfile.mkdtemp(prefix="lacc-fst-"))
        (tree / "graph").mkdir()
        (tree / "graph" / "Gr.fst").write_bytes(
            struct.pack("<i", 2125659606) + b"\x06\x00\x00\x00vector" + b"\x00" * 32
        )
        env = dict(
            os.environ,
            GIT_AUTHOR_NAME="x",
            GIT_AUTHOR_EMAIL="x@invalid",
            GIT_COMMITTER_NAME="x",
            GIT_COMMITTER_EMAIL="x@invalid",
        )
        subprocess.run(["git", "init", "-q", str(tree)], check=True, env=env)
        subprocess.run(["git", "-C", str(tree), "add", "-A"], check=True, env=env)
        self.assertNotEqual(
            [], scan_tree(tree, ROOT / "tests" / "data" / "catalog_digests.txt")
        )

    def test_F5_covers_does_not_accept_a_receipt_for_another_manifest(self):
        other = replace(self.receipt, manifest_digest="0" * 64)
        with self.assertRaises(TypeError):
            covers(self.fx.pocket, other)  # weak two-argument form
        try:
            result = covers(
                self.fx.pocket, other, manifest_digest=FIXTURE_MANIFEST
            )
        except CoverageRefused as exc:
            self.assertEqual(exc.field, "manifest_digest")
        else:
            self.fail(
                f"covers() returned {result!r} for a receipt bound to another manifest"
            )

    def test_F6_receipt_write_recovers_after_a_crash(self):
        store = ReceiptStore(self.root / "receipts")
        with self.assertRaises(AtomicWriteCrashed):
            store.write(self.receipt, crash_before_replace=True)
        store.write(self.receipt)
        self.assertIsNotNone(
            store.lookup(self.receipt.record_digest, self.receipt.manifest_digest)
        )


def _live_store_is_masked() -> bool:
    live = str(live_store_root())
    try:
        lines = Path("/proc/self/mountinfo").read_text().splitlines()
    except OSError:
        return False
    for line in lines:
        fields = line.split()
        if len(fields) > 4 and fields[4] == live and " - tmpfs lacc-sentinel " in line:
            return True
    return False


@unittest.skipUnless(_live_store_is_masked(), "runs only with tmpfs lacc-sentinel over the live store")
class LaccGuardFinding(unittest.TestCase):
    def test_F4_guard_refuses_dir_fd_relative_create(self):
        live = live_store_root()
        fd = os.open(str(live.parent), os.O_RDONLY | os.O_DIRECTORY)
        try:
            with self.assertRaises(LiveStoreForbidden):
                os.close(
                    os.open(
                        "gpu_terminal/lacc-f4-dirfd.json",
                        os.O_CREAT | os.O_WRONLY,
                        0o600,
                        dir_fd=fd,
                    )
                )
        finally:
            os.close(fd)

    def test_F4_guard_refuses_truncate(self):
        target = live_store_root() / "sentinel.txt"
        with self.assertRaises(LiveStoreForbidden):
            os.truncate(str(target), 0)


class LaccGuardAlways(unittest.TestCase):
    def test_F4_guard_refuses_dir_fd_relative_create(self):
        live = live_root()
        fd = os.open(str(live.parent), os.O_RDONLY | os.O_DIRECTORY)
        try:
            with self.assertRaises(LiveStoreForbidden):
                os.open(
                    "gpu_terminal/lacc-f4-dirfd.json",
                    os.O_CREAT | os.O_WRONLY,
                    0o600,
                    dir_fd=fd,
                )
        finally:
            os.close(fd)

    def test_F4_guard_refuses_truncate(self):
        with self.assertRaises(LiveStoreForbidden):
            os.truncate(str(live_root() / "sentinel.txt"), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
