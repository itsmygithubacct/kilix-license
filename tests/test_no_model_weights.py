import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from weight_scan import catalog_matches_generator, scan_tree, sha256_file

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "tests" / "data" / "catalog_digests.txt"


def _git_init(tree: Path) -> None:
    env = dict(os.environ)
    env["GIT_AUTHOR_NAME"] = "itsmygithubacct"
    env["GIT_AUTHOR_EMAIL"] = "itsmygithubacct@users.noreply.github.com"
    env["GIT_COMMITTER_NAME"] = "itsmygithubacct"
    env["GIT_COMMITTER_EMAIL"] = "itsmygithubacct@users.noreply.github.com"
    subprocess.run(["git", "init", "-q", str(tree)], check=True, env=env)
    subprocess.run(["git", "-C", str(tree), "add", "-A"], check=True, env=env)
    subprocess.run(
        [
            "git",
            "-C",
            str(tree),
            "-c",
            "user.name=itsmygithubacct",
            "-c",
            "user.email=itsmygithubacct@users.noreply.github.com",
            "commit",
            "-q",
            "-m",
            "fixture",
        ],
        check=True,
        env=env,
    )


class WeightGuardTests(unittest.TestCase):
    def test_repository_tracked_tree_has_no_weights(self) -> None:
        findings = scan_tree(ROOT, CATALOG)
        self.assertEqual([], findings)

    def test_planted_weight_suffix_fails(self) -> None:
        tree = Path(tempfile.mkdtemp(prefix="kilix-license-weight-suffix-"))
        (tree / "planted.gguf").write_bytes(b"not a real model")
        _git_init(tree)
        catalog = tree / "catalog_digests.txt"
        catalog.write_text(CATALOG.read_text(encoding="utf-8"), encoding="utf-8")
        findings = scan_tree(tree, catalog)
        self.assertTrue(any(item.reason.startswith("weight-suffix:") for item in findings))

    def test_planted_gguf_magic_fails(self) -> None:
        tree = Path(tempfile.mkdtemp(prefix="kilix-license-weight-magic-"))
        (tree / "planted.dat").write_bytes(b"GGUF" + b"\x00" * 16)
        _git_init(tree)
        catalog = tree / "catalog_digests.txt"
        catalog.write_text(CATALOG.read_text(encoding="utf-8"), encoding="utf-8")
        findings = scan_tree(tree, catalog)
        self.assertTrue(any(item.reason == "magic:GGUF" for item in findings))

    def test_planted_catalog_digest_blob_fails(self) -> None:
        tree = Path(tempfile.mkdtemp(prefix="kilix-license-weight-digest-"))
        blob = tree / "planted.bin"
        blob.write_bytes(b"catalog-digest-planted-blob")
        digest = sha256_file(blob)
        catalog = tree / "catalog_digests.txt"
        catalog.write_text(
            CATALOG.read_text(encoding="utf-8") + digest + "\n",
            encoding="utf-8",
        )
        _git_init(tree)
        findings = scan_tree(tree, catalog)
        self.assertTrue(
            any(item.reason == f"catalog-digest:{digest}" for item in findings)
        )

    def test_regeneration_matches_committed_list(self) -> None:
        self.assertTrue(catalog_matches_generator(ROOT, CATALOG))

    def test_hand_edited_digest_list_is_refused(self) -> None:
        scratch = Path(tempfile.mkdtemp(prefix="kilix-license-catalog-edit-"))
        planted = scratch / "catalog_digests.txt"
        planted.write_text(
            CATALOG.read_text(encoding="utf-8") + ("a" * 64) + "\n",
            encoding="utf-8",
        )
        self.assertFalse(catalog_matches_generator(ROOT, planted))
