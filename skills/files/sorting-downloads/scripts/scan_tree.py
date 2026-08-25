#!/usr/bin/env python3
"""Inventory a directory: sizes, ages, extensions, duplicate content.

Emits a compact JSON summary so a skill never loads a raw recursive listing.

  scan <root> [--max-depth N] [--min-size-mb N]
              --max-depth 1 scans only files directly in <root>;
              2 adds one level of subdirectories, and so on.
  plan-check <root> <plan.json>     verify every path in a plan stays inside root

Refuses to touch anything on the denylist. Never follows symlinks out of root.
Stdlib only.
"""
import argparse, hashlib, json, os, time
from collections import defaultdict

DENY_NAMES = {".ssh", ".gnupg", ".aws", ".config", ".kube", "Library"}

CATEGORIES = {
    "image": {".png",".jpg",".jpeg",".gif",".heic",".webp",".svg",".tiff"},
    "video": {".mp4",".mov",".mkv",".avi",".webm"},
    "audio": {".mp3",".wav",".m4a",".flac",".aac"},
    "document": {".pdf",".doc",".docx",".txt",".md",".rtf",".pages"},
    "spreadsheet": {".xls",".xlsx",".csv",".numbers"},
    "presentation": {".ppt",".pptx",".key"},
    "archive": {".zip",".tar",".gz",".dmg",".pkg",".7z",".rar"},
    "code": {".py",".js",".ts",".tsx",".go",".rs",".java",".c",".cpp",".sh",".json"},
    "installer": {".dmg",".pkg",".app"},
}
EXT_TO_CAT = {e: c for c, exts in CATEGORIES.items() for e in exts}


def denied(path, root):
    """True if path escapes root or touches a denylisted location."""
    real_root = os.path.realpath(root)
    real = os.path.realpath(path)
    if not (real == real_root or real.startswith(real_root + os.sep)):
        return True
    rel = os.path.relpath(real, real_root)
    parts = rel.split(os.sep)
    if any(p in DENY_NAMES for p in parts):
        return True
    if parts and parts[0].startswith(".") and parts[0] != ".":
        return True   # dotfile at the root of the scanned tree
    return False


def digest(path, cap=1 << 20):
    """Hash first + last 1 MB plus size — enough to find real duplicates cheaply."""
    h = hashlib.sha256()
    size = os.path.getsize(path)
    h.update(str(size).encode())
    with open(path, "rb") as fh:
        h.update(fh.read(cap))
        if size > cap * 2:
            fh.seek(-cap, os.SEEK_END)
            h.update(fh.read(cap))
    return h.hexdigest()[:16]


def scan(root, max_depth, min_size_mb):
    root = os.path.expanduser(root)
    if not os.path.isdir(root):
        raise SystemExit(f"not a directory: {root}")
    now = time.time()
    files, skipped = [], 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        # depth 1 is the root itself, so --max-depth 1 means "root files only"
        rel = os.path.relpath(dirpath, root)
        depth = 1 if rel == "." else rel.count(os.sep) + 2
        if max_depth is not None and depth >= max_depth:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames if not denied(os.path.join(dirpath, d), root)]
        for name in filenames:
            full = os.path.join(dirpath, name)
            if denied(full, root) or os.path.islink(full):
                skipped += 1
                continue
            try:
                st = os.stat(full)
            except OSError:
                skipped += 1
                continue
            ext = os.path.splitext(name)[1].lower()
            files.append({
                "path": os.path.relpath(full, root),
                "name": name,
                "ext": ext,
                "category": EXT_TO_CAT.get(ext, "other"),
                "size_bytes": st.st_size,
                "size_mb": round(st.st_size / 1e6, 2),
                "age_days": int((now - st.st_mtime) / 86400),
            })

    by_cat, by_age = defaultdict(lambda: {"count": 0, "size_mb": 0.0}), defaultdict(int)
    for f in files:
        c = by_cat[f["category"]]
        c["count"] += 1
        c["size_mb"] = round(c["size_mb"] + f["size_mb"], 2)
        a = f["age_days"]
        bucket = "0-7d" if a < 7 else "7-30d" if a < 30 else "30-90d" if a < 90 else \
                 "90-365d" if a < 365 else "over-1y"
        by_age[bucket] += 1

    big = sorted((f for f in files if f["size_mb"] >= min_size_mb),
                 key=lambda f: -f["size_mb"])[:25]

    groups = defaultdict(list)
    for f in files:
        if f["size_bytes"] > 0:   # empty files are not meaningful duplicates
            try:
                groups[digest(os.path.join(root, f["path"]))].append(f["path"])
            except OSError:
                pass
    dupes = {k: v for k, v in groups.items() if len(v) > 1}

    return {
        "root": root,
        "total_files": len(files),
        "total_size_mb": round(sum(f["size_mb"] for f in files), 2),
        "skipped_denied_or_symlink": skipped,
        "by_category": dict(by_cat),
        "by_age": dict(by_age),
        "largest": big,
        "duplicate_groups": len(dupes),
        "duplicate_wasted_mb": round(sum(
            sum(f["size_mb"] for f in files if f["path"] == p)
            for v in dupes.values() for p in v[1:]), 4),
        "duplicates": [v for v in dupes.values()][:20],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("root")
    s.add_argument("--max-depth", type=int, default=None,
                   help="1 = root files only, 2 = one level of subdirectories, etc.")
    s.add_argument("--min-size-mb", type=float, default=50.0)
    c = sub.add_parser("plan-check")
    c.add_argument("root")
    c.add_argument("plan")

    args = ap.parse_args()
    if args.cmd == "scan":
        print(json.dumps(scan(args.root, args.max_depth, args.min_size_mb), indent=2))
        return

    root = os.path.expanduser(args.root)
    plan = json.load(open(args.plan, encoding="utf-8"))
    bad = []
    for move in plan.get("moves", []):
        for key in ("from", "to"):
            p = os.path.join(root, move[key])
            if denied(p, root):
                bad.append({"action": "move", key: move[key], "reason": "escapes root or denylisted"})
    print(json.dumps({"ok": not bad, "violations": bad}, indent=2))
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
