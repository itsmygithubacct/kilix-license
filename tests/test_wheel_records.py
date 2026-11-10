"""Verify the built/installed wheel, including every source record family."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

from kilix_license.records import LicenseRecord

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'src/kilix_license/data'


class WheelRecordTests(unittest.TestCase):
    def test_all_record_families_and_notice_bytes_survive_wheel_install(self):
        expected_data = {
            str(path.relative_to(ROOT / 'src')): path.read_bytes()
            for path in DATA.rglob('*') if path.is_file()
        }
        expected_records = {}
        families = {}
        for folder in sorted(DATA.iterdir()):
            if not folder.is_dir() or not folder.name.endswith('records'):
                continue
            paths = sorted(folder.glob('*.json'))
            self.assertTrue(paths, folder.name)
            families[folder.name] = len(paths)
            for path in paths:
                record = LicenseRecord.from_bytes(path.read_bytes())
                self.assertNotIn(record.id, expected_records)
                expected_records[record.id] = record.digest
        self.assertIn('female02-records', families)
        self.assertIn('kilix-female-02', expected_records)
        self.assertIn('paradee-records', families)
        self.assertIn('paradee-8m-v1.2', expected_records)
        self.assertIn('whisper-medium-records', families)
        self.assertIn('faster-whisper-medium-en', expected_records)
        self.assertIn('demucs-records', families)
        self.assertIn('demucs-htdemucs-6s', expected_records)
        self.assertIn('whisper-large-v3-records', families)
        self.assertIn('faster-whisper-large-v3', expected_records)
        self.assertIn('en-core-web-sm-records', families)
        self.assertIn('en-core-web-sm-3.8.0', expected_records)
        self.assertIn('pp-ocrv6-small-records', families)
        self.assertIn('pp-ocrv6-small-det', expected_records)
        self.assertIn('pp-ocrv6-small-rec', expected_records)
        self.assertIn('noloop02-records', families)
        self.assertIn('qwen-0.8b-no-loop-02', expected_records)
        with tempfile.TemporaryDirectory(prefix='license-wheel-') as temp:
            root = Path(temp)
            # An independent build export; no live tree build/egg-info writes.
            export = root / 'source'
            export.mkdir()
            for name in ('pyproject.toml', 'README.md', 'LICENSE'):
                shutil.copyfile(ROOT / name, export / name)
            shutil.copytree(ROOT / 'src', export / 'src',
                            ignore=shutil.ignore_patterns('__pycache__', '*.egg-info'))
            wheels = root / 'wheels'
            wheels.mkdir()
            command = 'from setuptools.build_meta import build_wheel; import sys; build_wheel(sys.argv[1])'
            built = subprocess.run([sys.executable, '-c', command, str(wheels)],
                                   cwd=export, capture_output=True, text=True,
                                   timeout=60, env=dict(os.environ, PIP_NO_INDEX='1'))
            self.assertEqual(built.returncode, 0, built.stderr)
            wheel, = wheels.glob('*.whl')
            installed = root / 'installed'
            installed.mkdir()
            with zipfile.ZipFile(wheel) as archive:
                names = archive.namelist()
                self.assertEqual(sorted(set(expected_data) - set(names)), [])
                actual_data = {name: archive.read(name) for name in names
                               if name.startswith('kilix_license/data/') and not name.endswith('/')}
                self.assertEqual(actual_data, expected_data)
                for name in names:
                    self.assertFalse(name.startswith('/') or '..' in Path(name).parts)
                archive.extractall(installed)
            probe = '''import sys,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import kilix_license as lic
records={record.id:record.digest for record in lic.load_determined_records()}
assert 'kilix-female-02' in records
assert 'paradee-8m-v1.2' in records
assert 'faster-whisper-medium-en' in records
assert 'demucs-htdemucs-6s' in records
assert 'faster-whisper-large-v3' in records
assert 'en-core-web-sm-3.8.0' in records
assert 'pp-ocrv6-small-det' in records
assert 'pp-ocrv6-small-rec' in records
assert 'qwen-0.8b-no-loop-02' in records
lic.load_determined_texts(Path(sys.argv[2]))
print(json.dumps(records,sort_keys=True))
'''
            python = os.environ.get('KILIX_RECORD_TEST_PYTHON', sys.executable)
            checked = subprocess.run([python, '-I', '-c', probe, str(installed), str(root / 'texts')],
                                     cwd=root, capture_output=True, text=True, timeout=20)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertEqual(json.loads(checked.stdout), expected_records)
            if os.environ.get('KILIX_WHEEL_TEST_RESULT'):
                Path(os.environ['KILIX_WHEEL_TEST_RESULT']).write_text(json.dumps({
                    'status': 'pass', 'record_families': families,
                    'record_digests': expected_records,
                    'all_data_files': {name: hashlib.sha256(raw).hexdigest()
                                       for name, raw in sorted(expected_data.items())},
                    'data_file_count': len(expected_data),
                    'wheel_sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(),
                    'installed_python': python,
                    'scope': 'Actual wheel bytes and installed authority only; no model or receipt changes'
                }, indent=2) + '\n')
