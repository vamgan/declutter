"""Tests for scripts/scan_tree.py.

The confinement tests matter most: this module decides what a file skill is
allowed to see and touch.
"""
import json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import scan_tree  # noqa: E402


class TestConfinement(unittest.TestCase):
    """denied() is the guard between a plan and the user's home directory."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, "sub"), exist_ok=True)

    def test_file_inside_root_allowed(self):
        self.assertFalse(scan_tree.denied(os.path.join(self.root, "a.txt"), self.root))

    def test_nested_file_allowed(self):
        self.assertFalse(scan_tree.denied(os.path.join(self.root, "sub", "a.txt"), self.root))

    def test_parent_traversal_denied(self):
        self.assertTrue(scan_tree.denied(os.path.join(self.root, "..", "escape.txt"), self.root))

    def test_deep_traversal_denied(self):
        self.assertTrue(scan_tree.denied(
            os.path.join(self.root, "sub", "..", "..", "..", "etc", "passwd"), self.root))

    def test_absolute_path_outside_root_denied(self):
        self.assertTrue(scan_tree.denied("/etc/passwd", self.root))

    def test_root_itself_allowed(self):
        self.assertFalse(scan_tree.denied(self.root, self.root))

    def test_sibling_prefix_directory_denied(self):
        # /tmp/rootEVIL must not pass just because it starts with /tmp/root
        self.assertTrue(scan_tree.denied(self.root + "EVIL", self.root))

    def test_denylisted_name_anywhere_in_path_denied(self):
        for name in (".ssh", ".gnupg", ".aws", ".kube", "Library"):
            with self.subTest(name=name):
                self.assertTrue(scan_tree.denied(
                    os.path.join(self.root, name, "secret"), self.root))

    def test_dotfile_at_root_denied(self):
        self.assertTrue(scan_tree.denied(os.path.join(self.root, ".env"), self.root))

    def test_dotfile_deeper_is_allowed(self):
        # Only the root level is treated as sensitive; a dotfile inside a
        # project folder the user pointed at is ordinary content.
        self.assertFalse(scan_tree.denied(
            os.path.join(self.root, "sub", ".gitignore"), self.root))


class TestScan(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self._write("a.pdf", "identical payload")
        self._write("a-copy.pdf", "identical payload")
        self._write("unique.txt", "something else")
        self._write("empty1.txt", "")
        self._write("empty2.txt", "")
        os.makedirs(os.path.join(self.root, "nested"))
        self._write(os.path.join("nested", "deep.zip"), "zip payload")

    def _write(self, rel, content):
        p = os.path.join(self.root, rel)
        with open(p, "w") as fh:
            fh.write(content)
        return p

    def scan(self, **kw):
        kw.setdefault("max_depth", None)
        kw.setdefault("min_size_mb", 0)
        return scan_tree.scan(self.root, kw["max_depth"], kw["min_size_mb"])

    def test_finds_all_files(self):
        self.assertEqual(self.scan()["total_files"], 6)

    def test_detects_identical_content_as_duplicate(self):
        d = self.scan()
        self.assertEqual(d["duplicate_groups"], 1)
        self.assertEqual(sorted(d["duplicates"][0]), ["a-copy.pdf", "a.pdf"])

    def test_empty_files_are_not_duplicates(self):
        # Two empty files are not a meaningful pair to deduplicate.
        for group in self.scan()["duplicates"]:
            self.assertNotIn("empty1.txt", group)

    def test_categorizes_by_extension(self):
        cats = self.scan()["by_category"]
        self.assertEqual(cats["document"]["count"], 5)   # pdf + txt
        self.assertEqual(cats["archive"]["count"], 1)    # zip

    def test_symlinks_are_skipped(self):
        os.symlink("/etc/passwd", os.path.join(self.root, "escape.txt"))
        d = self.scan()
        self.assertEqual(d["total_files"], 6)            # unchanged
        self.assertGreaterEqual(d["skipped_denied_or_symlink"], 1)

    def test_symlinked_directory_is_not_followed(self):
        os.symlink("/etc", os.path.join(self.root, "escapedir"))
        self.assertEqual(self.scan()["total_files"], 6)

    def test_max_depth_limits_recursion(self):
        self.assertEqual(self.scan(max_depth=1)["total_files"], 5)  # nested/ excluded

    def test_missing_root_is_clear_error(self):
        with self.assertRaises(SystemExit):
            scan_tree.scan(os.path.join(self.root, "nope"), None, 0)


class TestPlanCheck(unittest.TestCase):
    """plan-check must exit non-zero so a skill's shell step stops."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        with open(os.path.join(self.root, "a.txt"), "w") as fh:
            fh.write("x")

    def _check(self, plan):
        p = os.path.join(self.root, "plan.json")
        with open(p, "w") as fh:
            json.dump(plan, fh)
        return subprocess.run(
            [sys.executable, os.path.join(ROOT, "scripts", "scan_tree.py"),
             "plan-check", self.root, p], capture_output=True, text=True)

    def test_safe_plan_passes(self):
        r = self._check({"moves": [{"from": "a.txt", "to": "sub/a.txt"}]})
        self.assertEqual(r.returncode, 0)
        self.assertTrue(json.loads(r.stdout)["ok"])

    def test_escaping_plan_fails_with_nonzero_exit(self):
        r = self._check({"moves": [{"from": "a.txt", "to": "../../../etc/evil"}]})
        self.assertEqual(r.returncode, 1)
        self.assertFalse(json.loads(r.stdout)["ok"])

    def test_escaping_source_also_fails(self):
        r = self._check({"moves": [{"from": "../../../etc/passwd", "to": "a.txt"}]})
        self.assertEqual(r.returncode, 1)

    def test_denylisted_destination_fails(self):
        r = self._check({"moves": [{"from": "a.txt", "to": ".ssh/id_rsa"}]})
        self.assertEqual(r.returncode, 1)

    def test_violation_is_reported_not_just_flagged(self):
        r = self._check({"moves": [{"from": "a.txt", "to": "../evil"}]})
        self.assertTrue(json.loads(r.stdout)["violations"])


