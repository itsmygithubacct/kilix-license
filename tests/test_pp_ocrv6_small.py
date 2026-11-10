import json
import shutil
import tempfile
import unittest
from pathlib import Path

from kilix_license.catalog import load_determined_records, load_determined_texts, record_path
from kilix_license.generate import DATA_DIR
from kilix_license.pp_ocrv6_small import (
    LICENCE_SHA256, MODEL_IDS, STATEMENTS, generate_pp_ocrv6_small_records,
)
from kilix_license.records import LicenseRecord
from kilix_license.screen import render_screen
from kilix_license.standard_policy import standard_policy_eligible
from fake_store import FakeStore


class PpOcrv6SmallTerms(unittest.TestCase):
    def test_apache_terms_and_the_card_only_grant_are_displayed(self):
        generated = {r.id: r for r in generate_pp_ocrv6_small_records(DATA_DIR)}
        self.assertEqual(tuple(generated), MODEL_IDS)
        for model_id in MODEL_IDS:
            with self.subTest(model=model_id):
                record = load_determined_records().by_id(model_id)
                self.assertEqual(record.digest, generated[model_id].digest)
                path = record_path(model_id)
                self.assertEqual(path.parent.name, 'pp-ocrv6-small-records')
                self.assertEqual(record.digest, LicenseRecord.from_bytes(path.read_bytes()).digest)
                self.assertEqual(record.licence_ids, ('Apache-2.0',))
                self.assertEqual(record.licensor, 'PaddlePaddle')
                self.assertEqual(record.decision_class, 'affirmative')
                self.assertEqual(record.expected_decision, 'accept')
                self.assertEqual(record.text_sha256, LICENCE_SHA256)
                self.assertEqual(tuple((s.id, s.text_sha256) for s in record.statements), STATEMENTS)
                self.assertFalse(record.binding_conditions)
                self.assertTrue(standard_policy_eligible(record))
                with tempfile.TemporaryDirectory() as tmp:
                    texts = load_determined_texts(Path(tmp) / 'texts')
                    screen = render_screen(record, texts, receipts=FakeStore(Path(tmp) / 'receipts'))
                    self.assertIn(b'Apache License', screen)
                    self.assertIn(b'Neither repository contains a LICENSE or NOTICE file', screen)

    def test_the_determination_records_the_missing_licence_file(self):
        data = json.loads((DATA_DIR / 'determinations-pp-ocrv6-small.json').read_text(encoding='utf-8'))
        authority = data['authority']
        self.assertIsNone(authority['repository_licence_file'])
        self.assertIn('go with Apache-2.0, note the reality', authority['determined_by'])
        self.assertEqual([m['card_licence_line'] for m in authority['models']],
                         ['license: apache-2.0'] * 2)

    def test_changed_determination_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / 'data'
            shutil.copytree(DATA_DIR, data)
            file = data / 'determinations-pp-ocrv6-small.json'
            file.write_bytes(file.read_bytes() + b' ')
            with self.assertRaisesRegex(ValueError, 'pin mismatch'):
                generate_pp_ocrv6_small_records(data)

    def test_a_licence_file_claim_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / 'data'
            shutil.copytree(DATA_DIR, data)
            file = data / 'determinations-pp-ocrv6-small.json'
            parsed = json.loads(file.read_text(encoding='utf-8'))
            parsed['authority']['repository_licence_file'] = 'LICENSE'
            raw = (json.dumps(parsed, indent=2) + '\n').encode()
            file.write_bytes(raw)
            import hashlib
            (data / 'determinations-pp-ocrv6-small.sha256').write_text(hashlib.sha256(raw).hexdigest() + '\n')
            with self.assertRaisesRegex(ValueError, 'neither repository has a LICENSE file'):
                generate_pp_ocrv6_small_records(data)
