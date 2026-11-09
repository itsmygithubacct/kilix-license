import dataclasses
import json
import tempfile
import unittest
from pathlib import Path

from kilix_license.catalog import load_determined_records, load_determined_texts, record_path
from kilix_license.noloop02 import APACHE, CC_BY, COMPONENT, LICENSOR, SOURCE, SOURCE_LICENCE, generate_noloop02_records
from kilix_license.generate import DATA_DIR
from kilix_license.records import LicenseRecord
from kilix_license.screen import render_screen
from kilix_license.standard_policy import standard_policy_eligible
from fake_store import FakeStore


class NoLoop02Terms(unittest.TestCase):
    def test_apache_and_cc_by_terms_are_displayed(self):
        record = load_determined_records().by_id("qwen-0.8b-no-loop-02")
        self.assertEqual(record.digest, generate_noloop02_records(DATA_DIR)[0].digest)
        self.assertEqual(record.digest, LicenseRecord.from_bytes(record_path(record.id).read_bytes()).digest)
        self.assertEqual(record.licence_ids, ("Apache-2.0", "CC-BY-4.0"))
        self.assertEqual(record.decision_class, "affirmative")
        self.assertEqual(record.expected_decision, "accept")
        self.assertEqual(record.text_sha256, APACHE)
        self.assertEqual(record.licensor, LICENSOR)
        self.assertEqual(record.licence_text_id, "debian/common-licenses/Apache-2.0")
        self.assertEqual([(c.id, c.exception_text_sha256) for c in record.components], [(COMPONENT, CC_BY)])
        self.assertEqual([s.id for s in record.statements],
                         ["modified-model", "weight-edit-attribution", "weight-edit-source-licence"])
        determination = (DATA_DIR / "determinations-noloop02.json").read_text(encoding="utf-8")
        self.assertIn(SOURCE, determination)
        with tempfile.TemporaryDirectory() as tmp:
            texts = load_determined_texts(Path(tmp) / "texts")
            screen = render_screen(record, texts, receipts=FakeStore(Path(tmp) / "receipts"))
            self.assertIn(texts.get(record.text_sha256), screen)
            self.assertIn(b"Apache License", screen)
            self.assertIn(texts.get(CC_BY), screen)
            self.assertIn(b"Attribution 4.0 International", screen)
            self.assertIn(texts.get(SOURCE_LICENCE), screen)
            self.assertIn(b"Copyright 2026 Alibaba Cloud", screen)
            self.assertIn(b"Modified by: itsmygithubacct", screen)
            self.assertIn(b"exp8_math/runs/p50c/edit", screen)
            self.assertIn(b"4d09ba6d6a7e891dd8063974dfe81b3d78e3494f", screen)
            self.assertIn(b"the edit is scaled to one third (alpha 2 of 6)", screen)

    def test_owner_approved_both_components(self):
        value = json.loads((DATA_DIR / "determinations-noloop02.json").read_bytes())
        self.assertEqual(value["owner_determination"]["components"],
                         {"apache-2.0": "approved", "cc-by-4.0": "approved"})
        # itsmygithubacct is recorded as the modifier, not as a licensor.
        self.assertEqual(value["authority"]["modifier"], "itsmygithubacct")
        self.assertNotIn("itsmygithubacct", LICENSOR)

    def test_standard_policy_covers_the_pinned_cc_by_component(self):
        # The owner put the CC BY 4.0 weight edit under the standard
        # distribution policy, as for kilix-female-02: no typed answer.
        record = load_determined_records().by_id("qwen-0.8b-no-loop-02")
        self.assertTrue(standard_policy_eligible(record))
        # Only those exact bytes: another text in the same component prompts.
        changed = dataclasses.replace(record, components=tuple(
            dataclasses.replace(c, exception_text_sha256="0" * 64) for c in record.components))
        self.assertFalse(standard_policy_eligible(changed))

    def test_changed_determination_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            import shutil
            shutil.copytree(DATA_DIR, data)
            file = data / "determinations-noloop02.json"
            file.write_bytes(file.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "pin mismatch"):
                generate_noloop02_records(data)
