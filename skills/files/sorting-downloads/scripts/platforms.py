#!/usr/bin/env python3
"""Platform differences, in one place.

Skills and scripts ask this module where things live and how to do the three
operations that genuinely differ across operating systems: locating app data,
trashing a file, and checking whether an app is running.

  locate <app>        -> candidate store paths for this platform
  trash <path>        -> move to the platform's trash/recycle bin
  running <app>       -> is the app currently running?
  platform            -> what we detected, and how well it is supported

Stdlib only.
"""
import argparse, glob, json, os, shutil, subprocess, sys, time
from urllib.parse import quote

MAC, LINUX, WINDOWS = "darwin", "linux", "windows"


def system():
    if sys.platform.startswith("darwin"):
        return MAC
    if sys.platform.startswith("win"):
        return WINDOWS
    return LINUX


# Verified means: someone has actually run declutter end to end on it.
SUPPORT = {MAC: "verified", LINUX: "implemented, unverified",
           WINDOWS: "implemented, unverified"}


def home(*parts):
    return os.path.join(os.path.expanduser("~"), *parts)


def _appdata(kind="local"):
    """Windows app-data roots, with fallbacks if the env vars are missing."""
    if kind == "roaming":
        return os.environ.get("APPDATA") or home("AppData", "Roaming")
    return os.environ.get("LOCALAPPDATA") or home("AppData", "Local")


# Chromium family: one storage format, many vendors, three path conventions.
CHROMIUM = {
    "chrome":   {MAC: "Google/Chrome",              LINUX: "google-chrome",              WINDOWS: r"Google\Chrome\User Data"},
    "brave":    {MAC: "BraveSoftware/Brave-Browser", LINUX: "BraveSoftware/Brave-Browser", WINDOWS: r"BraveSoftware\Brave-Browser\User Data"},
    "edge":     {MAC: "Microsoft Edge",             LINUX: "microsoft-edge",             WINDOWS: r"Microsoft\Edge\User Data"},
    "chromium": {MAC: "Chromium",                   LINUX: "chromium",                   WINDOWS: r"Chromium\User Data"},
    "vivaldi":  {MAC: "Vivaldi",                    LINUX: "vivaldi",                    WINDOWS: r"Vivaldi\User Data"},
    "arc":      {MAC: "Arc/User Data",              LINUX: None,                         WINDOWS: r"Arc\User Data"},
    "opera":    {MAC: "com.operasoftware.Opera",    LINUX: "opera",                      WINDOWS: r"Opera Software\Opera Stable"},
}

FIREFOX = {
    "firefox": {MAC: home("Library", "Application Support", "Firefox", "Profiles"),
                LINUX: home(".mozilla", "firefox"),
                WINDOWS: os.path.join(_appdata("roaming"), "Mozilla", "Firefox", "Profiles")},
    "tor":     {MAC: home("Library", "Application Support", "TorBrowser-Data", "Browser"),
                LINUX: home(".local", "share", "torbrowser", "tbb"),
                WINDOWS: os.path.join(_appdata("roaming"), "tor browser")},
}

PROCESS_NAMES = {
    "chrome":   {MAC: "Google Chrome",   LINUX: "chrome",       WINDOWS: "chrome.exe"},
    "brave":    {MAC: "Brave Browser",   LINUX: "brave",        WINDOWS: "brave.exe"},
    "edge":     {MAC: "Microsoft Edge",  LINUX: "msedge",       WINDOWS: "msedge.exe"},
    "chromium": {MAC: "Chromium",        LINUX: "chromium",     WINDOWS: "chrome.exe"},
    "vivaldi":  {MAC: "Vivaldi",         LINUX: "vivaldi-bin",  WINDOWS: "vivaldi.exe"},
    "arc":      {MAC: "Arc",             LINUX: None,           WINDOWS: "Arc.exe"},
    "opera":    {MAC: "Opera",           LINUX: "opera",        WINDOWS: "opera.exe"},
    "firefox":  {MAC: "firefox",         LINUX: "firefox",      WINDOWS: "firefox.exe"},
    "safari":   {MAC: "Safari",          LINUX: None,           WINDOWS: None},
    "obsidian": {MAC: "Obsidian",        LINUX: "obsidian",     WINDOWS: "Obsidian.exe"},
}


def chromium_root(app):
    sysname = system()
    vendor = CHROMIUM.get(app, {}).get(sysname)
    if not vendor:
        return None
    if sysname == MAC:
        return home("Library", "Application Support", vendor)
    if sysname == LINUX:
        return home(".config", vendor)
    return os.path.join(_appdata("local"), vendor)


BLOCKED_HELP = {
    MAC: ("macOS is blocking access to this app's data.\n"
          "Grant Full Disk Access to your terminal in\n"
          "System Settings > Privacy & Security > Full Disk Access, then retry."),
    LINUX: "The current user cannot read this app's data directory. Check file permissions.",
    WINDOWS: "The current user cannot read this app's data directory. Check folder permissions.",
}


def _blocked(paths=None):
    return {"paths": paths or [], "blocked": True,
            "remediation": BLOCKED_HELP[system()]}


def _ok(paths):
    return {"paths": paths, "blocked": False, "remediation": None}


