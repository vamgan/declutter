#!/usr/bin/env python3
"""Inventory a photo library without decoding a single image.

Everything here is read from file headers, so there are no dependencies and it
behaves the same on every platform. What that buys:

  * the real date a photo was taken, from EXIF, not the file's modified time,
    which any copy or sync will have destroyed
  * the camera, which separates real photographs from screenshots and saved images
  * dimensions, from the PNG and JPEG headers
  * bursts, from timestamps seconds apart rather than pixel comparison

What it deliberately does not do is judge whether two photos look alike. That
needs decoding, and guessing at it from file size would throw away pictures.

  scan <root> [--max-depth N]   inventory and group
  dates <root>                  date coverage only, a cheap first question

Stdlib only.
"""
import argparse, hashlib, json, os, re, struct, sys
from collections import defaultdict

PHOTO_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".gif", ".webp", ".tif",
             ".tiff", ".bmp", ".dng", ".raw", ".cr2", ".nef", ".arw"}
VIDEO_EXT = {".mov", ".mp4", ".m4v", ".avi", ".mkv", ".3gp"}

# How each platform names a screenshot. Filenames are the honest signal here;
# dimensions guess wrong on anyone with an unusual display.
SCREENSHOT_PATTERNS = [
    re.compile(r"^screen\s?shot\b", re.I),          # macOS, both spellings
    re.compile(r"^screenshot[_\s(-]", re.I),        # Windows, Android, Linux
    re.compile(r"^screenshot\.\w+$", re.I),
    re.compile(r"^screen_?capture", re.I),
    re.compile(r"^simulator screen shot", re.I),
    re.compile(r"^cleanshot", re.I),
]


def is_screenshot_name(name):
    return any(p.search(name) for p in SCREENSHOT_PATTERNS)


# ---------- header readers ----------

def _exif_from_jpeg(fh):
    """Pull DateTimeOriginal, Make and Model out of a JPEG's APP1 segment."""
    fh.seek(0)
    if fh.read(2) != b"\xff\xd8":
        return {}
    while True:
        marker = fh.read(2)
        if len(marker) < 2 or marker[0] != 0xFF:
            return {}
        if marker[1] in (0xD9, 0xDA):        # end of image, or start of scan
            return {}
        size_bytes = fh.read(2)
        if len(size_bytes) < 2:
            return {}
        size = struct.unpack(">H", size_bytes)[0] - 2
        if marker[1] == 0xE1:
            payload = fh.read(size)
            if payload[:6] != b"Exif\x00\x00":
                continue
            return _parse_tiff(payload[6:])
        fh.seek(size, os.SEEK_CUR)


def _parse_tiff(data):
    """Walk IFD0 and the Exif sub-IFD for the three tags worth having."""
    if len(data) < 8:
        return {}
    endian = "<" if data[:2] == b"II" else ">" if data[:2] == b"MM" else None
    if not endian:
        return {}
    try:
        first_ifd = struct.unpack(endian + "I", data[4:8])[0]
    except struct.error:
        return {}

    WANT = {0x9003: "date_taken", 0x0132: "date_modified",
            0x010F: "make", 0x0110: "model", 0xA002: "width", 0xA003: "height"}
    found, seen = {}, set()

    def walk(offset, depth=0):
        if depth > 2 or offset in seen or offset + 2 > len(data):
            return
        seen.add(offset)
        try:
            count = struct.unpack(endian + "H", data[offset:offset + 2])[0]
        except struct.error:
            return
        for i in range(count):
            entry = offset + 2 + i * 12
            if entry + 12 > len(data):
                return
            tag, typ, num = struct.unpack(endian + "HHI", data[entry:entry + 8])
            value_field = data[entry + 8:entry + 12]
            if tag == 0x8769:                     # pointer to the Exif sub-IFD
                walk(struct.unpack(endian + "I", value_field)[0], depth + 1)
                continue
            if tag not in WANT:
                continue
            if typ == 2:                          # ASCII
                start = struct.unpack(endian + "I", value_field)[0]
                raw = data[start:start + num - 1] if num > 4 else value_field[:num - 1]
                try:
                    found[WANT[tag]] = raw.decode("ascii", "ignore").strip("\x00 ")
                except Exception:
                    pass
            elif typ in (3, 4):                   # SHORT, LONG
                fmt = endian + ("H" if typ == 3 else "I")
                size = 2 if typ == 3 else 4
                found[WANT[tag]] = struct.unpack(fmt, value_field[:size])[0]

    walk(first_ifd)
    return found


def _png_size(fh):
    fh.seek(0)
    if fh.read(8) != b"\x89PNG\r\n\x1a\n":
        return None
    fh.seek(16)
    try:
        return struct.unpack(">II", fh.read(8))
    except struct.error:
        return None


def _jpeg_size(fh):
    fh.seek(2)
    while True:
        marker = fh.read(2)
        if len(marker) < 2 or marker[0] != 0xFF:
            return None
        if 0xC0 <= marker[1] <= 0xCF and marker[1] not in (0xC4, 0xC8, 0xCC):
            fh.seek(3, os.SEEK_CUR)
            try:
                h, w = struct.unpack(">HH", fh.read(4))
                return (w, h)
            except struct.error:
                return None
        size = fh.read(2)
        if len(size) < 2:
            return None
        fh.seek(struct.unpack(">H", size)[0] - 2, os.SEEK_CUR)


