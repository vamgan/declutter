"""Tests for scripts/bookmarks.py."""
import json, os, plistlib, sqlite3, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import bookmarks  # noqa: E402


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def chromium_fixture(children):
    return {"checksum": "stale",
            "roots": {"bookmark_bar": {"type": "folder", "id": "1", "guid": "bb",
                                       "name": "Bookmarks Bar", "children": children}}}


def url_node(guid, name, url):
    return {"type": "url", "id": guid, "guid": guid, "name": name, "url": url}


class TestCanonicalization(unittest.TestCase):
    """Duplicate detection is only as good as the URL canonical form."""

    def test_tracking_params_ignored(self):
        self.assertEqual(bookmarks.canon("https://a.com/x?utm_source=news"),
                         bookmarks.canon("https://a.com/x"))

    def test_www_ignored(self):
        self.assertEqual(bookmarks.canon("https://www.a.com/x"),
                         bookmarks.canon("https://a.com/x"))

    def test_trailing_slash_ignored(self):
        self.assertEqual(bookmarks.canon("https://a.com/x/"),
                         bookmarks.canon("https://a.com/x"))

    def test_scheme_normalized(self):
        self.assertEqual(bookmarks.canon("http://a.com/x"),
                         bookmarks.canon("https://a.com/x"))

    def test_case_insensitive_host_only(self):
        self.assertEqual(bookmarks.canon("https://A.COM/x"),
                         bookmarks.canon("https://a.com/x"))

    def test_meaningful_params_preserved(self):
        self.assertNotEqual(bookmarks.canon("https://a.com/s?q=cats"),
                            bookmarks.canon("https://a.com/s?q=dogs"))

    def test_different_paths_stay_different(self):
        self.assertNotEqual(bookmarks.canon("https://a.com/x"),
                            bookmarks.canon("https://a.com/y"))

    def test_malformed_url_does_not_raise(self):
        bookmarks.canon("not a url at all")   # must not raise


