# Contributing

Thanks for your interest. Issues and pull requests are welcome.

## Ground rules

- **Read-only stays read-only.** Pull requests that add a Slack method that writes (post, react, edit, delete, join, leave…) will not be merged. New read methods must be added to both allow-lists: `extension/validate.js` / `extension/worker.js` and `extension/slack-api.js`.
- **The token never leaves the tab.** No change may send the session token, or cookies, to the bridge, the terminal or the disk.
- **No dependencies** for the command line (Python standard library only) and the extension (plain JavaScript, no build step).

## Development setup

```bash
git clone https://github.com/Yop-La/slack-chrome-bridge.git
cd slack-chrome-bridge
make test
make lint
```

To try a change end to end, reload the unpacked extension in `chrome://extensions`, reload your Slack tab, click the extension icon, then run `python3 bridge/slack_chrome_bridge.py doctor`.

## Pull requests

- One topic per pull request.
- Add or update tests: `tests/test_bridge.py` for the command line, `tests/validate.test.mjs` for request validation.
- Update the README when you change a command or an error message.
- Describe how you tested it against a real Slack workspace, without pasting any message content or token.
