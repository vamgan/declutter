"""Structural tests for the skills, references, and plugin manifests.

Skill judgment cannot be automated; a human still reads the prose. Everything
structural can be, and is gated here: valid frontmatter, safety rules actually
cited, no hardcoded paths, and descriptions that will realistically trigger.
"""
import glob, json, os, re, unittest


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = sorted(glob.glob(os.path.join(ROOT, "skills", "*", "*", "SKILL.md")))


def frontmatter(path):
    text = open(path, encoding="utf-8").read()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None, text
    meta = {}
    key = None
    for line in m.group(1).splitlines():
        if re.match(r"^\s+", line) and key:
            meta[key] += " " + line.strip()
        elif ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            meta[key] = val.strip()
    return meta, text[m.end():]


class TestSkillsExist(unittest.TestCase):
    def test_skills_are_present(self):
        self.assertGreaterEqual(len(SKILLS), 4)

    def test_every_skill_sits_in_a_category(self):
        for p in SKILLS:
            category = p.split(os.sep)[-3]
            with self.subTest(skill=p):
                self.assertIn(category, {"browser", "files", "notes"})


class TestFrontmatter(unittest.TestCase):
    def test_frontmatter_parses(self):
        for p in SKILLS:
            with self.subTest(skill=os.path.basename(os.path.dirname(p))):
                meta, _ = frontmatter(p)
                self.assertIsNotNone(meta, "missing or malformed frontmatter")

    def test_name_matches_directory(self):
        for p in SKILLS:
            meta, _ = frontmatter(p)
            expected = os.path.basename(os.path.dirname(p))
            with self.subTest(skill=expected):
                self.assertEqual(meta.get("name"), expected)

    def test_description_is_substantial(self):
        # The description is the only thing the model sees when deciding whether
        # to reach for a skill. A vague one means the skill never fires.
        for p in SKILLS:
            meta, _ = frontmatter(p)
            with self.subTest(skill=meta.get("name")):
                self.assertGreater(len(meta.get("description", "")), 60)

    def test_description_says_when_to_use_it(self):
        for p in SKILLS:
            meta, _ = frontmatter(p)
            with self.subTest(skill=meta.get("name")):
                self.assertIn("use when", meta["description"].lower())

    def test_names_are_unique(self):
        names = [frontmatter(p)[0]["name"] for p in SKILLS]
        self.assertEqual(len(names), len(set(names)))


class TestTriggering(unittest.TestCase):
    """A skill nobody triggers is dead weight.

    Each phrase is something a real person would type. It must match exactly one
    skill's description, so the right one fires and the others stay quiet.
    """

    PHRASES = {
        "my bookmarks are a mess":              "organizing-bookmarks",
        "dedupe my bookmarks":                  "organizing-bookmarks",
        "my downloads folder is out of control": "sorting-downloads",
        "clean up downloads":                   "sorting-downloads",
        "my desktop is covered in files":       "clearing-desktop",
        "organize my desktop":                  "clearing-desktop",
        "find orphan notes":                    "organizing-obsidian-vault",
        "organize my vault":                    "organizing-obsidian-vault",
    }

    def setUp(self):
        self.descriptions = {}
        for p in SKILLS:
            meta, _ = frontmatter(p)
            self.descriptions[meta["name"]] = meta["description"].lower()

    def _score(self, phrase, description):
        stop = {"my", "is", "are", "a", "of", "up", "in", "the", "out"}
        words = [w for w in re.findall(r"[a-z]+", phrase.lower()) if w not in stop]
        return sum(1 for w in words if w in description)

    def test_each_phrase_matches_its_skill(self):
        for phrase, expected in self.PHRASES.items():
            with self.subTest(phrase=phrase):
                self.assertGreater(self._score(phrase, self.descriptions[expected]), 0,
                                   f"'{phrase}' would not trigger {expected}")

    def test_each_phrase_prefers_the_right_skill(self):
        for phrase, expected in self.PHRASES.items():
            scores = {n: self._score(phrase, d) for n, d in self.descriptions.items()}
            best = max(scores.values())
            winners = [n for n, sc in scores.items() if sc == best]
            with self.subTest(phrase=phrase):
                self.assertIn(expected, winners,
                              f"'{phrase}' matched {winners} instead of {expected}")