class TestFormatDetection(unittest.TestCase):
    """Detection is by content: filenames vary across profiles and copies."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def _write(self, name, data, mode="w"):
        p = os.path.join(self.dir, name)
        with open(p, mode) as fh:
            fh.write(data)
        return p

    def test_chromium_detected_regardless_of_filename(self):
        p = self._write("weird-name-no-extension", json.dumps(chromium_fixture([])))
        self.assertEqual(bookmarks.detect(p), "chromium")

    def test_safari_binary_plist_detected(self):
        p = os.path.join(self.dir, "anything")
        with open(p, "wb") as fh:
            plistlib.dump({"WebBookmarkType": "WebBookmarkTypeList", "Children": []},
                          fh, fmt=plistlib.FMT_BINARY)
        self.assertEqual(bookmarks.detect(p), "safari")

    def test_safari_xml_plist_detected(self):
        p = os.path.join(self.dir, "anything-xml")
        with open(p, "wb") as fh:
            plistlib.dump({"WebBookmarkType": "WebBookmarkTypeList", "Children": []},
                          fh, fmt=plistlib.FMT_XML)
        self.assertEqual(bookmarks.detect(p), "safari")

    def test_empty_file_is_clear_error(self):
        p = os.path.join(self.dir, "empty")
        open(p, "wb").close()
        with self.assertRaises(SystemExit) as cm:
            bookmarks.detect(p)
        self.assertIn("empty", str(cm.exception))

    def test_firefox_detected_by_magic_bytes(self):
        p = os.path.join(self.dir, "places-copy")
        con = sqlite3.connect(p)
        con.execute("CREATE TABLE t (x)")   # header is not written until now
        con.commit()
        con.close()
        self.assertEqual(bookmarks.detect(p), "firefox")

    def test_missing_file_is_clear_error(self):
        with self.assertRaises(SystemExit) as cm:
            bookmarks.detect(os.path.join(self.dir, "nope"))
        self.assertIn("no such bookmark store", str(cm.exception))

    def test_unrecognized_content_is_clear_error(self):
        p = self._write("junk", "!!!not a bookmark store!!!")
        with self.assertRaises(SystemExit) as cm:
            bookmarks.detect(p)
        self.assertIn("unrecognized", str(cm.exception))


class TestReadAndSummarize(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "Bookmarks")
        data = chromium_fixture([
            url_node("a", "Docs", "https://docs.python.org/3/"),
            url_node("b", "Docs dup", "https://www.docs.python.org/3?utm_source=x"),
            url_node("c", "Other", "https://example.com/"),
            {"type": "folder", "id": "f", "guid": "f", "name": "Sub", "children": [
                url_node("d", "Nested", "https://example.org/deep")]},
            {"type": "folder", "id": "e", "guid": "e", "name": "Empty", "children": []},
        ])
        with open(self.path, "w") as fh:
            json.dump(data, fh)

    def test_counts_urls_and_folders(self):
        _, nodes = bookmarks.load(self.path)
        s = bookmarks.summarize(nodes)
        self.assertEqual(s["total_bookmarks"], 4)
        self.assertEqual(s["total_folders"], 2)

    def test_duplicates_detected_across_url_variants(self):
        _, nodes = bookmarks.load(self.path)
        s = bookmarks.summarize(nodes)
        self.assertEqual(s["duplicate_groups"], 1)
        self.assertEqual(s["duplicate_bookmarks"], 1)

    def test_nested_bookmarks_are_found(self):
        _, nodes = bookmarks.load(self.path)
        titles = [n["title"] for n in nodes if n["kind"] == "url"]
        self.assertIn("Nested", titles)

    def test_empty_folder_reported(self):
        _, nodes = bookmarks.load(self.path)
        self.assertEqual(bookmarks.summarize(nodes)["empty_folders"], 1)


class TestApplyRefusesWithoutBackup(unittest.TestCase):
    """The backup requirement is the undo mechanism. It is not advisory."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = os.path.join(self.dir, "Bookmarks")
        with open(self.store, "w") as fh:
            json.dump(chromium_fixture([url_node("a", "X", "https://a.com")]), fh)
        self.plan = os.path.join(self.dir, "plan.json")
        with open(self.plan, "w") as fh:
            json.dump({"delete": ["a"]}, fh)

    def _run(self, backup):
        return subprocess.run(
            [sys.executable, os.path.join(ROOT, "scripts", "bookmarks.py"),
             "apply", self.store, self.plan, "--backup", backup],
            capture_output=True, text=True)

    def test_refuses_when_backup_dir_missing(self):
        r = self._run(os.path.join(self.dir, "no-such-dir"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("refusing to write", r.stdout + r.stderr)

    def test_refuses_when_backup_dir_exists_but_is_empty(self):
        empty = os.path.join(self.dir, "empty")
        os.makedirs(empty)
        r = self._run(empty)
        self.assertNotEqual(r.returncode, 0)

    def test_store_is_untouched_after_refusal(self):
        before = read(self.store)
        self._run(os.path.join(self.dir, "no-such-dir"))
        self.assertEqual(read(self.store), before)

    def test_applies_when_backup_present(self):
        backup = os.path.join(self.dir, "backup")
        os.makedirs(backup)
        with open(os.path.join(backup, "Bookmarks"), "w") as fh:
            fh.write(read(self.store))
        r = self._run(backup)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["deleted"], 1)


class TestApplyCorrectness(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = os.path.join(self.dir, "Bookmarks")
        with open(self.store, "w") as fh:
            json.dump(chromium_fixture([
                url_node("keep", "Keep", "https://keep.com"),
                url_node("drop", "Drop", "https://drop.com"),
                {"type": "folder", "id": "f", "guid": "f", "name": "Sub", "children": [
                    url_node("deep-drop", "Deep", "https://deep.com"),
                    url_node("deep-keep", "DeepKeep", "https://deepkeep.com")]},
            ]), fh)
        self.backup = os.path.join(self.dir, "backup")
        os.makedirs(self.backup)
        with open(os.path.join(self.backup, "Bookmarks"), "w") as fh:
            fh.write(read(self.store))

    def _apply(self, delete):
        plan = os.path.join(self.dir, "plan.json")
        with open(plan, "w") as fh:
            json.dump({"delete": delete}, fh)
        return subprocess.run(
            [sys.executable, os.path.join(ROOT, "scripts", "bookmarks.py"),
             "apply", self.store, plan, "--backup", self.backup],
            capture_output=True, text=True)

    def _titles(self):
        _, nodes = bookmarks.load(self.store)
        return {n["title"] for n in nodes if n["kind"] == "url"}

    def test_deletes_only_targeted_nodes(self):
        self._apply(["drop"])
        self.assertEqual(self._titles(), {"Keep", "Deep", "DeepKeep"})

    def test_deletes_inside_nested_folders(self):
        self._apply(["deep-drop"])
        self.assertNotIn("Deep", self._titles())
        self.assertIn("DeepKeep", self._titles())

    def test_unknown_id_deletes_nothing(self):
        r = self._apply(["does-not-exist"])
        self.assertEqual(json.loads(r.stdout)["deleted"], 0)
        self.assertEqual(len(self._titles()), 4)

    def test_stale_checksum_is_dropped(self):
        # Chromium rejects the file if the checksum does not match its contents.
        self._apply(["drop"])
        self.assertNotIn("checksum", json.load(open(self.store)))

    def test_result_includes_restore_command(self):
        r = self._apply(["drop"])
        self.assertIn("restore", json.loads(r.stdout))

    def test_backup_restores_original_exactly(self):
        original = open(os.path.join(self.backup, "Bookmarks")).read()
        self._apply(["drop", "deep-drop"])
        with open(self.store, "w") as fh:      # simulate the printed undo
            fh.write(original)
        self.assertEqual(self._titles(), {"Keep", "Drop", "Deep", "DeepKeep"})


if __name__ == "__main__":
    unittest.main()
