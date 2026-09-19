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
from kilix_license.changed import CHANGED_HEADER, MAX_RECEIPT_BYTES, changed_texts, scan_receipts
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
# os.read is spied per opened name, so "never read" is measured, not inferred
# from the outcome (LIC4-VERIFY LIC4-1, LIC4-2). The race swaps the entry after
# its Nth stat for a FIFO or a symlink (T2). "ctty" makes the child a session
# leader with no controlling terminal and swaps in a pty slave (LIC4-6).
_SPY_PRELUDE = r"""
import json, os, resource, sys
resource.setrlimit(resource.RLIMIT_AS, (4 << 30, 4 << 30))
opened, raced, flags, nread, per_open, fds, stats = [], [], {}, {}, {}, {}, {}
real_open, real_stat, real_read = os.open, os.stat, os.read
RACE = {"name": "", "swap": "fifo", "after": 1}
def spy_open(path, fl, *args, **kwargs):
    name = os.path.basename(os.fsdecode(path))
    opened.append(name)
    flags.setdefault(name, []).append(fl)
    fd = real_open(path, fl, *args, **kwargs)
    per_open.setdefault(name, []).append(0)
    fds[fd] = (name, len(per_open[name]) - 1)
    return fd
def spy_read(fd, count):
    data = real_read(fd, count)
    if fd in fds:
        name, index = fds[fd]
        nread[name] = nread.get(name, 0) + len(data)
        per_open[name][index] += len(data)
    return data
def racing_stat(path, *args, **kwargs):
    result = real_stat(path, *args, **kwargs)
    name = os.path.basename(os.fsdecode(path))
    if RACE["name"] and name == RACE["name"] and not raced:
        stats[name] = stats.get(name, 0) + 1
        if stats[name] == RACE["after"]:
            raced.append(name)  # regular at the check, something else at the open
            os.unlink(path)
            if RACE["swap"] == "fifo":
                os.mkfifo(path)
            else:
                os.symlink(RACE["swap"], path)
    return result
def spies_on():
    os.open, os.stat, os.read = spy_open, racing_stat, spy_read
def spies_off():
    os.open, os.stat, os.read = real_open, real_stat, real_read
def has_ctty():
    try:
        fd = real_open("/dev/tty", os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
    except OSError:
        return False
    os.close(fd)
    return True
def spy_report(**extra):
    extra.update({"opened": sorted(opened), "raced": raced, "read": nread,
                  "read_per_open": per_open, "flags": {k: v for k, v in flags.items()}})
    print(json.dumps(extra))
"""
_SCAN_CHILD = _SPY_PRELUDE + r"""
from kilix_license import changed
from fake_store import FakeStore
root, RACE["name"] = sys.argv[1], sys.argv[2]
RACE["swap"] = sys.argv[3] if len(sys.argv) > 3 else "fifo"
mode = sys.argv[4] if len(sys.argv) > 4 else ""
store = FakeStore(root)
ctty_before = None
if mode.startswith("ctty"):
    os.setsid()
    master, slave = os.openpty()
    RACE["swap"] = os.ttyname(slave)
    os.close(slave)
    ctty_before = has_ctty()
    if mode == "ctty-control":
        # The positive control: this environment lets a tty opened without
        # O_NOCTTY become the controlling terminal of this session leader.
        os.close(os.open(RACE["swap"], os.O_RDONLY | os.O_NONBLOCK))
        spy_report(ctty_before=ctty_before, ctty_after=has_ctty())
        sys.exit(0)
spies_on()
try:
    scan = changed.scan_receipts(store)
finally:
    spies_off()
spy_report(receipts=[r.licence_id for r in scan.receipts], skipped=sorted(scan.skipped),
           ctty_before=ctty_before, ctty_after=has_ctty() if mode else None)
"""


