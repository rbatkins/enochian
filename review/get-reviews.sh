#!/usr/bin/env bash
# Gather independent critiques of Treaty from local model CLIs.
#
# Run this ON YOUR MACHINE (not in a cloud sandbox), from the repo root, where
# your codex / grok / glm / kimi CLIs and their API keys are configured.
#
#     bash review/get-reviews.sh
#
# It feeds review/REVIEW_PACKET.md to each model and writes review/out/<model>.md.
# CLI invocations vary by tool/version -- adjust the commands below to match how
# your CLIs actually read a prompt (stdin vs. an argument, flag names, etc.).

set -u
cd "$(dirname "$0")/.." || exit 1
PACKET="review/REVIEW_PACKET.md"
OUT="review/out"
mkdir -p "$OUT"

[ -f "$PACKET" ] || { echo "missing $PACKET"; exit 1; }

# Map of: label -> command that reads the prompt on stdin and prints a reply.
# EDIT the right-hand commands to match your installed CLIs.
run_one() {
  local label="$1"; shift
  echo ">> $label"
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "   (skipped: '$1' not found on PATH)"
    return
  fi
  # Prompt on stdin; capture stdout+stderr.
  if "$@" < "$PACKET" > "$OUT/$label.md" 2>&1; then
    echo "   wrote $OUT/$label.md"
  else
    echo "   $label exited non-zero (see $OUT/$label.md)"
  fi
}

# --- adjust these lines to your actual CLIs -------------------------------
# Common patterns shown; uncomment/edit the ones that match your tools.

# OpenAI Codex CLI (reads prompt as an arg in some versions):
# codex exec "$(cat "$PACKET")" > "$OUT/codex.md" 2>&1 && echo "wrote codex"
run_one codex codex exec

# xAI Grok CLI:
run_one grok grok

# Zhipu GLM CLI:
run_one glm glm

# Moonshot Kimi CLI:
run_one kimi kimi
# --------------------------------------------------------------------------

echo
echo "Done. Reviews (if any) are in $OUT/. Paste them back to Claude to fold in."
