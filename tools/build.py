#!/usr/bin/env python3
"""Validate the skill against Agensi's packaging rules and build the upload ZIP.

  python3 tools/build.py          # validate + write dist/social-comments-analyzer-<version>.zip
  python3 tools/build.py --check  # validate only (non-zero exit on errors)

The checks mirror the documented Agensi scan (docs/packaging, docs/review-and-approval):
frontmatter with name/description, name == folder, no executables, no dangerous
commands, no secrets, no env harvesting, no network calls, no obfuscation, no
prices in SKILL.md, script logic under ~20 KB, at most 10 tools.
"""
import argparse
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = "social-comments-analyzer"
SKILL_DIR = os.path.join(ROOT, SKILL)
DIST = os.path.join(ROOT, "dist")

BANNED_EXT = {".exe", ".dll", ".so", ".dylib", ".bin", ".app", ".dmg", ".msi", ".deb", ".rpm", ".wasm",
              ".class", ".jar", ".war"}
SKIP = {"__pycache__", ".DS_Store", ".git"}
CHECKS = [  # (level, label, regex) applied to every text file in the package
    ("fail", "dangerous command", r"os\.system\(|shell\s*=\s*True|chmod\s+777|rm\s+-rf\s+/|curl[^\n|]*\|\s*(ba)?sh"),
    ("fail", "dynamic code", r"(?<![\w.])(eval|exec|compile|__import__)\("),
    ("fail", "network access", r"^\s*(import|from)\s+(urllib|http\.client|socket|requests|httpx|aiohttp|ftplib|smtplib)\b"),
    ("fail", "environment access", r"os\.environ|os\.getenv|getenv\("),
    ("fail", "subprocess", r"^\s*(import|from)\s+subprocess\b"),
    ("fail", "secret", r"(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|EAA[A-Za-z0-9]{40,})"),
    ("warn", "base64", r"\bbase64\b"),
    ("warn", "sudo", r"\bsudo\b"),
]


def frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None
    fm = {}
    for line in m.group(1).splitlines():
        mm = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if mm:
            fm[mm.group(1)] = mm.group(2).strip()
    return fm


def package_files():
    for base, dirs, files in os.walk(SKILL_DIR):
        dirs[:] = sorted(d for d in dirs if d not in SKIP)
        for f in sorted(files):
            if f in SKIP or f.endswith(".pyc"):
                continue
            yield os.path.join(base, f)


def validate():
    errors, warnings = [], []
    path = os.path.join(SKILL_DIR, "SKILL.md")
    if not os.path.exists(path):
        return ["SKILL.md missing"], warnings, {}
    text = open(path, encoding="utf-8").read()
    fm = frontmatter(text)
    if fm is None:
        return ["SKILL.md has no frontmatter"], warnings, {}
    if fm.get("name") != SKILL:
        errors.append("frontmatter name %r must equal folder %r" % (fm.get("name"), SKILL))
    if not re.fullmatch(r"[a-z0-9-]+", fm.get("name", "")):
        errors.append("name must be lowercase letters, digits and hyphens")
    if len(fm.get("description", "")) < 40:
        errors.append("description missing or too short")
    if re.search(r"\$\s?\d", text):
        errors.append("SKILL.md must not contain prices")
    tools = re.findall(r"^- `([^`]+)`:", text.split("## Tools", 1)[-1].split("\n## ", 1)[0], re.M)
    if len(tools) > 10:
        errors.append("%d tools listed; Agensi allows 10" % len(tools))

    for f in package_files():
        rel = os.path.relpath(f, ROOT)
        if os.path.splitext(f)[1].lower() in BANNED_EXT:
            errors.append("%s: executable file type" % rel)
            continue
        try:
            body = open(f, encoding="utf-8").read()
        except UnicodeDecodeError:
            warnings.append("%s: not a text file (agents cannot read it)" % rel)
            continue
        for level, label, rx in CHECKS:
            for m in re.finditer(rx, body, re.M):
                line = body.count("\n", 0, m.start()) + 1
                (errors if level == "fail" else warnings).append("%s:%d: %s (%s)" % (rel, line, label, m.group(0).strip()))
        if f.endswith(".py"):
            if not os.access(f, os.X_OK):
                errors.append("%s: not executable (chmod +x)" % rel)
            # logic size: drop docstrings, comments and long data literals
            logic = re.sub(r'"""[\s\S]*?"""', "", body)
            # module-level data tables (UPPER_CASE = {...} / [...]) do not count, per Agensi's packaging guide
            logic = re.sub(r"^[A-Z_]+ = [\[{(][\s\S]*?^[\]})]\)?$", "", logic, flags=re.M)
            logic = "\n".join(l for l in logic.splitlines() if l.strip() and not l.strip().startswith("#"))
            if len(logic.encode()) > 20000:
                warnings.append("%s: ~%d bytes of logic (Agensi guideline: under 20 KB)" % (rel, len(logic.encode())))
            if re.search(r"open\([^)]*(\.\./|SKILL\.md|scripts/)", body):
                errors.append("%s: reads other package files; scripts run alone from a temp file" % rel)
    return errors, warnings, fm


def build(fm):
    os.makedirs(DIST, exist_ok=True)
    out = os.path.join(DIST, "%s-%s.zip" % (SKILL, fm.get("version", "0")))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in package_files():
            rel = os.path.relpath(f, SKILL_DIR)  # SKILL.md at the ZIP root
            info = zipfile.ZipInfo(rel, date_time=(2026, 1, 1, 0, 0, 0))
            info.external_attr = (0o755 if f.endswith(".py") else 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            with open(f, "rb") as fh:
                z.writestr(info, fh.read())
    size = os.path.getsize(out)
    if size > 50 * 1024 * 1024:
        print("error: ZIP over 50 MB", file=sys.stderr)
        return None
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    errors, warnings, fm = validate()
    for w in warnings:
        print("WARN  " + w)
    for e in errors:
        print("FAIL  " + e)
    if errors:
        return 1
    print("OK    %s %s passes the local checks" % (SKILL, fm.get("version")))
    if a.check:
        return 0
    out = build(fm)
    if not out:
        return 1
    with zipfile.ZipFile(out) as z:
        for n in z.namelist():
            print("      " + n)
    print("ZIP   %s (%.1f KB)" % (os.path.relpath(out, ROOT), os.path.getsize(out) / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
