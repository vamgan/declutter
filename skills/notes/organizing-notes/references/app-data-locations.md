# App Data Locations

**This file is the reason one skill covers many apps.** A skill targets a *category*
and looks the path up here. Adding support for a new app is usually a row in a table.

> **Do not read paths out of this file by hand.** Ask the resolver, which knows the
> conventions for the platform it is running on and reports permission problems
> clearly instead of failing:
>
> ```bash
> python3 scripts/platforms.py locate chrome
> python3 scripts/platforms.py running chrome
> ```
>
> The tables below document what the resolver knows, so you can extend it.

---

## Platform support

| Platform | Status | App data root | Permission needed |
|---|---|---|---|
| macOS | verified | `~/Library/Application Support/` | **Full Disk Access** |
| Linux | implemented, unverified | `~/.config/` | none |
| Windows | implemented, unverified | `%LOCALAPPDATA%` and `%APPDATA%` | none |

macOS is the most restricted of the three. It is the only platform where reading an
app's own data files requires an explicit grant, and it is the most likely place for a
first run to stop with a permission message.

"Implemented, unverified" means the paths and platform logic are written and the
storage formats are identical, but nobody has yet run declutter end to end on that
platform. Doing so and reporting back is a genuinely useful contribution.

---

## Category: browser

### Chromium family

One storage format, many vendors, three path conventions. A skill written against this
row supports every app in it.

| App | macOS | Linux | Windows |
|---|---|---|---|
| Chrome | `Google/Chrome` | `google-chrome` | `Google\Chrome\User Data` |
| Brave | `BraveSoftware/Brave-Browser` | `BraveSoftware/Brave-Browser` | `BraveSoftware\Brave-Browser\User Data` |
| Edge | `Microsoft Edge` | `microsoft-edge` | `Microsoft\Edge\User Data` |
| Chromium | `Chromium` | `chromium` | `Chromium\User Data` |
| Vivaldi | `Vivaldi` | `vivaldi` | `Vivaldi\User Data` |
| Opera | `com.operasoftware.Opera` | `opera` | `Opera Software\Opera Stable` |
| Arc | `Arc/User Data` | not available | `Arc\User Data` |
| Whale | `Naver/Whale` | `naver-whale` | `Naver\Naver Whale\User Data` |

The bookmarks file is `<root>/<Profile>/Bookmarks`, where `<Profile>` is `Default` or
`Profile 1`, `Profile 2`, and so on. The resolver enumerates profiles; never assume
`Default` is the only one.

- **Must quit app to write:** **Yes, every platform.** Chromium rewrites this file on
  exit and will clobber external edits.
- **Parser:** `scripts/bookmarks.py`
- **Note:** a `Bookmarks.bak` sits alongside it. That is Chromium's own backup, not
  yours. Do not rely on it and do not overwrite it.

### Safari

macOS only. `~/Library/Safari/Bookmarks.plist`, a binary plist.

- **Must quit app to write:** Yes
- **Parser:** `scripts/bookmarks.py` (via `plistlib`)
- **Note:** Reading List lives in the same file under `com.apple.ReadingList`.

### Firefox family

