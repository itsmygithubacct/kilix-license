"""SR-4: "changed since your last acceptance" is part of the kilix-license screen.

C2E-VERIFY F1 (junk receipts never fatal), F2 (identity keyed by the text,
across sibling records and binding renames) and F3 (in kilix-license, so every
render_screen consumer shows it). The marker never grants coverage.
"""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from kilix_license.agreement import capture_agreement, typed_agreement_line
from kilix_license.catalog import load_determined_records, load_determined_texts
from kilix_license.changed import CHANGED_HEADER, changed_texts, scan_receipts
from kilix_license.coverage import AssetRef, covers, require
from kilix_license.digest import canonical_json
from kilix_license.errors import AgreementRequired, CoverageRefused
from kilix_license.receipts import receipt_from_agreement
from kilix_license.records import (
    BindingCondition,
    Component,
    LicenseRecord,
    RecordIndex,
)
from kilix_license.screen import render_screen
from kilix_license.texts import TextStore

from fake_store import FakeStore
from fixtures import FIXTURE_CATALOGUE, FIXTURE_MANIFEST, FIXTURE_RELEASE, build_fixtures

ROOT = Path(__file__).resolve().parents[1]
LEGACY_RECEIPTS = ROOT / "tests" / "data" / "receipts-fbdfb546"
HEADER = (CHANGED_HEADER + "\n").encode("utf-8")
POLICY_V1 = b"Example usage policy. Last revised 1 August.\nDo not do harmful things.\n"
POLICY_V2 = b"Example usage policy. Last revised 2 August.\nDo not do harmful things.\n"
TEXT_ID = "example.org/legal/usage-policy"


def _accept(record: LicenseRecord, store, *, legacy: bool = False, manifest: str = FIXTURE_MANIFEST):
    receipt = receipt_from_agreement(
        record,
        capture_agreement(record, typed_agreement_line(record)),
        manifest_digest=manifest,
        release_digest=FIXTURE_RELEASE,
        catalogue_digest=FIXTURE_CATALOGUE,
    )
    if legacy:
        # The receipt/v1 shape fbdfb546 wrote: no LIC4 context keys.
        receipt = replace(
            receipt,
            binding_text_ids=None,
            component_exception_digests=None,
            statement_digests=None,
        )
    store.write(receipt)
    return receipt


def _listing(root: Path) -> list[tuple[str, bytes | None]]:
    return [
        (p.name, p.read_bytes() if p.is_file() else None)
        for p in sorted(root.iterdir())
        if p.name != ".store.lock"
    ]


class ChangedTextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="kilix-license-changed-"))
        self.texts = TextStore(self.root / "texts")
        self.store = FakeStore(self.root / "receipts")
        self.licence = self.texts.put(b"Apache-2.0 fixture licence text.\n", label="licence")
        self.v1 = self.texts.put(POLICY_V1, label="policy-v1")
        self.v2 = self.texts.put(POLICY_V2, label="policy-v2")

    def _record(self, record_id: str, binding_id: str, digest: str, text_id: str | None = TEXT_ID, **extra):
        return LicenseRecord(
            id=record_id,
            licensor="Example Labs",
            text_sha256=extra.pop("licence", self.licence),
            binding_conditions=(BindingCondition(binding_id, digest, True, text_id=text_id),),
            decision_class="affirmative",
            **extra,
        )

    def _siblings(self):
        ternary = self._record("image:ternary", "usage-policy", self.v1)
        binary_v2 = self._record("image:binary", "usage-policy-binary", self.v2)
        return ternary, binary_v2

    def _assert_marked(self, screen: bytes, section: str, shown: bytes, accepted: str, under: str) -> None:
        head = f"=== {section} ===\n".encode("utf-8")
        start = screen.find(head)
        self.assertGreaterEqual(start, 0)
        self.assertEqual(screen[start + len(head): start + len(head) + len(shown)], shown)
        marker = screen.rfind(HEADER, 0, start)
        self.assertGreaterEqual(marker, 0)
        block = screen[marker:start].decode("utf-8")
        self.assertIn(f"changed: {section}\n", block)
        self.assertIn(f"accepted sha256: {accepted}\n", block)
        self.assertIn(f"accepted under: {under}\n", block)
        self.assertEqual(block.count(CHANGED_HEADER), 1)

    def test_marker_is_shown_across_sibling_records(self) -> None:
        ternary, binary_v2 = self._siblings()
        _accept(ternary, self.store)
        changed = changed_texts(binary_v2, self.store)
        self.assertEqual(list(changed), ["binding:usage-policy-binary"])
        item = changed["binding:usage-policy-binary"]
        self.assertEqual(item.identity, f"text:{TEXT_ID}")
        self.assertEqual(item.accepted_sha256, (self.v1,))
        self.assertEqual(item.shown_sha256, self.v2)
        self.assertEqual(item.accepted_under, ("image:ternary",))
        screen = render_screen(binary_v2, self.texts, receipts=self.store)
        self._assert_marked(screen, "binding:usage-policy-binary", POLICY_V2, self.v1, "image:ternary")
        self.assertEqual(screen.count(HEADER), 1)

    def test_marker_across_siblings_from_a_receipt_written_before_lic4(self) -> None:
        ternary, binary_v2 = self._siblings()
        legacy = _accept(ternary, self.store, legacy=True)
        self.assertNotIn(b"binding_text_ids", legacy.to_bytes())
        # That receipt names no identity; the record its licence id names today does.
        ternary_v2 = self._record("image:ternary", "usage-policy", self.v2)
        index = RecordIndex((ternary_v2, binary_v2))
        screen = render_screen(binary_v2, self.texts, receipts=self.store, records=index)
        self._assert_marked(screen, "binding:usage-policy-binary", POLICY_V2, self.v1, "image:ternary")
        # Without the index nothing names that receipt's identity: the full text
        # and a typed acceptance are still required, only the marker is absent.
        self.assertEqual(changed_texts(binary_v2, self.store), {})

    def test_marker_is_shown_across_a_binding_rename(self) -> None:
        before = self._record("image:ternary", "usage-policy", self.v1)
        _accept(before, self.store)
        renamed = self._record("image:ternary", "usage-policy-2026-10", self.v2)
        screen = render_screen(renamed, self.texts, receipts=self.store)
        self._assert_marked(screen, "binding:usage-policy-2026-10", POLICY_V2, self.v1, "image:ternary")
        with self.assertRaises(CoverageRefused):
            require(
                AssetRef("image", renamed.digest, FIXTURE_MANIFEST),
                records=RecordIndex((renamed,)),
                store=self.store,
            )

    def test_no_marker_when_the_digest_is_unchanged(self) -> None:
        ternary = self._record("image:ternary", "usage-policy", self.v1)
        binary = self._record("image:binary", "usage-policy-binary", self.v1)
        _accept(ternary, self.store)
        self.assertEqual(changed_texts(binary, self.store), {})
        screen = render_screen(binary, self.texts, receipts=self.store)
        self.assertNotIn(HEADER, screen)
        self.assertIn(b"=== binding:usage-policy-binary ===\n" + POLICY_V1, screen)
        # Accepting the same text for a sibling does not cover this record.
        with self.assertRaises(CoverageRefused) as refused:
            require(
                AssetRef("binary", binary.digest, FIXTURE_MANIFEST),
                records=RecordIndex((ternary, binary)),
                store=self.store,
            )
        self.assertEqual(refused.exception.field, "receipt")

    def test_no_marker_without_an_earlier_acceptance(self) -> None:
        _ternary, binary_v2 = self._siblings()
        self.assertEqual(changed_texts(binary_v2, self.store), {})
        self.assertNotIn(HEADER, render_screen(binary_v2, self.texts, receipts=self.store))

    def test_junk_and_future_schema_receipt_files_are_skipped(self) -> None:
        ternary, binary_v2 = self._siblings()
        valid = _accept(ternary, self.store)
        good = valid.to_jsonable()
        root = self.store.root
        planted = {
            "junk-not-utf8.json": b"\xff\xfe\x00\x81junk",
            "junk-not-json.json": b"{not json",
            "junk-array.json": b"[]",
            "junk-empty.json": b"",
            "future-schema.json": canonical_json(dict(good, schema="kilix.license.receipt/v2")),
            "r3-shape.json": canonical_json(dict(good, catalogue_digest=good["context"]["catalogue_digest"])),
            "truncated.json": valid.to_bytes()[:200],
            "unhashable-decision.json": canonical_json(dict(good, decision=[])),
            "deep.json": b"[" * 200000,
            "huge.json": b" " * ((1 << 20) + 1) + b"{}",
        }
        for name, data in planted.items():
            (root / name).write_bytes(data)
        (root / "a-directory.json").mkdir()
        os.symlink(root / "missing-target", root / "dangling.json")
        (root / ".hidden.json").write_bytes(b"{not json")
        # FIFOs, devices and races: ScanHazardTests, in a child with a timeout.
        expected = set(planted) | {"a-directory.json", "dangling.json"}
        if os.geteuid() != 0:
            (root / "unreadable.json").write_bytes(valid.to_bytes())
            os.chmod(root / "unreadable.json", 0)
            expected.add("unreadable.json")
        scan = scan_receipts(self.store)
        self.assertEqual(sorted(scan.skipped), sorted(expected))
        self.assertEqual([r.licence_id for r in scan.receipts], ["image:ternary"])
        # (b) the valid earlier receipt beside the junk still marks the sibling.
        screen = render_screen(binary_v2, self.texts, receipts=self.store)
        self._assert_marked(screen, "binding:usage-policy-binary", POLICY_V2, self.v1, "image:ternary")
        # (a) an unrelated record still renders, and coverage is decided as before.
        fx = build_fixtures(self.root / "fx")
        render_screen(fx.kristin, fx.texts, receipts=self.store)
        with self.assertRaises(CoverageRefused) as refused:
            require(
                AssetRef("kristin", fx.kristin.digest, FIXTURE_MANIFEST),
                records=fx.index,
                store=self.store,
            )
        self.assertEqual(refused.exception.field, "receipt")

    def test_marker_never_grants_coverage(self) -> None:
        ternary, binary_v2 = self._siblings()
        sibling_receipt = _accept(ternary, self.store)
        index = RecordIndex((ternary, binary_v2))
        before = _listing(self.store.root)
        changed = changed_texts(binary_v2, self.store, records=index)
        screen = render_screen(binary_v2, self.texts, receipts=self.store, records=index)
        self.assertIn("binding:usage-policy-binary", changed)
        self.assertIn(HEADER, screen)
        self.assertEqual(_listing(self.store.root), before)  # presentation only: nothing written
        asset = AssetRef("binary", binary_v2.digest, FIXTURE_MANIFEST)
        with self.assertRaises(CoverageRefused):
            require(asset, records=index, store=self.store)
        with self.assertRaises(CoverageRefused):
            covers(binary_v2, sibling_receipt, manifest_digest=FIXTURE_MANIFEST)
        # Nothing is silently accepted: the typed line is still required.
        with self.assertRaises(AgreementRequired):
            capture_agreement(binary_v2)
        with self.assertRaises(AgreementRequired):
            capture_agreement(binary_v2, typed_agreement_line(ternary))
        _accept(binary_v2, self.store)
        self.assertEqual(require(asset, records=index, store=self.store).licence_id, "image:binary")
        self.assertEqual(changed_texts(binary_v2, self.store, records=index), {})

    def test_a_covered_record_never_shows_a_marker(self) -> None:
        ternary, binary_v2 = self._siblings()
        _accept(ternary, self.store)
        _accept(binary_v2, self.store, legacy=True)
        self.assertEqual(changed_texts(binary_v2, self.store), {})
        exception_v1 = self.texts.put(b"Component exception v1.\n", label="exc-v1")
        exception_v2 = self.texts.put(b"Component exception v2.\n", label="exc-v2")
        with_v1 = self._record(
            "model:a", "usage-policy", self.v2,
            components=(Component("tokenizer", "exception", exception_v1),),
        )
        with_v2 = replace(with_v1, components=(Component("tokenizer", "exception", exception_v2),))
        _accept(with_v1, self.store)
        _accept(with_v2, self.store, legacy=True)  # covers with_v2; names no exception digest
        self.assertEqual(changed_texts(with_v2, self.store), {})

    def test_a_changed_licence_text_is_marked(self) -> None:
        l2 = self.texts.put(b"Apache-2.0 fixture licence text, revised.\n", label="licence-v2")
        record = self._record("model:a", "usage-policy", self.v1)
        _accept(record, self.store)
        revised = replace(record, text_sha256=l2)
        changed = changed_texts(revised, self.store)
        self.assertEqual(list(changed), ["licence:model:a"])
        self.assertEqual(changed["licence:model:a"].accepted_sha256, (self.licence,))

    def test_a_changed_component_exception_is_marked(self) -> None:
        exception_v1 = self.texts.put(b"Component exception v1.\n", label="exc-v1")
        exception_v2 = self.texts.put(b"Component exception v2.\n", label="exc-v2")
        record = self._record(
            "model:a", "usage-policy", self.v1,
            components=(Component("tokenizer", "exception", exception_v1),),
        )
        _accept(record, self.store)
        revised = replace(record, components=(Component("tokenizer", "exception", exception_v2),))
        screen = render_screen(revised, self.texts, receipts=self.store)
        self._assert_marked(screen, "component:tokenizer", b"Component exception v2.\n", exception_v1, "model:a")

    def test_record_decisions_are_not_acceptances(self) -> None:
        fx = build_fixtures(self.root / "fx")
        receipt = receipt_from_agreement(
            fx.kristin,
            capture_agreement(fx.kristin),
            manifest_digest=FIXTURE_MANIFEST,
            release_digest=FIXTURE_RELEASE,
            catalogue_digest=FIXTURE_CATALOGUE,
        )
        self.store.write(receipt)
        revised = replace(fx.kristin, text_sha256=fx.texts.put(b"Public domain, revised.\n"))
        self.assertEqual(changed_texts(revised, self.store), {})

    def test_the_screen_cannot_be_rendered_without_the_receipt_store(self) -> None:
        ternary, _binary = self._siblings()
        with self.assertRaises(TypeError):
            render_screen(ternary, self.texts)  # the pre-LIC4 two-argument form
        with self.assertRaises(TypeError):
            render_screen(ternary, self.texts, receipts=None)
        with self.assertRaises(TypeError):
            changed_texts(ternary, self.root / "receipts")


