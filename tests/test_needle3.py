import json
import shutil
import tempfile
import unittest
from pathlib import Path

from kilix_license.catalog import load_determined_records, load_determined_texts, record_path
from kilix_license.generate import DATA_DIR
from kilix_license.needle3 import generate_needle3_records
from kilix_license.records import LicenseRecord
from kilix_license.screen import render_screen
from fake_store import FakeStore


class Needle3Terms(unittest.TestCase):
    def test_original_licences_and_modification_notices_are_displayed(self):
        record = load_determined_records().by_id('needle3-kilix-commands')
        self.assertEqual(record.digest, generate_needle3_records(DATA_DIR)[0].digest)
        self.assertEqual(record.digest, LicenseRecord.from_bytes(record_path(record.id).read_bytes()).digest)
        self.assertEqual(record.licence_ids, ('Apache-2.0', 'MIT'))
        with tempfile.TemporaryDirectory() as tmp:
            texts = load_determined_texts(Path(tmp) / 'texts')
            screen = render_screen(record, texts, receipts=FakeStore(Path(tmp) / 'receipts'))
            for digest in [record.text_sha256] + [x.text_sha256 for x in record.statements] + [x.exception_text_sha256 for x in record.components]:
                self.assertIn(texts.get(digest), screen)
            self.assertIn(b'Apache License', screen)
            self.assertIn(b'MIT License', screen)
            self.assertIn(b'Needle 3 command fine-tune', screen)

    def test_changed_determination_or_missing_runtime_notice_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / 'data'
            shutil.copytree(DATA_DIR, data)
            file = data / 'determinations-needle3.json'
            original = file.read_bytes()
            file.write_bytes(original + b' ')
            with self.assertRaisesRegex(ValueError, 'pin mismatch'):
                generate_needle3_records(data)
            file.write_bytes(original)
            digest = json.loads(original)['authority']['runtime_notice_sha256']
            (data / 'texts' / digest).unlink()
            with self.assertRaises(Exception):
                generate_needle3_records(data)