def read_header(path):
    """Everything obtainable without decoding the image."""
    ext = os.path.splitext(path)[1].lower()
    info = {"date_taken": None, "date_source": "file", "make": None,
            "model": None, "width": None, "height": None}
    try:
        with open(path, "rb") as fh:
            if ext in (".jpg", ".jpeg"):
                exif = _exif_from_jpeg(fh)
                stamp = exif.get("date_taken") or exif.get("date_modified")
                if stamp:
                    info["date_taken"] = stamp
                    info["date_source"] = "exif"
                info["make"] = exif.get("make")
                info["model"] = exif.get("model")
                size = _jpeg_size(fh)
                if size:
                    info["width"], info["height"] = size
            elif ext == ".png":
                size = _png_size(fh)
                if size:
                    info["width"], info["height"] = size
    except OSError:
        pass
    return info


def parse_exif_date(stamp):
    """EXIF writes 'YYYY:MM:DD HH:MM:SS'. Return (year, month, seconds)."""
    m = re.match(r"(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2}):(\d{2})", stamp or "")
    if not m:
        return None
    y, mo, d, h, mi, s = (int(x) for x in m.groups())
    if not (1970 <= y <= 2100):
        return None
    seconds = ((((y * 12 + mo) * 31 + d) * 24 + h) * 60 + mi) * 60 + s
    return y, mo, seconds


def digest(path, cap=1 << 20):
    h = hashlib.sha256()
    size = os.path.getsize(path)
    h.update(str(size).encode())
    with open(path, "rb") as fh:
        h.update(fh.read(cap))
        if size > cap * 2:
            fh.seek(-cap, os.SEEK_END)
            h.update(fh.read(cap))
    return h.hexdigest()[:16]


def scan(root, max_depth=None):
    root = os.path.expanduser(root)
    if not os.path.isdir(root):
        raise SystemExit(f"not a directory: {root}")

    photos, skipped = [], 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel = os.path.relpath(dirpath, root)
        depth = 1 if rel == "." else rel.count(os.sep) + 2
        if max_depth is not None and depth >= max_depth:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            ext = os.path.splitext(name)[1].lower()
            if ext not in PHOTO_EXT and ext not in VIDEO_EXT:
                continue
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                skipped += 1
                continue
            try:
                st = os.stat(full)
            except OSError:
                skipped += 1
                continue
            head = read_header(full) if ext in PHOTO_EXT else {
                "date_taken": None, "date_source": "file", "make": None,
                "model": None, "width": None, "height": None}
            photos.append({
                "path": os.path.relpath(full, root),
                "name": name,
                "ext": ext,
                "kind": "video" if ext in VIDEO_EXT else "photo",
                "size_bytes": st.st_size,
                "size_mb": round(st.st_size / 1e6, 2),
                "mtime": st.st_mtime,
                "screenshot": is_screenshot_name(name),
                **head,
            })

    # A photo with no camera and no EXIF date is not something a camera made.
    for p in photos:
        if p["screenshot"]:
            continue
        if p["ext"] == ".png" and not p["make"]:
            p["screenshot"] = None      # unknown, worth asking about

    dated = [p for p in photos if parse_exif_date(p["date_taken"])]
    by_period = defaultdict(int)
    for p in dated:
        y, mo, _ = parse_exif_date(p["date_taken"])
        by_period[f"{y}-{mo:02d}"] += 1

    # Bursts: same camera, timestamps within three seconds of each other.
    bursts, run = [], []
    ordered = sorted(dated, key=lambda p: parse_exif_date(p["date_taken"])[2])
    for p in ordered:
        secs = parse_exif_date(p["date_taken"])[2]
        if run and secs - parse_exif_date(run[-1]["date_taken"])[2] <= 3 \
                and p["model"] == run[-1]["model"]:
            run.append(p)
        else:
            if len(run) >= 3:
                bursts.append([x["path"] for x in run])
            run = [p]
    if len(run) >= 3:
        bursts.append([x["path"] for x in run])

    groups = defaultdict(list)
    for p in photos:
        if p["size_bytes"] > 0:
            try:
                groups[digest(os.path.join(root, p["path"]))].append(p["path"])
            except OSError:
                pass
    duplicates = [v for v in groups.values() if len(v) > 1]

    shots = [p for p in photos if p["screenshot"] is True]
    unsure = [p for p in photos if p["screenshot"] is None]
    cameras = defaultdict(int)
    for p in photos:
        if p["model"]:
            cameras[f"{(p['make'] or '').strip()} {p['model']}".strip()] += 1

    return {
        "root": root,
        "total": len(photos),
        "photos": sum(1 for p in photos if p["kind"] == "photo"),
        "videos": sum(1 for p in photos if p["kind"] == "video"),
        "total_size_mb": round(sum(p["size_mb"] for p in photos), 2),
        "skipped_symlinks": skipped,
        "with_real_date": len(dated),
        "without_real_date": len(photos) - len(dated),
        "by_month": dict(sorted(by_period.items())),
        "screenshots": len(shots),
        "screenshot_examples": [p["path"] for p in shots[:10]],
        "maybe_not_photographs": len(unsure),
        "cameras": dict(sorted(cameras.items(), key=lambda kv: -kv[1])),
        "burst_groups": len(bursts),
        "bursts": bursts[:15],
        "duplicate_groups": len(duplicates),
        "duplicates": duplicates[:20],
        "largest": sorted(photos, key=lambda p: -p["size_mb"])[:15],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("root")
    s.add_argument("--max-depth", type=int, default=None,
                   help="1 = the root's own files, 2 adds one level, and so on")
    d = sub.add_parser("dates")
    d.add_argument("root")

    args = ap.parse_args()
    result = scan(args.root, getattr(args, "max_depth", None))
    if args.cmd == "dates":
        result = {k: result[k] for k in
                  ("root", "total", "with_real_date", "without_real_date", "by_month")}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