class ScanHazardTests(unittest.TestCase):
    """C2E-FIX2-VERIFY T1 and T2, and symlink targets that cannot be stat'ed."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="kilix-license-scan-hazard-"))
        self.store = FakeStore(self.root / "receipts")
        fx = build_fixtures(self.root / "fx")
        self.valid = _accept(fx.pocket, self.store)
        self.valid_name = self.store.path_for(self.valid.record_digest, self.valid.manifest_digest).name

    def _scan(self, race: str = "", swap: str = "fifo", mode: str = "") -> dict:
        return _run_child(_SCAN_CHILD, str(self.store.root), race, swap, mode)

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

    def test_a_device_swapped_in_after_the_check_is_never_read(self) -> None:
        # LIC4-VERIFY LIC4-1 (mutant V05): without the post-open fstat S_ISREG
        # check the scan reads 1 MiB + 1 bytes from /dev/zero before skipping it.
        # The outcome alone ("skipped") cannot tell; the bytes read can.
        for swap in ("/dev/zero", "/dev/urandom", "fifo"):
            if swap != "fifo" and not os.path.exists(swap):
                continue
            with self.subTest(swap=swap):
                raced = self.store.root / "raced.json"
                shutil.copy2(self.store.root / self.valid_name, raced)
                try:
                    result = self._scan(race="raced.json", swap=swap)
                finally:
                    raced.unlink(missing_ok=True)
                self.assertEqual(result["raced"], ["raced.json"])
                self.assertIn("raced.json", result["opened"])  # the race was really run
                self.assertEqual(result["read"].get("raced.json", 0), 0)
                self.assertEqual(result["skipped"], ["raced.json"])
                self.assertEqual(result["receipts"], [self.valid.licence_id])
                self.assertGreater(result["read"][self.valid_name], 0)

    def test_the_scan_opens_with_o_nonblock_and_o_noctty(self) -> None:
        # LIC4-VERIFY LIC4-6: a terminal swapped in must not become a controlling terminal.
        result = self._scan()
        self.assertTrue(result["flags"])
        for name, used in result["flags"].items():
            for flags in used:
                with self.subTest(name=name):
                    self.assertTrue(flags & os.O_NONBLOCK)
                    self.assertTrue(flags & os.O_NOCTTY)
                    self.assertEqual(flags & os.O_ACCMODE, os.O_RDONLY)

    def test_a_terminal_swapped_in_never_becomes_the_controlling_terminal(self) -> None:
        # LIC4-VERIFY LIC4-6, behaviourally: the child is a session leader with no
        # controlling terminal, and the entry becomes a pty slave between stat and open.
        control = self._scan(mode="ctty-control")
        if control["ctty_before"] or not control["ctty_after"]:
            self.skipTest("this environment does not assign a controlling terminal on open")
        shutil.copy2(self.store.root / self.valid_name, self.store.root / "raced.json")
        result = self._scan(race="raced.json", mode="ctty")
        self.assertEqual(result["raced"], ["raced.json"])
        self.assertIn("raced.json", result["opened"])
        self.assertFalse(result["ctty_before"])
        self.assertFalse(result["ctty_after"])
        self.assertEqual(result["read"].get("raced.json", 0), 0)
        self.assertEqual(result["skipped"], ["raced.json"])

    def test_an_entry_whose_size_lies_is_read_boundedly_and_skipped(self) -> None:
        # LIC4-VERIFY LIC4-2 (mutant V06b): /proc/self/pagemap is a regular file of
        # st_size 0 with unbounded content, so only the read budget bounds it.
        # Without the budget the child raises MemoryError under its 4 GiB limit.
        target = "/proc/self/pagemap"
        try:
            os.stat(target)
        except OSError:
            self.skipTest(f"{target} is not available")
        os.symlink(target, self.store.root / "pagemap.json")
        result = self._scan()
        self.assertIn("pagemap.json", result["opened"])  # it is regular: it is read
        self.assertEqual(len(result["read_per_open"]["pagemap.json"]), 1)
        self.assertLessEqual(result["read"].get("pagemap.json", 0), MAX_RECEIPT_BYTES + 1)
        self.assertEqual(result["skipped"], ["pagemap.json"])
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


def _run_child(program: str, *args: str) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src"), str(ROOT / "tests" / "support")])
    proc = subprocess.run(
        [sys.executable, "-c", program, *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise AssertionError(f"child exited {proc.returncode}: {proc.stderr[-2000:]}")
    return json.loads(proc.stdout)


# require() reads through the same discipline as the scan (LIC4-VERIFY LIC4-7).
_REQUIRE_CHILD = _SPY_PRELUDE + r"""
from pathlib import Path
from kilix_license.coverage import AssetRef, require
from kilix_license.errors import CoverageRefused
from fake_store import FakeStore
from fixtures import FIXTURE_MANIFEST, build_fixtures
root, asked, RACE["name"], RACE["swap"] = sys.argv[1:5]
RACE["after"] = 1  # the reader's own stat is the check; the swap lands before its open
fx = build_fixtures(Path(root) / "fx-child")
store = FakeStore(Path(root) / "receipts")
outcome = {}
spies_on()
try:
    for label, manifest in (("asked", asked), ("own", FIXTURE_MANIFEST)):
        try:
            found = require(AssetRef("pocket", fx.pocket.digest, manifest), records=fx.index, store=store)
            outcome[label] = "COVERED " + found.licence_id
        except CoverageRefused as exc:
            outcome[label] = "REFUSED " + exc.field
finally:
    spies_off()
