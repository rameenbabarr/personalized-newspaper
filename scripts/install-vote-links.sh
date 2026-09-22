#!/bin/sh
# Register this checkout as the handler for rameen-vote:// links, so clicking
# "more like this" / "less" in the PDF records the vote without a browser tab.
# Safe to re-run (e.g. after moving the repo). Undo with:
#   rm ~/.local/share/applications/rameen-vote.desktop
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY=$(command -v python3)
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APPS"

cat > "$APPS/rameen-vote.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Rameen Times vote
Comment=Records more/less votes clicked in the morning paper
Exec="$PY" -m src.taste.votelink %u
Path=$ROOT
NoDisplay=true
Terminal=false
MimeType=x-scheme-handler/rameen-vote;
DESKTOP

update-desktop-database "$APPS" 2>/dev/null || true
xdg-mime default rameen-vote.desktop x-scheme-handler/rameen-vote
echo "rameen-vote:// links now go to $ROOT"
