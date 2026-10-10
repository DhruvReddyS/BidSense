#!/usr/bin/env bash
# Restore and verify the primary corpus (Section 9.1).
#
# The four tender notifications are large public downloads, tracked as metadata
# rather than committed (data/.gitignore excludes data/**/*.pdf). That is a
# reasonable choice for 9MB of public PDFs and an unreasonable one without a
# record of WHERE they came from -- and `portal_source` was recorded as
# CONFIRM_ME for all four, so the primary data of this project could not be
# re-obtained by anyone, including its author. An evaluation whose inputs cannot
# be re-fetched is not reproducible however carefully its scripts are written.
#
# This closes that gap in two steps:
#
#   1. Whoever holds the PDFs records their checksums, once:
#        scripts/fetch_corpus.sh --record
#      This fills the sha256 column of data/corpus_sources.csv from the files
#      on disk, so the bytes behind every published figure become pinned. The
#      url column still has to be filled in by hand -- only the collector knows
#      which portal each document came from.
#
#   2. Anyone else restores and verifies:
#        scripts/fetch_corpus.sh
#      Each document is downloaded to data/notifications/ and its SHA-256 is
#      checked against the manifest. A mismatch fails loudly: a silently
#      different revision of a tender would change every number downstream.
#
# The same checksums appear in the evaluation manifest written by
# scripts/evaluate_all.py, so a reviewer can confirm that the corpus a figure
# was computed over is the corpus they just downloaded.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$ROOT/data/corpus_sources.csv"
TARGET="$ROOT/data/notifications"

if [[ ! -f "$MANIFEST" ]]; then
  echo "No manifest at $MANIFEST" >&2
  exit 1
fi

checksum() {
  if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1
  fi
}

# --- step 1: record checksums from files already on disk -------------------- #
if [[ "${1:-}" == "--record" ]]; then
  tmp="$(mktemp)"
  head -1 "$MANIFEST" > "$tmp"
  recorded=0 missing=0
  tail -n +2 "$MANIFEST" | while IFS=, read -r id portal url sha pages notes; do
    pdf="$TARGET/$id.pdf"
    if [[ -f "$pdf" ]]; then
      sha="$(checksum "$pdf")"
      recorded=$((recorded + 1))
      echo "  recorded  $id  $sha" >&2
    else
      echo "  MISSING   $id  (no $pdf)" >&2
      missing=$((missing + 1))
    fi
    echo "$id,$portal,$url,$sha,$pages,$notes"
  done >> "$tmp"
  mv "$tmp" "$MANIFEST"
  echo
  echo "Wrote checksums to $MANIFEST."
  echo "Now fill the url column by hand -- only you know the source portal."
  exit 0
fi

# --- step 2: fetch and verify ---------------------------------------------- #
mkdir -p "$TARGET"
failed=0 skipped=0 ok=0

tail -n +2 "$MANIFEST" | while IFS=, read -r id portal url sha pages notes; do
  pdf="$TARGET/$id.pdf"

  if [[ "$url" == "CONFIRM_ME" || -z "$url" ]]; then
    echo "SKIP  $id  -- no source URL recorded. Add it to $(basename "$MANIFEST")." >&2
    skipped=$((skipped + 1))
    continue
  fi

  if [[ ! -f "$pdf" ]]; then
    echo "FETCH $id  <- $url"
    if ! curl -fsSL --max-time 300 -o "$pdf" "$url"; then
      echo "FAIL  $id  -- download failed" >&2
      rm -f "$pdf"
      failed=$((failed + 1))
      continue
    fi
  fi

  if [[ "$sha" == "CONFIRM_ME" || -z "$sha" ]]; then
    echo "WARN  $id  -- present but unverified (no checksum in manifest)." >&2
    continue
  fi

  got="$(checksum "$pdf")"
  if [[ "$got" != "$sha" ]]; then
    echo "FAIL  $id  -- checksum mismatch." >&2
    echo "        expected $sha" >&2
    echo "        got      $got" >&2
    echo "      A different revision of a tender changes every figure" >&2
    echo "      downstream. Not using this file." >&2
    failed=$((failed + 1))
  else
    echo "OK    $id  verified"
    ok=$((ok + 1))
  fi
done

echo
echo "Next: cd backend && python -m scripts.bootstrap && python -m scripts.ingest"
echo "Then: python -m scripts.evaluate_all"