spy_report(outcome=outcome)
"""


class RequireHazardTests(unittest.TestCase):
    """LIC4-VERIFY LIC4-7: an entry named <record digest>-*.json never hangs require().

    A FIFO, a device, a directory or an entry whose size lies, at the exact
    receipt path or under another manifest, is not a receipt: require() fails
    closed with CoverageRefused, reads nothing from it (or at most the bound),
    and still covers with the valid receipt beside it.
    """

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="kilix-license-require-hazard-"))
        self.store = FakeStore(self.root / "receipts")
        self.fx = build_fixtures(self.root / "fx")
        self.valid = _accept(self.fx.pocket, self.store)
        self.valid_name = self.store.path_for(self.valid.record_digest, self.valid.manifest_digest).name
        self.asked = "a" * 64  # a manifest with no receipt
        self.exact = self.store.path_for(self.fx.pocket.digest, self.asked)
        self.other = self.store.path_for(self.fx.pocket.digest, "f" * 64)

    def _require(self, race: str = "", swap: str = "fifo") -> dict:
        return _run_child(_REQUIRE_CHILD, str(self.root), self.asked, race, swap)

    def _assert_fail_closed(self, result: dict, name: str, *, read_at_most: int = 0) -> None:
        self.assertEqual(result["outcome"]["asked"], "REFUSED manifest_digest")
        self.assertEqual(result["outcome"]["own"], "COVERED " + self.fx.pocket.id)
        # Each open of the hazard reads at most read_at_most bytes (lookup() and
        # for_record() may each open the exact path once).
        for count in result["read_per_open"].get(name, []):
            self.assertLessEqual(count, read_at_most)

    def test_a_non_regular_entry_is_never_opened_or_waited_on(self) -> None:
        planted = {
            "fifo": lambda path: os.mkfifo(path),
            "dev-zero": lambda path: os.symlink("/dev/zero", path),
            "dev-ptmx": lambda path: os.symlink("/dev/ptmx", path),
            "directory": lambda path: path.mkdir(),
        }
        for where in ("exact", "other"):
            for kind, plant in planted.items():
                with self.subTest(where=where, kind=kind):
                    path = getattr(self, where)
                    plant(path)
                    try:
                        result = self._require()
                    finally:
                        shutil.rmtree(path) if path.is_dir() and not path.is_symlink() else path.unlink()
                    self.assertNotIn(path.name, result["opened"])
                    self._assert_fail_closed(result, path.name)

    def test_without_another_receipt_the_refusal_is_receipt(self) -> None:
        self.store.root.joinpath(self.valid_name).unlink()
        os.mkfifo(self.other)
        result = self._require()
        self.assertEqual(result["outcome"]["asked"], "REFUSED receipt")
        self.assertEqual(result["outcome"]["own"], "REFUSED receipt")
        self.assertNotIn(self.other.name, result["opened"])

    def test_an_entry_whose_size_lies_is_read_boundedly(self) -> None:
        target = "/proc/self/pagemap"
        try:
            os.stat(target)
        except OSError:
            self.skipTest(f"{target} is not available")
        for where in ("exact", "other"):
            with self.subTest(where=where):
                path = getattr(self, where)
                os.symlink(target, path)
                try:
                    result = self._require()
                finally:
                    path.unlink()
                self.assertIn(path.name, result["opened"])  # it is regular: it is read
                self._assert_fail_closed(result, path.name, read_at_most=MAX_RECEIPT_BYTES + 1)

    def test_an_oversized_sparse_entry_is_not_read(self) -> None:
        sparse = self.root / "sparse.bin"
        with open(sparse, "wb") as handle:
            handle.truncate(8 << 30)
        for where in ("exact", "other"):
            with self.subTest(where=where):
                path = getattr(self, where)
                os.symlink(sparse, path)
                try:
                    result = self._require()
                finally:
                    path.unlink()
                self._assert_fail_closed(result, path.name)

    def test_an_exact_receipt_swapped_after_the_check_is_never_read(self) -> None:
        # A real covering receipt for the asked manifest is regular at the check
        # and a FIFO or device at the open: the descriptor fstat rejects it.
        covering = _accept(self.fx.pocket, self.store, manifest=self.asked)
        self.assertEqual(self.store.path_for(covering.record_digest, covering.manifest_digest), self.exact)
        for swap in ("fifo", "/dev/zero"):
            with self.subTest(swap=swap):
                if not self.exact.exists():
                    _accept(self.fx.pocket, self.store, manifest=self.asked)
                result = self._require(race=self.exact.name, swap=swap)
                self.exact.unlink()
                self.assertEqual(result["raced"], [self.exact.name])
                self.assertIn(self.exact.name, result["opened"])  # the race was really run
                self._assert_fail_closed(result, self.exact.name)


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