class TestSafetyIsCited(unittest.TestCase):
    """Skills must point at the shared rules rather than restating them."""

    def test_every_skill_cites_safe_mutation_rules(self):
        for p in SKILLS:
            meta, body = frontmatter(p)
            with self.subTest(skill=meta["name"]):
                self.assertIn("safe-mutation-rules.md", body)

    def test_every_skill_cites_the_preflight(self):
        for p in SKILLS:
            meta, body = frontmatter(p)
            with self.subTest(skill=meta["name"]):
                self.assertIn("pre-flight", body.lower())

    def test_every_skill_has_a_never_section(self):
        for p in SKILLS:
            meta, body = frontmatter(p)
            with self.subTest(skill=meta["name"]):
                self.assertIn("## Never", body)

    def test_every_skill_states_content_is_not_instructions(self):
        for p in SKILLS:
            meta, body = frontmatter(p)
            with self.subTest(skill=meta["name"]):
                self.assertIn("instruction", body.lower())

    def test_no_hardcoded_home_paths(self):
        # Paths belong in app-data-locations.md and are resolved by platforms.py,
        # so a skill never has to be rewritten for another operating system.
        bad = re.compile(r"~/Library|%APPDATA%|%LOCALAPPDATA%|/Users/")
        for p in SKILLS:
            meta, body = frontmatter(p)
            hits = [ln for ln in body.splitlines()
                    if bad.search(ln) and "Desktop-Archive" not in ln]
            with self.subTest(skill=meta["name"]):
                self.assertEqual(hits, [], f"hardcoded path: {hits}")

    def test_no_raw_rm(self):
        for p in SKILLS:
            meta, body = frontmatter(p)
            for line in body.splitlines():
                if re.search(r"^\s*rm\s+-", line):
                    self.fail(f"{meta['name']} uses rm: {line.strip()}")


class TestReferencedFilesExist(unittest.TestCase):
    def test_referenced_scripts_exist(self):
        for p in SKILLS:
            meta, body = frontmatter(p)
            for script in re.findall(r"scripts/([a-z_]+\.py)", body):
                with self.subTest(skill=meta["name"], script=script):
                    self.assertTrue(os.path.exists(os.path.join(ROOT, "scripts", script)))

    def test_reference_files_exist(self):
        for name in ("safe-mutation-rules.md", "app-data-locations.md"):
            self.assertTrue(os.path.exists(os.path.join(ROOT, "references", name)))

    def test_preflight_lives_in_the_rules_file(self):
        body = open(os.path.join(ROOT, "references", "safe-mutation-rules.md"),
                    encoding="utf-8").read()
        self.assertIn("Pre-flight check", body)


class TestManifests(unittest.TestCase):
    def setUp(self):
        self.plugin = json.load(open(os.path.join(ROOT, ".claude-plugin", "plugin.json")))
        self.market = json.load(open(os.path.join(ROOT, ".claude-plugin", "marketplace.json")))

    def test_plugin_has_required_fields(self):
        for field in ("name", "description", "version", "license"):
            self.assertIn(field, self.plugin)

    def test_marketplace_lists_the_plugin(self):
        names = [p["name"] for p in self.market["plugins"]]
        self.assertIn(self.plugin["name"], names)

    def test_versions_agree(self):
        entry = next(p for p in self.market["plugins"]
                     if p["name"] == self.plugin["name"])
        self.assertEqual(entry["version"], self.plugin["version"])

    def test_marketplace_source_points_at_this_repo(self):
        entry = self.market["plugins"][0]
        self.assertEqual(entry["source"]["repo"], "vamgan/declutter")


if __name__ == "__main__":
    unittest.main()


class TestPublishedCountsMatchCode(unittest.TestCase):
    """The README and the site make a numeric claim. Claims drift; tests do not.

    Opera was added to the code and both the site and the README kept
    advertising the old number until this test existed.
    """

    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "platforms", os.path.join(ROOT, "scripts", "platforms.py"))
        self.platforms = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.platforms)
        self.expected = (len(self.platforms.CHROMIUM)
                         + 1                              # Safari
                         + len(self.platforms.FIREFOX))   # Firefox and Tor

    def test_site_browser_count_matches_code(self):
        site = read(os.path.join(ROOT, "site", "index.html"))
        m = re.search(r'class="stat">(\d+)<', site)
        self.assertIsNotNone(m, "site no longer states a browser count")
        self.assertEqual(int(m.group(1)), self.expected)

    def test_readme_browser_count_matches_code(self):
        words = {8: "Eight", 9: "Nine", 10: "Ten", 11: "Eleven", 12: "Twelve"}
        readme = read(os.path.join(ROOT, "README.md"))
        self.assertIn(f"**{words[self.expected]} browsers, one markdown file.**", readme)

    def test_every_chromium_app_appears_on_the_site(self):
        site = read(os.path.join(ROOT, "site", "index.html"))
        for app in self.platforms.CHROMIUM:
            with self.subTest(app=app):
                self.assertIn(app.capitalize(), site)
