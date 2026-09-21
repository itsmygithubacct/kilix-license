import os
from pathlib import Path
import tempfile
import unittest

from kilix_license.errors import LiveStoreForbidden
from kilix_license.paths import (
    STACK_HOME_DIRS,
    is_under_live_store,
    live_store_root,
    live_store_roots,
    nss_home,
    user_home,
)

from fake_store import FakeStore
from live_store_guard import live_root


class HarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._scratch = Path(tempfile.mkdtemp(prefix="kilix-license-harness-"))
        self.store = FakeStore(self._scratch / "receipts")

    def test_fake_store_root_is_temp(self) -> None:
        self.assertTrue(str(self.store.root).startswith(str(self._scratch)))
        self.assertFalse(str(self.store.root).startswith(str(live_store_root())))

    def test_fake_store_refuses_live_root(self) -> None:
        with self.assertRaises(LiveStoreForbidden):
            FakeStore(live_store_root())
        with self.assertRaises(LiveStoreForbidden):
            FakeStore(live_store_root() / "license-receipts")

    def test_planted_live_store_write_is_refused(self) -> None:
        planted = live_root() / "planted-kilix-license-must-not-exist.json"
        existed_before = planted.exists()
        with self.assertRaises(LiveStoreForbidden):
            planted.write_text("planted", encoding="utf-8")
        self.assertEqual(existed_before, planted.exists())
        self.assertFalse(existed_before)

    def test_planted_live_store_open_is_refused(self) -> None:
        planted = live_root() / "planted-kilix-license-open.json"
        with self.assertRaises(LiveStoreForbidden):
            open(planted, "w", encoding="utf-8")
        self.assertFalse(planted.exists())

    def test_guard_root_is_nss_home_not_redirected_home(self) -> None:
        self.assertEqual(live_root(), live_store_root())
        self.assertEqual(live_root().parts[-2:], (".local", "gpu_terminal"))
        # Asserted against pw_dir itself, not against live_store_root(), so a
        # change that moves BOTH to $HOME fails here (LIC6-VERIFY F1, mutant
        # v5). $HOME is redirected into a scratch directory by `make test`, so
        # a $HOME-based guard stops guarding the real store while the suite
        # runs -- the one moment it has to work.
        self.assertEqual(live_root(), nss_home().joinpath(*STACK_HOME_DIRS))
        home = user_home()
        if str(home) != str(nss_home()):
            self.assertFalse(str(live_root()).startswith(str(home) + os.sep))
            self.assertNotEqual(live_root(), home.joinpath(*STACK_HOME_DIRS))

    def test_the_guard_refuses_both_spellings_of_the_live_store(self) -> None:
        # The receipt root now follows $HOME (F1). The guard must refuse that
        # spelling too, so nothing the guard used to catch became writable.
        roots = live_store_roots()
        self.assertIn(live_store_root(), roots)
        self.assertIn(user_home().joinpath(*STACK_HOME_DIRS), roots)
        for root in roots:
            with self.subTest(root=str(root)):
                self.assertTrue(is_under_live_store(str(root)))
                self.assertTrue(is_under_live_store(str(root / "license-receipts")))
                with self.assertRaises(LiveStoreForbidden):
                    FakeStore(root / "license-receipts")
        self.assertFalse(is_under_live_store(str(self._scratch)))

    def test_planted_dir_fd_relative_create_is_refused(self) -> None:
        live = live_root()
        planted = live / "lacc-f4-dirfd.json"
        fd = os.open(str(live.parent), os.O_RDONLY | os.O_DIRECTORY)
        try:
            with self.assertRaises(LiveStoreForbidden):
                os.open(
                    "gpu_terminal/lacc-f4-dirfd.json",
                    os.O_CREAT | os.O_WRONLY,
                    0o600,
                    dir_fd=fd,
                )
        finally:
            os.close(fd)
        self.assertFalse(planted.exists())

    def test_planted_truncate_is_refused(self) -> None:
        target = live_root() / "sentinel.txt"
        with self.assertRaises(LiveStoreForbidden):
            os.truncate(str(target), 0)

    def test_planted_chmod_is_refused(self) -> None:
        with self.assertRaises(LiveStoreForbidden):
            os.chmod(str(live_root() / "sentinel.txt"), 0o666)

    def test_planted_utime_is_refused(self) -> None:
        with self.assertRaises(LiveStoreForbidden):
            os.utime(str(live_root() / "sentinel.txt"), None)

    def test_utime_none_outside_live_store_still_works(self) -> None:
        path = self._scratch / "touch-me"
        path.write_text("x", encoding="utf-8")
        os.utime(path, None)

    def test_planted_rmdir_is_refused(self) -> None:
        with self.assertRaises(LiveStoreForbidden):
            os.rmdir(str(live_root() / "emptydir"))
