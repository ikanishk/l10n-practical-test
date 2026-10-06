#!/usr/bin/env bash
#
# run_checks.sh - pipeline wrapper around tools/check_locales.py
#
# Usage:
#   bash tools/run_checks.sh [LOCALES_DIR]
#   LOCALES_DIR=path/to/locales bash tools/run_checks.sh
#
# LOCALES_DIR defaults to "locales". A relative path is resolved against the
# repo root (not the caller's cwd), so the result is the same wherever the
# script is called from - the same thing Jenkins does from the workspace root.
#
# Writes the validator output to reports/locale-report.txt and the console,
# then exits with the validator's exit code:
#   0 = clean, 1 = locale problems found, 2 = validator could not run.
# Wrapper-level failures (no Python, missing dir, ...) also exit 2.

# -e: exit on any failing command   -u: unset variables are errors
# -o pipefail: a pipeline fails if ANY command in it fails, not just the last
set -euo pipefail

# Fail loudly: say where it died instead of exiting silently.
# Exit 2 so the caller can tell "wrapper broke" from "locales have problems" (1).
trap 'echo "ERROR: ${BASH_SOURCE[0]}:${LINENO}: command failed: ${BASH_COMMAND}" >&2; exit 2' ERR

die() {
    echo "ERROR: $*" >&2
    exit 2
}

# --- Resolve paths so the script works from any directory ------------------
# BASH_SOURCE[0] is this file's path as invoked ("tools/run_checks.sh",
# "run_checks.sh", "/abs/path/run_checks.sh"). Strip the file name with a
# parameter expansion (no dependency on dirname); cd -P resolves symlinks.
SCRIPT_PATH="${BASH_SOURCE[0]}"
if [[ "${SCRIPT_PATH}" == */* ]]; then SCRIPT_DIR="${SCRIPT_PATH%/*}"; else SCRIPT_DIR="."; fi
SCRIPT_DIR="$(cd -P -- "${SCRIPT_DIR}" && pwd)"
REPO_ROOT="$(cd -P -- "${SCRIPT_DIR}/.." && pwd)"
cd -- "${REPO_ROOT}"

LOCALES_DIR="${1:-${LOCALES_DIR:-locales}}"
SOURCE_FILE="en.json"
VALIDATOR="tools/check_locales.py"
REPORT_DIR="reports"
REPORT_FILE="${REPORT_DIR}/locale-report.txt"

# --- Find a usable Python (>= 3.9) ------------------------------------------
PYTHON=""
for candidate in python3 python; do
    if command -v "${candidate}" >/dev/null 2>&1 \
        && "${candidate}" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
        PYTHON="${candidate}"
        break
    fi
done
[[ -n "${PYTHON}" ]] || die "Python 3.9+ not found on PATH (tried python3, python). Install it and retry."

# --- Sanity-check inputs ------------------------------------------------------
[[ -f "${VALIDATOR}" ]]                   || die "validator not found: ${REPO_ROOT}/${VALIDATOR}"
[[ -d "${LOCALES_DIR}" ]]                 || die "locales directory not found: ${LOCALES_DIR}"
[[ -f "${LOCALES_DIR}/${SOURCE_FILE}" ]]  || die "source file not found: ${LOCALES_DIR}/${SOURCE_FILE}"

# Count keys with a real JSON parser (not grep - see notes on count_keys.sh).
# If en.json is malformed this fails and we report it clearly.
if ! KEY_COUNT="$("${PYTHON}" -c 'import json, sys; print(len(json.load(open(sys.argv[1], encoding="utf-8"))))' \
        "${LOCALES_DIR}/${SOURCE_FILE}" 2>/dev/null)"; then
    die "${LOCALES_DIR}/${SOURCE_FILE} is not valid JSON"
fi

# nullglob: an empty directory gives an empty array, not a literal "*.json".
shopt -s nullglob
LOCALE_FILES=("${LOCALES_DIR}"/*.json)
shopt -u nullglob

echo "Python      : $(command -v "${PYTHON}") ($("${PYTHON}" --version 2>&1))"
echo "Repo root   : ${REPO_ROOT}"
echo "Locales dir : ${LOCALES_DIR}"
echo "Keys in ${SOURCE_FILE}: ${KEY_COUNT}"
echo "Locale files found : ${#LOCALE_FILES[@]} (including ${SOURCE_FILE})"
echo "------------------------------------------------------------"

# --- Run the validator, tee to console + report ------------------------------
mkdir -p -- "${REPORT_DIR}"

# The validator is EXPECTED to exit non-zero when it finds problems, so
# switch off -e and the ERR trap for this one pipeline, then read each
# command's own status from PIPESTATUS.
set +e
trap - ERR
"${PYTHON}" "${VALIDATOR}" --locales-dir "${LOCALES_DIR}" --source "${SOURCE_FILE}" 2>&1 | tee "${REPORT_FILE}"
pipe_status=("${PIPESTATUS[@]}")
set -e
trap 'echo "ERROR: ${BASH_SOURCE[0]}:${LINENO}: command failed: ${BASH_COMMAND}" >&2; exit 2' ERR

validator_rc="${pipe_status[0]}"
tee_rc="${pipe_status[1]}"

# A tee failure means the report artifact is missing or incomplete, and CI
# would archive a misleading file - so treat it as a wrapper failure.
[[ "${tee_rc}" -eq 0 ]] || die "tee exited ${tee_rc}; ${REPORT_FILE} may be missing or incomplete"

echo "------------------------------------------------------------"
echo "Report written to ${REPORT_FILE}"
echo "Validator exit code: ${validator_rc}"
exit "${validator_rc}"