def locate(app):
    """Where this app's data lives on this platform.

    Returns {paths, blocked, remediation}. A permission denial is a normal,
    expected outcome here rather than an error: on macOS it is the single most
    common first-run result, and it deserves a sentence, not a traceback.
    """
    sysname = system()
    app = app.lower()

    if app in CHROMIUM:
        root = chromium_root(app)
        if not root:
            return _ok([])
        try:
            if not os.path.isdir(root):
                return _ok([])
            entries = sorted(os.listdir(root))
        except PermissionError:
            return _blocked()
        found = []
        for entry in entries:
            if entry == "Default" or entry.startswith("Profile "):
                p = os.path.join(root, entry, "Bookmarks")
                try:
                    if os.path.exists(p):
                        found.append(p)
                except PermissionError:
                    return _blocked(found)
        return _ok(found)

    if app == "safari":
        if sysname != MAC:
            return _ok([])          # Safari does not exist off macOS
        p = home("Library", "Safari", "Bookmarks.plist")
        try:
            return _ok([p] if os.path.exists(p) else [])
        except PermissionError:
            return _blocked()

    if app in FIREFOX:
        root = FIREFOX[app][sysname]
        if not root:
            return _ok([])
        try:
            return _ok(sorted(glob.glob(os.path.join(root, "*", "places.sqlite"))))
        except PermissionError:
            return _blocked()

    if app == "obsidian":
        if sysname == MAC:
            cfg = home("Library", "Application Support", "obsidian", "obsidian.json")
        elif sysname == LINUX:
            cfg = home(".config", "obsidian", "obsidian.json")
        else:
            cfg = os.path.join(_appdata("roaming"), "obsidian", "obsidian.json")
        try:
            if not os.path.exists(cfg):
                return _ok([])
            with open(cfg, encoding="utf-8") as fh:
                data = json.load(fh)
            return _ok([v["path"] for v in data.get("vaults", {}).values()
                        if os.path.isdir(v.get("path", ""))])
        except PermissionError:
            return _blocked()
        except (OSError, ValueError, KeyError):
            return _ok([])

    return _ok([])


def running(app):
    """True if the app is currently running. None if we cannot tell."""
    sysname = system()
    name = PROCESS_NAMES.get(app.lower(), {}).get(sysname)
    if not name:
        return None
    try:
        if sysname == WINDOWS:
            out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}"],
                                 capture_output=True, text=True, timeout=10)
            return name.lower() in out.stdout.lower()
        out = subprocess.run(["pgrep", "-x", name],
                             capture_output=True, text=True, timeout=10)
        return out.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return None


def trash(path):
    """Move a file to the platform's trash. Never unlinks."""
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(path):
        raise SystemExit(f"no such file: {path}")
    sysname = system()

    if sysname == MAC:
        dest_dir = home(".Trash")
        os.makedirs(dest_dir, exist_ok=True)
        return _move_unique(path, dest_dir)

    if sysname == LINUX:
        # FreeDesktop trash spec: the file moves to files/, and a .trashinfo
        # sidecar records where it came from so the file manager can restore it.
        base = os.environ.get("XDG_DATA_HOME") or home(".local", "share")
        files_dir = os.path.join(base, "Trash", "files")
        info_dir = os.path.join(base, "Trash", "info")
        os.makedirs(files_dir, exist_ok=True)
        os.makedirs(info_dir, exist_ok=True)
        dest = _move_unique(path, files_dir)
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        with open(os.path.join(info_dir, os.path.basename(dest) + ".trashinfo"),
                  "w", encoding="utf-8") as fh:
            fh.write(f"[Trash Info]\nPath={quote(path)}\nDeletionDate={stamp}\n")
        return dest

    # Windows: the Recycle Bin is not a directory you can move files into.
    # Moving into $Recycle.Bin by hand produces an entry Explorer cannot
    # restore. The shell API is the only correct route.
    return _windows_recycle(path)


def _move_unique(path, dest_dir):
    name = os.path.basename(path)
    dest = os.path.join(dest_dir, name)
    stem, ext = os.path.splitext(name)
    n = 1
    while os.path.exists(dest):
        dest = os.path.join(dest_dir, f"{stem} {n}{ext}")
        n += 1
    shutil.move(path, dest)
    return dest


def _windows_recycle(path):
    import ctypes
    from ctypes import wintypes

    FO_DELETE = 3
    FOF_ALLOWUNDO = 0x0040
    FOF_NOCONFIRMATION = 0x0010
    FOF_SILENT = 0x0004

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", ctypes.c_uint16),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    op = SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    op.pFrom = path + "\0\0"          # double-null terminated list
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if rc != 0 or op.fAnyOperationsAborted:
        raise SystemExit(
            f"could not move to Recycle Bin (SHFileOperationW returned {rc}).\n"
            "Nothing was deleted. Move the file manually instead."
        )
    return "Recycle Bin"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("locate", "running"):
        s = sub.add_parser(name)
        s.add_argument("app")
    t = sub.add_parser("trash")
    t.add_argument("path")
    sub.add_parser("platform")

    args = ap.parse_args()
    sysname = system()

    if args.cmd == "platform":
        print(json.dumps({"platform": sysname, "support": SUPPORT[sysname],
                          "needs_full_disk_access": sysname == MAC}, indent=2))
    elif args.cmd == "locate":
        result = locate(args.app)
        print(json.dumps({"app": args.app, "platform": sysname, **result}, indent=2))
        if result["blocked"]:
            raise SystemExit(2)
    elif args.cmd == "running":
        print(json.dumps({"app": args.app, "running": running(args.app)}, indent=2))
    else:
        print(json.dumps({"trashed_to": trash(args.path)}, indent=2))


if __name__ == "__main__":
    main()