# The scan runs in a child: 4 GiB address space, 60 s timeout. A regression
# that opens a device or blocks on a FIFO fails here instead of hanging the suite.
# os.open is spied, so "never opened" does not depend on the read bound (T1).
_SCAN_CHILD = r"""
import json, os, resource, sys
resource.setrlimit(resource.RLIMIT_AS, (4 << 30, 4 << 30))
from kilix_license import changed
from fake_store import FakeStore
root, race = sys.argv[1], sys.argv[2]
store = FakeStore(root)
opened, raced = [], []
real_open, real_stat = os.open, os.stat
def spy_open(path, flags, *args, **kwargs):
    opened.append(os.path.basename(os.fsdecode(path)))
    return real_open(path, flags, *args, **kwargs)
def racing_stat(path, *args, **kwargs):
    result = real_stat(path, *args, **kwargs)
    if race and os.path.basename(os.fsdecode(path)) == race and not raced:
        raced.append(race)  # T2: regular at the check, a FIFO at the open
        os.unlink(path)
        os.mkfifo(path)
    return result
os.open, os.stat = spy_open, racing_stat
try:
    scan = changed.scan_receipts(store)
finally:
    os.open, os.stat = real_open, real_stat
print(json.dumps({"receipts": [r.licence_id for r in scan.receipts],
                  "skipped": sorted(scan.skipped), "opened": sorted(opened), "raced": raced}))
"""


