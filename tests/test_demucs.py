"""Demucs htdemucs_6s terms: its own record, Meta's MIT text, no digest moved."""
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
from kilix_license.demucs import (
    LICENCE_SHA256, MODEL_ID, REVISION, generate_demucs_records,
)

# kilix-license before this family existed.
BASE = '7c70078f8da3d21cc0ee9d0e9a0a133a06bc1a42'
WEIGHTS_SHA256 = '34c22ccb381c6f9fdbf324f04e1e2fe21aaaf293f5ded163a162697ff9a02ddd'


def _repin(data: Path, mutate) -> None:
    path = data / 'determinations-demucs.json'
    value = json.loads(path.read_bytes())
    mutate(value)
    raw = (json.dumps(value, indent=2) + '\n').encode()
    path.write_bytes(raw)
    (data / 'determinations-demucs.sha256').write_text(sha256_hex(raw) + '\n')


class DemucsTerms(unittest.TestCase):
    def test_exact_generated_record_with_meta_mit_text(self):
        index = lic.load_determined_records()
        demucs = index.by_id(MODEL_ID)
        self.assertEqual(demucs.digest, generate_demucs_records(DATA_DIR)[0].digest)
        self.assertEqual(demucs.licensor, 'Meta Platforms, Inc. and affiliates')
        self.assertEqual(demucs.licence_ids, ('MIT',))
        self.assertEqual(demucs.decision_class, 'affirmative')
        self.assertEqual(demucs.licence_text_id, 'github.com/adefossez/demucs/LICENSE')
        # The same Meta MIT bytes the EnCodec converter record shows.
        encodec = index.by_id('encodec-converter-runtime-code')
        self.assertEqual(demucs.text_sha256, encodec.text_sha256)
        self.assertEqual(demucs.text_sha256, LICENCE_SHA256)
        text = (DATA_DIR / 'texts' / LICENCE_SHA256).read_bytes()
        self.assertTrue(text.startswith(b'MIT License\n\nCopyright (c) Meta Platforms, Inc. and affiliates.\n'))
        self.assertEqual((demucs.advisories, demucs.statements, demucs.binding_conditions,
                          demucs.components), ((), (), (), ()))
        self.assertTrue(lic.standard_policy_eligible(demucs))
        self.assertEqual(record_path(MODEL_ID).parent.name, 'demucs-records')

    def test_the_determination_pins_the_weights_and_the_owners_determination(self):
        data = json.loads((DATA_DIR / 'determinations-demucs.json').read_bytes())
        authority = data['authority']
        files = {item['path']: (item['bytes'], item['sha256']) for item in authority['files']}
        self.assertEqual(files, {'5c90dfd2-34c22ccb.th': (54996327, WEIGHTS_SHA256)})
        # htdemucs_6s is that one model with default weights.
        self.assertEqual(authority['bag_definition']['text'], "models: ['5c90dfd2']")
        # Demucs checks a .th file against the sha256 prefix in its name.
        self.assertTrue(WEIGHTS_SHA256.startswith('34c22ccb'))
        self.assertEqual(authority['revision'], REVISION)
        self.assertEqual(authority['owner_request'],
                         {'date': '2026-11-08',
                          'words': 'route kilix split properly through kilix-license.'})
        self.assertIn('training data', authority['unproved'])
        self.assertEqual(authority['owner_record'], {
            'path': 'licence-evidence-demucs-htdemucs-6s-2026-11-08/OWNER-DETERMINATION-demucs-htdemucs-6s.md',
            'bytes': 3506,
            'sha256': 'c58b90a793b5a0866253d5351de0cc61000f05835daf6736a0ae3a2e2e22def0'})
        self.assertIn('Make it my determination (Recommended)', authority['determined_by'])

    def test_the_record_covers_only_its_own_artifact(self):
        index = lic.load_determined_records()
        demucs = index.by_id(MODEL_ID)
        other = index.by_id('basic-pitch-icassp-2022-onnx')
        agreement = lic.capture_standard_policy(demucs)
        self.assertIsNone(agreement.typed_text)
        receipt = lic.receipt_from_agreement(demucs, agreement, manifest_digest='1' * 64,
                                             catalogue_digest='2' * 64, release_digest='3' * 64)
        self.assertTrue(lic.covers(demucs, receipt, manifest_digest='1' * 64))
        with self.assertRaises(lic.CoverageRefused):
            lic.covers(demucs, receipt, manifest_digest='4' * 64)
        with self.assertRaises(lic.CoverageRefused):
            lic.covers(other, receipt, manifest_digest='1' * 64)

    def test_changed_authority_or_missing_text_refuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / 'data'
            shutil.copytree(DATA_DIR, data)
            path = data / 'determinations-demucs.json'
            pin_path = data / 'determinations-demucs.sha256'
            original, pin = path.read_bytes(), pin_path.read_bytes()

            def restore():
                path.write_bytes(original)
                pin_path.write_bytes(pin)

            path.write_bytes(original + b' ')
            with self.assertRaisesRegex(ValueError, 'pin mismatch'):
                generate_demucs_records(data)
            restore()
            cases = (
                (lambda v: v['authority'].update(revision='0' * 40), 'upstream binding'),
                (lambda v: v['authority']['files'][0].update(sha256='0' * 64), 'upstream binding'),
                (lambda v: v['authority']['files'][0].update(
                    url='https://huggingface.co/adefossez/HTDemucs-6s/resolve/main/5c90dfd2.safetensors'),
                 'upstream binding'),
                (lambda v: v['authority'].update(readme_licence_line='Demucs is released under CC BY-NC 4.0.'),
                 'licence evidence'),
                (lambda v: v['authority'].update(relicensing={}), 'licence evidence'),
                (lambda v: v['authority']['bag_definition'].update(text="models: ['5c90dfd2', 'x']"),
                 'licence evidence'),
                (lambda v: v['authority'].pop('owner_record'), "owner's determination"),
                (lambda v: v['authority']['owner_record'].update(sha256='0' * 64),
                 "owner's determination"),
                (lambda v: v['authority'].update(licence_sha256='0' * 64), 'not displayed'),
                (lambda v: v['records'][0].update(licensor='Meta'), 'classification'),
                (lambda v: v['records'][0].update(decision_class='informational'), 'classification'),
                (lambda v: v['records'][0].update(
                    advisories=[{'id': 'x', 'text_sha256': LICENCE_SHA256}]), 'terms or scope'),
            )
            for mutate, message in cases:
                with self.subTest(message=message):
                    _repin(data, mutate)
                    with self.assertRaisesRegex(ValueError, message):
                        generate_demucs_records(data)
                    restore()
            self.assertEqual(generate_demucs_records(data)[0].id, MODEL_ID)
            (data / 'texts' / LICENCE_SHA256).unlink()
            with self.assertRaises((ValueError, FileNotFoundError)):
                generate_demucs_records(data)

    def test_no_preexisting_record_or_text_moves(self):
        root = Path(__file__).resolve().parents[1]
        entries = subprocess.check_output(
            ['git', 'ls-tree', '-r', '--name-only', BASE, 'src/kilix_license/data'],
            cwd=root, text=True).splitlines()
        self.assertTrue(entries)
        for name in entries:
            original = subprocess.check_output(['git', 'show', f'{BASE}:{name}'], cwd=root)
            self.assertEqual((root / name).read_bytes(), original, name)
