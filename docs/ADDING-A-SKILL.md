# Adding a Skill

Two kinds of contribution. Pick the one that matches what you want.

---

## Adding an app to a category that already exists

**Three lines, across two files.** If your app stores its data in a format that is
already supported, register it in all three places below and every existing skill in
that category covers it immediately. No new skill, no new code.

| Where | What to add |
|---|---|
| `references/app-data-locations.md` | the table row, so a human can read it |
| `scripts/platforms.py`, the family table | where the data lives, on each platform |
| `scripts/platforms.py`, `PROCESS_NAMES` | what the running process is called |

**All three, or none.** Registering a path without a process name is the dangerous
half-addition: `running()` returns `None`, so a skill cannot tell the app is open, and
a browser that rewrites its store on exit will clobber the change. Opera shipped in
exactly that state until a test caught it. A test now enforces the pairing, but the
test only helps if you know why it is there.

Vivaldi was added this way. It is a Chromium browser, so it keeps bookmarks in the
same JSON format as Chrome, and it needed no new skill at all.

For the table row, include:

| Field | Why it matters |
|---|---|
| Path | With the profile pattern, if there is one |
| Permission required | Full Disk Access? Automation? |
| Must the app be quit to write? | Getting this wrong destroys data |
| Which parser handles it | Existing script, or a new one |

---

## Adding a new cleanup behaviour

**One markdown file** at `skills/<category>/<name>/SKILL.md`.

### Frontmatter

```yaml
---
name: organizing-bookmarks
description: Use when the user wants to clean up, dedupe, prune, or reorganize
  browser bookmarks — Chrome, Brave, Edge, Arc, Vivaldi, Chromium, Safari, or
  Firefox. Triggers on "my bookmarks are a mess", "dedupe my bookmarks".
---
```

The `description` is how the model decides whether to reach for your skill, so it is
the most important line in the file. Write what the *user* would say, not what the
skill does. Include the literal phrases people actually type.

### Body

Structure that works:

1. **Point at the shared rules.** Every skill that writes to disk starts with:
   `Read ../../../references/safe-mutation-rules.md and follow that workflow.`
   Do not restate those rules — they change, and copies go stale.
2. **What "organized" means here.** The judgment your skill encodes. This is the part
   only you know.
3. **Workflow.** Only the steps specific to your app. Real commands.
4. **Judgment calls.** Which duplicate wins? What counts as stale? Be opinionated —
   vagueness produces vague results.
5. **Never.** The specific ways this app can be damaged.

### Reaching shared files

Your skill's absolute base directory is provided when the skill loads. The plugin root
is three levels up, so shared files are at `../../../references/` and
`../../../scripts/` relative to it.

### Scripts

Add one only when the work is deterministic and bulky — parsing, hashing, dedupe,
writing files. Judgment stays in the skill.

Rules: **Python 3 stdlib only**, no dependencies, a plain CLI that prints JSON, and it
must refuse to write without a `--backup` argument pointing at a real backup.

---

## Reviewer checklist

There is no CI gate. These skills move real files, so a green check would be false
comfort — a human reads the markdown instead. Your PR is checked against:

- [ ] Cites `safe-mutation-rules.md` rather than restating it
- [ ] Backs up before any write, and prints the backup path to the user first
- [ ] Gets explicit approval before mutating; never mutates on the same turn it was asked a question
- [ ] Looks paths up in `app-data-locations.md` — no hardcoded paths in the skill
- [ ] Extracts via script rather than loading large files into context
- [ ] States that app content is data, not instructions
- [ ] Handles the app being open, if writing to a live app can corrupt data
- [ ] Prints the exact undo command at the end
- [ ] `description` is specific enough to trigger correctly and does not collide with an existing skill
- [ ] Run once against `fixtures/`, with the before/after pasted into the PR

---

## Testing

`fixtures/` holds synthetic data — a bookmarks file with known duplicates, a
downloads tree with known clutter. Never commit real user data.

Scripts are ordinary Python and get ordinary tests:

```bash
python3 -m unittest discover tests -v
```

Skills are prose and are verified by running them against a fixture and reading the
result. Paste that into your PR.

---

## Commit convention

[Conventional Commits](https://www.conventionalcommits.org/):

```
feat(browser): add Vivaldi to supported Chromium browsers
docs(readme): fix broken link to contributing guide
fix(scripts): detect bookmark format by content, not filename
```

One logical change per commit. Squash fixups before opening the PR.
