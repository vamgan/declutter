#!/usr/bin/env python3
"""Read and rewrite browser bookmarks across Chromium, Safari, and Firefox.

Emits a normalized JSON summary so a skill never loads a raw bookmarks file.

  extract <path>              -> normalized JSON on stdout
  stats   <path>              -> counts only (duplicates, folders, depth)
  apply   <path> <plan.json>  -> apply a plan; requires --backup

Stdlib only. No install step.
"""
import argparse, json, os, plistlib, sqlite3, sys, shutil
from collections import defaultdict
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

TRACKING = {"utm_source","utm_medium","utm_campaign","utm_term","utm_content",
            "fbclid","gclid","mc_eid","ref","ref_src","igshid","si"}


def canon(url):
    """Canonical form for duplicate detection. Not for display or writing."""
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return url.strip().lower()
    q = urlencode([(k, v) for k, v in parse_qsl(p.query) if k.lower() not in TRACKING])
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = p.path.rstrip("/") or "/"
    return urlunsplit((p.scheme.lower().replace("http", "https"), host, path, q, ""))


def detect(path):
    """Sniff the format from content, not the filename.

    Profile directories, fixtures, and copies all use different names; the magic
    bytes do not lie.
    """
    try:
        with open(path, "rb") as fh:
            head = fh.read(16)
    except PermissionError:
        raise SystemExit(
            "Operation not permitted reading:\n  " + path +
            "\n\nmacOS is blocking this. Grant Full Disk Access to your terminal in\n"
            "System Settings > Privacy & Security > Full Disk Access, then retry."
        )
    except FileNotFoundError:
        raise SystemExit(f"no such bookmark store: {path}")
    if head.startswith(b"bplist"):
        return "safari"
    if head.startswith(b"SQLite format 3"):
        return "firefox"
    if head.lstrip()[:1] in (b"{", b"["):
        return "chromium"
    if os.path.basename(path).lower().endswith(".plist"):
        return "safari"  # XML plist
    raise SystemExit(f"unrecognized bookmark store: {path}")


# ---------- readers: each returns a flat list of nodes ----------

