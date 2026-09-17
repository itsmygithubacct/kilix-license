"""LIC2: records generated from the pinned determinations JSON."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from kilix_license.agreement import capture_agreement, typed_agreement_line
from kilix_license.catalog import load_determined_records, load_determined_texts
from kilix_license.errors import AgreementRequired, HandEditedRecord, ParaphraseRefused
from kilix_license.generate import (
    CONVERTER_ID,
    FORBIDDEN_PREFIXES,
    REQUIRED_RECORD_IDS,
    check_records,
    data_dir,
    decision_class_for_entry,
    generate_records,
    licence_ids_of,
    licence_text_digest,
    load_determinations,
    licensors_of,
    record_filename,
    render_record_bytes,
    write_quote_texts,
)
from kilix_license.paraphrase import POCKET_TERMS_SUMMARY_BYTES
from kilix_license.screen import render_screen
from kilix_license.texts import TextStore

ROOT = Path(__file__).resolve().parents[1]
DATA = data_dir()
GENERATOR = ROOT / "tools" / "generate_records.py"


def _run_generator(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GENERATOR), *args],
        cwd=str(cwd or ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


class GeneratedRecordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data, cls.payload, cls.pin = load_determinations(DATA)
        cls.texts_dir = DATA / "texts"
        cls.records = generate_records(
            cls.payload, pin=cls.pin, texts_dir=cls.texts_dir
        )
        cls.by_id = {record.id: record for record in cls.records}
        cls.entries = {entry["entry_id"]: entry for entry in cls.payload["entries"]}

    def test_pin_matches_determinations_bytes(self) -> None:
        self.assertEqual(self.pin, self.payload and self.pin)
        listed = (DATA / "determinations.sha256").read_text(encoding="utf-8")
        self.assertIn(self.pin, listed)
        self.assertEqual(len(self.pin), 64)

    def test_committed_records_match_generator(self) -> None:
        check_records(self.records, DATA / "records")

    def test_generator_check_is_green(self) -> None:
        result = _run_generator("--check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("match generator", result.stdout)

    def test_hand_edited_record_is_refused(self) -> None:
        scratch = Path(tempfile.mkdtemp(prefix="kilix-license-hand-edit-"))
        dest = scratch / "src" / "kilix_license" / "data"
        shutil.copytree(DATA, dest)
        planted = dest / "records" / record_filename("small-en-us")
        payload = json.loads(planted.read_text(encoding="utf-8"))
        payload["licensor"] = "Planted Licensor"
        planted.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
        result = _run_generator("--check", "--root", str(scratch))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("small-en-us", result.stderr)
        with self.assertRaises(HandEditedRecord):
            check_records(
                generate_records(
                    self.payload, pin=self.pin, texts_dir=dest / "texts"
                ),
                dest / "records",
            )

    def test_planted_licensor_change_fails(self) -> None:
        planted = json.loads(self.data.decode("utf-8"))
        original = planted["entries"][0]["licensors"][0]["name"]
        planted["entries"][0]["licensors"][0]["name"] = "Planted Licensor Inc."
        generated = generate_records(
            planted, pin=self.pin, texts_dir=self.texts_dir
        )
        committed = self.by_id[planted["entries"][0]["entry_id"]]
        self.assertNotEqual(generated[0].licensor, committed.licensor)
        self.assertEqual(generated[0].licensor, "Planted Licensor Inc.")
        self.assertEqual(committed.licensor, original)
        self.assertNotEqual(
            render_record_bytes(generated[0]), render_record_bytes(committed)
        )

    def test_records_equal_the_json(self) -> None:
        for entry in self.payload["entries"]:
            record = self.by_id[entry["entry_id"]]
            self.assertEqual(record.id, entry["entry_id"])
            self.assertEqual(record.licensor, licensors_of(entry))
            self.assertEqual(record.text_sha256, licence_text_digest(entry))
            self.assertEqual(record.licence_ids, licence_ids_of(entry))
            self.assertEqual(record.decision_class, entry["agreement"]["decision_class"])
            self.assertEqual(record.decision_class, decision_class_for_entry(entry))
            self.assertEqual(record.determinations_sha256, self.pin)
            self.assertEqual(
                [item.id for item in record.binding_conditions],
                [item["quote_id"] for item in entry.get("binding_conditions") or []],
            )
            for condition, quote in zip(
                record.binding_conditions,
                entry.get("binding_conditions") or [],
                strict=True,
            ):
                self.assertEqual(condition.text_sha256, quote["text_sha256"])
                self.assertTrue(condition.agreement_required)

    def test_each_record_cites_the_determinations_sha256(self) -> None:
        for record in self.records:
            self.assertEqual(record.determinations_sha256, self.pin)

    def test_required_in_closure_models_have_records(self) -> None:
        self.assertEqual(set(REQUIRED_RECORD_IDS), set(self.by_id))

    def test_no_kilix_llm_record(self) -> None:
        for record_id in self.by_id:
            self.assertFalse(
                any(record_id.startswith(prefix) for prefix in FORBIDDEN_PREFIXES)
            )
        for item in self.payload["not_entries"]:
            if str(item.get("entry_id", "")).startswith("kilix-llm"):
                self.assertNotIn(item["entry_id"], self.by_id)

    def test_decision_class_affirmative_iff_binding_or_restrictive(self) -> None:
        kristin = self.by_id["piper-en-us-kristin-medium"]
        self.assertEqual(kristin.decision_class, "informational")
        self.assertEqual(kristin.expected_decision, "record")
        self.assertFalse(kristin.binding_conditions)
        pocket = self.by_id["pocket-tts-english-q8_0"]
        self.assertEqual(pocket.decision_class, "affirmative")
        self.assertTrue(pocket.binding_conditions)
        encodec = self.by_id["encodec-24khz-stateful"]
        self.assertEqual(encodec.decision_class, "affirmative")
        self.assertTrue(encodec.binding_conditions)
        apache = self.by_id["small-en-us"]
        self.assertEqual(apache.decision_class, "affirmative")
        self.assertEqual(apache.licence_ids, ("Apache-2.0",))
        converter = self.by_id[CONVERTER_ID]
        self.assertEqual(converter.decision_class, "informational")
        self.assertFalse(converter.binding_conditions)
        self.assertEqual(converter.licence_ids, ("MIT",))

    def test_converter_notice_record_is_mit_notice_only(self) -> None:
        record = self.by_id[CONVERTER_ID]
        self.assertEqual(record.expected_decision, "record")
        self.assertIn("Meta Platforms", record.licensor)
        capture_agreement(record)
        with self.assertRaises(AgreementRequired):
            capture_agreement(record, "accept")

    def test_kristin_generated_needs_no_typed_agreement(self) -> None:
        record = self.by_id["piper-en-us-kristin-medium"]
        agreement = capture_agreement(record)
        self.assertEqual(agreement.decision, "record")

    def test_affirmative_without_extra_binding_requires_typed_accept(self) -> None:
        record = self.by_id["small-en-us"]
        with self.assertRaises(AgreementRequired):
            capture_agreement(record)
        line = typed_agreement_line(record)
        self.assertIn("small-en-us", line)
        self.assertIn("Alpha Cephei Inc.", line)
        agreement = capture_agreement(record, line)
        self.assertEqual(agreement.decision, "accept")

    def test_pocket_binding_text_is_the_json_span_not_a_paraphrase(self) -> None:
        record = self.by_id["pocket-tts-english-q8_0"]
        store = TextStore(Path(tempfile.mkdtemp(prefix="kilix-license-pocket-texts-")))
        load_determined_texts(store.root)
        with self.assertRaises(ParaphraseRefused):
            store.put(POCKET_TERMS_SUMMARY_BYTES, label="planted-summary")
        output = render_screen(record, store)
        quote = self.entries["pocket-tts-english-q8_0"]["binding_conditions"][0]
        self.assertIn(quote["text"].encode("utf-8"), output)
        self.assertNotIn(POCKET_TERMS_SUMMARY_BYTES, output)

    def test_licence_text_bytes_match_digests(self) -> None:
        for record in self.records:
            path = self.texts_dir / record.text_sha256
            self.assertTrue(path.is_file(), record.id)
            data = path.read_bytes()
            self.assertEqual(
                __import__("hashlib").sha256(data).hexdigest(), record.text_sha256
            )

    def test_load_determined_records_round_trip(self) -> None:
        index = load_determined_records()
        for record_id, record in self.by_id.items():
            loaded = index.by_id(record_id)
            self.assertEqual(render_record_bytes(loaded), render_record_bytes(record))

    def test_write_quote_texts_is_idempotent(self) -> None:
        write_quote_texts(self.payload, self.texts_dir)
        write_quote_texts(self.payload, self.texts_dir)
