# NOTES — L10n practical test

Branch: `feature/kanishk-locale-qa` · Shell used: **Bash** (macOS) · Python 3.9+ (stdlib only)

```bash
python3 tools/check_locales.py                 # validator
bash tools/run_checks.sh                       # CI wrapper -> reports/locale-report.txt
bash tools/run_checks.sh path/to/other/locales # or LOCALES_DIR=... bash tools/run_checks.sh
```

## Exit-code contract (used by all three layers)

| Code | Meaning | Jenkins result |
|---|---|---|
| 0 | all locales clean | SUCCESS |
| 1 | locale problems found | UNSTABLE (FAILURE if `STRICT=true`) |
| 2 | the tool could not run (bad path, broken `en.json`, no Python) | FAILURE |

Separating 1 from 2 is the point: "French is missing 6 strings" and "the
pipeline is broken" need different people to act.

## Task 1 — `tools/check_locales.py`

- Missing / extra keys: set difference on keys.
- Placeholders: regex `\{[^{}]+\}`, compared as a **multiset** (`Counter`), so
  `{count} of {count}` vs `{count}` is a mismatch, and renamed tokens
  (`{pct}`, `{prozent}`) or dropped ones (ja `battery.status`) are caught.
  Doubled braces `{{`/`}}` are treated as escaped literals and stripped first.
- Empty values: `""` or whitespace-only. An empty value is reported once, not
  also as a placeholder mismatch.
- Bad files never produce a traceback: unreadable, non-UTF-8, UTF-8 BOM,
  invalid JSON (with line/col), non-object top level, and **duplicate keys**
  (`json.load` silently keeps the last one — relevant to the merge below).
  A bad locale file is a problem (exit 1) and the other locales are still
  checked; a bad `en.json` is exit 2 because nothing can be judged without it.
- Non-string values reported; nested objects are flattened to dotted keys.

Known limits: ICU plural/select messages (`{count, plural, one {...}}`) have
nested braces and would need a real parser; placeholders are compared
exactly, so `{ percent }` ≠ `{percent}` (by design — "unchanged").

## Task 2 — `tools/run_checks.sh`

