"""Whisper large-v3 terms: its own record, medium.en's terms, no digest moved."""
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
from kilix_license.whisper_large_v3 import (
    ADVISORIES, FILES, LICENCE_SHA256, MODEL_ID, REVISION, generate_whisper_large_v3_records,
)

# kilix-license before this family existed.
BASE = '80aab439d7243936dc69ddcf6a7e90c0753ea7bb'
NAME = 'determinations-whisper-large-v3'


def _repin(data: Path, mutate) -> None:
    path = data / f'{NAME}.json'
    value = json.loads(path.read_bytes())
    mutate(value)
    raw = (json.dumps(value, indent=2) + '\n').encode()
    path.write_bytes(raw)
    (data / f'{NAME}.sha256').write_text(sha256_hex(raw) + '\n')


class WhisperLargeV3Terms(unittest.TestCase):
    def test_exact_generated_record_with_medium_en_terms(self):
        index = lic.load_determined_records()
        large = index.by_id(MODEL_ID)
        medium = index.by_id('faster-whisper-medium-en')
        self.assertEqual(large.digest, generate_whisper_large_v3_records(DATA_DIR)[0].digest)
        self.assertNotEqual(large.digest, medium.digest)
        for field in ('licensor', 'licence_ids', 'licence_text_id', 'text_sha256',
                      'decision_class', 'binding_conditions', 'components'):
            self.assertEqual(getattr(large, field), getattr(medium, field), field)
        self.assertEqual([(s.id, s.text_sha256) for s in large.statements],
                         [(s.id, s.text_sha256) for s in medium.statements])
        self.assertEqual([(a.id, a.text_sha256) for a in large.advisories],
                         [(a.id, a.text_sha256) for a in medium.advisories])
        self.assertTrue(lic.standard_policy_eligible(large))
        self.assertEqual(record_path(MODEL_ID).parent.name, 'whisper-large-v3-records')

    def test_the_determination_pins_the_artifact_and_the_owners_choice(self):
        authority = json.loads((DATA_DIR / f'{NAME}.json').read_bytes())['authority']
        self.assertEqual(authority['revision'], REVISION)
        # large-v3 needs its preprocessor config: it has 128 mel bins, not 80.
        self.assertEqual({path for path, _bytes, _sha in FILES},
                         {'config.json', 'model.bin', 'preprocessor_config.json',
                          'tokenizer.json', 'vocabulary.json'})
        self.assertEqual(authority['owner_record'], {
            'path': 'licence-evidence-whisper-large-v3-2026-11-08/OWNER-DETERMINATION-whisper-large-v3.md',
            'bytes': 3218,
            'sha256': '8d8c1cf3648b52e13ae0a55aee9bb23c295dcb3619e89dcf3f50717c2fced311'})
        self.assertIn('only after a yes', authority['scope'])
        self.assertIn('never installed by default', authority['scope'])

    def test_the_record_covers_only_its_own_artifact(self):
        index = lic.load_determined_records()
        large = index.by_id(MODEL_ID)
        medium = index.by_id('faster-whisper-medium-en')
        agreement = lic.capture_agreement(large, 'yes')
        receipt = lic.receipt_from_agreement(large, agreement, manifest_digest='1' * 64,
                                             catalogue_digest='2' * 64, release_digest='3' * 64)
        self.assertTrue(lic.covers(large, receipt, manifest_digest='1' * 64))
        with self.assertRaises(lic.CoverageRefused):
            lic.covers(medium, receipt, manifest_digest='1' * 64)

    def test_changed_authority_owner_record_or_missing_texts_refuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / 'data'
            shutil.copytree(DATA_DIR, data)
            path = data / f'{NAME}.json'
            original = path.read_bytes()
            pin = (data / f'{NAME}.sha256').read_bytes()
            path.write_bytes(original + b' ')
            with self.assertRaisesRegex(ValueError, 'pin mismatch'):
                generate_whisper_large_v3_records(data)
            path.write_bytes(original)
            _repin(data, lambda v: v['authority'].update(revision='0' * 40))
            with self.assertRaisesRegex(ValueError, 'upstream binding'):
                generate_whisper_large_v3_records(data)
            path.write_bytes(original)
            _repin(data, lambda v: v['authority']['files'][1].update(sha256='0' * 64))
            with self.assertRaisesRegex(ValueError, 'upstream binding'):
                generate_whisper_large_v3_records(data)
            path.write_bytes(original)
            _repin(data, lambda v: v['authority']['files'].pop(2))
            with self.assertRaisesRegex(ValueError, 'upstream binding'):
                generate_whisper_large_v3_records(data)
            path.write_bytes(original)
            _repin(data, lambda v: v['authority'].pop('owner_record'))
            with self.assertRaisesRegex(ValueError, "owner's determination"):
                generate_whisper_large_v3_records(data)
            path.write_bytes(original)
            _repin(data, lambda v: v['records'][0].update(advisories=[]))
            with self.assertRaisesRegex(ValueError, 'card caution'):
                generate_whisper_large_v3_records(data)
            path.write_bytes(original)
            _repin(data, lambda v: v['records'][0].update(
                advisories=[{'id': i, 'text_sha256': d} for i, d in ADVISORIES], licensor='OpenAI'))
            with self.assertRaisesRegex(ValueError, 'classification'):
                generate_whisper_large_v3_records(data)
            path.write_bytes(original)
            (data / f'{NAME}.sha256').write_bytes(pin)
            self.assertEqual(generate_whisper_large_v3_records(data)[0].id, MODEL_ID)
            (data / 'texts' / LICENCE_SHA256).unlink()
            with self.assertRaises((ValueError, FileNotFoundError)):
                generate_whisper_large_v3_records(data)

    def test_no_preexisting_record_or_text_moves(self):
        root = Path(__file__).resolve().parents[1]
        entries = subprocess.check_output(
            ['git', 'ls-tree', '-r', '--name-only', BASE, 'src/kilix_license/data'],
            cwd=root, text=True).splitlines()
        self.assertTrue(entries)
        # The same change gives Demucs and medium.en a distribution entry each
        # (the owner's default-install decision). Their terms and record
        # digests are unchanged; test_demucs and test_whisper_medium pin that.
        distribution = {
            'src/kilix_license/data/determinations-demucs.json',
            'src/kilix_license/data/determinations-demucs.sha256',
            'src/kilix_license/data/demucs-records/demucs-htdemucs-6s.json',
            'src/kilix_license/data/determinations-whisper-medium.json',
            'src/kilix_license/data/determinations-whisper-medium.sha256',
            'src/kilix_license/data/whisper-medium-records/faster-whisper-medium-en.json',
        }
        for name in entries:
            if name in distribution:
                continue
            original = subprocess.check_output(['git', 'show', f'{BASE}:{name}'], cwd=root)
            self.assertEqual((root / name).read_bytes(), original, name)
        for name in sorted(distribution):
            if name.endswith('.json') and '-records/' in name:
                before = json.loads(subprocess.check_output(['git', 'show', f'{BASE}:{name}'], cwd=root))
                after = json.loads((root / name).read_bytes())
                before.pop('determinations_sha256')
                after.pop('determinations_sha256')
                self.assertEqual(after, before, name)


if __name__ == '__main__':
    unittest.main()
