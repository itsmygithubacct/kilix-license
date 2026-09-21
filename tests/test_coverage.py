from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from kilix_license.agreement import capture_agreement, typed_agreement_line
from kilix_license.coverage import AssetRef, covers, require
from kilix_license.errors import CoverageRefused, ReceiptShapeError
from kilix_license.receipts import parse_receipt, receipt_from_agreement

from fake_store import FakeStore
from fixtures import (
    FIXTURE_CATALOGUE,
    FIXTURE_MANIFEST,
    FIXTURE_RELEASE,
    build_fixtures,
)


def _flip(digest: str) -> str:
    return digest[:-1] + ("0" if digest[-1] != "0" else "1")


class CoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="kilix-license-coverage-"))
        self.fixtures = build_fixtures(self.root)
        self.store = FakeStore(self.root / "receipts")
        agreement = capture_agreement(
            self.fixtures.pocket, typed_agreement_line(self.fixtures.pocket)
        )
        self.receipt = receipt_from_agreement(
            self.fixtures.pocket,
            agreement,
            manifest_digest=FIXTURE_MANIFEST,
            release_digest=FIXTURE_RELEASE,
            catalogue_digest=FIXTURE_CATALOGUE,
        )
        self.store.write(self.receipt)
        self.asset = AssetRef(
            id="pocket-tts",
            record_digest=self.receipt.record_digest,
            manifest_digest=self.receipt.manifest_digest,
        )

    def test_unchanged_binding_covers(self) -> None:
        self.assertTrue(
            covers(
                self.fixtures.pocket,
                self.receipt,
                manifest_digest=FIXTURE_MANIFEST,
            )
        )
        found = require(
            self.asset, records=self.fixtures.index, store=self.store
        )
        self.assertEqual(found.record_digest, self.receipt.record_digest)

    def test_each_bound_field_one_byte_change_names_the_field(self) -> None:
        cases = [
            ("record_digest", replace(self.receipt, record_digest=_flip(self.receipt.record_digest))),
            ("licence_id", replace(self.receipt, licence_id=self.receipt.licence_id + "x")),
            (
                "licence_text_digest",
                replace(
                    self.receipt,
                    licence_text_digest=_flip(self.receipt.licence_text_digest),
                ),
            ),
            ("decision", replace(self.receipt, decision="record")),
            ("licensor", replace(self.receipt, licensor="KyutaJ")),
            (
                "binding_condition_text_digests:pocket-prohibited-use",
                replace(
                    self.receipt,
                    binding_condition_text_digests={
                        "pocket-prohibited-use": _flip(
                            self.receipt.binding_condition_text_digests[
                                "pocket-prohibited-use"
                            ]
                        )
                    },
                ),
            ),
        ]
        for field, mutated in cases:
            with self.subTest(field=field):
                with self.assertRaises(CoverageRefused) as refused:
                    covers(
                        self.fixtures.pocket,
                        mutated,
                        manifest_digest=FIXTURE_MANIFEST,
                    )
                self.assertEqual(refused.exception.field, field)

        flipped_receipt = replace(
            self.receipt, manifest_digest=_flip(self.receipt.manifest_digest)
        )
        with self.assertRaises(CoverageRefused) as refused:
            covers(
                self.fixtures.pocket,
                flipped_receipt,
                manifest_digest=FIXTURE_MANIFEST,
            )
        self.assertEqual(refused.exception.field, "manifest_digest")

        flipped_manifest = replace(
            self.asset, manifest_digest=_flip(self.asset.manifest_digest)
        )
        with self.assertRaises(CoverageRefused) as refused:
            require(flipped_manifest, records=self.fixtures.index, store=self.store)
        self.assertEqual(refused.exception.field, "manifest_digest")

    def test_release_and_advisory_digest_changes_keep_coverage(self) -> None:
        advisory = replace(
            self.receipt, advisory_digests={"research-use": "ab" * 32}
        )
        release = replace(self.receipt, release_digest=_flip(self.receipt.release_digest))
        catalogue = replace(
            self.receipt, catalogue_digest=_flip(self.receipt.catalogue_digest)
        )
        self.assertTrue(
            covers(self.fixtures.pocket, advisory, manifest_digest=FIXTURE_MANIFEST)
        )
        self.assertTrue(
            covers(self.fixtures.pocket, release, manifest_digest=FIXTURE_MANIFEST)
        )
        self.assertTrue(
            covers(self.fixtures.pocket, catalogue, manifest_digest=FIXTURE_MANIFEST)
        )

    def test_covers_refuses_binding_key_set_mismatch(self) -> None:
        extra = replace(
            self.receipt,
            binding_condition_text_digests={
                **self.receipt.binding_condition_text_digests,
                "extra-condition": "ab" * 32,
            },
        )
        with self.assertRaises(CoverageRefused) as refused:
            covers(self.fixtures.pocket, extra, manifest_digest=FIXTURE_MANIFEST)
        self.assertEqual(
            refused.exception.field, "binding_condition_text_digests:extra-condition"
        )
        missing = replace(self.receipt, binding_condition_text_digests={})
        with self.assertRaises(CoverageRefused) as refused:
            covers(self.fixtures.pocket, missing, manifest_digest=FIXTURE_MANIFEST)
        self.assertEqual(
            refused.exception.field,
            "binding_condition_text_digests:pocket-prohibited-use",
        )

    def test_a_malformed_file_in_the_store_refuses_rather_than_raising(
        self,
    ) -> None:
        # LIC6-FIX-VERIFY V4. LIC6-VERIFY F7's stated harm was that one
        # malformed file in the store turns kilix-content's first-use flow
        # into a traceback rather than a refusal, because
        # needs_agreement() catches CoverageRefused only. LIC6 typed the
        # failure -- ReceiptShapeError instead of TypeError or ValueError --
        # but ReceiptShapeError is not a CoverageRefused either, so the
        # consumer symptom was unchanged: only the class in the traceback
        # moved. A file this authority cannot read as a receipt covers
        # nothing, so require() now says that.
        #
        # The consumer's own clause is written out literally below, because
        # what has to hold is that THAT clause catches it.
        path = self.store.path_for(
            self.asset.record_digest, self.asset.manifest_digest
        )
        for name, blob in (
            ("not json", b"\x00\x01 not a receipt at all"),
            ("truncated", self.receipt.to_bytes()[: len(self.receipt.to_bytes()) // 2]),
            ("json but not an object", b"[1, 2, 3]\n"),
        ):
            with self.subTest(planted=name):
                path.write_bytes(blob)
                with self.assertRaises(CoverageRefused) as refused:
                    require(
                        self.asset, records=self.fixtures.index, store=self.store
                    )
                self.assertEqual(refused.exception.field, "receipt")
                self.assertIn("not a receipt this authority can read", str(
                    refused.exception
                ))
                # the consumer's clause, verbatim
                caught = False
                try:
                    require(
                        self.asset, records=self.fixtures.index, store=self.store
                    )
                except CoverageRefused:
                    caught = True
                self.assertTrue(
                    caught,
                    "needs_agreement() catches CoverageRefused only; this is "
                    "the clause that has to catch a malformed stored receipt",
                )
                # and the chained cause is still the typed shape failure, so
                # a corrupt store stays diagnosable
                self.assertIsInstance(
                    refused.exception.__cause__, ReceiptShapeError
                )

        # A malformed sibling receipt -- one for the same record under a
        # different manifest, which require() reads only when the exact
        # lookup misses -- refuses the same way instead of raising.
        path.unlink()
        sibling = self.store.path_for(self.asset.record_digest, _flip(FIXTURE_MANIFEST))
        sibling.write_bytes(b"{ this is not json")
        with self.assertRaises(CoverageRefused) as refused:
            require(self.asset, records=self.fixtures.index, store=self.store)
        self.assertEqual(refused.exception.field, "receipt")

        # The typed contract inside the authority is untouched: reading the
        # bytes directly still raises the shape error, naming the field.
        from kilix_license.receipts import parse_receipt_bytes

        with self.assertRaises(ReceiptShapeError) as shape:
            parse_receipt_bytes(b"\x00\x01 not a receipt at all")
        self.assertEqual(shape.exception.field, "receipt")
        # and an intact receipt still covers, so nothing was widened.
        sibling.unlink()
        self.store.write(self.receipt)
        self.assertEqual(
            require(
                self.asset, records=self.fixtures.index, store=self.store
            ).record_digest,
            self.receipt.record_digest,
        )

    def test_planted_r3_catalogue_digest_binding_is_refused(self) -> None:
        raw = self.receipt.to_jsonable()
        planted = dict(raw)
        planted["catalogue_digest"] = raw["context"]["catalogue_digest"]
        with self.assertRaises(ReceiptShapeError) as refused:
            parse_receipt(planted)
        self.assertEqual(refused.exception.field, "catalogue_digest")
        r3 = dict(raw)
        r3["catalog_sha256"] = raw["context"]["catalogue_digest"]
        with self.assertRaises(ReceiptShapeError) as refused:
            parse_receipt(r3)
        self.assertEqual(refused.exception.field, "catalog_sha256")
        planted_sha = dict(raw)
        planted_sha["catalogue_sha256"] = raw["context"]["catalogue_digest"]
        with self.assertRaises(ReceiptShapeError) as refused:
            parse_receipt(planted_sha)
        self.assertEqual(refused.exception.field, "catalogue_sha256")
        self.assertIn("R3 shape", str(refused.exception))
