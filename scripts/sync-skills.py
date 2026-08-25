#!/usr/bin/env python3
"""Vendor the shared references and scripts into each skill directory.

Why this exists: cross-agent installers (`npx skills add`) copy a skill's own
directory and nothing else. A skill that reads ../../../references/ works from a
git clone and silently loses every safety rule when installed any other way,
which is the worst failure this project could ship.

So `references/` and `scripts/` stay the single source of truth that humans edit
and tests run against, and this script copies what each skill needs into it.

  sync    copy shared files into every skill directory, and refresh the
          browser counts and lists that the README and the site publish
  check   exit non-zero if anything is out of date (used by CI)

Adding a browser should cost three lines in two files and this command.
Anything a human has to remember to update by hand will eventually be wrong,
which is why the published numbers are derived here rather than typed.
"""
import argparse, glob, hashlib, importlib.util, os, re, shutil, sys

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


NUMBER = {1:"One",2:"Two",3:"Three",4:"Four",5:"Five",6:"Six",7:"Seven",8:"Eight",
          9:"Nine",10:"Ten",11:"Eleven",12:"Twelve",13:"Thirteen",14:"Fourteen"}


def load_platforms():
    spec = importlib.util.spec_from_file_location(
        "platforms", os.path.join(ROOT, "scripts", "platforms.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def published(check_only):
    """Keep the numbers the README and the site advertise equal to the code."""
    pf = load_platforms()
    chromium = [a.capitalize() for a in pf.CHROMIUM]
    total = len(pf.CHROMIUM) + 1 + len(pf.FIREFOX)      # + Safari + Firefox family
    stale = []

    site_path = os.path.join(ROOT, "site", "index.html")
    site = open(site_path, encoding="utf-8").read()
    new_site = re.sub(r'(class="stat">)\d+(<)', r"\g<1>%d\g<2>" % total, site)
    chips = "".join('<span class="chip">%s</span>' % a for a in chromium)
    new_site = re.sub(r'(<dt>Chromium JSON</dt>\s*<dd>).*?(</dd>)',
                      lambda m: m.group(1) + chips + m.group(2), new_site, flags=re.S)

    readme_path = os.path.join(ROOT, "README.md")
    readme = open(readme_path, encoding="utf-8").read()
    new_readme = re.sub(r'\*\*\w+ browsers, one markdown file\.\*\*',
                        "**%s browsers, one markdown file.**" % NUMBER[total], readme)
    new_readme = re.sub(r'(\| Chromium `Bookmarks` JSON \| ).*?( \|)',
                        lambda m: m.group(1) + " \u00b7 ".join(chromium) + m.group(2),
                        new_readme)

    for path, old, new, label in ((site_path, site, new_site, "site/index.html"),
                                  (readme_path, readme, new_readme, "README.md")):
        if old == new:
            continue
        if check_only:
            stale.append(label + " (published browser count or list)")
        else:
            open(path, "w", encoding="utf-8").write(new)
    return stale


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

    stale += published(check_only)

    if check_only:
        if stale:
            print("Vendored copies are out of date:\n  " + "\n  ".join(stale))
            print("\nRun: python3 scripts/sync-skills.py sync")
            return 1
        print(f"All {len(skill_dirs())} skills and published counts are in sync.")
        return 0

    print(f"Synced {len(skill_dirs())} skills and the published browser counts.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["sync", "check"])
    sys.exit(run(ap.parse_args().cmd == "check"))