if __name__ == "__main__":
    unittest.main()


class TestConflictedCopies(unittest.TestCase):
    """Conflicted copies are the one clutter type unique to synced folders.

    Every sync client marks them differently and none clean up after themselves,
    so the names are the only signal available.
    """

    def _name(self, n):
        return scan_tree.conflict_of(n)

    def test_dropbox_dated_conflict(self):
        self.assertEqual(self._name("Budget (Sarah's conflicted copy 2025-11-03).xlsx"),
                         "Dropbox")

    def test_dropbox_case_conflict(self):
        self.assertIsNotNone(self._name("Photo (Case Conflict).jpg"))

    def test_onedrive_machine_suffix(self):
        self.assertEqual(self._name("Notes-DESKTOP-A1B2C3.docx"), "OneDrive")

    def test_nextcloud_conflict(self):
        self.assertIsNotNone(self._name("Report_conflict-20251103-140233.pdf"))

    def test_ordinary_names_are_not_conflicts(self):
        for name in ("Budget.xlsx", "holiday photo.jpg", "notes-final.docx",
                     "report-v2.pdf", "Screenshot 2026-08-14.png"):
            with self.subTest(name=name):
                self.assertIsNone(self._name(name))

    def test_plain_numbered_copy_is_not_called_a_conflict(self):
        # "(1)" is ambiguous: it is also just a second download. Content
        # comparison decides that one, not the filename.
        self.assertIsNone(self._name("invoice (1).pdf"))

    def test_base_name_recovers_the_original(self):
        cases = {
            "Budget (Sarah's conflicted copy 2025-11-03).xlsx": "Budget.xlsx",
            "Notes-DESKTOP-A1B2C3.docx": "Notes.docx",
        }
        for conflicted, original in cases.items():
            with self.subTest(name=conflicted):
                self.assertEqual(scan_tree.base_name_of(conflicted), original)

    def test_extension_survives_stripping(self):
        for name in ("Budget (Sarah's conflicted copy 2025-11-03).xlsx",
                     "Notes-DESKTOP-A1B2C3.docx"):
            with self.subTest(name=name):
                self.assertTrue(scan_tree.base_name_of(name).count(".") >= 1)


