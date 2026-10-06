#!/usr/bin/env bash
# Quick and dirty key counter used by the release checklist.
# TODO: someone should really rewrite this.

FILE=$1
grep -c '":' "$FILE"
