"""LIC2: records generated from the pinned determinations JSON."""

from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from kilix_license.agreement import capture_agreement, typed_agreement_line
from kilix_license.catalog import load_determined_records, load_determined_texts
from kilix_license.errors import (
    AgreementRequired,
    HandEditedRecord,
    ParaphraseRefused,
    TextDigestMismatch,
)
from kilix_license.generate import (
    ADVISORY_NOTE_AUTHORED,
    ADVISORY_NOTE_AUTHORED_PIN,
    ADVISORY_NOTE_AUTHORED_SHA256,
    ADVISORY_TEXT_SOURCES,
    ADVISORY_TEXTS,
    AUTHORED_DECLARATION,
    BINDING_TEXT_IDS,
    CONVERTER_ID,
    LICENCE_TEXT_IDS,
    FORBIDDEN_PREFIXES,
    PDF_ENGINE_RECORD_IDS,
    REQUIRED_RECORD_IDS,
    authored_digest,
    authored_lines,
    authored_text,
    check_advisory_note_authored,
    check_advisory_note_prose,
    check_advisory_note_sources,
    check_advisory_texts,
    check_binding_text_ids,
    check_licence_text_ids,
    check_records,
    data_dir,
    decision_class_for_entry,
    generate_records,
    licence_ids_of,
    licence_text_digest,
    licensors_of,
    load_determinations,
    load_pin,
    parse_advisory_note,
    parse_quoted_blocks,
    quote_blobs,
    record_filename,
    record_from_entry,
    render_record_bytes,
    states_a_licence,
    write_quote_texts,
)
from kilix_license.paraphrase import POCKET_TERMS_SUMMARY_BYTES
from kilix_license.screen import render_screen
from kilix_license.texts import TextStore

from fake_store import FakeStore
from source_pins import literal_constant

ROOT = Path(__file__).resolve().parents[1]
DATA = data_dir()
GENERATOR = ROOT / "tools" / "generate_records.py"
GENERATE_PY = ROOT / "src" / "kilix_license" / "generate.py"

# LIC6-FIX-VERIFY V1. The authored text of the one shipped advisory note,
# digested. TYPED here, and typed again in ADVISORY_NOTE_AUTHORED_PIN in
# src/kilix_license/generate.py: two files, neither figure derived from the
# note, so a declaration computed from the note file cannot satisfy either.
# Change it only in the same commit as a deliberate note edit, as step 2 of
# the path README.md and every refusal state.
AUTHORED_PIN = "120dc2042a48e4d793d47dd4653ad0f52e7d27d443a2b9b3776a8b40bb67f5c8"


def tracked_files() -> set[str]:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return set()
    return {line for line in result.stdout.splitlines() if line}


def _numbered_sections(text: str) -> dict[int, dict[int, str]]:
    """Split a "== N. title" report into {section number: {line number: line}}.

    The pinned note source is such a report. Reading its structure back out of
    the file is what lets the suite derive which lines the note should quote
    instead of repeating the answer (LIC5-VERIFY F1, mutant V6).
    """
    sections: dict[int, dict[int, str]] = {}
    current: dict[int, str] | None = None
    header = re.compile(r"^== (\d+)\. ")
    for number, line in enumerate(text.split("\n"), start=1):
        found = header.match(line)
        if found is not None:
            current = {number: line}
            sections[int(found.group(1))] = current
        elif line == "":
            current = None
        elif current is not None:
            current[number] = line
    return sections


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        digest.update(str(path.relative_to(root)).encode("utf-8") + b"\0")
        if path.is_file():
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


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
        # LIC3-2: exactly one pin line, and it is the digest of the bytes.
        listed = (DATA / "determinations.sha256").read_text(encoding="utf-8")
        pins = [
            line.split()
            for line in listed.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertEqual(pins, [[hashlib.sha256(self.data).hexdigest(), "determinations.json"]])
        self.assertEqual(self.pin, hashlib.sha256(self.data).hexdigest())

    def test_a_second_pin_line_is_refused(self) -> None:
        # LIC3-2 (verifier mutant M10): a stale pin appended after the real one.
        scratch = Path(tempfile.mkdtemp(prefix="kilix-license-two-pins-"))
        shutil.copy2(DATA / "determinations.json", scratch / "determinations.json")
        text = (DATA / "determinations.sha256").read_text(encoding="utf-8")
        stale = "af7c5fe9d74fab86bdb4fb832cc63766900df3018ff991284438f6faf3b8cee4"
        for planted in (text + f"{stale}  determinations.json\n", f"{stale}  determinations.json\n" + text):
            with self.subTest(order=planted.index(stale)):
                (scratch / "determinations.sha256").write_text(planted, encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_pin(scratch)
                with self.assertRaises(ValueError):
                    load_determinations(scratch)
        (scratch / "determinations.sha256").write_text(text, encoding="utf-8")
        self.assertEqual(load_pin(scratch), self.pin)

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
        receipts = FakeStore(Path(tempfile.mkdtemp(prefix="kilix-license-pocket-receipts-")))
        output = render_screen(record, store, receipts=receipts)
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
        # LIC3-3: into a copy. The suite never writes the package tree.
        scratch = Path(tempfile.mkdtemp(prefix="kilix-license-quote-texts-")) / "texts"
        shutil.copytree(self.texts_dir, scratch)
        before = _tree_digest(scratch)
        write_quote_texts(self.payload, scratch)
        write_quote_texts(self.payload, scratch)
        self.assertEqual(_tree_digest(scratch), before)

    def test_every_needed_text_is_committed(self) -> None:
        # LIC3-3 (verifier mutant M7): a commit that lacks a text blob fails.
        needed = set(quote_blobs(self.payload))
        for record in self.records:
            needed.add(record.text_sha256)
            needed.update(
                c.exception_text_sha256
                for c in record.components
                if c.exception_text_sha256 is not None
            )
            needed.update(b.text_sha256 for b in record.binding_conditions)
            needed.update(a.text_sha256 for a in record.advisories)
            needed.update(t.text_sha256 for t in record.statements)
        missing = sorted(d for d in needed if not (self.texts_dir / d).is_file())
        self.assertEqual(missing, [])
        tracked = tracked_files()
        if not tracked:
            self.skipTest("not a git checkout; tracked set unobservable")
        prefix = "src/kilix_license/data/texts/"
        untracked = sorted(d for d in needed if prefix + d not in tracked)
        self.assertEqual(untracked, [])

    def test_generator_check_writes_nothing_and_fails_on_a_missing_text(self) -> None:
        # LIC3-3: --check is read-only. A missing quote text fails and stays missing.
        scratch = Path(tempfile.mkdtemp(prefix="kilix-license-check-ro-"))
        dest = scratch / "src" / "kilix_license" / "data"
        shutil.copytree(DATA, dest)
        before = _tree_digest(dest)
        result = _run_generator("--check", "--root", str(scratch))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_tree_digest(dest), before)
        blob = sorted(quote_blobs(self.payload))[0]
        (dest / "texts" / blob).unlink()
        before = _tree_digest(dest)
        result = _run_generator("--check", "--root", str(scratch))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"missing {blob}", result.stderr)
        self.assertFalse((dest / "texts" / blob).exists())
        self.assertEqual(_tree_digest(dest), before)


