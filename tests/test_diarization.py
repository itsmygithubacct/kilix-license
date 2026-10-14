import tempfile
import unittest
from pathlib import Path
from kilix_license.catalog import load_determined_records,load_determined_texts
from kilix_license.generate import DATA_DIR
from kilix_license.diarization import generate_diarization_records
from kilix_license.agreement import capture_agreement
from kilix_license.errors import AgreementRequired
from kilix_license.screen import render_screen
from fake_store import FakeStore

class DiarizationTests(unittest.TestCase):
    def test_exact_grant_component_notices_and_modification_are_shown_before_agreement(self):
        record=load_determined_records().by_id('kilix-diarization-cpu')
        self.assertEqual(record.digest,generate_diarization_records(DATA_DIR)[0].digest)
        with tempfile.TemporaryDirectory() as root:
            texts=load_determined_texts(Path(root)/'texts')
            screen=render_screen(record,texts,receipts=FakeStore(Path(root)/'receipts'))
            for digest in [record.text_sha256]+[x.exception_text_sha256 for x in record.components if x.exception_text_sha256]+[x.text_sha256 for x in record.statements]:
                self.assertIn(texts.get(digest),screen)
            self.assertIn(b'5b1a88b6f8d85826',screen)
            self.assertIn(b'converted locally to ONNX',screen)
            for answer in (None,'no'):
                with self.subTest(answer=answer),self.assertRaises(AgreementRequired):capture_agreement(record,answer)
            self.assertEqual(capture_agreement(record,'yes').decision,'accept')
