import json
import shutil
import tempfile
import unittest
from pathlib import Path

from kilix_license.agreement import capture_agreement, typed_agreement_line
from kilix_license.catalog import load_determined_records, load_determined_texts, record_path
from kilix_license.errors import AgreementRequired
from kilix_license.generate import DATA_DIR
from kilix_license.lfm2 import generate_lfm2_records
from kilix_license.records import LicenseRecord
from kilix_license.screen import render_screen
from kilix_license.standard_policy import standard_policy_eligible
from fake_store import FakeStore


class LFM2Tests(unittest.TestCase):
    def test_full_terms_commercial_condition_and_notices_are_shown_as_a_notice(self):
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
            # Owner determination 2026-11-07 (Debian style): the commercial-use
            # limitation is shown and shipped as a notice, and no typed
            # agreement is taken or recorded. The terms are not waived.
            condition, = record.binding_conditions
            self.assertEqual(condition.id, 'commercial-use-limitation')
            self.assertFalse(condition.agreement_required)
            self.assertEqual(record.expected_decision, 'record')
            self.assertFalse(standard_policy_eligible(record))
            for answer in ('yes', 'y', typed_agreement_line(record)):
                with self.subTest(answer=answer), self.assertRaises(AgreementRequired):
                    capture_agreement(record, answer)
            notice = capture_agreement(record)
            self.assertEqual((notice.decision, notice.typed_text), ('record', None))

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
