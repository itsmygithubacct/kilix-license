"""Receipts written by fbdfb546 still read and cover; LIC4 context is additive.

tests/data/receipts-fbdfb546/ holds five receipts written by the kilix-license
code at fbdfb546 (a git archive of that commit) for packaged records, with
manifest sha256("lic4-compat-manifest:<record id>"), release
sha256("lic4-compat-release") and catalogue sha256("lic4-compat-catalogue").
tests/data/record-digests-fbdfb546.txt lists the record digests that code
computed. OD-AQ / C2E-VERIFY F6: statement (NOTICE) digests shown on the screen
are recorded in the receipt context, not bound.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
import tempfile
import unittest

from kilix_license.agreement import capture_agreement, typed_agreement_line
from kilix_license.catalog import load_determined_records
from kilix_license.coverage import AssetRef, covers, require
from kilix_license.errors import ReceiptShapeError
from kilix_license.receipts import (
    CONTEXT_FIELDS,
    OPTIONAL_CONTEXT_FIELDS,
    parse_receipt,
    parse_receipt_bytes,
    receipt_from_agreement,
)
from kilix_license.records import Statement

from fake_store import FakeStore
from fixtures import FIXTURE_CATALOGUE, FIXTURE_MANIFEST, FIXTURE_RELEASE

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT / "tests" / "data" / "receipts-fbdfb546"
LIC4 = ROOT / "tests" / "data" / "receipts-967a2455"


def _lic4_receipt(record):
    typed = typed_agreement_line(record) if record.expected_decision == "accept" else None
    return receipt_from_agreement(
        record,
        capture_agreement(record, typed),
        manifest_digest=FIXTURE_MANIFEST,
        release_digest=FIXTURE_RELEASE,
        catalogue_digest=FIXTURE_CATALOGUE,
    )


class Fbdfb546ReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = load_determined_records()
        cls.files = sorted(LEGACY.glob("*.json"))

    def test_fixture_set_is_the_five_written_receipts(self) -> None:
        ids = sorted(parse_receipt_bytes(p.read_bytes()).licence_id for p in self.files)
        self.assertEqual(
            ids,
            [
                "bitnet-b1.58-2b4t",
                "bonsai-image-4b:ternary-gemlite",
                "piper-en-us-kristin-medium",
                "pocket-tts-english-q8_0",
                "small-en-us",
            ],
        )

    def test_old_receipts_read_round_trip_and_cover(self) -> None:
        for path in self.files:
            with self.subTest(receipt=path.name):
                data = path.read_bytes()
                receipt = parse_receipt_bytes(data)
                self.assertEqual(parse_receipt(receipt.to_jsonable()), receipt)
                self.assertEqual(receipt.to_bytes(), data)
                for field in OPTIONAL_CONTEXT_FIELDS:
                    self.assertIsNone(getattr(receipt, field))
                record = self.index.by_digest(receipt.record_digest)
                self.assertTrue(covers(record, receipt, manifest_digest=receipt.manifest_digest))

    def test_old_receipts_satisfy_require_from_a_store(self) -> None:
        store = FakeStore(Path(tempfile.mkdtemp(prefix="kilix-license-compat-")) / "receipts")
        for path in self.files:
            shutil.copy2(path, store.root / path.name)
        for path in self.files:
            receipt = parse_receipt_bytes(path.read_bytes())
            with self.subTest(licence_id=receipt.licence_id):
                found = require(
                    AssetRef(receipt.licence_id, receipt.record_digest, receipt.manifest_digest),
                    records=self.index,
                    store=store,
                )
                self.assertEqual(found, receipt)


class Lic4ReceiptContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = load_determined_records()

    def test_lic4_receipt_records_what_the_screen_showed(self) -> None:
        for record in self.index:
            with self.subTest(record=record.id):
                receipt = _lic4_receipt(record)
                context = receipt.to_jsonable()["context"]
                self.assertEqual(set(context), set(CONTEXT_FIELDS) | set(OPTIONAL_CONTEXT_FIELDS))
                self.assertEqual(context["statement_digests"], record.statement_digests())
                self.assertEqual(
                    context["component_exception_digests"], record.component_exception_digests()
                )
                self.assertEqual(context["binding_text_ids"], record.binding_text_ids())
                self.assertEqual(context["licence_text_id"], record.licence_text_id)
                self.assertEqual(parse_receipt_bytes(receipt.to_bytes()), receipt)
                self.assertTrue(covers(record, receipt, manifest_digest=FIXTURE_MANIFEST))
        ternary = _lic4_receipt(self.index.by_id("bonsai-image-4b:ternary-gemlite"))
        self.assertEqual(ternary.binding_text_ids, {"bfl-usage-policy": "bfl.ai/legal/usage-policy"})
        self.assertEqual(list(ternary.statement_digests), ["bonsai-image-notice-ternary-gemlite"])
        bitnet = _lic4_receipt(self.index.by_id("bitnet-b1.58-2b4t"))
        self.assertEqual(list(bitnet.component_exception_digests), ["tokenizer-derived-from-llama-3"])

    def test_a_changed_notice_keeps_coverage_and_the_receipt_shows_which_was_seen(self) -> None:
        record = self.index.by_id("bonsai-image-4b:ternary-gemlite")
        old = _lic4_receipt(record)
        statement = record.statements[0]
        swapped = replace(record, statements=(Statement(statement.id, "ab" * 32),))
        self.assertEqual(swapped.digest, record.digest)
        self.assertTrue(covers(swapped, old, manifest_digest=FIXTURE_MANIFEST))
        new = _lic4_receipt(swapped)
        self.assertEqual(old.statement_digests, {statement.id: statement.text_sha256})
        self.assertEqual(new.statement_digests, {statement.id: "ab" * 32})

    def test_lic4_context_is_never_compared_by_covers(self) -> None:
        record = self.index.by_id("bonsai-image-4b:ternary-gemlite")
        receipt = _lic4_receipt(record)
        for field, value in (
            ("binding_text_ids", {"bfl-usage-policy": "example.org/other"}),
            ("statement_digests", {"planted": "cd" * 32}),
            ("component_exception_digests", {"planted": "ef" * 32}),
            ("licence_text_id", "example.org/other-licence"),
        ):
            with self.subTest(field=field):
                self.assertTrue(
                    covers(record, replace(receipt, **{field: value}), manifest_digest=FIXTURE_MANIFEST)
                )

    def test_malformed_lic4_context_is_refused_by_the_parser(self) -> None:
        raw = _lic4_receipt(self.index.by_id("bonsai-image-4b:ternary-gemlite")).to_jsonable()

        def with_context(**fields):
            planted = dict(raw)
            planted["context"] = dict(raw["context"], **fields)
            return planted

        with self.assertRaises(ReceiptShapeError) as refused:
            parse_receipt(with_context(binding_text_ids={"not-bound": "example.org/policy"}))
        self.assertEqual(refused.exception.field, "binding_text_ids")
        with self.assertRaises(ValueError):
            parse_receipt(with_context(binding_text_ids={"bfl-usage-policy": "has space"}))
        with self.assertRaises(ValueError):
            parse_receipt(with_context(statement_digests={"x": "not-a-digest"}))
        with self.assertRaises(ReceiptShapeError) as refused:
            parse_receipt(with_context(shown_at="2026-09-19"))
        self.assertEqual(refused.exception.field, "shown_at")
        for bad in ("has space", "", 7, {"x": "y"}):
            with self.subTest(licence_text_id=bad):
                with self.assertRaises(ValueError):
                    parse_receipt(with_context(licence_text_id=bad))


class Lic4ReceiptTests(unittest.TestCase):
    """tests/data/receipts-967a2455/ holds five receipts written by the LIC4 code
    (a git archive of 967a2455): LIC4 context keys, no licence_text_id. Manifest
    sha256("lic4fix-compat-manifest:<record id>"), release
    sha256("lic4fix-compat-release"), catalogue sha256("lic4fix-compat-catalogue")."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.index = load_determined_records()
        cls.files = sorted(LIC4.glob("*.json"))

    def test_fixture_set_is_the_five_written_receipts(self) -> None:
        ids = sorted(parse_receipt_bytes(p.read_bytes()).licence_id for p in self.files)
        self.assertEqual(
            ids,
            [
                "bitnet-b1.58-2b4t",
                "bonsai-image-4b:ternary-gemlite",
                "encodec-24khz-stateful",
                "piper-en-us-kristin-medium",
                "small-en-us",
            ],
        )

    def test_lic4_receipts_read_round_trip_and_cover(self) -> None:
        store = FakeStore(Path(tempfile.mkdtemp(prefix="kilix-license-compat-lic4-")) / "receipts")
        for path in self.files:
            shutil.copy2(path, store.root / path.name)
        for path in self.files:
            with self.subTest(receipt=path.name):
                data = path.read_bytes()
                receipt = parse_receipt_bytes(data)
                self.assertEqual(receipt.to_bytes(), data)
                self.assertIsNone(receipt.licence_text_id)
                self.assertIsNotNone(receipt.binding_text_ids)
                self.assertIsNotNone(receipt.statement_digests)
                record = self.index.by_digest(receipt.record_digest)
                self.assertTrue(covers(record, receipt, manifest_digest=receipt.manifest_digest))
                found = require(
                    AssetRef(receipt.licence_id, receipt.record_digest, receipt.manifest_digest),
                    records=self.index,
                    store=store,
                )
                self.assertEqual(found, receipt)


if __name__ == "__main__":
    unittest.main()
