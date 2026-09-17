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


class RepositoryIdentityTests(unittest.TestCase):
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
