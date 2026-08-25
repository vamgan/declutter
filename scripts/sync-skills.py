#!/usr/bin/env python3
"""Vendor the shared references and scripts into each skill directory.

Why this exists: cross-agent installers (`npx skills add`) copy a skill's own
directory and nothing else. A skill that reads ../../../references/ works from a
git clone and silently loses every safety rule when installed any other way,
which is the worst failure this project could ship.

So `references/` and `scripts/` stay the single source of truth that humans edit
and tests run against, and this script copies what each skill needs into it.

  sync    copy shared files into every skill directory
  check   exit non-zero if any skill is out of date (used by CI)
"""
import argparse, filecmp, glob, hashlib, os, re, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Every skill needs the rules it cites and the resolver it calls.
ALWAYS = [
    ("references", "safe-mutation-rules.md"),
    ("references", "app-data-locations.md"),
    ("scripts", "platforms.py"),
]
# Anything else is pulled in only if the skill actually mentions it.
ON_DEMAND = [("scripts", "bookmarks.py"), ("scripts", "scan_tree.py")]


def skill_dirs():
    return sorted(os.path.dirname(p)
                  for p in glob.glob(os.path.join(ROOT, "skills", "*", "*", "SKILL.md")))


def wanted(skill_dir):
    body = open(os.path.join(skill_dir, "SKILL.md"), encoding="utf-8").read()
    files = list(ALWAYS)
    for kind, name in ON_DEMAND:
        if name in body:
            files.append((kind, name))
    return files


def digest(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def run(check_only):
    stale = []
    for skill in skill_dirs():
        keep = set()
        for kind, name in wanted(skill):
            src = os.path.join(ROOT, kind, name)
            dst = os.path.join(skill, kind, name)
            keep.add(os.path.relpath(dst, skill))
            if check_only:
                if not os.path.exists(dst) or digest(src) != digest(dst):
                    stale.append(os.path.relpath(dst, ROOT))
            else:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)

        # Remove vendored files the skill no longer references.
        for kind in ("references", "scripts"):
            d = os.path.join(skill, kind)
            if not os.path.isdir(d):
                continue
            for f in os.listdir(d):
                rel = os.path.join(kind, f)
                if rel in keep:
                    continue
                if check_only:
                    stale.append(os.path.relpath(os.path.join(skill, rel), ROOT) + " (orphan)")
                else:
                    os.remove(os.path.join(skill, rel))

    if check_only:
        if stale:
            print("Vendored copies are out of date:\n  " + "\n  ".join(stale))
            print("\nRun: python3 scripts/sync-skills.py sync")
            return 1
        print(f"All {len(skill_dirs())} skills are in sync.")
        return 0

    print(f"Synced {len(skill_dirs())} skills.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["sync", "check"])
    sys.exit(run(ap.parse_args().cmd == "check"))
