#!/bin/sh
# One-step setup: registers the local bridge for the extension in this folder,
# and installs the `slack-chrome-bridge` command in ~/.local/bin.
#
# Usage: ./install.sh [chrome|chrome-beta|chromium|brave|edge]
set -eu

ROOT="$(cd "$(dirname "$0")" && pwd)"
BROWSER="${1:-chrome}"

if [ "$(uname)" != "Darwin" ]; then
  echo "Sorry, only macOS is supported for now." >&2
  exit 1
fi

# Pick a Python 3.9+ that will still exist later. Chrome starts the bridge with this exact
# interpreter, so avoid version-manager shims (pyenv, asdf) and virtualenvs that can change.
PYTHON=""
for candidate in /usr/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  if [ -x "$candidate" ] && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
    PYTHON="$candidate"
    break
  fi
done
if [ -z "$PYTHON" ]; then
  echo "Python 3.9 or later is required." >&2
  echo "Install the Xcode command line tools (xcode-select --install), then run this script again." >&2
  exit 1
fi
# /usr/bin/python3 is a stub until the command line tools are installed: resolve the real binary.
PYTHON="$("$PYTHON" -c 'import sys; print(sys.executable)')"

# A clone made through a browser download can carry the quarantine flag: remove it.
xattr -dr com.apple.quarantine "$ROOT" 2>/dev/null || true
chmod +x "$ROOT/bridge/slack_chrome_bridge.py"

"$PYTHON" "$ROOT/bridge/slack_chrome_bridge.py" install --browser "$BROWSER" >/dev/null

mkdir -p "$HOME/.local/bin"
ln -sf "$ROOT/bridge/slack_chrome_bridge.py" "$HOME/.local/bin/slack-chrome-bridge"

cat <<EOF

Bridge registered for $BROWSER (Python: $PYTHON).

Two steps left, in your browser:

  1. Open chrome://extensions, turn on "Developer mode",
     click "Load unpacked" and choose this folder:
       $ROOT/extension
     (Keep this folder where it is: the extension and the bridge use it.)

  2. Open your workspace in Slack Web (https://app.slack.com),
     then click the "Slack Chrome Bridge" icon. The badge shows OK.
     If you do not see the icon, open the puzzle-piece menu and pin it.

Then check everything with:
  slack-chrome-bridge doctor

EOF
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *)
    echo "Note: ~/.local/bin is not on your PATH yet. Add it with:"
    echo "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc && source ~/.zshrc"
    echo "or run $ROOT/bridge/slack_chrome_bridge.py directly."
    ;;
esac
