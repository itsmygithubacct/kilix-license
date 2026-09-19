"""LIC2: records generated from the pinned determinations JSON."""

from __future__ import annotations

import copy
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
    PDF_ENGINE_RECORD_IDS,
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
    record_from_entry,
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


class PdfEngineRecordTests(unittest.TestCase):
    """LIC3 (R4-047): OD-AY records for the kilix-pdf-conversion engine models."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.data, cls.payload, cls.pin = load_determinations(DATA)
        cls.texts_dir = DATA / "texts"
        cls.records = generate_records(
            cls.payload, pin=cls.pin, texts_dir=cls.texts_dir
        )
        cls.by_id = {record.id: record for record in cls.records}
        cls.entries = {entry["entry_id"]: entry for entry in cls.payload["entries"]}

    def test_od_ay_entries_are_exactly_the_pdf_records(self) -> None:
        od_ay = sorted(
            entry["entry_id"]
            for entry in self.payload["entries"]
            if (entry.get("owner_decision") or {}).get("id") == "OD-AY"
        )
        self.assertEqual(od_ay, sorted(PDF_ENGINE_RECORD_IDS))
        for record_id in PDF_ENGINE_RECORD_IDS:
            self.assertIn(record_id, self.by_id)
            self.assertEqual(self.entries[record_id]["status"], "DETERMINED")

    def test_pdf_records_equal_the_r3_determinations(self) -> None:
        # Owner-determined values (OD-AY) as an independent check on the JSON.
        determined = {
            "granite-docling-258m": ("IBM", ("Apache-2.0",)),
            "documentfigureclassifier-v2.5": ("docling-project", ("MIT",)),
            "granite-vision-4.1-4b": ("IBM", ("Apache-2.0",)),
        }
        self.assertEqual(set(determined), set(PDF_ENGINE_RECORD_IDS))
        for record_id, (licensor, licence_ids) in determined.items():
            with self.subTest(record_id=record_id):
                entry = self.entries[record_id]
                record = self.by_id[record_id]
                self.assertEqual(record.licensor, licensors_of(entry))
                self.assertEqual(record.licensor, licensor)
                self.assertEqual(record.licence_ids, licence_ids_of(entry))
                self.assertEqual(record.licence_ids, licence_ids)
                self.assertEqual(record.text_sha256, licence_text_digest(entry))
                self.assertEqual(record.determinations_sha256, self.pin)
                self.assertEqual(
                    [item.id for item in record.statements],
                    [q["quote_id"] for q in entry["statements"] + entry["attribution"]],
                )
                for statement, quote in zip(
                    record.statements,
                    entry["statements"] + entry["attribution"],
                    strict=True,
                ):
                    self.assertEqual(statement.text_sha256, quote["text_sha256"])
                    stored = (self.texts_dir / statement.text_sha256).read_bytes()
                    self.assertEqual(stored, quote["text"].encode("utf-8"))
                self.assertEqual(record.components, ())
                self.assertEqual(record.advisories, ())

    def test_planted_licensor_change_on_pdf_record_fails(self) -> None:
        records_dir = DATA / "records"
        check_records(self.records, records_dir)
        for record_id in PDF_ENGINE_RECORD_IDS:
            with self.subTest(record_id=record_id):
                planted = json.loads(self.data.decode("utf-8"))
                entry = next(
                    item for item in planted["entries"] if item["entry_id"] == record_id
                )
                entry["licensors"][0]["name"] = "Planted Licensor Inc."
                generated = generate_records(
                    planted, pin=self.pin, texts_dir=self.texts_dir
                )
                changed = {record.id: record for record in generated}[record_id]
                self.assertEqual(changed.licensor, "Planted Licensor Inc.")
                self.assertNotEqual(changed.licensor, self.by_id[record_id].licensor)
                with self.assertRaises(HandEditedRecord) as caught:
                    check_records(generated, records_dir)
                listed = str(caught.exception).split(": ", 1)[1].split(", ")
                self.assertEqual(listed, [record_filename(record_id)])

    def test_hand_edited_pdf_record_is_refused(self) -> None:
        scratch = Path(tempfile.mkdtemp(prefix="kilix-license-pdf-hand-edit-"))
        dest = scratch / "src" / "kilix_license" / "data"
        shutil.copytree(DATA, dest)
        for record_id in PDF_ENGINE_RECORD_IDS:
            planted = dest / "records" / record_filename(record_id)
            payload = json.loads(planted.read_text(encoding="utf-8"))
            payload["licensor"] = "Planted Licensor"
            planted.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
        result = _run_generator("--check", "--root", str(scratch))
        self.assertNotEqual(result.returncode, 0)
        for record_id in PDF_ENGINE_RECORD_IDS:
            self.assertIn(record_filename(record_id), result.stderr)

    def test_pdf_decision_class_is_generated_not_typed(self) -> None:
        for record_id in PDF_ENGINE_RECORD_IDS:
            with self.subTest(record_id=record_id):
                entry = self.entries[record_id]
                record = self.by_id[record_id]
                # Permissive, no binding condition: LIC2's rule still yields
                # affirmative because Apache-2.0 and MIT condition use.
                self.assertEqual(entry["binding_conditions"], [])
                self.assertEqual(record.binding_conditions, ())
                self.assertEqual(decision_class_for_entry(entry), "affirmative")
                self.assertEqual(record.decision_class, "affirmative")
                stripped = copy.deepcopy(entry)
                stripped["agreement"] = None
                generated = record_from_entry(
                    stripped, pin=self.pin, texts_dir=self.texts_dir
                )
                self.assertEqual(generated.decision_class, "affirmative")
                typed = copy.deepcopy(entry)
                typed["agreement"]["decision_class"] = "informational"
                with self.assertRaises(ValueError):
                    record_from_entry(typed, pin=self.pin, texts_dir=self.texts_dir)
                with self.assertRaises(AgreementRequired):
                    capture_agreement(record)
                line = typed_agreement_line(record)
                self.assertIn(record_id, line)
                self.assertEqual(capture_agreement(record, line).decision, "accept")

    def test_card_only_grants_show_canonical_text_without_a_supplied_holder(self) -> None:
        apache = {self.by_id[r].text_sha256 for r in ("granite-docling-258m", "granite-vision-4.1-4b")}
        self.assertEqual(apache, {self.by_id["small-en-us"].text_sha256})
        mit = (self.texts_dir / self.by_id["documentfigureclassifier-v2.5"].text_sha256).read_bytes()
        self.assertTrue(mit.startswith(b"MIT License\n"))
        holders = [line for line in mit.splitlines() if line.startswith(b"Copyright")]
        self.assertEqual(holders, [b"Copyright (c) <year> <copyright holders>"])
        for digest in apache:
            text = (self.texts_dir / digest).read_bytes()
            holders = [line.strip() for line in text.splitlines() if b"Copyright" in line and b"[" in line]
            self.assertEqual(holders, [b"Copyright [yyyy] [name of copyright owner]"])

    def test_no_record_for_refused_or_out_of_scope_pdf_models(self) -> None:
        for record_id in self.by_id:
            for word in ("datalab", "surya", "marker", "gonoto", "chart2csv", "mlx"):
                self.assertNotIn(word, record_id.lower())
        refused = [
            item
            for item in self.payload["not_entries"]
            if "OD-AY" in str(item.get("reason", ""))
        ]
        self.assertEqual(len(refused), 2)
        for item in refused:
            self.assertNotIn(item["entry_id"], self.by_id)