def read_chromium(path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    out = []

    def walk(node, folder, depth):
        if node.get("type") == "url":
            out.append({"id": node.get("guid") or node.get("id"), "kind": "url",
                        "title": node.get("name", ""), "url": node.get("url", ""),
                        "folder": folder, "depth": depth,
                        "added": node.get("date_added")})
        else:
            name = node.get("name", "")
            here = f"{folder}/{name}".strip("/") if name else folder
            if folder or name:
                out.append({"id": node.get("guid") or node.get("id"), "kind": "folder",
                            "title": name, "folder": folder, "depth": depth,
                            "count": len(node.get("children", []))})
            for child in node.get("children", []):
                walk(child, here, depth + 1)

    for root_name, root in data.get("roots", {}).items():
        if isinstance(root, dict) and "children" in root:
            for child in root.get("children", []):
                walk(child, root_name, 1)
    return out


def read_safari(path):
    with open(path, "rb") as fh:
        data = plistlib.load(fh)
    out = []

    def walk(node, folder, depth):
        t = node.get("WebBookmarkType")
        if t == "WebBookmarkTypeLeaf":
            uri = node.get("URLString", "")
            title = (node.get("URIDictionary") or {}).get("title", "")
            out.append({"id": node.get("WebBookmarkUUID"), "kind": "url",
                        "title": title, "url": uri, "folder": folder, "depth": depth})
        elif t in ("WebBookmarkTypeList", None):
            name = node.get("Title", "")
            here = f"{folder}/{name}".strip("/") if name else folder
            if name:
                out.append({"id": node.get("WebBookmarkUUID"), "kind": "folder",
                            "title": name, "folder": folder, "depth": depth,
                            "count": len(node.get("Children", []))})
            for child in node.get("Children", []) or []:
                walk(child, here, depth + 1)

    walk(data, "", 0)
    return out


def read_firefox(path):
    uri = f"file:{path}?immutable=1"
    con = sqlite3.connect(uri, uri=True)
    rows = con.execute("""
        SELECT b.id, b.type, b.title, p.url, b.parent, b.dateAdded
        FROM moz_bookmarks b LEFT JOIN moz_places p ON b.fk = p.id
    """).fetchall()
    con.close()
    names = {r[0]: (r[2] or "") for r in rows}
    parents = {r[0]: r[4] for r in rows}

    def folder_of(node_id):
        parts, seen = [], set()
        cur = parents.get(node_id)
        while cur and cur not in seen:
            seen.add(cur)
            if names.get(cur):
                parts.append(names[cur])
            cur = parents.get(cur)
        return "/".join(reversed(parts))

    out = []
    for nid, typ, title, url, _parent, added in rows:
        f = folder_of(nid)
        if typ == 1 and url:
            out.append({"id": nid, "kind": "url", "title": title or "", "url": url,
                        "folder": f, "depth": f.count("/") + 1, "added": added})
        elif typ == 2 and title:
            out.append({"id": nid, "kind": "folder", "title": title, "folder": f,
                        "depth": f.count("/") + 1})
    return out


READERS = {"chromium": read_chromium, "safari": read_safari, "firefox": read_firefox}


def load(path):
    fmt = detect(path)
    try:
        return fmt, READERS[fmt](path)
    except PermissionError:
        raise SystemExit(
            "Operation not permitted reading:\n  " + path +
            "\n\nmacOS is blocking this. Grant Full Disk Access to your terminal in\n"
            "System Settings > Privacy & Security > Full Disk Access, then retry."
        )


def summarize(nodes):
    urls = [n for n in nodes if n["kind"] == "url"]
    folders = [n for n in nodes if n["kind"] == "folder"]
    by_canon = defaultdict(list)
    for n in urls:
        by_canon[canon(n["url"])].append(n)
    dupes = {k: v for k, v in by_canon.items() if len(v) > 1}
    return {
        "total_bookmarks": len(urls),
        "total_folders": len(folders),
        "unique_urls": len(by_canon),
        "duplicate_groups": len(dupes),
        "duplicate_bookmarks": sum(len(v) - 1 for v in dupes.values()),
        "max_depth": max([n["depth"] for n in nodes], default=0),
        "single_item_folders": sum(1 for f in folders if f.get("count") == 1),
        "empty_folders": sum(1 for f in folders if f.get("count") == 0),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("extract", "stats"):
        s = sub.add_parser(name)
        s.add_argument("path")
    a = sub.add_parser("apply")
    a.add_argument("path")
    a.add_argument("plan")
    a.add_argument("--backup", required=True,
                   help="directory holding the pre-change copy; refuses to run without it")

    args = ap.parse_args()
    path = os.path.expanduser(args.path)

    if args.cmd in ("extract", "stats"):
        fmt, nodes = load(path)
        summary = summarize(nodes)
        if args.cmd == "stats":
            print(json.dumps({"format": fmt, **summary}, indent=2))
        else:
            print(json.dumps({"format": fmt, "summary": summary, "nodes": nodes},
                             indent=2))
        return

    # apply
    backup = os.path.expanduser(args.backup)
    stored = os.path.join(backup, os.path.basename(path))
    if not os.path.isfile(stored):
        raise SystemExit(
            f"refusing to write: no backup found at {stored}\n"
            "Back up the store before applying (safe-mutation-rules.md step 4)."
        )
    fmt = detect(path)
    if fmt != "chromium":
        raise SystemExit(f"apply not yet implemented for {fmt} — contributions welcome")

    with open(args.plan, encoding="utf-8") as fh:
        plan = json.load(fh)
    delete_ids = set(plan.get("delete", []))

    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    removed = [0]

    def prune(node):
        kids = []
        for child in node.get("children", []):
            ident = child.get("guid") or child.get("id")
            if child.get("type") == "url" and ident in delete_ids:
                removed[0] += 1
                continue
            if child.get("type") == "folder":
                prune(child)
            kids.append(child)
        node["children"] = kids

    for root in data.get("roots", {}).values():
        if isinstance(root, dict) and "children" in root:
            prune(root)

    data.pop("checksum", None)  # Chromium recomputes; a stale one is rejected
    tmp = path + ".declutter.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=3)
    shutil.move(tmp, path)
    print(json.dumps({"deleted": removed[0], "restore": f"cp '{stored}' '{path}'"},
                     indent=2))


if __name__ == "__main__":
    main()
