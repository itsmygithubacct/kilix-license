import json
import shutil
import tempfile
import unittest
from pathlib import Path

from kilix_license.agreement import capture_agreement
from kilix_license.catalog import load_determined_records, load_determined_texts, record_path
from kilix_license.errors import AgreementRequired
from kilix_license.generate import DATA_DIR
from kilix_license.lfm2 import generate_lfm2_records
from kilix_license.records import LicenseRecord
from kilix_license.screen import render_screen
from fake_store import FakeStore


class LFM2Tests(unittest.TestCase):
    def test_full_terms_commercial_condition_and_notices_precede_agreement(self):
        record = load_determined_records().by_id('lfm2-kilix-commands')
        self.assertEqual(record.digest, generate_lfm2_records(DATA_DIR)[0].digest)
        self.assertEqual(record.digest, LicenseRecord.from_bytes(record_path(record.id).read_bytes()).digest)
        with tempfile.TemporaryDirectory() as tmp:
            texts = load_determined_texts(Path(tmp) / 'texts')
            screen = render_screen(record, texts, receipts=FakeStore(Path(tmp) / 'receipts'))
            for digest in [record.text_sha256] + [x.text_sha256 for x in record.binding_conditions + record.statements] + [x.exception_text_sha256 for x in record.components]:
                self.assertIn(texts.get(digest), screen)
            self.assertIn(b'LFM Open License v1.0', screen)
            self.assertIn(b'Commercial Use Limitation', screen)
            self.assertIn(b'modified LiquidAI/LFM2-1.2B-Tool', screen)
            for answer in (None, 'no'):
                with self.subTest(answer=answer), self.assertRaises(AgreementRequired):
                    capture_agreement(record, answer)
            self.assertEqual(capture_agreement(record, 'yes').decision, 'accept')

    def test_tampered_determination_or_missing_text_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / 'data'
            shutil.copytree(DATA_DIR, data)
            file = data / 'determinations-lfm2.json'
            original = file.read_bytes()
            file.write_bytes(original + b' ')
            with self.assertRaisesRegex(ValueError, 'pin mismatch'):
                generate_lfm2_records(data)
            file.write_bytes(original)
            digest = json.loads(original)['authority']['licence_sha256']
            (data / 'texts' / digest).unlink()
            with self.assertRaises(Exception):
                generate_lfm2_records(data)
