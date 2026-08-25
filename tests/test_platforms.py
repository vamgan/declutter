"""Tests for scripts/platforms.py.

Platform behaviour is tested by forcing the platform, so the Linux and Windows
path logic is exercised even when the suite runs on a Mac.
"""
import os, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import platforms  # noqa: E402


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class TestSystemDetection(unittest.TestCase):
    def test_darwin(self):
        with mock.patch.object(sys, "platform", "darwin"):
            self.assertEqual(platforms.system(), platforms.MAC)

    def test_windows(self):
        with mock.patch.object(sys, "platform", "win32"):
            self.assertEqual(platforms.system(), platforms.WINDOWS)

    def test_linux(self):
        with mock.patch.object(sys, "platform", "linux"):
            self.assertEqual(platforms.system(), platforms.LINUX)

    def test_unknown_unix_treated_as_linux(self):
        with mock.patch.object(sys, "platform", "freebsd14"):
            self.assertEqual(platforms.system(), platforms.LINUX)

    def test_every_platform_declares_support_status(self):
        for p in (platforms.MAC, platforms.LINUX, platforms.WINDOWS):
            self.assertIn(p, platforms.SUPPORT)


class TestChromiumRoots(unittest.TestCase):
    """The same browser lives in three different places. All three must resolve."""

    def _root(self, app, sysname, env=None):
        with mock.patch.object(platforms, "system", lambda: sysname), \
             mock.patch.dict(os.environ, env or {}, clear=False):
            return platforms.chromium_root(app)

    def test_mac_uses_application_support(self):
        self.assertIn("Application Support", self._root("chrome", platforms.MAC))

    def test_linux_uses_dot_config(self):
        r = self._root("chrome", platforms.LINUX)
        self.assertIn(".config", r)
        self.assertTrue(r.endswith("google-chrome"))

    def test_windows_uses_localappdata(self):
        r = self._root("chrome", platforms.WINDOWS,
                       {"LOCALAPPDATA": r"C:\Users\x\AppData\Local"})
        self.assertIn("AppData", r)
        self.assertIn("User Data", r)

    def test_windows_falls_back_when_env_missing(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(platforms, "system", lambda: platforms.WINDOWS):
                self.assertIsNotNone(platforms.chromium_root("chrome"))

    def test_arc_is_absent_on_linux(self):
        self.assertIsNone(self._root("arc", platforms.LINUX))

    def test_unknown_app_returns_none(self):
        self.assertIsNone(self._root("netscape", platforms.MAC))

    def test_all_chromium_apps_resolve_on_mac_and_windows(self):
        for app in platforms.CHROMIUM:
            for sysname in (platforms.MAC, platforms.WINDOWS):
                with self.subTest(app=app, platform=sysname):
                    self.assertIsNotNone(self._root(app, sysname))


class TestLocateContract(unittest.TestCase):
    """locate() must always return the same shape, including on failure."""

    def _assert_shape(self, result):
        self.assertIn("paths", result)
        self.assertIn("blocked", result)
        self.assertIn("remediation", result)
        self.assertIsInstance(result["paths"], list)

    def test_shape_on_success(self):
        self._assert_shape(platforms.locate("safari"))

    def test_shape_on_unknown_app(self):
        r = platforms.locate("netscape")
        self._assert_shape(r)
        self.assertEqual(r["paths"], [])
        self.assertFalse(r["blocked"])

    def test_permission_denied_is_data_not_an_exception(self):
        # A TCC denial is the most common first-run outcome on macOS.
        # It must never surface as a traceback.
        with mock.patch.object(platforms.os, "listdir", side_effect=PermissionError()), \
             mock.patch.object(platforms.os.path, "isdir", lambda p: True), \
             mock.patch.object(platforms, "chromium_root", lambda a: "/fake"):
            r = platforms.locate("chrome")
        self._assert_shape(r)
        self.assertTrue(r["blocked"])
        self.assertTrue(r["remediation"])

    def test_remediation_names_full_disk_access_on_mac(self):
        with mock.patch.object(platforms, "system", lambda: platforms.MAC):
            self.assertIn("Full Disk Access", platforms._blocked()["remediation"])

    def test_every_platform_has_remediation_text(self):
        for p in (platforms.MAC, platforms.LINUX, platforms.WINDOWS):
            self.assertTrue(platforms.BLOCKED_HELP[p])

    def test_safari_absent_off_mac_without_error(self):
        with mock.patch.object(platforms, "system", lambda: platforms.LINUX):
            r = platforms.locate("safari")
        self.assertEqual(r["paths"], [])
        self.assertFalse(r["blocked"])


class TestTrash(unittest.TestCase):
    """Trash must move, never unlink, and never collide."""

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.work = tempfile.mkdtemp()

    def _fake_home(self, *parts):
        return os.path.join(self.home, *parts)

    def _file(self, name, content="x"):
        p = os.path.join(self.work, name)
        with open(p, "w") as fh:
            fh.write(content)
        return p

    def test_mac_moves_to_trash_directory(self):
        p = self._file("doomed.txt")
        with mock.patch.object(platforms, "system", lambda: platforms.MAC), \
             mock.patch.object(platforms, "home", self._fake_home):
            dest = platforms.trash(p)
        self.assertFalse(os.path.exists(p))
        self.assertTrue(os.path.exists(dest))

    def test_content_survives_the_move(self):
        p = self._file("keepme.txt", "important")
        with mock.patch.object(platforms, "system", lambda: platforms.MAC), \
             mock.patch.object(platforms, "home", self._fake_home):
            dest = platforms.trash(p)
        self.assertEqual(read(dest), "important")

    def test_name_collision_does_not_overwrite(self):
        with mock.patch.object(platforms, "system", lambda: platforms.MAC), \
             mock.patch.object(platforms, "home", self._fake_home):
            first = platforms.trash(self._file("dup.txt", "first"))
            second = platforms.trash(self._file("dup.txt", "second"))
        self.assertNotEqual(first, second)
        self.assertEqual(read(first), "first")
        self.assertEqual(read(second), "second")

    def test_linux_writes_freedesktop_trashinfo(self):
        p = self._file("linux.txt")
        with mock.patch.object(platforms, "system", lambda: platforms.LINUX), \
             mock.patch.dict(os.environ, {"XDG_DATA_HOME": self.home}, clear=False):
            dest = platforms.trash(p)
        info = os.path.join(self.home, "Trash", "info",
                            os.path.basename(dest) + ".trashinfo")
        self.assertTrue(os.path.exists(info), "restore metadata missing")
        body = read(info)
        self.assertIn("[Trash Info]", body)
        self.assertIn("Path=", body)
        self.assertIn("DeletionDate=", body)

    def test_linux_trashinfo_records_original_location(self):
        p = self._file("origin.txt")
        with mock.patch.object(platforms, "system", lambda: platforms.LINUX), \
             mock.patch.dict(os.environ, {"XDG_DATA_HOME": self.home}, clear=False):
            dest = platforms.trash(p)
        info = open(os.path.join(self.home, "Trash", "info",
                                 os.path.basename(dest) + ".trashinfo")).read()
        self.assertIn("origin.txt", info)

    def test_missing_file_is_clear_error(self):
        with self.assertRaises(SystemExit):
            platforms.trash(os.path.join(self.work, "not-here.txt"))


class TestProcessNames(unittest.TestCase):
    def test_every_locatable_app_has_process_names(self):
        for app in list(platforms.CHROMIUM) + ["firefox", "safari", "obsidian"]:
            with self.subTest(app=app):
                self.assertIn(app, platforms.PROCESS_NAMES)

    def test_running_returns_none_for_unknown_app(self):
        self.assertIsNone(platforms.running("netscape"))

    def test_running_returns_none_where_app_does_not_exist(self):
        with mock.patch.object(platforms, "system", lambda: platforms.LINUX):
            self.assertIsNone(platforms.running("safari"))


if __name__ == "__main__":
    unittest.main()