class TestCloudScan(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.dbx = os.path.join(self.root, "Dropbox", "Family")
        os.makedirs(self.dbx)
        self._write("Budget.xlsx", "newer version")
        self._write("Budget (Sarah's conflicted copy 2025-11-03).xlsx", "older")
        self._write("Notes.docx", "same bytes")
        self._write("Notes-DESKTOP-A1B2C3.docx", "same bytes")
        self._write("Recipes.pdf", "unrelated")

    def _write(self, name, content):
        with open(os.path.join(self.dbx, name), "w") as fh:
            fh.write(content)

    def scan(self):
        return scan_tree.scan(self.dbx, None, 0)

    def test_detects_the_sync_provider_from_the_path(self):
        self.assertEqual(self.scan()["cloud_provider"], "Dropbox")

    def test_plain_folder_reports_no_provider(self):
        plain = tempfile.mkdtemp()
        self.assertIsNone(scan_tree.scan(plain, None, 0)["cloud_provider"])

    def test_counts_only_real_conflicts(self):
        self.assertEqual(self.scan()["conflicted_copies"], 2)

    def test_pairs_each_copy_with_its_original(self):
        by_copy = {c["copy"]: c for c in self.scan()["conflicts"]}
        self.assertEqual(
            by_copy["Budget (Sarah's conflicted copy 2025-11-03).xlsx"]["original"],
            "Budget.xlsx")
        self.assertEqual(by_copy["Notes-DESKTOP-A1B2C3.docx"]["original"], "Notes.docx")

    def test_flags_which_conflicts_are_identical(self):
        # Identical to the original is safe to remove. Differing needs a human.
        by_copy = {c["copy"]: c for c in self.scan()["conflicts"]}
        self.assertTrue(by_copy["Notes-DESKTOP-A1B2C3.docx"]["same_content"])
        self.assertFalse(
            by_copy["Budget (Sarah's conflicted copy 2025-11-03).xlsx"]["same_content"])

    def test_unpaired_conflict_reports_no_original(self):
        self._write("Orphan (conflicted copy).txt", "x")
        match = [c for c in self.scan()["conflicts"] if c["copy"].startswith("Orphan")]
        self.assertEqual(match[0]["original"], None)


class TestPlaceholders(unittest.TestCase):
    """Acting on a file the sync client has evicted destroys its content."""

    def setUp(self):
        self.root = tempfile.mkdtemp()

    def _touch(self, name, content=""):
        with open(os.path.join(self.root, name), "w") as fh:
            fh.write(content)

    def test_icloud_placeholder_detected(self):
        self._touch("Holiday.mov.icloud")
        self.assertEqual(scan_tree.scan(self.root, None, 0)["placeholders_not_downloaded"], 1)

    def test_zero_byte_file_treated_as_not_downloaded(self):
        self._touch("Photo.jpg")
        self.assertEqual(scan_tree.scan(self.root, None, 0)["placeholders_not_downloaded"], 1)

    def test_real_files_are_not_placeholders(self):
        self._touch("Photo.jpg", "actual bytes")
        self.assertEqual(scan_tree.scan(self.root, None, 0)["placeholders_not_downloaded"], 0)

    def test_keep_files_are_not_placeholders(self):
        self._touch(".gitkeep")
        self._touch("real.txt", "x")
        self.assertEqual(scan_tree.scan(self.root, None, 0)["placeholders_not_downloaded"], 0)