CARD_ONLY_CANONICAL = {
    "granite-docling-258m": ("Apache-2.0", "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"),
    "documentfigureclassifier-v2.5": ("MIT", "b05785f9f18e6716bab63424b11454513b9943a222595b70411009202fc592b5"),
    "granite-vision-4.1-4b": ("Apache-2.0", "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"),
}


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

    def test_card_only_grants_are_the_canonical_texts_byte_for_byte(self) -> None:
        # LIC3-1: pinned by digest, so a holder planted on any line fails
        # (verifier mutant M5b kept the template line and added one below it).
        # Apache-2.0: the Debian common-licenses bytes R2 shows for Vosk.
        # MIT: SPDX license-list-data v3.29.0 text/MIT.txt (builder reading R3 item 1).
        for record_id, (licence_id, digest) in CARD_ONLY_CANONICAL.items():
            with self.subTest(record_id=record_id):
                record = self.by_id[record_id]
                self.assertEqual(record.licence_ids, (licence_id,))
                self.assertEqual(record.text_sha256, digest)
                data = (self.texts_dir / digest).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), digest)
                entry = self.entries[record_id]
                texts = [t for t in entry["licence_texts"] if t["role"] == "licence"]
                self.assertEqual([t["sha256"] for t in texts], [digest])

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