class ScanHazardTests(unittest.TestCase):
    """C2E-FIX2-VERIFY T1 and T2, and symlink targets that cannot be stat'ed."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="kilix-license-scan-hazard-"))
        self.store = FakeStore(self.root / "receipts")
        fx = build_fixtures(self.root / "fx")
        self.valid = _accept(fx.pocket, self.store)
        self.valid_name = self.store.path_for(self.valid.record_digest, self.valid.manifest_digest).name

    def _scan(self, race: str = "") -> dict:
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src"), str(ROOT / "tests" / "support")])
        proc = subprocess.run(
            [sys.executable, "-c", _SCAN_CHILD, str(self.store.root), race],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_character_device_symlinks_are_never_opened(self) -> None:
        links = {}
        for device in ("/dev/ptmx", "/dev/zero", "/dev/null", "/dev/tty", "/dev/random"):
            if os.path.exists(device):
                name = "device-" + os.path.basename(device) + ".json"
                os.symlink(device, self.store.root / name)
                links[name] = device
        self.assertIn("device-ptmx.json", links)
        result = self._scan()
        self.assertEqual(result["receipts"], [self.valid.licence_id])
        self.assertIn(self.valid_name, result["opened"])
        for name in links:
            with self.subTest(link=name):
                self.assertNotIn(name, result["opened"])
                self.assertIn(name, result["skipped"])

    def test_a_fifo_is_never_opened(self) -> None:
        os.mkfifo(self.store.root / "a-fifo.json")
        result = self._scan()
        self.assertNotIn("a-fifo.json", result["opened"])
        self.assertEqual(result["skipped"], ["a-fifo.json"])
        self.assertEqual(result["receipts"], [self.valid.licence_id])

    def test_a_fifo_swapped_in_after_the_check_does_not_block(self) -> None:
        shutil.copy2(self.store.root / self.valid_name, self.store.root / "raced.json")
        result = self._scan(race="raced.json")
        self.assertEqual(result["raced"], ["raced.json"])
        self.assertIn("raced.json", result["opened"])  # the race was really run
        self.assertEqual(result["skipped"], ["raced.json"])
        self.assertEqual(result["receipts"], [self.valid.licence_id])

    def test_an_oversized_sparse_entry_is_skipped_unread(self) -> None:
        # 8 GiB of holes, and a link to it; the child may map at most 4 GiB.
        sparse = self.root / "sparse.bin"
        with open(sparse, "wb") as handle:
            handle.truncate(8 << 30)
        os.link(sparse, self.store.root / "sparse.json")
        os.symlink(sparse, self.store.root / "sparse-link.json")
        result = self._scan()
        self.assertEqual(result["skipped"], ["sparse-link.json", "sparse.json"])
        self.assertEqual(result["receipts"], [self.valid.licence_id])

    def test_unresolvable_symlink_targets_are_skipped(self) -> None:
        root = self.store.root
        os.symlink(root / "loop-b.json", root / "loop-a.json")
        os.symlink(root / "loop-a.json", root / "loop-b.json")
        os.symlink("x" * 300 + ".json", root / "long-name.json")
        # A component over NAME_MAX (stat: ENAMETOOLONG), and a 4004-byte target.
        os.symlink("/".join(["y" * 199] * 20) + ".json", root / "long-path.json")
        expected = {"loop-a.json", "loop-b.json", "long-name.json", "long-path.json"}
        locked = self.root / "locked"
        locked.mkdir()
        shutil.copy2(root / self.valid_name, locked / "receipt.json")
        os.symlink(locked / "receipt.json", root / "unsearchable.json")
        os.chmod(locked, 0)
        try:
            if os.geteuid() != 0:
                expected.add("unsearchable.json")
            result = self._scan()
        finally:
            os.chmod(locked, 0o700)
        self.assertEqual(sorted(set(result["skipped"]) & (expected | {"unsearchable.json"})), sorted(expected))
        for name in expected:
            self.assertNotIn(name, result["opened"])
        self.assertIn(self.valid.licence_id, result["receipts"])


class RealRecordChangedTextTests(unittest.TestCase):
    """The packaged Bonsai Image records: one BFL policy under two binding ids (F2)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.index = load_determined_records()
        cls.ternary = cls.index.by_id("bonsai-image-4b:ternary-gemlite")
        cls.binary = cls.index.by_id("bonsai-image-4b:binary-gemlite")

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="kilix-license-real-changed-"))
        self.texts = load_determined_texts(self.root / "texts")
        self.store = FakeStore(self.root / "receipts")
        policy = self.binary.binding_conditions[0]
        original = self.texts.get(policy.text_sha256)
        i = len(original) // 2
        self.revised_bytes = original[:i] + (b"X" if original[i:i + 1] != b"X" else b"Y") + original[i + 1:]
        revised = self.texts.put(self.revised_bytes, label="bfl-policy-planted")
        self.binary_v2 = replace(self.binary, binding_conditions=(replace(policy, text_sha256=revised),))
        self.accepted = policy.text_sha256

    def test_planted_policy_change_on_binary_is_marked_after_accepting_ternary(self) -> None:
        _accept(self.ternary, self.store)
        screen = render_screen(self.binary_v2, self.texts, receipts=self.store, records=self.index)
        head = b"=== binding:bfl-usage-policy-binary ===\n"
        start = screen.find(head)
        self.assertEqual(screen[start + len(head): start + len(head) + len(self.revised_bytes)], self.revised_bytes)
        block = screen[screen.rfind(HEADER, 0, start): start].decode("utf-8")
        self.assertIn("text identity: text:bfl.ai/legal/usage-policy\n", block)
        self.assertIn(f"accepted sha256: {self.accepted}\n", block)
        self.assertIn("accepted under: bonsai-image-4b:ternary-gemlite\n", block)

    def test_the_fbdfb546_ternary_receipt_marks_the_revised_binary_policy(self) -> None:
        name = f"{self.ternary.digest}-"
        legacy = [p for p in LEGACY_RECEIPTS.iterdir() if p.name.startswith(name)]
        self.assertEqual(len(legacy), 1)
        shutil.copy2(legacy[0], self.store.root / legacy[0].name)
        changed = changed_texts(self.binary_v2, self.store, records=self.index)
        self.assertEqual(list(changed), ["binding:bfl-usage-policy-binary"])
        self.assertEqual(changed["binding:bfl-usage-policy-binary"].accepted_sha256, (self.accepted,))
        # Unchanged binary: no marker, and the ternary receipt does not cover it.
        self.assertEqual(changed_texts(self.binary, self.store, records=self.index), {})
        with self.assertRaises(CoverageRefused):
            require(
                AssetRef("binary", self.binary.digest, FIXTURE_MANIFEST),
                records=self.index,
                store=self.store,
            )


if __name__ == "__main__":
    unittest.main()
