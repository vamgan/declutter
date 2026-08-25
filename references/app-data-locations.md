# App Data Locations

**This file is the reason one skill covers many apps.** A skill targets a *category*
and looks the path up here. Adding support for a new app is usually a row in a table.

`~` is the user's home directory. All paths are macOS. Linux and Windows columns are
[open for contribution](../docs/ADDING-A-SKILL.md).

---

## Category: browser

### Chromium family — `Bookmarks` (JSON)

One format, six apps. A skill written against this row supports all of them.

| App | Vendor directory |
|---|---|
| Google Chrome | `Google/Chrome` |
| Brave | `BraveSoftware/Brave-Browser` |
| Microsoft Edge | `Microsoft Edge` |
| Arc | `Arc/User Data` |
| Chromium | `Chromium` |
| Vivaldi | `Vivaldi` |

```
~/Library/Application Support/<vendor>/<Profile>/Bookmarks
```

`<Profile>` is `Default`, or `Profile 1`, `Profile 2`… for secondary profiles.
Enumerate with `ls` rather than assuming `Default` is the only one.

- **Permission:** Full Disk Access
- **Must quit app to write:** **Yes.** Chromium rewrites this file on exit and will
  clobber external edits.
- **Parser:** `scripts/bookmarks.py`
- **Note:** a `Bookmarks.bak` sits alongside it — that is Chromium's own backup, not
  yours. Do not rely on it and do not overwrite it.

### Safari — `Bookmarks.plist` (binary plist)

```
~/Library/Safari/Bookmarks.plist
```

- **Permission:** Full Disk Access
- **Must quit app to write:** Yes
- **Parser:** `scripts/bookmarks.py` (via `plistlib`)
- **Note:** Reading List lives in the same file under a `com.apple.ReadingList` key.

### Firefox family — `places.sqlite`

| App | Profile directory |
|---|---|
| Firefox | `~/Library/Application Support/Firefox/Profiles/*/` |
| Tor Browser | `~/Library/Application Support/TorBrowser-Data/Browser/*/` |

- **Permission:** Full Disk Access
- **Must quit app to write:** **Yes.** SQLite WAL locking — writes to a live profile
  will fail or corrupt.
- **Parser:** `scripts/bookmarks.py` (via `sqlite3`)
- **Note:** open the DB read-only for extraction:
  `file:places.sqlite?immutable=1`. Bookmarks are in `moz_bookmarks` joined to
  `moz_places`.

---

## Category: files

| Target | Path |
|---|---|
| Desktop | `~/Desktop` |
| Downloads | `~/Downloads` |
| Documents | `~/Documents` |

- **Permission:** Full Disk Access for Desktop/Documents/Downloads on modern macOS
- **Must quit app:** No
- **Parser:** `scripts/scan_tree.py`
- **Trash:** deletion means moving to `~/.Trash`, which supports Finder's "Put Back".
  Never `rm`.

---

## Category: notes

### Obsidian — markdown vault

Vault paths are listed in:

```
~/Library/Application Support/obsidian/obsidian.json
```

- **Permission:** none for a local vault; Full Disk Access if the vault is in iCloud
  (`~/Library/Mobile Documents/iCloud~md~obsidian/Documents`)
- **Must quit app to write:** No — Obsidian picks up external file changes live
- **Parser:** plain markdown; no script needed
- **Note:** `.obsidian/` holds config and must never be touched. Moving a note breaks
  `[[wikilinks]]` pointing at it unless they are updated too.

### Apple Notes — *not yet supported*

```
~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite
```

- **Permission:** Full Disk Access **and** Automation (AppleScript) consent
- **Status:** reads are feasible; writes must go through AppleScript because the
  schema is protobuf-in-SQLite and undocumented. Tracked as the next adapter.

---

## Adding an app

1. Add a row here — path, permission, whether the app must be quit, which parser.
2. If it shares a format with an app already listed, **you are done.** Every existing
   skill in that category now covers it.
3. If the format is new, add a parser to `scripts/` and a fixture to `fixtures/`.
