import hashlib
from pathlib import Path
import re
import subprocess
import tomllib
import unittest

import kilix_license


ROOT = Path(__file__).resolve().parents[1]

RECOGNISED_DISPOSITIONS = {"LOCAL_ONLY", "PUBLISHED"}
RECOGNISED_AUTHORIZATIONS = {"AUTHORIZED", "UNRESOLVED"}


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


def configured_remotes() -> list[str] | None:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "remote"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return [line for line in result.stdout.splitlines() if line]


# OD-AV: the repository licence is MIT. LIC3-4: pinned byte for byte, and
# checked to be the SPDX MIT text (v3.29.0, the digest-named text in
# data/texts) apart from line wrapping and the filled-in copyright line.
LICENSE_SHA256 = "443acd34ba896c5ee92d9ebd200436eb96f2f1aa0815e16c12c42c8f1a5fd30f"
SPDX_MIT_TEXT = ROOT / "src" / "kilix_license" / "data" / "texts" / "b05785f9f18e6716bab63424b11454513b9943a222595b70411009202fc592b5"
LICENSE_COPYRIGHT = "Copyright (c) 2026 Kilix License contributors"
SPDX_COPYRIGHT_TEMPLATE = "Copyright (c) <year> <copyright holders>"


class RepositoryIdentityTests(unittest.TestCase):
    def test_licence_file_is_the_mit_text(self) -> None:
        data = (ROOT / "LICENSE").read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), LICENSE_SHA256)
        spdx = SPDX_MIT_TEXT.read_bytes()
        self.assertEqual(hashlib.sha256(spdx).hexdigest(), SPDX_MIT_TEXT.name)
        text = data.decode("utf-8")
        self.assertEqual(
            [line for line in text.splitlines() if line.startswith("Copyright")],
            [LICENSE_COPYRIGHT],
        )
        filled = text.replace(LICENSE_COPYRIGHT, SPDX_COPYRIGHT_TEMPLATE)
        self.assertEqual(filled.split(), spdx.decode("utf-8").split())

    def test_version_sources_agree(self) -> None:
        self.assertEqual(
            (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
            kilix_license.__version__,
        )
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(pyproject["project"]["version"], kilix_license.__version__)

    def test_required_identity_files_exist(self) -> None:
        tracked = tracked_files()
        if not tracked:
            self.skipTest("not a git checkout; tracked set unobservable")
        missing = sorted(path for path in tracked if not (ROOT / path).is_file())
        self.assertEqual([], missing, f"tracked files missing from disk: {missing}")

    def test_the_shipping_rule_is_written_where_a_reader_meets_it(self) -> None:
        # OD-BC. No flag in this repository can enforce "a receipt is never
        # shipped": it is a rule about what is built, and its only enforcement
        # is that somebody reads it. So it is pinned where a reader arrives -
        # README.md, in the section about receipts - and cannot be quietly
        # dropped while the code that motivates it stays.
        # Whitespace-normalised, so a rule that is still there but re-wrapped
        # does not read as a rule that was deleted.
        raw_readme = (ROOT / "README.md").read_text(encoding="utf-8")
        readme = " ".join(raw_readme.split())
        for required in (
            "never shipped, vendored or provisioned",
            "not an acceptable remedy for a gate that refuses",
            "acceptance at first use, or no weights",
            "distinct schema",
            "kilix.license.receipt/v1",
            # and the honest statement of what a receipt is worth
            "does not prove that a human accepted anything",
            "does not say which",
            "does not prove that the recorded time is the real time",
        ):
            with self.subTest(required=required):
                # msg= instead of the whole README in the failure.
                self.assertIn(
                    required, readme,
                    f"README.md no longer states {required!r}. OD-BC put this "
                    "rule where a reader meets it because nothing else can "
                    "enforce it; restore it rather than deleting this check.",
                )
        # OD-BC "record neither": no document may describe an identity field.
        for forbidden in ("captured_by_account", "captured_by_uid"):
            with self.subTest(forbidden=forbidden):
                for name, text in (
                    ("README.md", raw_readme),
                    ("CHANGELOG.md", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")),
                ):
                    self.assertNotIn(
                        forbidden, text,
                        f"{name} names {forbidden!r}; OD-BC records neither "
                        "identity field, so no document may imply one exists.",
                    )

    def test_publication_disposition_is_explicit(self) -> None:
        disposition_text = (ROOT / "PUBLICATION.md").read_text(encoding="utf-8")
        found = {
            name
            for name in RECOGNISED_DISPOSITIONS
            if re.search(rf"\*\*Disposition:\*\*\s*`{name}`", disposition_text)
        }
        self.assertEqual(
            1,
            len(found),
            f"expected exactly 1 recognised disposition, found {sorted(found)}",
        )
        disposition = found.pop()
        authorizations = {
            name
            for name in RECOGNISED_AUTHORIZATIONS
            if re.search(rf"\*\*Authorization:\*\*\s*`{name}`", disposition_text)
        }
        self.assertEqual(
            1,
            len(authorizations),
            "PUBLICATION.md must declare exactly 1 recognised Authorization "
            f"value, found {sorted(authorizations)}",
        )
        remotes = configured_remotes()
        if remotes is None:
            self.skipTest("repository state unobservable; consistency not checked")
        if disposition == "LOCAL_ONLY":
            extra = [name for name in remotes if name != "origin"]
            self.assertEqual(
                [],
                extra,
                "PUBLICATION.md declares LOCAL_ONLY but the repository has "
                f"non-origin remotes {extra}; git clone always creates origin "
                "and that is not a publication remote",
            )
        else:
            self.assertNotEqual(
                [],
                remotes,
                "PUBLICATION.md declares PUBLISHED but no remote is configured",
            )

    def test_uv_and_python_pins(self) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(pyproject["tool"]["uv"]["required-version"], "==0.12.5")
        self.assertEqual(pyproject["project"]["requires-python"], ">=3.12.8,<3.13")
        self.assertEqual(
            (ROOT / ".python-version").read_text(encoding="utf-8").strip(),
            "3.12.8",
        )

    def test_runtime_dependency_closure_is_stdlib_only(self) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(pyproject["project"]["dependencies"], [])
        lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
        package_names = re.findall(r"(?m)^name = \"([^\"]+)\"", lock)
        self.assertEqual(package_names, ["kilix-license"])

    def test_changelog_has_unreleased_entry(self) -> None:
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## Unreleased", text)
        unreleased, _, rest = text.partition("## Unreleased")
        next_heading = rest.find("\n## ")
        section = rest if next_heading < 0 else rest[:next_heading]
        self.assertRegex(section, r"(?m)^- ")

    def test_no_git_remote(self) -> None:
        # Follow PUBLICATION.md. LOCAL_ONLY ⇒ empty remotes on the
        # publication subject. `git clone` always creates origin; that is
        # not a failure of an unmodified clone (R4-035). Extra remotes
        # still fail. PUBLISHED requires a remote.
        remotes = configured_remotes()
        if remotes is None:
            self.skipTest("repository state unobservable")
        disposition_text = (ROOT / "PUBLICATION.md").read_text(encoding="utf-8")
        if re.search(r"\*\*Disposition:\*\*\s*`PUBLISHED`", disposition_text):
            self.assertNotEqual([], remotes)
            return
        extra = [name for name in remotes if name != "origin"]
        self.assertEqual([], extra)

    def test_author_and_committer_identity(self) -> None:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(ROOT),
                "log",
                "--all",
                "--format=%an <%ae>%n%cn <%ce>",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            self.skipTest("no commits yet")
        identities = {line for line in result.stdout.splitlines() if line}
        allowed = {"itsmygithubacct <itsmygithubacct@users.noreply.github.com>"}
        self.assertTrue(
            identities <= allowed,
            f"unexpected identities: {sorted(identities - allowed)}",
        )


if __name__ == "__main__":
    unittest.main()
