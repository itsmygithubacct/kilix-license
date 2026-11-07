"""Whisper medium.en terms: its own record, small.en's terms, no digest moved."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import kilix_license as lic
from kilix_license.catalog import record_path
from kilix_license.digest import sha256_hex
from kilix_license.generate import DATA_DIR
from kilix_license.whisper_medium import (
    ADVISORIES, LICENCE_SHA256, MODEL_ID, REVISION, generate_whisper_medium_records,
)

# kilix-license before this family existed.
BASE = '0984dd222bcb7f97859222b0dc2303b9225191fe'


def _repin(data: Path, mutate) -> None:
    path = data / 'determinations-whisper-medium.json'
    value = json.loads(path.read_bytes())
    mutate(value)
    raw = (json.dumps(value, indent=2) + '\n').encode()
    path.write_bytes(raw)
    (data / 'determinations-whisper-medium.sha256').write_text(sha256_hex(raw) + '\n')


class WhisperMediumTerms(unittest.TestCase):
    def test_exact_generated_record_with_small_en_terms(self):
        index = lic.load_determined_records()
        medium = index.by_id(MODEL_ID)
        small = index.by_id('faster-whisper-small-en')
        self.assertEqual(medium.digest, generate_whisper_medium_records(DATA_DIR)[0].digest)
        self.assertNotEqual(medium.digest, small.digest)
        for field in ('licensor', 'licence_ids', 'licence_text_id', 'text_sha256',
                      'decision_class', 'binding_conditions', 'components'):
            self.assertEqual(getattr(medium, field), getattr(small, field), field)
        self.assertEqual([(s.id, s.text_sha256) for s in medium.statements],
                         [(s.id, s.text_sha256) for s in small.statements])
        self.assertEqual([(a.id, a.text_sha256) for a in medium.advisories],
                         [(a.id, a.text_sha256) for a in small.advisories])
        self.assertEqual(lic.standard_policy_eligible(medium), lic.standard_policy_eligible(small))
        self.assertEqual(record_path(MODEL_ID).parent.name, 'whisper-medium-records')

    def test_the_record_covers_only_its_own_artifact(self):
        index = lic.load_determined_records()
        medium = index.by_id(MODEL_ID)
        small = index.by_id('faster-whisper-small-en')
        agreement = lic.capture_agreement(medium, 'yes')
        receipt = lic.receipt_from_agreement(medium, agreement, manifest_digest='1' * 64,
                                             catalogue_digest='2' * 64, release_digest='3' * 64)
        self.assertTrue(lic.covers(medium, receipt, manifest_digest='1' * 64))
        with self.assertRaises(lic.CoverageRefused):
            lic.covers(small, receipt, manifest_digest='1' * 64)

    def test_changed_authority_or_missing_texts_refuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / 'data'
            shutil.copytree(DATA_DIR, data)
            path = data / 'determinations-whisper-medium.json'
            original = path.read_bytes()
            path.write_bytes(original + b' ')
            with self.assertRaisesRegex(ValueError, 'pin mismatch'):
                generate_whisper_medium_records(data)
            path.write_bytes(original)
            pin = (data / 'determinations-whisper-medium.sha256').read_bytes()
            _repin(data, lambda v: v['authority'].update(revision='0' * 40))
            with self.assertRaisesRegex(ValueError, 'upstream binding'):
                generate_whisper_medium_records(data)
            _repin(data, lambda v: v['authority'].update(revision=REVISION) or
                   v['authority']['files'][1].update(sha256='0' * 64))
            with self.assertRaisesRegex(ValueError, 'upstream binding'):
                generate_whisper_medium_records(data)
            _repin(data, lambda v: v['authority']['files'][1].update(
                sha256='11b220779aea4c6f3ce9d2549c8a95ea869ed84066864b999531ef53e594fe5b')
                or v['records'][0].update(advisories=[]))
            with self.assertRaisesRegex(ValueError, 'card caution'):
                generate_whisper_medium_records(data)
            _repin(data, lambda v: v['records'][0].update(
                advisories=[{'id': i, 'text_sha256': d} for i, d in ADVISORIES], licensor='OpenAI'))
            with self.assertRaisesRegex(ValueError, 'classification'):
                generate_whisper_medium_records(data)
            path.write_bytes(original)
            (data / 'determinations-whisper-medium.sha256').write_bytes(pin)
            self.assertEqual(generate_whisper_medium_records(data)[0].id, MODEL_ID)
            (data / 'texts' / LICENCE_SHA256).unlink()
            with self.assertRaises((ValueError, FileNotFoundError)):
                generate_whisper_medium_records(data)

    def test_no_preexisting_record_or_text_moves(self):
        root = Path(__file__).resolve().parents[1]
        entries = subprocess.check_output(
            ['git', 'ls-tree', '-r', '--name-only', BASE, 'src/kilix_license/data'],
            cwd=root, text=True).splitlines()
        # LFM2's modification notice advances with its own delivery.
        lfm2_revision = {
            'src/kilix_license/data/determinations-lfm2.json',
            'src/kilix_license/data/determinations-lfm2.sha256',
            'src/kilix_license/data/lfm2-records/lfm2-kilix-commands.json',
        }
        for name in entries:
            if name in lfm2_revision:
                continue
            original = subprocess.check_output(['git', 'show', f'{BASE}:{name}'], cwd=root)
            self.assertEqual((root / name).read_bytes(), original, name)


if __name__ == '__main__':
    unittest.main()