class BindingTextIdentityTests(unittest.TestCase):
    """SR-4 / C2E-VERIFY F2: each binding text carries an identity keyed by the text."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.data, cls.payload, cls.pin = load_determinations(DATA)
        cls.texts_dir = DATA / "texts"
        cls.records = generate_records(cls.payload, pin=cls.pin, texts_dir=cls.texts_dir)
        cls.by_id = {record.id: record for record in cls.records}

    def test_every_binding_condition_has_its_declared_identity(self) -> None:
        quotes = {
            quote["quote_id"]
            for entry in self.payload["entries"]
            for quote in entry.get("binding_conditions") or []
        }
        self.assertEqual(quotes, set(BINDING_TEXT_IDS))
        for record in self.records:
            for condition in record.binding_conditions:
                with self.subTest(record=record.id, binding=condition.id):
                    self.assertEqual(condition.text_id, BINDING_TEXT_IDS[condition.id])

    def test_sibling_records_share_one_identity_for_one_text(self) -> None:
        ternary = self.by_id["bonsai-image-4b:ternary-gemlite"].binding_conditions[0]
        binary = self.by_id["bonsai-image-4b:binary-gemlite"].binding_conditions[0]
        self.assertNotEqual(ternary.id, binary.id)
        self.assertEqual(ternary.text_id, binary.text_id)
        self.assertEqual(ternary.text_id, "bfl.ai/legal/usage-policy")
        e24 = self.by_id["encodec-24khz-stateful"].binding_conditions[0]
        e48 = self.by_id["encodec-48khz-frame"].binding_conditions[0]
        self.assertEqual(e24.text_id, e48.text_id)

    def test_identity_is_outside_the_record_digest(self) -> None:
        # Receipts written by fbdfb546 name these digests; none may move.
        pinned = {}
        for line in (ROOT / "tests" / "data" / "record-digests-fbdfb546.txt").read_text(
            encoding="utf-8"
        ).splitlines():
            digest, record_id = line.split("  ", 1)
            pinned[record_id] = digest
        self.assertEqual({r.id: r.digest for r in self.records}, pinned)
        for record in self.records:
            stripped = replace(
                record,
                binding_conditions=tuple(
                    replace(item, text_id=None) for item in record.binding_conditions
                ),
                licence_text_id=None,
            )
            self.assertEqual(stripped.digest, record.digest)
        committed = (DATA / "records" / record_filename("bonsai-image-4b:binary-gemlite")).read_bytes()
        self.assertIn(b'"text_id":"bfl.ai/legal/usage-policy"', committed)
        self.assertIn(b'"licence_text_id":"huggingface.co/prism-ml#LICENSE"', committed)

    def test_a_binding_quote_without_an_identity_is_refused(self) -> None:
        planted = json.loads(self.data.decode("utf-8"))
        entry = next(e for e in planted["entries"] if e["entry_id"] == "bonsai-image-4b:binary-gemlite")
        entry["binding_conditions"][0]["quote_id"] = "bfl-usage-policy-2026-10"
        with self.assertRaises(ValueError) as caught:
            generate_records(planted, pin=self.pin, texts_dir=self.texts_dir)
        self.assertIn("bfl-usage-policy-2026-10", str(caught.exception))

    def test_a_renamed_binding_keeps_its_identity(self) -> None:
        planted = json.loads(self.data.decode("utf-8"))
        entry = next(e for e in planted["entries"] if e["entry_id"] == "bonsai-image-4b:binary-gemlite")
        entry["binding_conditions"][0]["quote_id"] = "bfl-usage-policy-2026-10"
        table = dict(BINDING_TEXT_IDS, **{"bfl-usage-policy-2026-10": "bfl.ai/legal/usage-policy"})
        with mock.patch.dict("kilix_license.generate.BINDING_TEXT_IDS", table):
            generated = {r.id: r for r in generate_records(planted, pin=self.pin, texts_dir=self.texts_dir)}
        renamed = generated["bonsai-image-4b:binary-gemlite"].binding_conditions[0]
        self.assertEqual(renamed.id, "bfl-usage-policy-2026-10")
        self.assertEqual(renamed.text_id, "bfl.ai/legal/usage-policy")

    def test_identity_table_cannot_merge_or_split_texts(self) -> None:
        check_binding_text_ids(self.payload)
        merged = dict(BINDING_TEXT_IDS, **{"pocket-prohibited-use": "bfl.ai/legal/usage-policy"})
        with self.assertRaises(ValueError) as caught:
            check_binding_text_ids(self.payload, merged)
        self.assertIn("more than one source document", str(caught.exception))
        split = dict(BINDING_TEXT_IDS, **{"bfl-usage-policy-binary": "bfl.ai/legal/usage-policy-binary"})
        with self.assertRaises(ValueError) as caught:
            check_binding_text_ids(self.payload, split)
        self.assertIn("several text identities", str(caught.exception))


class LicenceTextIdentityTests(unittest.TestCase):
    """LIC4-VERIFY LIC4-3: a record's licence text carries a document identity."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.data, cls.payload, cls.pin = load_determinations(DATA)
        cls.texts_dir = DATA / "texts"
        cls.records = generate_records(cls.payload, pin=cls.pin, texts_dir=cls.texts_dir)
        cls.by_id = {record.id: record for record in cls.records}

    def test_every_record_has_its_declared_licence_text_identity(self) -> None:
        self.assertEqual(set(LICENCE_TEXT_IDS), set(self.by_id))
        for record in self.records:
            with self.subTest(record=record.id):
                self.assertEqual(record.licence_text_id, LICENCE_TEXT_IDS[record.id])
        for record in load_determined_records():
            with self.subTest(committed=record.id):
                self.assertEqual(record.licence_text_id, LICENCE_TEXT_IDS[record.id])

    def test_one_licence_text_one_identity(self) -> None:
        # The identity and the licence text digest correspond one to one today, so
        # no record is marked against another with nothing revised, and siblings
        # that show one licence text share one identity.
        by_identity: dict[str, set[str]] = {}
        by_digest: dict[str, set[str]] = {}
        for record in self.records:
            by_identity.setdefault(record.licence_text_id, set()).add(record.text_sha256)
            by_digest.setdefault(record.text_sha256, set()).add(record.licence_text_id)
        self.assertEqual([k for k, v in by_identity.items() if len(v) != 1], [])
        self.assertEqual([k for k, v in by_digest.items() if len(v) != 1], [])
        self.assertEqual(len(by_identity), len(by_digest))
        siblings = (
            ("bonsai-image-4b:ternary-gemlite", "bonsai-image-4b:binary-gemlite", "bonsai-8b", "bonsai-27b"),
            ("encodec-24khz-stateful", "encodec-48khz-frame"),
            ("qwen3-tts-0.6b-base", "qwen3-tts-0.6b-customvoice", "qwen3-tts-1.7b-voicedesign"),
            ("yolox_s", "yolox_tiny", "yolox_nano"),
            ("small-en-us", "lgraph-en-us", "granite-docling-258m", "granite-vision-4.1-4b"),
        )
        for group in siblings:
            with self.subTest(group=group):
                self.assertEqual(len({self.by_id[r].licence_text_id for r in group}), 1)
                self.assertEqual(len({self.by_id[r].text_sha256 for r in group}), 1)
        self.assertEqual(
            self.by_id["bonsai-image-4b:binary-gemlite"].licence_text_id,
            "huggingface.co/prism-ml#LICENSE",
        )

    def test_a_record_without_a_licence_text_identity_is_refused(self) -> None:
        planted = json.loads(self.data.decode("utf-8"))
        entry = next(e for e in planted["entries"] if e["entry_id"] == "bonsai-image-4b:binary-gemlite")
        entry["entry_id"] = "bonsai-image-4b:binary-gemlite-v2"
        with self.assertRaises(ValueError) as caught:
            generate_records(planted, pin=self.pin, texts_dir=self.texts_dir)
        self.assertIn("bonsai-image-4b:binary-gemlite-v2", str(caught.exception))
        self.assertIn("LICENCE_TEXT_IDS", str(caught.exception))

    def test_a_renamed_record_keeps_its_licence_text_identity(self) -> None:
        planted = json.loads(self.data.decode("utf-8"))
        entry = next(e for e in planted["entries"] if e["entry_id"] == "encodec-48khz-frame")
        entry["entry_id"] = "encodec-48khz-frame-v2"
        table = dict(LICENCE_TEXT_IDS, **{"encodec-48khz-frame-v2": LICENCE_TEXT_IDS["encodec-48khz-frame"]})
        with mock.patch.dict("kilix_license.generate.LICENCE_TEXT_IDS", table):
            renamed = record_from_entry(entry, pin=self.pin, texts_dir=self.texts_dir)
            check_licence_text_ids(planted)
        self.assertEqual(renamed.id, "encodec-48khz-frame-v2")
        self.assertEqual(renamed.licence_text_id, self.by_id["encodec-24khz-stateful"].licence_text_id)
        self.assertEqual(renamed.digest, replace(self.by_id["encodec-48khz-frame"], id=renamed.id).digest)

    def test_identity_table_cannot_merge_or_split_licence_texts(self) -> None:
        check_licence_text_ids(self.payload)
        merged = dict(LICENCE_TEXT_IDS, yolox_s=LICENCE_TEXT_IDS["bonsai-8b"])
        with self.assertRaises(ValueError) as caught:
            check_licence_text_ids(self.payload, merged)
        self.assertIn("more than one licence text", str(caught.exception))
        # The LIC4-3 defect: one sibling left with an identity of its own.
        split = dict(LICENCE_TEXT_IDS, **{"bonsai-image-4b:binary-gemlite": "huggingface.co/prism-ml/bonsai-image-binary/LICENSE"})
        with self.assertRaises(ValueError) as caught:
            check_licence_text_ids(self.payload, split)
        self.assertIn("several text identities", str(caught.exception))
        shared = dict(LICENCE_TEXT_IDS, **{"bitnet-b1.58-2b4t": BINDING_TEXT_IDS["llama3-community-licence-full-text"]})
        with self.assertRaises(ValueError) as caught:
            check_licence_text_ids(self.payload, shared)
        self.assertIn("also name binding texts", str(caught.exception))
        with mock.patch.dict("kilix_license.generate.LICENCE_TEXT_IDS", split):
            with self.assertRaises(ValueError):
                generate_records(self.payload, pin=self.pin, texts_dir=self.texts_dir)


