from dataclasses import replace
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest

from kilix_license.agreement import Agreement, capture_agreement, typed_agreement_line
from kilix_license.coverage import covers
from kilix_license.errors import (
    AgreementRequired,
    AtomicWriteCrashed,
    CoverageRefused,
    ParaphraseRefused,
)
from kilix_license.paraphrase import POCKET_TERMS_SUMMARY, POCKET_TERMS_SUMMARY_BYTES
from kilix_license.receipts import receipt_from_agreement
from kilix_license.records import (
    Advisory,
    BindingCondition,
    Component,
    LicenseRecord,
    Statement,
)
from kilix_license.screen import render_screen
from kilix_license.store import ReceiptStore

from fake_store import FakeStore
from fixtures import (
    FIXTURE_CATALOGUE,
    FIXTURE_MANIFEST,
    FIXTURE_RELEASE,
    build_fixtures,
)


class AuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="kilix-license-authority-"))
        self.fixtures = build_fixtures(self.root)
        self.store = FakeStore(self.root / "receipts")

    def _pocket_receipt(self):
        agreement = capture_agreement(
            self.fixtures.pocket,
            typed_agreement_line(self.fixtures.pocket),
        )
        return receipt_from_agreement(
            self.fixtures.pocket,
            agreement,
            manifest_digest=FIXTURE_MANIFEST,
            release_digest=FIXTURE_RELEASE,
            catalogue_digest=FIXTURE_CATALOGUE,
        )

    def test_screen_texts_are_byte_identical_to_stored_digests(self) -> None:
        output = render_screen(
            self.fixtures.pocket, self.fixtures.texts, receipts=self.store
        )
        self.assertIn(self.fixtures.pocket_licence, output)
        self.assertIn(self.fixtures.pocket_prohibited, output)
        self.assertIn(self.fixtures.advisory, output)
        self.assertNotIn(POCKET_TERMS_SUMMARY_BYTES, output)
        self.assertNotIn(POCKET_TERMS_SUMMARY.encode("utf-8"), output)

    def test_planted_pocket_terms_summary_paraphrase_refused(self) -> None:
        with self.assertRaises(ParaphraseRefused):
            self.fixtures.texts.put(POCKET_TERMS_SUMMARY_BYTES, label="planted")

    def test_kristin_needs_no_typed_agreement(self) -> None:
        agreement = capture_agreement(self.fixtures.kristin)
        self.assertEqual(agreement.decision, "record")
        self.assertIsNone(agreement.typed_text)
        receipt = receipt_from_agreement(
            self.fixtures.kristin,
            agreement,
            manifest_digest=FIXTURE_MANIFEST,
            release_digest=FIXTURE_RELEASE,
            catalogue_digest=FIXTURE_CATALOGUE,
        )
        self.assertEqual(receipt.binding_condition_text_digests, {})
        self.assertTrue(
            covers(self.fixtures.kristin, receipt, manifest_digest=FIXTURE_MANIFEST)
        )

    def test_kristin_rejects_typed_agreement(self) -> None:
        with self.assertRaises(AgreementRequired):
            capture_agreement(self.fixtures.kristin, "accept")

    def test_pocket_requires_typed_agreement_naming_binding_texts(self) -> None:
        with self.assertRaises(AgreementRequired):
            capture_agreement(self.fixtures.pocket)
        with self.assertRaises(AgreementRequired):
            capture_agreement(self.fixtures.pocket, "accept")
        licence_only = (
            f"accept {self.fixtures.pocket.id} from {self.fixtures.pocket.licensor}"
        )
        with self.assertRaises(AgreementRequired):
            capture_agreement(self.fixtures.pocket, licence_only)
        line = typed_agreement_line(self.fixtures.pocket)
        self.assertIn("cc-by-4.0-pocket-tts", line)
        self.assertIn("pocket-prohibited-use", line)
        self.assertIn("Kyutai", line)
        agreement = capture_agreement(self.fixtures.pocket, line)
        self.assertEqual(agreement.decision, "accept")

    def test_receipt_json_has_bound_fields_plus_context(self) -> None:
        receipt = self._pocket_receipt()
        payload = receipt.to_jsonable()
        self.assertEqual(
            set(payload),
            {
                "schema",
                "record_digest",
                "manifest_digest",
                "licence_id",
                "licence_text_digest",
                "decision",
                "licensor",
                "binding_condition_text_digests",
                "context",
            },
        )
        # LIC4 adds three context keys (recorded, not bound); fbdfb546 wrote three.
        self.assertEqual(
            set(payload["context"]),
            {
                "advisory_digests",
                "release_digest",
                "catalogue_digest",
                "binding_text_ids",
                "component_exception_digests",
                "statement_digests",
            },
        )
        self.assertEqual(payload["decision"], "accept")
        self.assertEqual(payload["licensor"], "Kyutai")
        self.assertIn("pocket-prohibited-use", payload["binding_condition_text_digests"])

    def test_advisory_change_does_not_void_coverage(self) -> None:
        receipt = self._pocket_receipt()
        self.assertTrue(
            covers(self.fixtures.pocket, receipt, manifest_digest=FIXTURE_MANIFEST)
        )
        other = replace(
            receipt,
            advisory_digests={
                "research-use": "0" * 63 + "1",
            },
        )
        self.assertTrue(
            covers(self.fixtures.pocket, other, manifest_digest=FIXTURE_MANIFEST)
        )
        released = replace(receipt, release_digest="1" * 64)
        self.assertTrue(
            covers(self.fixtures.pocket, released, manifest_digest=FIXTURE_MANIFEST)
        )
        catalogued = replace(receipt, catalogue_digest="2" * 64)
        self.assertTrue(
            covers(self.fixtures.pocket, catalogued, manifest_digest=FIXTURE_MANIFEST)
        )

    def test_advisory_change_planted_in_the_record_keeps_coverage(self) -> None:
        receipt = self._pocket_receipt()
        digest = self.fixtures.texts.put(
            self.fixtures.advisory + b"Revised.\n", label="advisory-v2"
        )
        revised = replace(
            self.fixtures.pocket, advisories=(Advisory("research-use", digest),)
        )
        self.assertEqual(revised.digest, self.fixtures.pocket.digest)
        self.assertTrue(
            covers(revised, receipt, manifest_digest=FIXTURE_MANIFEST)
        )
        next_receipt = receipt_from_agreement(
            revised,
            capture_agreement(revised, typed_agreement_line(revised)),
            manifest_digest=FIXTURE_MANIFEST,
            release_digest=FIXTURE_RELEASE,
            catalogue_digest=FIXTURE_CATALOGUE,
        )
        self.assertEqual(next_receipt.record_digest, receipt.record_digest)
        self.assertEqual(next_receipt.advisory_digests["research-use"], digest)
        self.assertNotEqual(receipt.advisory_digests["research-use"], digest)
        screen = render_screen(revised, self.fixtures.texts, receipts=self.store)
        self.assertIn(self.fixtures.advisory + b"Revised.\n", screen)

    def test_statement_change_planted_in_the_record_keeps_coverage(self) -> None:
        agreement = capture_agreement(self.fixtures.kristin)
        receipt = receipt_from_agreement(
            self.fixtures.kristin,
            agreement,
            manifest_digest=FIXTURE_MANIFEST,
            release_digest=FIXTURE_RELEASE,
            catalogue_digest=FIXTURE_CATALOGUE,
        )
        digest = self.fixtures.texts.put(
            self.fixtures.kristin_text + b"Note.\n", label="statement-v2"
        )
        revised = replace(
            self.fixtures.kristin,
            statements=(Statement("trainer-statement", digest),),
        )
        self.assertEqual(revised.digest, self.fixtures.kristin.digest)
        self.assertTrue(
            covers(revised, receipt, manifest_digest=FIXTURE_MANIFEST)
        )

    def test_component_without_exception_change_keeps_coverage(self) -> None:
        receipt = self._pocket_receipt()
        revised = replace(
            self.fixtures.pocket,
            components=(Component(id="pocket-tts", role="renamed"),),
        )
        self.assertEqual(revised.digest, self.fixtures.pocket.digest)
        self.assertTrue(
            covers(revised, receipt, manifest_digest=FIXTURE_MANIFEST)
        )

    def test_binding_text_change_re_presents(self) -> None:
        receipt = self._pocket_receipt()
        new_text = self.fixtures.pocket_prohibited + b"X"
        digest = self.fixtures.texts.put(new_text, label="pocket-prohibited-changed")
        changed = LicenseRecord(
            id=self.fixtures.pocket.id,
            licensor=self.fixtures.pocket.licensor,
            text_sha256=self.fixtures.pocket.text_sha256,
            components=self.fixtures.pocket.components,
            binding_conditions=(
                BindingCondition(
                    id="pocket-prohibited-use",
                    text_sha256=digest,
                    agreement_required=True,
                ),
            ),
            advisories=self.fixtures.pocket.advisories,
            statements=self.fixtures.pocket.statements,
        )
        with self.assertRaises(CoverageRefused) as refused:
            covers(changed, receipt, manifest_digest=FIXTURE_MANIFEST)
        self.assertEqual(
            refused.exception.field,
            "binding_condition_text_digests:pocket-prohibited-use",
        )
        self.store.write(receipt)
        screen = render_screen(changed, self.fixtures.texts, receipts=self.store)
        section = b"=== binding:pocket-prohibited-use ===\n" + new_text
        self.assertIn(section, screen)
        # SR-4: the earlier acceptance of other bytes is marked, before the text.
        marker = screen.find(b"=== changed since your last acceptance ===\n")
        self.assertGreaterEqual(marker, 0)
        self.assertLess(marker, screen.find(section))
        with self.assertRaises(AgreementRequired):
            receipt_from_agreement(
                changed,
                capture_agreement(
                    self.fixtures.pocket, typed_agreement_line(self.fixtures.pocket)
                ),
                manifest_digest=FIXTURE_MANIFEST,
                release_digest=FIXTURE_RELEASE,
                catalogue_digest=FIXTURE_CATALOGUE,
            )

    def test_accept_receipt_requires_the_typed_line(self) -> None:
        forged = Agreement(
            self.fixtures.pocket.id, ("pocket-prohibited-use",), "accept", None
        )
        with self.assertRaises(AgreementRequired):
            receipt_from_agreement(
                self.fixtures.pocket,
                forged,
                manifest_digest=FIXTURE_MANIFEST,
                release_digest=FIXTURE_RELEASE,
                catalogue_digest=FIXTURE_CATALOGUE,
            )

    def test_receipt_from_agreement_requires_named_binding_ids(self) -> None:
        agreement = capture_agreement(
            self.fixtures.pocket, typed_agreement_line(self.fixtures.pocket)
        )
        stripped = replace(agreement, named_binding_ids=())
        with self.assertRaises(AgreementRequired):
            receipt_from_agreement(
                self.fixtures.pocket,
                stripped,
                manifest_digest=FIXTURE_MANIFEST,
                release_digest=FIXTURE_RELEASE,
                catalogue_digest=FIXTURE_CATALOGUE,
            )

    def test_crash_mid_write_leaves_no_covering_receipt(self) -> None:
        receipt = self._pocket_receipt()
        with self.assertRaises(AtomicWriteCrashed):
            self.store.write(receipt, crash_before_replace=True)
        self.assertIsNone(
            self.store.lookup(receipt.record_digest, receipt.manifest_digest)
        )
        leftovers = list(self.store.root.glob("*.json"))
        self.assertEqual([], leftovers)
        tmps = [p for p in self.store.root.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(1, len(tmps))
        self.assertEqual(tmps[0].read_bytes(), receipt.to_bytes())
        with self.assertRaises(CoverageRefused):
            from kilix_license.coverage import require, AssetRef

            require(
                AssetRef(
                    id="pocket-tts",
                    record_digest=receipt.record_digest,
                    manifest_digest=receipt.manifest_digest,
                ),
                records=self.fixtures.index,
                store=self.store,
            )

    def test_receipt_write_recovers_after_a_crash(self) -> None:
        receipt = self._pocket_receipt()
        with self.assertRaises(AtomicWriteCrashed):
            self.store.write(receipt, crash_before_replace=True)
        self.store.write(receipt)
        self.assertIsNotNone(
            self.store.lookup(receipt.record_digest, receipt.manifest_digest)
        )

    def test_receipt_write_recovers_after_sigkill_at_replace(self) -> None:
        receipt = self._pocket_receipt()
        root = Path(tempfile.mkdtemp(prefix="kilix-license-sigkill-"))
        repo = Path(__file__).resolve().parents[1]
        helper = r"""
import os, signal, sys
from pathlib import Path
from kilix_license.agreement import capture_agreement, typed_agreement_line
from kilix_license.receipts import receipt_from_agreement
from kilix_license.store import ReceiptStore
from fixtures import FIXTURE_CATALOGUE, FIXTURE_MANIFEST, FIXTURE_RELEASE, build_fixtures
root = Path(sys.argv[1])
fx = build_fixtures(root / "fx")
r = receipt_from_agreement(
    fx.pocket,
    capture_agreement(fx.pocket, typed_agreement_line(fx.pocket)),
    manifest_digest=FIXTURE_MANIFEST,
    release_digest=FIXTURE_RELEASE,
    catalogue_digest=FIXTURE_CATALOGUE,
)
store = ReceiptStore(root / "receipts")
os.replace = lambda *a, **k: os.kill(os.getpid(), signal.SIGKILL)
store.write(r)
"""
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(repo / "src"), str(repo / "tests" / "support")]
        )
        proc = subprocess.run(
            [sys.executable, "-c", helper, str(root)],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, -signal.SIGKILL, proc.stderr)
        store = ReceiptStore(root / "receipts")
        store.write(receipt)
        self.assertIsNotNone(
            store.lookup(receipt.record_digest, receipt.manifest_digest)
        )

    def test_screen_includes_component_exception_bytes(self) -> None:
        digest = self.fixtures.texts.put(
            b"Tokenizer component exception fixture.\n", label="component-exception"
        )
        record = replace(
            self.fixtures.pocket,
            components=(
                Component(
                    id="pocket-tts",
                    role="model",
                    exception_text_sha256=digest,
                ),
            ),
        )
        output = render_screen(record, self.fixtures.texts, receipts=self.store)
        self.assertIn(b"=== component:pocket-tts ===\n", output)
        self.assertIn(b"Tokenizer component exception fixture.\n", output)

    def test_screen_includes_statement_bytes(self) -> None:
        output = render_screen(
            self.fixtures.kristin, self.fixtures.texts, receipts=self.store
        )
        self.assertIn(b"=== statement:trainer-statement ===\n", output)
        self.assertIn(self.fixtures.kristin_text, output)

    def test_paraphrase_with_surrounding_whitespace_is_refused(self) -> None:
        with self.assertRaises(ParaphraseRefused):
            self.fixtures.texts.put(
                POCKET_TERMS_SUMMARY_BYTES + b"\r\n", label="crlf"
            )
        with self.assertRaises(ParaphraseRefused):
            self.fixtures.texts.put(
                b"  " + POCKET_TERMS_SUMMARY_BYTES + b"\n", label="padded"
            )
