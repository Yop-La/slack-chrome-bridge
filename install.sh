#!/bin/sh
# One-step setup: registers the local bridge for the extension in this folder,
# and installs the `slack-chrome-bridge` command in ~/.local/bin.
set -eu

ROOT="$(cd "$(dirname "$0")" && pwd)"
BROWSER="${1:-chrome}"

if [ "$(uname)" != "Darwin" ]; then
  echo "Sorry, only macOS is supported for now." >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required (install it with: xcode-select --install)." >&2
  exit 1
fi

chmod +x "$ROOT/bridge/slack_chrome_bridge.py"
python3 "$ROOT/bridge/slack_chrome_bridge.py" install --browser "$BROWSER" >/dev/null

mkdir -p "$HOME/.local/bin"
ln -sf "$ROOT/bridge/slack_chrome_bridge.py" "$HOME/.local/bin/slack-chrome-bridge"

cat <<EOF

Bridge registered. Two steps left, in Chrome:

  1. Open chrome://extensions, turn on "Developer mode",
     click "Load unpacked" and choose this folder:
       $ROOT/extension

  2. Open your workspace in Slack Web (https://app.slack.com),
     then click the "Slack Chrome Bridge" icon. The badge shows OK.

Then check everything with:
  slack-chrome-bridge doctor

EOF
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) echo "Note: add ~/.local/bin to your PATH, or run $ROOT/bridge/slack_chrome_bridge.py directly." ;;
esac
