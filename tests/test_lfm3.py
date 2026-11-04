import unittest

from kilix_license.catalog import load_determined_records
from kilix_license.generate import data_dir
from kilix_license.lfm3 import generate_lfm3_records


class LFM3RecordTests(unittest.TestCase):
    def test_upstream_model_has_its_own_binding(self):
        record, = generate_lfm3_records(data_dir(None))
        self.assertEqual(record.id, 'lfm3-kilix-commands')
        self.assertEqual(record.decision_class, 'affirmative')
        self.assertTrue(record.binding_conditions[0].agreement_required)
        self.assertEqual(record.statements[0].id, 'upstream-model')
        self.assertEqual(load_determined_records().by_id(record.id).digest, record.digest)
