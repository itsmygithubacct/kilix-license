from dataclasses import replace
import unittest

import kilix_license as lic
from kilix_license.agreement import STANDARD_POLICY


class StandardPolicyTests(unittest.TestCase):
    def setUp(self):
        self.records = lic.load_determined_records()

    def test_standard_models_cover_exact_manifest_without_claiming_a_typed_answer(self):
        for name in ('yolox_nano', 'yolox_s', 'yamnet', 'whistle',
                     'kilix-female-02', 'needle3-kilix-commands', 'needle2',
                     'needle2-runtime', 'whisper-tiny-ggml'):
            with self.subTest(name=name):
                record = self.records.by_id(name)
                agreement = lic.capture_standard_policy(record)
                self.assertIsNone(agreement.typed_text)
                self.assertEqual(agreement.authorization_policy, STANDARD_POLICY)
                receipt = lic.receipt_from_agreement(record, agreement,
                    manifest_digest='1' * 64, release_digest='2' * 64,
                    catalogue_digest='3' * 64)
                self.assertIn(STANDARD_POLICY, receipt.statement_digests)
                self.assertTrue(lic.covers(record, receipt, manifest_digest='1' * 64))
                with self.assertRaises(lic.CoverageRefused):
                    lic.covers(record, receipt, manifest_digest='4' * 64)

    def test_custom_terms_and_unknown_notices_need_explicit_agreement(self):
        for record in self.records:
            if record.binding_conditions or 'NC' in ' '.join(record.licence_ids):
                with self.subTest(name=record.id), self.assertRaises(lic.AgreementRequired):
                    lic.capture_standard_policy(record)
        record = self.records.by_id('needle3-kilix-commands')
        changed = replace(record, components=(replace(record.components[0],
                          exception_text_sha256='a' * 64),))
        self.assertFalse(lic.standard_policy_eligible(changed))

    def test_policy_cannot_claim_a_typed_yes(self):
        record = self.records.by_id('yolox_s')
        agreement = replace(lic.capture_standard_policy(record), typed_text='yes')
        with self.assertRaises(lic.AgreementRequired):
            lic.receipt_from_agreement(record, agreement, manifest_digest='1' * 64,
                                      release_digest='2' * 64, catalogue_digest='3' * 64)

    def test_policy_marker_cannot_cover_noncommercial_terms(self):
        from kilix_license.standard_policy import POLICY_SHA256
        record = next(r for r in self.records if 'NC' in ' '.join(r.licence_ids))
        # An otherwise valid explicit receipt must not be relabelled as policy.
        agreement = lic.capture_agreement(record, lic.typed_agreement_line(record))
        receipt = lic.receipt_from_agreement(record, agreement,
            manifest_digest='1' * 64, release_digest='2' * 64, catalogue_digest='3' * 64)
        forged = replace(receipt, statement_digests={STANDARD_POLICY: POLICY_SHA256})
        with self.assertRaises(lic.CoverageRefused):
            lic.covers(record, forged, manifest_digest='1' * 64)


if __name__ == '__main__':
    unittest.main()
