import shutil
import tempfile
import unittest
from pathlib import Path

from kilix_license.catalog import load_determined_records, load_determined_texts, record_path
from kilix_license.en_core_web_sm import (
    LICENSE_SHA256, MODEL_ID, SOURCE, SOURCES_SHA256, generate_en_core_web_sm_records,
)
from kilix_license.generate import DATA_DIR
from kilix_license.records import LicenseRecord
from kilix_license.screen import render_screen
from kilix_license.standard_policy import standard_policy_eligible
from fake_store import FakeStore


class EnCoreWebSmTerms(unittest.TestCase):
    def test_mit_terms_and_training_sources_are_displayed(self):
        record = load_determined_records().by_id(MODEL_ID)
        generated = generate_en_core_web_sm_records(DATA_DIR)[0]
        self.assertEqual(record.digest, generated.digest)
        self.assertEqual(record.digest, LicenseRecord.from_bytes(record_path(record.id).read_bytes()).digest)
        self.assertEqual(record_path(record.id).parent.name, 'en-core-web-sm-records')
        self.assertEqual(record.licence_ids, ('MIT',))
        self.assertEqual(record.decision_class, 'affirmative')
        self.assertEqual(record.expected_decision, 'accept')
        self.assertEqual(record.licensor, 'ExplosionAI GmbH')
        self.assertEqual(record.text_sha256, LICENSE_SHA256)
        self.assertEqual([(item.id, item.text_sha256) for item in record.statements],
                         [('training-sources', SOURCES_SHA256)])
        self.assertFalse(record.binding_conditions)
        self.assertTrue(standard_policy_eligible(record))
        determination = (DATA_DIR / 'determinations-en-core-web-sm.json').read_text(encoding='utf-8')
        self.assertIn(SOURCE, determination)
        with tempfile.TemporaryDirectory() as tmp:
            texts = load_determined_texts(Path(tmp) / 'texts')
            screen = render_screen(record, texts, receipts=FakeStore(Path(tmp) / 'receipts'))
            self.assertIn(texts.get(record.text_sha256), screen)
            self.assertIn(b'Permission is hereby granted', screen)
            self.assertIn(texts.get(SOURCES_SHA256), screen)

    def test_changed_determination_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / 'data'
            shutil.copytree(DATA_DIR, data)
            file = data / 'determinations-en-core-web-sm.json'
            file.write_bytes(file.read_bytes() + b' ')
            with self.assertRaisesRegex(ValueError, 'pin mismatch'):
                generate_en_core_web_sm_records(data)