| App | macOS | Linux | Windows |
|---|---|---|---|
| Firefox | `~/Library/Application Support/Firefox/Profiles/*/` | `~/.mozilla/firefox/*/` | `%APPDATA%\Mozilla\Firefox\Profiles\*\` |
| Tor Browser | `~/Library/Application Support/TorBrowser-Data/Browser/*/` | `~/.local/share/torbrowser/tbb/` | `%APPDATA%\tor browser\` |

Bookmarks live in `places.sqlite`, table `moz_bookmarks` joined to `moz_places`.

- **Must quit app to write:** **Yes.** SQLite WAL locking means writing to a live
  profile will fail or corrupt.
- **Parser:** `scripts/bookmarks.py`, opening the database read-only via
  `file:places.sqlite?immutable=1`

---

## Category: files

| Target | macOS and Linux | Windows |
|---|---|---|
| Desktop | `~/Desktop` | `%USERPROFILE%\Desktop` |
| Downloads | `~/Downloads` | `%USERPROFILE%\Downloads` |
| Documents | `~/Documents` | `%USERPROFILE%\Documents` |

### Cloud drives

Sync folders are ordinary directories, so the same skill covers them. `scan_tree.py`
reports which provider a path belongs to.

| Provider | Where it usually lives |
|---|---|
| iCloud Drive | `~/Library/Mobile Documents/`, and `~/iCloud Drive` |
| Dropbox | `~/Dropbox` |
| OneDrive | `~/OneDrive`, `%USERPROFILE%\OneDrive` |
| Google Drive | `~/Google Drive`, `~/Library/CloudStorage/GoogleDrive-*` |
| Box | `~/Box` |
| Nextcloud | `~/Nextcloud` |

Two hazards, both handled by `scan_tree.py`:

- **Placeholders.** Evicted files are left as stubs. Acting on one destroys its
  content. Reported as `placeholders_not_downloaded`.
- **Conflicted copies.** Every client names them differently and none clean up after
  themselves. Reported as `conflicts`, each paired with the original it competes with
  and flagged `same_content` so identical copies can be separated from ones holding
  work that exists nowhere else.

- **Permission:** Full Disk Access on macOS for all three. Nothing on Linux or Windows.
- **Parser:** `scripts/scan_tree.py`
- **Deletion:** never `rm`. Use `python3 scripts/platforms.py trash <path>`, which
  routes to `~/.Trash` on macOS, the FreeDesktop trash on Linux, and the Recycle Bin
  via the shell API on Windows. All three are restorable by the user's file manager.

---

## Category: media

Photos are ordinary files, so the locations are unremarkable. What matters is that the
**file's modified date is not when the photo was taken.** Copying, syncing, restoring a
backup, or receiving an image through a messaging app all rewrite it.

| Target | macOS | Linux | Windows |
|---|---|---|---|
| Pictures | `~/Pictures` | `~/Pictures` | `%USERPROFILE%\Pictures` |
| Screenshots | wherever the user set them, `~/Desktop` by default on macOS | `~/Pictures/Screenshots` | `%USERPROFILE%\Pictures\Screenshots` |
| Camera imports | `~/Pictures/<import folder>` | varies | `%USERPROFILE%\Pictures\Camera Roll` |

- **Permission:** Full Disk Access on macOS for `~/Pictures`
- **Parser:** `scripts/photos.py`, which reads EXIF dates, camera make and model, and
  image dimensions straight from file headers. It never decodes an image, so there are
  no dependencies and it behaves the same on every platform.

### Apple Photos library, not supported

`~/Pictures/Photos Library.photoslibrary` is a package with its own SQLite database.
Reaching inside it corrupts the library. Photos.app must be driven through AppleScript
instead. If a user points at one, say so and stop rather than treating it as a folder.

A folder **exported** from Photos.app is an ordinary folder and is fine.

---

## Category: notes

### Obsidian

Vault paths are listed in the Obsidian config file:

| Platform | Config |
|---|---|
| macOS | `~/Library/Application Support/obsidian/obsidian.json` |
| Linux | `~/.config/obsidian/obsidian.json` |
| Windows | `%APPDATA%\obsidian\obsidian.json` |

- **Permission:** none for a local vault. Full Disk Access on macOS if the vault sits
  in iCloud (`~/Library/Mobile Documents/iCloud~md~obsidian/`).
- **Must quit app to write:** No. Obsidian picks up external changes live.
- **Parser:** plain markdown, no script needed
- **Note:** `.obsidian/` holds config and must never be touched. Moving a note breaks
  `[[wikilinks]]` pointing at it unless they are updated in the same operation.

### Apple Notes

macOS only, and not yet supported.
`~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite`

- **Permission:** Full Disk Access **and** Automation (AppleScript) consent
- **Status:** reads are feasible. Writes must go through AppleScript, because the
  schema is protobuf embedded in SQLite and undocumented.

---

## Adding an app

1. Add a row here, and add the app to the matching table in `scripts/platforms.py`.
2. If it shares a format with an app already listed, **you are done.** Every existing
   skill in that category now covers it.
3. If the format is new, add a parser to `scripts/` and a fixture to `fixtures/`.
4. If you only know one platform's path, add that one. A partial row beats no row, as
   long as the others are marked unknown rather than guessed.
