#!/usr/bin/env bash
# Install the skill for local testing in Claude Code by linking it into ~/.claude/skills.
#   tools/install-local.sh            # personal skill (all projects)
#   tools/install-local.sh --project  # only in the current directory's project (.claude/skills)
#   tools/install-local.sh --remove   # remove the link
set -euo pipefail

SKILL=social-comments-analyzer
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/$SKILL"
DEST_DIR="$HOME/.claude/skills"
[[ "${1:-}" == "--project" ]] && DEST_DIR="$PWD/.claude/skills"
DEST="$DEST_DIR/$SKILL"

if [[ "${1:-}" == "--remove" ]]; then
  if [[ -L "$DEST" ]]; then rm "$DEST"; echo "Removed $DEST"; else echo "No link at $DEST"; fi
  exit 0
fi

mkdir -p "$DEST_DIR"
if [[ -e "$DEST" && ! -L "$DEST" ]]; then
  echo "error: $DEST exists and is not a link; move it away first" >&2
  exit 1
fi
ln -sfn "$SRC" "$DEST"
echo "Linked $DEST -> $SRC"
echo "Start Claude Code and ask, for example:"
echo "  Analyze the comments in examples/instagram-agensi.json and examples/tiktok-agensi.json and make an HTML report in Spanish"
