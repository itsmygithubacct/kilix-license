from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from kilix_license.agreement import capture_agreement, typed_agreement_line
from kilix_license.coverage import covers
from kilix_license.errors import (
    AgreementRequired,
    AtomicWriteCrashed,
    CoverageRefused,
    ParaphraseRefused,
)
from kilix_license.paraphrase import POCKET_TERMS_SUMMARY, POCKET_TERMS_SUMMARY_BYTES
from kilix_license.receipts import receipt_from_agreement
from kilix_license.records import BindingCondition, LicenseRecord
from kilix_license.screen import render_screen
from kilix_license.texts import TextStore

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
        output = render_screen(self.fixtures.pocket, self.fixtures.texts)
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
        self.assertTrue(covers(self.fixtures.kristin, receipt))

    def test_kristin_rejects_typed_agreement(self) -> None:
        with self.assertRaises(AgreementRequired):
            capture_agreement(self.fixtures.kristin, "accept")

    def test_pocket_requires_typed_agreement_naming_binding_texts(self) -> None:
        with self.assertRaises(AgreementRequired):
            capture_agreement(self.fixtures.pocket)
        with self.assertRaises(AgreementRequired):
            capture_agreement(self.fixtures.pocket, "accept")
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
        self.assertEqual(
            set(payload["context"]),
            {"advisory_digests", "release_digest", "catalogue_digest"},
        )
        self.assertEqual(payload["decision"], "accept")
        self.assertEqual(payload["licensor"], "Kyutai")
        self.assertIn("pocket-prohibited-use", payload["binding_condition_text_digests"])

    def test_advisory_change_does_not_void_coverage(self) -> None:
        receipt = self._pocket_receipt()
        self.assertTrue(covers(self.fixtures.pocket, receipt))
        other = replace(
            receipt,
            advisory_digests={
                "research-use": "0" * 63 + "1",
            },
        )
        self.assertTrue(covers(self.fixtures.pocket, other))
        released = replace(receipt, release_digest="1" * 64)
        self.assertTrue(covers(self.fixtures.pocket, released))
        catalogued = replace(receipt, catalogue_digest="2" * 64)
        self.assertTrue(covers(self.fixtures.pocket, catalogued))

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
            covers(changed, receipt)
        self.assertEqual(
            refused.exception.field,
            "binding_condition_text_digests:pocket-prohibited-use",
        )
        screen = render_screen(changed, self.fixtures.texts)
        self.assertIn(b"=== binding:pocket-prohibited-use ===\n" + new_text, screen)

    def test_crash_mid_write_leaves_no_covering_receipt(self) -> None:
        receipt = self._pocket_receipt()
        with self.assertRaises(AtomicWriteCrashed):
            self.store.write(receipt, crash_before_replace=True)
        self.assertIsNone(
            self.store.lookup(receipt.record_digest, receipt.manifest_digest)
        )
        leftovers = list(self.store.root.glob("*.json"))
        self.assertEqual([], leftovers)
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
