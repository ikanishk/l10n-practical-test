#!/usr/bin/env python3
"""Validate locale JSON files against the English source of truth.

For every locales/*.json file (other than the source) this reports:
  1. missing keys          - in the source but not in the locale
  2. extra keys            - in the locale but not in the source
  3. placeholder mismatch  - the {placeholders} differ from the source string
  4. empty values          - key present but translated as "" (or whitespace)
Plus two things json.load() would otherwise hide or crash on:
  - malformed / unreadable / non-UTF-8 files (reported, never a traceback)
  - duplicate keys inside one file (json.load silently keeps the last one)

Exit codes (so CI can tell "bad translations" from "tool could not run"):
  0  every locale is clean
  1  at least one problem was found in a locale file
  2  the check itself could not run (bad args, missing dir, broken source file)

Usage:
  python tools/check_locales.py
  python tools/check_locales.py --locales-dir path/to/locales
  python tools/check_locales.py --source en.json

Standard library only (Python 3.9+).
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

EXIT_OK = 0
EXIT_PROBLEMS = 1
EXIT_ERROR = 2

# A placeholder is {name}: one or more chars that are not braces.
# Doubled braces ({{ and }}) are treated as escaped literal braces (ICU /
# Python str.format convention) and are stripped before scanning.
PLACEHOLDER_RE = re.compile(r"\{[^{}]+\}")
ESCAPED_BRACE_RE = re.compile(r"\{\{|\}\}")

CHECKS = ("missing", "extra", "placeholders", "empty", "type")
CHECK_TITLES = {
    "missing": "Missing keys",
    "extra": "Extra keys",
    "placeholders": "Placeholder mismatches",
    "empty": "Empty values",
    "type": "Non-string values",
}


class LocaleFileError(Exception):
    """A locale file could not be read or parsed."""


def _reject_duplicates(pairs):
    """object_pairs_hook for json.load: fail on duplicate keys instead of
    silently keeping the last value."""
    seen = {}
    dupes = []
    for key, value in pairs:
        if key in seen:
            dupes.append(key)
        seen[key] = value
    if dupes:
        raise LocaleFileError("duplicate key(s): " + ", ".join(sorted(set(dupes))))
    return seen


def load_locale(path):
    """Read a JSON locale file and return a flat {key: value} dict.

    Raises LocaleFileError with a one-line, human-readable reason on any
    I/O, encoding or JSON problem.
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise LocaleFileError(f"cannot read file: {exc.strerror or exc}")

    if raw.startswith(b"\xef\xbb\xbf"):
        raise LocaleFileError("file starts with a UTF-8 BOM; save as UTF-8 without BOM")

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LocaleFileError(f"not valid UTF-8 (byte offset {exc.start})")

    try:
        data = json.loads(text, object_pairs_hook=_reject_duplicates)
    except json.JSONDecodeError as exc:
        raise LocaleFileError(f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}")

    if not isinstance(data, dict):
        raise LocaleFileError(f"top level must be a JSON object, got {type(data).__name__}")

    return flatten(data)


def flatten(data, prefix=""):
    """Flatten nested objects into dotted keys: {"a": {"b": "x"}} -> {"a.b": "x"}.
    The repo's files are already flat; this just keeps the tool honest if a
    nested file shows up."""
    flat = {}
    for key, value in data.items():
        full_key = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(flatten(value, prefix=f"{full_key}."))
        else:
            flat[full_key] = value
    return flat


def placeholders(text):
    """Return a Counter of the {placeholders} in a string.

    A Counter (multiset), not a set, so "{count} of {count}" vs "{count}" is
    caught as a mismatch too.
    """
    return Counter(PLACEHOLDER_RE.findall(ESCAPED_BRACE_RE.sub("", text)))


def fmt_placeholders(counter):
    return ", ".join(sorted(counter.elements())) or "(none)"


def compare(source, locale):
    """Compare one locale dict to the source dict.

    Returns {check_name: [message, ...]} for every check in CHECKS.
    """
    problems = {name: [] for name in CHECKS}

    problems["missing"] = sorted(source.keys() - locale.keys())
    problems["extra"] = sorted(locale.keys() - source.keys())

    for key in sorted(source.keys() & locale.keys()):
        src_value, loc_value = source[key], locale[key]

        if not isinstance(loc_value, str):
            problems["type"].append(f"{key}: expected a string, got {type(loc_value).__name__}")
            continue

        if not loc_value.strip():
            problems["empty"].append(key)
            continue  # an empty string is reported once, not also as a placeholder issue

        if isinstance(src_value, str):
            expected, found = placeholders(src_value), placeholders(loc_value)
            if expected != found:
                problems["placeholders"].append(
                    f"{key}: expected {fmt_placeholders(expected)}; found {fmt_placeholders(found)}"
                )

    return problems


def print_section(name, problems):
    count = sum(len(items) for items in problems.values())
    status = "OK" if count == 0 else f"{count} problem(s)"
    print(f"== {name}: {status} ==")
    for check in CHECKS:
        items = problems[check]
        if items:
            print(f"  {CHECK_TITLES[check]} ({len(items)}):")
            for item in items:
                print(f"    - {item}")
    print()
    return count


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Validate locale JSON files against the English source."
    )
    parser.add_argument(
        "--locales-dir",
        default="locales",
        type=Path,
        help="directory containing <locale>.json files (default: ./locales)",
    )
    parser.add_argument(
        "--source",
        default="en.json",
        help="file name of the source-of-truth locale inside --locales-dir (default: en.json)",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    locales_dir = args.locales_dir

    if not locales_dir.is_dir():
        print(f"ERROR: locales directory not found: {locales_dir}", file=sys.stderr)
        return EXIT_ERROR

    source_path = locales_dir / args.source
    if not source_path.is_file():
        print(f"ERROR: source file not found: {source_path}", file=sys.stderr)
        return EXIT_ERROR

    try:
        source = load_locale(source_path)
    except LocaleFileError as exc:
        # If the source of truth is broken, nothing else can be judged.
        print(f"ERROR: source file {source_path}: {exc}", file=sys.stderr)
        return EXIT_ERROR

    locale_files = sorted(p for p in locales_dir.glob("*.json") if p.name != args.source)

    print(f"Source: {source_path} ({len(source)} keys)")
    print(f"Checking {len(locale_files)} locale file(s) in {locales_dir}")
    print()

    if not locale_files:
        print("WARNING: no locale files found to check.")
        return EXIT_OK

    total = 0
    failing = []
    for path in locale_files:
        try:
            locale = load_locale(path)
        except LocaleFileError as exc:
            print(f"== {path.name}: UNREADABLE ==")
            print(f"  {exc}")
            print()
            total += 1
            failing.append(path.name)
            continue

        count = print_section(path.name, compare(source, locale))
        if count:
            total += count
            failing.append(path.name)

    print("-" * 60)
    print(f"TOTAL: {total} problem(s) in {len(failing)} of {len(locale_files)} locale file(s)")
    if failing:
        print(f"FAILED: {', '.join(failing)}")
        return EXIT_PROBLEMS
    print("PASSED: all locales match the source")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
