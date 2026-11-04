"""Unchanged upstream model terms, notices and existing record preservation."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import kilix_license as lic
from kilix_license.basic_pitch import generate_basic_pitch_records,MODEL_ID,LICENSE_SHA256,NOTICE_SHA256
from kilix_license.generate import DATA_DIR
from kilix_license.agreement import STANDARD_POLICY

class BasicPitchTerms(unittest.TestCase):
    def test_exact_generated_record_notice_and_standard_policy(self):
        record=lic.load_determined_records().by_id(MODEL_ID)
        self.assertEqual(record.digest,generate_basic_pitch_records(DATA_DIR)[0].digest)
        self.assertEqual(record.licence_ids,('Apache-2.0',))
        self.assertEqual(record.text_sha256,LICENSE_SHA256)
        self.assertEqual([(s.id,s.text_sha256) for s in record.statements],[('upstream-notice',NOTICE_SHA256)])
        self.assertTrue(lic.standard_policy_eligible(record))
        agreement=lic.capture_standard_policy(record)
        self.assertIsNone(agreement.typed_text)
        self.assertEqual(agreement.authorization_policy,STANDARD_POLICY)
        receipt=lic.receipt_from_agreement(record,agreement,manifest_digest='1'*64,catalogue_digest='2'*64,release_digest='3'*64)
        self.assertTrue(lic.covers(record,receipt,manifest_digest='1'*64))
        self.assertIn('upstream-notice',receipt.statement_digests)
        with self.assertRaises(lic.CoverageRefused):lic.covers(record,receipt,manifest_digest='4'*64)

    def test_changed_authority_and_missing_notice_refuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp)/'data';shutil.copytree(DATA_DIR,data)
            f=data/'determinations-basic-pitch.json';original=f.read_bytes();f.write_bytes(original+b' ')
            with self.assertRaisesRegex(ValueError,'pin mismatch'):generate_basic_pitch_records(data)
            f.write_bytes(original);(data/'texts'/NOTICE_SHA256).unlink()
            with self.assertRaises((ValueError,FileNotFoundError)):generate_basic_pitch_records(data)

    def test_unrelated_preexisting_records_and_licence_texts_are_unchanged(self):
        root=Path(__file__).resolve().parents[1]
        entries=subprocess.check_output(['git','ls-tree','-r','--name-only','4b29f156eb3edc793318fc1728c259298599d34e','src/kilix_license/data'],cwd=root,text=True).splitlines()
        # LFM2 has a separately versioned modification notice. Its determination
        # and generated record advance with that delivery; original licence
        # texts, Basic Pitch authority and every other record remain preserved.
        lfm2_revision = {
            'src/kilix_license/data/determinations-lfm2.json',
            'src/kilix_license/data/determinations-lfm2.sha256',
            'src/kilix_license/data/lfm2-records/lfm2-kilix-commands.json',
        }
        for name in entries:
            if name in lfm2_revision:
                continue
            original=subprocess.check_output(['git','show','4b29f156eb3edc793318fc1728c259298599d34e:'+name],cwd=root)
            self.assertEqual((root/name).read_bytes(),original,name)