- `set -euo pipefail` + an `ERR` trap that prints the failing line and exits 2.
- Finds `python3` then `python`, and checks it is ≥ 3.9 before using it.
- Key count uses a real JSON parse (inline `python -c`), not grep.
- Validator output is `tee`'d to console and `reports/locale-report.txt`.
  `set -e`/trap are suspended for that one pipeline, and the validator's own
  status is read from `PIPESTATUS[0]` (with `pipefail` alone, `$?` could be
  tee's). A tee failure is treated as a wrapper failure (bad artifact).
- Resolves the repo root from `BASH_SOURCE[0]`, so it behaves the same from
  repo root, from `tools/`, or by absolute path. Relative `LOCALES_DIR` is
  resolved against the repo root.
- `.gitattributes` pins LF for `*.sh`/`Jenkinsfile` so CRLF can't reach CI.

### Opinion on `tools/count_keys.sh`

It counts **lines containing `":`**, not keys:
- Minified JSON (`{"a":"x","b":"y"}`) → reports **1**.
- Nested objects count the parent key as a key; any value containing `":` on
  its own line would be counted too.
- No argument check: with no arg it runs `grep` on `""` and prints a grep error.
- When the count is 0, `grep -c` exits 1 — a caller using `set -e` dies on a
  valid empty file.
- No strict mode, no JSON validation — malformed JSON gets a number anyway.

Fix: `python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1], encoding="utf-8"))))' "$FILE"`
with an argument check. I left the file unchanged so we can discuss it.

## Task 3 — `Jenkinsfile`

Stages: **Checkout → Validate → Report → Quality Gate**, `post` with
`success` / `unstable` / `failure` / `cleanup`.

- Parameters: `LOCALES_DIR` (default `locales`), `STRICT` (default false).
- Validate uses `sh(returnStatus: true)` so a non-zero exit doesn't abort the
  stage; the Report stage always archives the report, then Quality Gate sets
  the result. (If Validate failed the stage directly, Report would be skipped
  and the one artifact you need would be missing.)
- Unstable vs failed: translation gaps are normal mid-cycle and shouldn't
  block developers → UNSTABLE. Release branches / pre-merge gates run with
  `STRICT=true` → FAILURE. Tooling errors always FAIL.
- The shell command is a **single-quoted** Groovy string, so `$LOCALES_DIR`
  is expanded by the shell from the environment, not interpolated by Groovy —
  no command injection through the parameter.
- `skipDefaultCheckout(true)`: "Pipeline script from SCM" already checks out
  implicitly; this avoids checking out twice.

**How it was run:** <!-- TODO Kanishk: fill in after running on your Mac -->
Real Jenkins in Docker (OrbStack) per the README, job `l10n` pointed at
`file:///repo`, branch `*/feature/kanishk-locale-qa`.
Build #1: _result_ · Build #2 (`STRICT=true`): _result_ · screenshots in `docs/`.

## Task 4 — merge of `feature/de-locale`

Conflict in `locales/en.json`, two hunks (viewed with
`git checkout --conflict=diff3 locales/en.json` to see the merge base).

**Hunk 1** — base: `"battery.status": "Battery at {percent}%"`
- `nav.support` (main) and `nav.help` (de) → **kept both**. Different keys.
- `battery.status` → **picked main** (`"Battery: {percent}%"`), dropped
  `"Battery level: {percent}%"`. Keeping both lines = duplicate key, which
  `python -m json.tool` accepts silently (last wins) — my validator rejects it.
  Main's change is the deliberate source-copy edit; a translation branch
  shouldn't reword English source.
  *Question I'd ask UX/content: which wording is approved?*

**Hunk 2** — base: `"© {year} Lenovo. All rights reserved."`
- main changed the **legal entity** → "Lenovo Group Limited".
- de changed **© → the word "Copyright"**.
- **Kept main's line, with ©.** The entity change is a legal decision. The ©
  swap looks like a workaround for an encoding problem somewhere; the file
  is UTF-8, so that should be fixed in the tool, not the source string.
  (Keeping both lines naively also breaks JSON: the first line has no comma.)
  *Question for Legal/PM: correct entity for all markets? Is © acceptable?*

After resolving: no conflict markers, `en.json` parses, no duplicate keys;
the validator now flags `de.json` (4 missing keys, `{prozent}` vs
`{percent}`). I did not "fix" translations — they go back to linguists.
Any change to English source (e.g. `battery.status`) also makes existing
translations stale; a real pipeline would flag those for re-translation.

## What I'd add in a real pipeline

- Run on every PR touching `locales/**` (GitHub Actions `paths:` / Gerrit
  Verified vote); JUnit XML output so Jenkins shows per-locale test results.
- Detect **stale** translations (source changed after translation) via a
  source hash per key, and Android `strings.xml` / iOS `.strings` support.
- Pseudo-localization build to catch truncation/layout issues early.

## AI tools used — and what had to be corrected

Used: **Claude (Cowork)** to draft the scripts, Jenkinsfile and these notes;
I reviewed and ran everything. Issues caught while reviewing/testing the
generated output:

1. `run_checks.sh` used `dirname` to find its own directory — with a broken
   `PATH` the script died on `dirname` before it could print the real error
   ("Python not found"). Replaced with a `${BASH_SOURCE[0]%/*}` expansion.
2. The `ERR` trap was disabled around the validator pipeline and **never
   re-enabled**, so later failures would have exited silently. Restored it.
3. A first version special-cased tee's SIGPIPE (141) as "report still
   complete" — not true, tee stops writing on SIGPIPE. Made any tee failure
   fatal instead.
4. Jenkinsfile used `env.VALIDATOR_RC as int`; switched to `.toInteger()`,
   which is safer under the Groovy sandbox.
5. ERR-trap failures originally exited with the failing command's code
   (often 1 = "locale problems"), blurring the exit-code contract. Now 2.

<!-- TODO Kanishk: add anything YOU changed or questioned while reviewing. -->

## Unfinished / where I'd go next

- Jenkins evidence (see Task 3) — pending my local run.
- ICU plural/select placeholder parsing is not implemented (see Task 1 limits).
- No `run_checks.ps1`; I work in Bash.