class AdvisoryNoteTests(unittest.TestCase):
    """LIC5 (C4-VERIFY F2, R4-068): the EnCodec screen shows the note, not its spec."""

    # No source file, digest or line number is named here: LIC5-VERIFY F3. The
    # note's sources are ADVISORY_TEXT_SOURCES, the note's own headers are read
    # back out of the note, and the source files themselves are pinned under
    # tests/data/note-sources/<sha256>. Adding or dropping a quoted block is a
    # change to that one table, and these tests follow it.
    ENCODEC_IDS = ("encodec-24khz-stateful", "encodec-48khz-frame")
    ADVISORY_ID = "encodec-licence-history-note"
    SOURCES = ROOT / "tests" / "data" / "note-sources"
    PACKET_RECORDS = SOURCES / "packet-records"

    @classmethod
    def setUpClass(cls) -> None:
        cls.data, cls.payload, cls.pin = load_determinations(DATA)
        cls.texts_dir = DATA / "texts"
        cls.records = generate_records(cls.payload, pin=cls.pin, texts_dir=cls.texts_dir)
        cls.by_id = {record.id: record for record in cls.records}
        cls.entries = {entry["entry_id"]: entry for entry in cls.payload["entries"]}
        cls.note_digest = ADVISORY_TEXTS[cls.ADVISORY_ID]

    def _screen(self, record_id: str) -> bytes:
        scratch = Path(tempfile.mkdtemp(prefix="kilix-license-lic5-screen-"))
        texts = load_determined_texts(scratch / "texts")
        receipts = FakeStore(scratch / "receipts")
        index = load_determined_records()
        return render_screen(
            index.by_id(record_id), texts, receipts=receipts, records=index
        )

    def test_both_encodec_records_bind_the_note(self) -> None:
        for record_id in self.ENCODEC_IDS:
            with self.subTest(record=record_id):
                record = self.by_id[record_id]
                self.assertEqual(
                    [(a.id, a.text_sha256) for a in record.advisories],
                    [(self.ADVISORY_ID, self.note_digest)],
                )
        first, second = (self.by_id[r] for r in self.ENCODEC_IDS)
        self.assertEqual(first.advisories, second.advisories)

    def test_the_note_is_committed_and_matches_its_digest(self) -> None:
        path = self.texts_dir / self.note_digest
        self.assertTrue(path.is_file(), self.note_digest)
        self.assertEqual(
            hashlib.sha256(path.read_bytes()).hexdigest(), self.note_digest
        )
        tracked = tracked_files()
        if not tracked:
            self.skipTest("not a git checkout; tracked set unobservable")
        self.assertIn(
            f"src/kilix_license/data/texts/{self.note_digest}", tracked
        )

    def test_the_spec_sentence_is_off_the_screen_and_the_note_is_on_it(self) -> None:
        # The defect: OD-AR's builder-facing specification of the screen stood
        # where the note belongs. Its bytes come from the determinations, never
        # retyped here.
        note = (self.texts_dir / self.note_digest).read_bytes()
        for record_id in self.ENCODEC_IDS:
            quote = self.entries[record_id]["advisories"][0]
            self.assertEqual(quote["quote_id"], self.ADVISORY_ID)
            spec = quote["text"].encode("utf-8")
            self.assertNotEqual(quote["text_sha256"], self.note_digest)
            with self.subTest(record=record_id):
                screen = self._screen(record_id)
                header = f"=== advisory:{self.ADVISORY_ID} ===\n".encode("utf-8")
                self.assertIn(header + note, screen)
                self.assertNotIn(spec, screen)

    def test_the_note_names_the_sources_it_quotes(self) -> None:
        # LIC5-VERIFY F3: driven by ADVISORY_TEXT_SOURCES, so a block added to
        # or dropped from the note needs no edit here.
        declared = ADVISORY_TEXT_SOURCES[self.note_digest]
        note = (self.texts_dir / self.note_digest).read_text(encoding="utf-8")
        headers = [
            line for line in note.splitlines() if line.startswith("quoted from ")
        ]
        self.assertEqual(len(headers), len(declared), headers)
        for source in declared:
            with self.subTest(source=source.path, lines=source.lines):
                self.assertIn(f"quoted from {source.path}", note)
                self.assertIn(source.sha256, note)
        self.assertTrue(note.endswith("\n"))

    def test_every_quoted_line_is_still_its_named_sources_bytes(self) -> None:
        # LIC5-VERIFY F1 (Major). The note's first two lines promise the user
        # that every line under a "quoted from" header is the named source's
        # bytes. Nothing enforced that: one byte of the quoted CC BY-NC
        # sentence could be changed, made self-consistent, and the suite stayed
        # green. Re-derive each quoted block from the pinned source file and
        # compare bytes, using the line numbers the note's OWN header claims,
        # so a header that claims one slice while quoting another fails too.
        note = (self.texts_dir / self.note_digest).read_bytes()
        blocks = parse_quoted_blocks(note)
        declared = ADVISORY_TEXT_SOURCES[self.note_digest]
        self.assertEqual(len(blocks), len(declared))
        for (claimed, quoted), source in zip(blocks, declared):
            with self.subTest(source=claimed.path, lines=claimed.lines):
                # What the header claims is what the note is checked against.
                self.assertEqual(claimed, source)
                pinned = self.SOURCES / claimed.sha256
                self.assertTrue(pinned.is_file(), claimed.sha256)
                data = pinned.read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), claimed.sha256)
                lines = data.split(b"\n")
                expected = b"".join(lines[n - 1] + b"\n" for n in claimed.lines)
                self.assertEqual(quoted, expected)

    def test_each_quoted_slice_is_one_the_source_itself_justifies(self) -> None:
        # LIC5-VERIFY F1, mutant V6: a slice shifted by one and declared
        # honestly quotes real source lines, so comparing bytes is not enough.
        # A note may take a whole section of its source, header line included,
        # or the two lines at which the recorded licence changed -- never an
        # arbitrary window. Both are derived from the pinned source here; no
        # line number is typed, so dropping or adding a block needs no edit.
        licence_of = re.compile(r"LICENSE \d+ B sha256 (\S+)")
        for source in ADVISORY_TEXT_SOURCES[self.note_digest]:
            with self.subTest(source=source.path, lines=source.lines):
                text = (self.SOURCES / source.sha256).read_text(encoding="utf-8")
                sections = _numbered_sections(text)
                self.assertTrue(sections, source.path)
                allowed = {tuple(sorted(body)) for body in sections.values()}
                for body in sections.values():
                    states = {
                        number: line
                        for number, line in body.items()
                        if licence_of.search(line) is not None
                    }
                    if len(states) < 2:
                        continue
                    first = min(states)
                    started = licence_of.search(states[first]).group(1)
                    changed = [
                        number
                        for number in sorted(states)
                        if number > first
                        and licence_of.search(states[number]).group(1) != started
                    ]
                    if changed:
                        allowed.add((first, changed[0]))
                self.assertIn(source.lines, allowed)

    def test_no_line_the_note_wrote_itself_states_a_licence(self) -> None:
        # LIC5-FIX-VERIFY F1, mutant M11. The guard above covers what the note
        # QUOTES. M11 put "Meta relicensed the encodec weights to Apache-2.0 in
        # 2024; commercial use is permitted." in the note's preamble -- above
        # the first "quoted from" header, so outside the note's own promise --
        # and the whole suite stayed green while a first-use accept screen
        # carried a fabricated licence claim.
        #
        # The rule: a line nobody upstream wrote may introduce, attribute and
        # cite, and may not say what a licence is. It binds the preamble and
        # each block's three header lines, which is every authored line there
        # is; nothing outside a quoted block is unguarded any more.
        note = (self.texts_dir / self.note_digest).read_bytes()
        authored = authored_lines(note)
        self.assertGreaterEqual(len(authored), 4, authored)
        check_advisory_note_prose(self.note_digest, authored)

        # The detector is live, proved against the upstream language itself:
        # every quoted block contains a line this same pattern flags. A regex
        # that had stopped matching fails here instead of passing everywhere.
        for position, (source, quoted) in enumerate(parse_quoted_blocks(note), 1):
            flagged = [
                line
                for line in quoted.decode("utf-8").splitlines()
                if states_a_licence(line) is not None
            ]
            with self.subTest(block=position, lines=source.lines):
                self.assertTrue(flagged, quoted.decode("utf-8"))

        # M11 itself, planted in the shipped note's preamble.
        planted = note.replace(
            b"\n\nquoted from ",
            b"\nMeta relicensed the encodec weights to Apache-2.0 in 2024; "
            b"commercial use is permitted.\n\nquoted from ",
            1,
        )
        self.assertNotEqual(planted, note)
        with self.assertRaises(ValueError) as caught:
            check_advisory_note_prose(self.note_digest, authored_lines(planted))
        self.assertIn("states a licence", str(caught.exception))
        # and reached the way a record is generated, not only by direct call.
        with self.assertRaises(ValueError):
            check_advisory_note_sources(self.note_digest, planted)

        # The same sentence in a block's attribution header, which is where
        # LIC5-FIX-VERIFY F2's orienting clause now lives, is refused too.
        header = planted.replace(
            b"\nMeta relicensed the encodec weights to Apache-2.0 in 2024; "
            b"commercial use is permitted.",
            b"",
        ).replace(
            b" repository that states a licence for model weights",
            b" repository relicensed to Apache-2.0 that states a licence for model weights",
            1,
        )
        self.assertNotEqual(header, note)
        with self.assertRaises(ValueError):
            check_advisory_note_prose(self.note_digest, authored_lines(header))

        # A note with no preamble at all is refused rather than accepted as
        # trivially claim-free.
        headless = note[note.index(b"quoted from ") :]
        with self.assertRaises(ValueError):
            authored_lines(headless)

    def test_the_authored_text_is_pinned_and_nothing_else_may_appear(self) -> None:
        # LIC6-VERIFY F3, residual m11b. The line above screens authored prose
        # for licence vocabulary. m11b is the proof that a detector over a
        # vocabulary cannot close the class: "Meta later allowed everyone to
        # reuse the encodec weights freely." contains no licence identifier and
        # no word from that pattern, rendered on a screen whose binding
        # condition is CC BY-NC 4.0 printed beneath it, with the suite green.
        #
        # So this does not detect. The authored text is PINNED: exactly the
        # lines ADVISORY_NOTE_AUTHORED declares, byte for byte, in order.
        # Any other authored sentence fails whatever its wording, because the
        # test is equality with a declaration.
        note = (self.texts_dir / self.note_digest).read_bytes()
        authored = authored_lines(note)
        declared = ADVISORY_NOTE_AUTHORED[self.note_digest]
        self.assertEqual(tuple(line for _n, line in authored), tuple(declared))
        check_advisory_note_authored(self.note_digest, authored)

        # ---- the assertion above cannot be allowed to become a tautology ----
        # LIC6-FIX-VERIFY V1, mutant M10: the same defect one level up. Both
        # sides of that equality are objects, and M10 made the declaration
        # derive from the note file -- a 12-line helper and
        # `{d: _authored_from_file(d) for d in ADVISORY_NOTE_AUTHORED}` -- so
        # the note was compared with itself. `make records` exited 0, the
        # suite stayed green, a false permissive sentence rendered on both
        # EnCodec screens, and zero added lines outside the digest-named blob
        # contained it. Asserting harder about the imported object cannot
        # help: the imported object is what the mutant controls.
        #
        # So, two anchors that a derived declaration cannot reach.
        #
        # 1. The declaration is a LITERAL in the source, read out of the file
        #    with ast and never imported. A comprehension, a call, or a second
        #    module-level assignment that replaces it fails here.
        source_declaration = literal_constant(GENERATE_PY, "ADVISORY_NOTE_AUTHORED")
        self.assertEqual(
            {k: tuple(v) for k, v in source_declaration.items()},
            {k: tuple(v) for k, v in ADVISORY_NOTE_AUTHORED.items()},
            "the imported declaration is not what generate.py has written in "
            "it; a pin satisfied by a computed value is not a pin",
        )
        for lines in source_declaration.values():
            self.assertTrue(
                lines and all(isinstance(line, str) for line in lines),
                "a declared note's authored text must be literal strings",
            )
        # 2. Its content hashes to a figure TYPED in two files, neither of
        #    them derived from the note. A declaration computed from the note
        #    would have to hash to this, and the moment the note changes it
        #    does not.
        source_pin = literal_constant(GENERATE_PY, "ADVISORY_NOTE_AUTHORED_PIN")
        self.assertEqual(source_pin, dict(ADVISORY_NOTE_AUTHORED_PIN))
        self.assertEqual(
            ADVISORY_NOTE_AUTHORED_PIN[self.note_digest],
            AUTHORED_PIN,
            "generate.py's pin and the suite's typed copy disagree. Both are "
            "step 2 of the deliberate path: put the digest the generator "
            "printed in ADVISORY_NOTE_AUTHORED_PIN and in AUTHORED_PIN above.",
        )
        self.assertEqual(
            literal_constant(Path(__file__), "AUTHORED_PIN"),
            AUTHORED_PIN,
            "the suite's own copy of the pin must be typed, not computed",
        )
        self.assertEqual(authored_digest(authored), AUTHORED_PIN)
        self.assertEqual(
            hashlib.sha256(
                b"".join(
                    f"{line}\n".encode("utf-8")
                    for line in source_declaration[self.note_digest]
                )
            ).hexdigest(),
            AUTHORED_PIN,
            "the lines written in generate.py do not hash to the pinned "
            "digest; this is the arm a derived declaration fails",
        )
        # and the generator enforces it, so `make records` refuses too, not
        # only this test: a pin whose declaration hashes to anything else.
        with self.assertRaises(ValueError) as caught:
            check_advisory_note_authored(
                self.note_digest,
                authored,
                {self.note_digest: tuple(declared) + ("smuggled line.",)},
            )
        self.assertIn("does not match its pinned digest", str(caught.exception))
        with self.assertRaises(ValueError) as caught:
            check_advisory_note_authored(self.note_digest, authored, None, {})
        self.assertIn("no pinned digest", str(caught.exception))
        # ---- end of the non-vacuity guard ----

        # The digest is derived from the declaration, never typed, so the
        # declaration and the digest cannot drift apart.
        self.assertEqual(
            authored_digest(authored), ADVISORY_NOTE_AUTHORED_SHA256[self.note_digest]
        )
        self.assertEqual(
            hashlib.sha256(authored_text(authored)).hexdigest(),
            ADVISORY_NOTE_AUTHORED_SHA256[self.note_digest],
        )
        self.assertEqual(
            ADVISORY_NOTE_AUTHORED_SHA256[self.note_digest],
            ADVISORY_NOTE_AUTHORED_PIN[self.note_digest],
            "the derived digest and the typed pin disagree",
        )
        # Every shipped note is pinned, not just this one -- in both tables.
        self.assertEqual(
            sorted(ADVISORY_TEXTS.values()), sorted(ADVISORY_NOTE_AUTHORED)
        )
        self.assertEqual(
            sorted(ADVISORY_TEXTS.values()), sorted(ADVISORY_NOTE_AUTHORED_PIN)
        )

        # m11b itself, in the preamble: refused, and the refusal names the one
        # place a future editor changes.
        outside_the_vocabulary = (
            b"Meta later allowed everyone to reuse the encodec weights freely."
        )
        self.assertIsNone(
            states_a_licence(outside_the_vocabulary.decode("utf-8")),
            "m11b is only interesting while the old detector misses it",
        )
        planted = note.replace(
            b"\n\nquoted from ",
            b"\n" + outside_the_vocabulary + b"\n\nquoted from ",
            1,
        )
        self.assertNotEqual(planted, note)
        with self.assertRaises(ValueError) as caught:
            check_advisory_note_authored(
                self.note_digest, authored_lines(planted)
            )
        message = str(caught.exception)
        self.assertIn("is not the text declared for it", message)
        self.assertIn(AUTHORED_DECLARATION, message)
        self.assertIn("make records", message)
        # and reached the way a record is generated, not only by direct call
        with self.assertRaises(ValueError):
            check_advisory_note_sources(self.note_digest, planted)

        # The same, in a block's attribution header rather than the preamble.
        in_a_header = note.replace(
            b" repository that states a licence",
            b" repository whose weights anyone may now reuse that states a licence",
            1,
        )
        self.assertNotEqual(in_a_header, note)
        with self.assertRaises(ValueError):
            check_advisory_note_sources(self.note_digest, in_a_header)

        # Every shape, not just insertion: altering a word, dropping a line,
        # and reordering two lines are each refused.
        altered = note.replace(b"nothing here is retyped", b"nothing here is invented", 1)
        dropped = note.replace(
            b"The source file is pinned by licence-evidence-encodec-errata-2026-09-17\n",
            b"",
            1,
        )
        for name, variant in (("altered", altered), ("dropped", dropped)):
            with self.subTest(shape=name):
                self.assertNotEqual(variant, note)
                with self.assertRaises(ValueError):
                    check_advisory_note_authored(
                        self.note_digest, authored_lines(variant)
                    )
        # Reordering, checked on the parsed lines so the note stays parseable.
        swapped = (authored[1], authored[0]) + authored[2:]
        with self.assertRaises(ValueError):
            check_advisory_note_authored(self.note_digest, swapped)

        # A note nobody declared authored text for is refused, rather than
        # reaching a screen as unpinned prose.
        with self.assertRaises(ValueError) as caught:
            check_advisory_note_authored(self.note_digest, authored, {})
        self.assertIn("declares no authored text", str(caught.exception))

    def test_the_generator_refuses_a_note_whose_authored_text_is_unpinned(self) -> None:
        # The pin, reached the way a record is generated: a seat that edits the
        # note and renames it to its new sha256 -- which is exactly what m11b
        # did, and what the content-addressed store forces -- gets a refusal
        # naming the declaration, not a green suite.
        scratch = Path(tempfile.mkdtemp(prefix="kilix-license-lic6fix-authored-"))
        dest = scratch / "data"
        shutil.copytree(DATA, dest)
        texts = dest / "texts"
        note = (texts / self.note_digest).read_bytes()
        planted = note.replace(
            b"\n\nquoted from ",
            b"\nMeta later allowed everyone to reuse the encodec weights freely."
            b"\n\nquoted from ",
            1,
        )
        digest = hashlib.sha256(planted).hexdigest()
        (texts / digest).write_bytes(planted)
        with mock.patch.dict(
            "kilix_license.generate.ADVISORY_TEXTS", {self.ADVISORY_ID: digest}
        ), mock.patch.dict(
            "kilix_license.generate.ADVISORY_TEXT_SOURCES",
            {digest: ADVISORY_TEXT_SOURCES[self.note_digest]},
        ), mock.patch.dict(
            "kilix_license.generate.ADVISORY_NOTE_AUTHORED",
            {digest: ADVISORY_NOTE_AUTHORED[self.note_digest]},
        ), mock.patch.dict(
            # V1: the declaration's own digest, declared for the renamed note
            # too, so what this test asserts is the note-vs-declaration
            # refusal and not the missing-pin one that now precedes it.
            "kilix_license.generate.ADVISORY_NOTE_AUTHORED_PIN",
            {digest: ADVISORY_NOTE_AUTHORED_PIN[self.note_digest]},
        ):
            with self.assertRaises(ValueError) as caught:
                generate_records(self.payload, pin=self.pin, texts_dir=texts)
        self.assertIn("is not the text declared for it", str(caught.exception))

        # And a note with NO authored declaration at all does not generate
        # either: check_advisory_texts refuses it before a screen exists.
        with mock.patch.dict(
            "kilix_license.generate.ADVISORY_TEXTS", {self.ADVISORY_ID: digest}
        ), mock.patch.dict(
            "kilix_license.generate.ADVISORY_TEXT_SOURCES",
            {digest: ADVISORY_TEXT_SOURCES[self.note_digest]},
        ), mock.patch.dict(
            "kilix_license.generate.ADVISORY_NOTE_AUTHORED", {}, clear=True
        ):
            with self.assertRaises(ValueError) as caught:
                generate_records(self.payload, pin=self.pin, texts_dir=texts)
        self.assertIn("declare no authored text", str(caught.exception))

    def test_text_appended_after_the_last_quoted_block_is_still_caught(self) -> None:
        # LIC5 mutant M13, made explicit. It was killed only implicitly: text
        # appended after the last block is swallowed into that block's quoted
        # lines and fails the byte comparison. Pinning the authored text must
        # not change that -- such a line is not an authored line at all, so
        # the pin never sees it, and the boundary has to keep holding on its
        # own. Asserted here so a later change to parse_advisory_note that
        # started treating trailing text as authored, or as neither, fails.
        note = (self.texts_dir / self.note_digest).read_bytes()
        appended = note.rstrip(b"\n") + (
            b"\nMeta later allowed everyone to reuse the encodec weights freely.\n"
        )
        self.assertNotEqual(appended, note)
        # It is NOT admitted as authored text: the authored lines are unchanged.
        self.assertEqual(authored_lines(appended), authored_lines(note))
        # It is swallowed into the last block's quoted bytes, and those no
        # longer match the source the header names.
        blocks = parse_quoted_blocks(appended)
        last = blocks[-1]
        self.assertIn(b"reuse the encodec weights freely", last[1])
        pinned = (self.SOURCES / last[0].sha256).read_bytes()
        lines = pinned.split(b"\n")
        expected = b"".join(lines[n - 1] + b"\n" for n in last[0].lines)
        self.assertNotEqual(last[1], expected)
        # A blank line before it instead is refused at the parse.
        with self.assertRaises(ValueError):
            parse_quoted_blocks(
                note.rstrip(b"\n") + b"\n\nMeta later allowed everyone freely.\n"
            )

    def test_the_quoted_sources_digest_has_a_second_witness_in_the_packet(self) -> None:
        # LIC5-FIX-VERIFY F3, mutant M8. The source file is pinned under
        # tests/data/note-sources/<its own sha256>, so a seat that forges the
        # file AND renames it to its new digest AND updates the note and the
        # declaration is self-consistent and green: the chain of trust ends in
        # this tree. M8 shipped a fabricated "Everything in this repository is
        # released under the MIT license" that way.
        #
        # The L-ENC-R2 packet records the same file independently -- its path,
        # its sha256, and the text of lines 13-20 -- in sources/quotes.json
        # under PACKET_HISTORY. That object is vendored beside the source, and
        # is a second witness: forging the source now also means forging the
        # packet's record of it, and the digest of the packet file that record
        # came from is the one the note shows the user in its preamble.
        #
        # It is a PARTIAL close. The packet records no copy of lines 91-94, so
        # block 2 has one witness and this test says which lines are covered.
        declared = ADVISORY_TEXT_SOURCES[self.note_digest]
        note = (self.texts_dir / self.note_digest).read_text(encoding="utf-8")
        preamble = note[: note.index("quoted from ")]
        covered: dict[tuple[int, ...], tuple[int, ...]] = {}
        for source in declared:
            with self.subTest(source=source.path, lines=source.lines):
                record_path = self.PACKET_RECORDS / f"{source.sha256}.json"
                self.assertTrue(
                    record_path.is_file(),
                    f"no packet record vendored for {source.sha256}; a declared "
                    "source with no second witness is exactly LIC5-FIX-VERIFY F3",
                )
                record = json.loads(record_path.read_text(encoding="utf-8"))
                # Witness 1: the digest the note and the declaration claim.
                self.assertEqual(record["sha256"], source.sha256)
                self.assertTrue(source.path.endswith(record["path"]), record["path"])
                # The packet file that record came from is the one the note
                # shows the user, so forging it is visible on the screen.
                self.assertIn(record["vendored_from"]["sha256"], preamble)
                self.assertIn(record["vendored_from"]["packet"], preamble)
                # Witness 2: the packet's own copy of each line the note quotes.
                pinned = (self.SOURCES / source.sha256).read_text(encoding="utf-8")
                lines = pinned.split("\n")
                witnessed = []
                for number in source.lines:
                    recorded = record["lines"].get(str(number))
                    if recorded is None:
                        continue
                    self.assertEqual(recorded, lines[number - 1])
                    witnessed.append(number)
                covered[source.lines] = tuple(witnessed)
        self.assertTrue(
            any(lines == witnessed for lines, witnessed in covered.items()),
            f"no declared block is fully witnessed by the packet: {covered}",
        )

    def test_a_note_whose_header_disagrees_with_its_sources_is_refused(self) -> None:
        # The guard behind F1, on the generator side: the same shifted-slice
        # and misdeclared-header shapes, planted, must not generate.
        note = (self.texts_dir / self.note_digest).read_bytes()
        check_advisory_note_sources(self.note_digest, note)
        blocks = parse_quoted_blocks(note)
        first = blocks[0][0]
        shifted = dict(ADVISORY_TEXT_SOURCES)
        shifted[self.note_digest] = (
            replace(first, lines=tuple(n + 1 for n in first.lines)),
        ) + tuple(source for source, _ in blocks[1:])
        with self.assertRaises(ValueError) as caught:
            check_advisory_note_sources(self.note_digest, note, shifted)
        self.assertIn("ADVISORY_TEXT_SOURCES declares", str(caught.exception))
        with self.assertRaises(ValueError):
            check_advisory_note_sources("f" * 64, note)
        truncated = note[: note.index(b"\nquoted from ")]
        with self.assertRaises(ValueError):
            parse_quoted_blocks(truncated)

    def test_the_generator_refuses_a_note_whose_header_moved(self) -> None:
        # The same guard, reached the way a record is generated: a seat that
        # edits a note's header without editing ADVISORY_TEXT_SOURCES gets a
        # refusal that names the table, not a green suite (LIC5-VERIFY F1).
        scratch = Path(tempfile.mkdtemp(prefix="kilix-license-lic5-header-"))
        dest = scratch / "data"
        shutil.copytree(DATA, dest)
        texts = dest / "texts"
        first = parse_quoted_blocks((texts / self.note_digest).read_bytes())[0][0]
        claimed = f", lines {first.lines[0]} and {first.lines[-1]}\n".encode("utf-8")
        note = (texts / self.note_digest).read_bytes()
        self.assertEqual(note.count(claimed), 1)
        moved = note.replace(
            claimed,
            f", lines {first.lines[0] + 1} and {first.lines[-1] + 1}\n".encode("utf-8"),
        )
        digest = hashlib.sha256(moved).hexdigest()
        (texts / digest).write_bytes(moved)
        with mock.patch.dict(
            "kilix_license.generate.ADVISORY_TEXTS", {self.ADVISORY_ID: digest}
        ), mock.patch.dict(
            "kilix_license.generate.ADVISORY_TEXT_SOURCES",
            {digest: ADVISORY_TEXT_SOURCES[self.note_digest]},
        ), mock.patch.dict(
            # LIC6-FIX: the authored-text pin is keyed by the note's digest,
            # so a renamed note needs an entry or it is refused for being
            # unpinned before this guard is reached. Declared here so the
            # refusal this test is about is the one it asserts.
            "kilix_license.generate.ADVISORY_NOTE_AUTHORED",
            {digest: ADVISORY_NOTE_AUTHORED[self.note_digest]},
        ), mock.patch.dict(
            "kilix_license.generate.ADVISORY_NOTE_AUTHORED_PIN",
            {digest: ADVISORY_NOTE_AUTHORED_PIN[self.note_digest]},
        ):
            with self.assertRaises(ValueError) as caught:
                generate_records(self.payload, pin=self.pin, texts_dir=texts)
        self.assertIn("ADVISORY_TEXT_SOURCES declares", str(caught.exception))

    def test_the_elided_48khz_pin_resolves_in_the_pinned_source(self) -> None:
        # LIC5-VERIFY F7: the displayed statement shows `47a15ffb…` and the full
        # 48 kHz model.safetensors digest is pinned nowhere in this repository,
        # so a consumer checking E2 against it cannot. It is on line 75 of the
        # source the note already quotes, which is now pinned here: the elision
        # resolves to exactly one full digest in that file.
        entry = self.entries[self.ENCODEC_IDS[0]]
        shown = entry["attribution"][0]
        self.assertEqual(shown["quote_id"], "encodec-e1-e2-pins")
        source = ADVISORY_TEXT_SOURCES[self.note_digest][0]
        data = (self.SOURCES / source.sha256).read_text(encoding="utf-8")

        # E1 is elided at both ends and is pinned in determinations.json.
        e1 = re.search(r"`([0-9a-f]{8})…([0-9a-f]{4})`", shown["text"])
        self.assertIsNotNone(e1, shown["text"])
        pinned = [
            item["sha256"]
            for item in entry["upstream"]["files"]
            if item["sha256"].startswith(e1.group(1))
            and item["sha256"].endswith(e1.group(2))
        ]
        self.assertEqual(len(pinned), 1, pinned)

        # E2 is elided at one end and was pinned nowhere in this repository.
        e2 = re.search(r"`([0-9a-f]{8})…`", shown["text"])
        self.assertIsNotNone(e2, shown["text"])
        full = sorted(set(re.findall(rf"\b{e2.group(1)}[0-9a-f]{{56}}\b", data)))
        self.assertEqual(len(full), 1, full)
        self.assertIn(
            f"encodec_48khz model.safetensors 76291152 lfs_sha256 {full[0]}", data
        )
        # LIC5-FIX-VERIFY F5: when this fires it is good news, and without a
        # msg= it fires by inlining 50 KB of determinations.json into the
        # failure. Say what to do instead. (unittest prints msg= INSTEAD of
        # the standard explanation, which is the point: the seat gets an
        # instruction, not a wall of JSON.)
        self.assertNotIn(
            full[0],
            self.data.decode("utf-8"),
            f"the 48 kHz model.safetensors digest {full[0]} is now pinned in "
            "determinations.json. That is the outcome this test exists to "
            "force: move the displayed statement's pin there (it is an owner "
            "quote, so un-eliding it is an owner/determinations change), then "
            "delete this assertion and the fixture pin it stands in for. "
            "LIC5-VERIFY F7, carried by LIC5-FIX-IMPL section 12 item 1.",
        )

    def test_the_note_is_outside_the_record_digest(self) -> None:
        # OD-AI/OD-AQ: an advisory is context. Replacing it moves no record
        # digest, so no receipt's coverage changes and no consumer re-pins.
        pinned = {}
        for line in (ROOT / "tests" / "data" / "record-digests-fbdfb546.txt").read_text(
            encoding="utf-8"
        ).splitlines():
            digest, record_id = line.split("  ", 1)
            pinned[record_id] = digest
        for record_id in self.ENCODEC_IDS:
            record = self.by_id[record_id]
            self.assertEqual(record.digest, pinned[record_id])
            planted = replace(
                record,
                advisories=(
                    replace(record.advisories[0], text_sha256="0" * 64),
                ),
            )
            self.assertEqual(planted.digest, record.digest)

    def test_a_missing_or_altered_note_text_is_refused(self) -> None:
        scratch = Path(tempfile.mkdtemp(prefix="kilix-license-lic5-note-"))
        dest = scratch / "data"
        shutil.copytree(DATA, dest)
        texts = dest / "texts"
        note = texts / self.note_digest
        altered = note.read_bytes() + b"tampered\n"
        note.write_bytes(altered)
        with self.assertRaises(TextDigestMismatch) as caught:
            generate_records(self.payload, pin=self.pin, texts_dir=texts)
        self.assertIn(self.note_digest, str(caught.exception))
        note.unlink()
        with self.assertRaises(FileNotFoundError) as missing:
            generate_records(self.payload, pin=self.pin, texts_dir=texts)
        self.assertIn(self.note_digest, str(missing.exception))

    def test_check_advisory_texts_refuses_a_stale_or_malformed_table(self) -> None:
        check_advisory_texts(self.payload)
        stale = dict(ADVISORY_TEXTS, **{"encodec-licence-history-note-2026": "a" * 64})
        with self.assertRaises(ValueError) as caught:
            check_advisory_texts(self.payload, stale)
        self.assertIn("no determinations quote", str(caught.exception))
        self.assertIn("encodec-licence-history-note-2026", str(caught.exception))
        malformed = dict(ADVISORY_TEXTS, **{self.ADVISORY_ID: "not-a-sha256"})
        with self.assertRaises(ValueError):
            check_advisory_texts(self.payload, malformed)

    def test_a_renamed_advisory_quote_must_be_remapped(self) -> None:
        planted = json.loads(self.data.decode("utf-8"))
        renamed = "encodec-licence-history-note-2026"
        for entry_id in self.ENCODEC_IDS:
            entry = next(e for e in planted["entries"] if e["entry_id"] == entry_id)
            entry["advisories"][0]["quote_id"] = renamed
        # Left unmapped, the rename is refused rather than silently restoring
        # the determinations quote to the screen.
        with self.assertRaises(ValueError) as caught:
            generate_records(planted, pin=self.pin, texts_dir=self.texts_dir)
        self.assertIn(self.ADVISORY_ID, str(caught.exception))
        table = {renamed: self.note_digest}
        with mock.patch.dict(
            "kilix_license.generate.ADVISORY_TEXTS", table, clear=True
        ):
            generated = {
                r.id: r
                for r in generate_records(
                    planted, pin=self.pin, texts_dir=self.texts_dir
                )
            }
        for record_id in self.ENCODEC_IDS:
            advisory = generated[record_id].advisories[0]
            self.assertEqual(advisory.id, renamed)
            self.assertEqual(advisory.text_sha256, self.note_digest)

    def test_an_advisory_with_no_replacement_stays_the_determinations_quote(self) -> None:
        # Control: every other advisory and note is still the quoted bytes.
        replaced = set(ADVISORY_TEXTS)
        self.assertEqual(replaced, {self.ADVISORY_ID})
        checked = 0
        for entry_id, entry in self.entries.items():
            quotes = list(entry.get("advisories") or []) + list(entry.get("notes") or [])
            for quote in quotes:
                if quote["quote_id"] in replaced:
                    continue
                record = self.by_id[entry_id]
                advisory = next(
                    a for a in record.advisories if a.id == quote["quote_id"]
                )
                self.assertEqual(advisory.text_sha256, quote["text_sha256"])
                stored = (self.texts_dir / advisory.text_sha256).read_bytes()
                self.assertEqual(stored, quote["text"].encode("utf-8"))
                checked += 1
        self.assertGreater(checked, 0)
