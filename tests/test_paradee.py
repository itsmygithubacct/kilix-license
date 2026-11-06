import tempfile
import unittest
from pathlib import Path

from kilix_license.catalog import load_determined_records, load_determined_texts, record_path
from kilix_license.paradee import APACHE, SOURCE, generate_paradee_records
from kilix_license.generate import DATA_DIR
from kilix_license.records import LicenseRecord
from kilix_license.screen import render_screen
from fake_store import FakeStore


class ParadeeTerms(unittest.TestCase):
    def test_apache_terms_are_displayed(self):
        record = load_determined_records().by_id("paradee-8m-v1.2")
        self.assertEqual(record.digest, generate_paradee_records(DATA_DIR)[0].digest)
        self.assertEqual(record.digest, LicenseRecord.from_bytes(record_path(record.id).read_bytes()).digest)
        self.assertEqual(record.licence_ids, ("Apache-2.0",))
        self.assertEqual(record.decision_class, "affirmative")
        self.assertEqual(record.expected_decision, "accept")
        self.assertEqual(record.text_sha256, APACHE)
        self.assertEqual(record.licensor, "Sahil Mahendrakar")
        self.assertEqual(record.licence_text_id, "debian/common-licenses/Apache-2.0")
        determination = (DATA_DIR / "determinations-paradee.json").read_text(encoding="utf-8")
        self.assertIn(SOURCE, determination)
        with tempfile.TemporaryDirectory() as tmp:
            texts = load_determined_texts(Path(tmp) / "texts")
            screen = render_screen(record, texts, receipts=FakeStore(Path(tmp) / "receipts"))
            self.assertIn(texts.get(record.text_sha256), screen)
            self.assertIn(b"Apache License", screen)

    def test_changed_determination_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            import shutil
            shutil.copytree(DATA_DIR, data)
            file = data / "determinations-paradee.json"
            file.write_bytes(file.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "pin mismatch"):
                generate_paradee_records(data)
