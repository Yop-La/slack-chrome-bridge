# Slack Chrome Bridge

Read-only Slack access from the command line, using the Slack Web session you already have open in Chrome.

Search messages, read threads and channel history, and download shared files, as JSON. No Slack app, no bot, no token to copy or refresh.

```console
$ slack-chrome-bridge search 'deploy in:#ops after:2026-11-01' --count 5
{
  "total": 42,
  "messages": [
    {
      "date": "2026-11-18 14:05",
      "user": "Ada Lovelace",
      "channel": "ops",
      "text": "Deploy of v2.3 is done, monitoring for 30 min",
      "permalink": "https://acme.slack.com/archives/C0123ABCD/p1795021500123456"
    }
  ]
}
```

It was built to let a coding agent (Claude Code, Codex...) look things up in Slack for you, but it works just as well in a terminal or a script.

## Quickstart (2 minutes, macOS)

```bash
git clone https://github.com/Yop-La/slack-chrome-bridge.git ~/slack-chrome-bridge
~/slack-chrome-bridge/install.sh
```

Then, in Chrome:

1. Open `chrome://extensions`, turn on **Developer mode**, click **Load unpacked**, and choose the `~/slack-chrome-bridge/extension` folder.
2. Open your workspace in [Slack Web](https://app.slack.com) and click the **Slack Chrome Bridge** icon. The badge shows **OK**.

Done. Try it:

```bash
slack-chrome-bridge doctor
slack-chrome-bridge search 'hello' --count 3
```

Requirements: macOS, Chrome (or Brave, Edge, Chromium) with Developer mode allowed, Python 3.9+ (preinstalled with the Xcode command line tools), and a Slack account signed in to Slack Web. Using another browser? Run `install.sh brave` (or `edge`, `chromium`, `chrome-beta`).

## Why

Reading Slack programmatically usually needs a Slack app with OAuth scopes, approved by a workspace admin. That is often not an option on a corporate workspace, and copying session cookies into scripts is fragile and unsafe.

This tool takes a third way: it asks your browser tab to make the request. Slack Web already makes these API calls for you, with your session. The extension makes the same calls, from the same tab, and hands the result to your terminal. Your session token stays inside the tab.

## How it works

```
terminal                  local bridge               Chrome extension            Slack Web tab
slack-chrome-bridge ──▶  named pipe (0600)  ──▶     Native Messaging   ──▶     fetch(api/…)
     ◀── JSON ──────────────────◀────────────────────────◀──────────────────── with your session
```

1. The command writes a request (operation + parameters) to a named pipe in a directory only your account can access.
2. The bridge, started by Chrome through [Native Messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging), forwards it to the extension. Only this extension is allowed to start the bridge.
3. The extension checks the request against a fixed list of read-only operations, then injects a small function into your Slack Web tab.
4. That function reads the session Slack Web keeps in the page and calls the Slack Web API, like Slack Web does. Chrome adds the session cookie.
5. The answer travels back the same way. Fields that could contain a token are removed before it leaves the tab.

More details in [docs/architecture.md](docs/architecture.md).

## Features

| Command | What it does | Slack API method |
|---|---|---|
| `search` | Search messages, with Slack's search modifiers (`from:`, `in:`, `after:`, `has:`…) and paging | `search.messages` |
| `thread` | Read a full thread from a channel ID and a message timestamp | `conversations.replies` |
| `link` | Read the thread behind any Slack permalink | `conversations.replies` |
| `history` | Read a channel over a time range | `conversations.history` |
| `file` | Download a shared file, and extract its text for PDFs and text files | `files.info` + file download |
| `doctor` | Check every link of the chain and say what to fix | |

User IDs in authors and mentions are replaced with names. Names are cached locally.

**Read-only by design.** The extension and the injected code each refuse any method outside the list above. Nothing can post, react, edit or delete.

## Prerequisites

- **macOS** (the installer targets macOS paths; Linux and Windows are not supported yet).
- **Google Chrome** or another Chromium browser (Chrome Beta, Chromium, Brave, Edge) where you can load an unpacked extension (Developer mode). On a managed browser, check that your IT policy allows it.
- **Python 3.9+**, standard library only, no package to install.
- **A Slack account** signed in to Slack Web (`app.slack.com`) in that browser profile.
- Optional: **`pdftotext`** to extract text from PDFs (`brew install poppler`).
- Optional, to run the tests: **Node.js 18+**.

## Manual installation

`install.sh` does three things. You can do them by hand instead:

1. **Register the bridge** for the extension folder. The extension ID is computed from the folder path, so it matches what Chrome shows:

   ```bash
   python3 bridge/slack_chrome_bridge.py install            # or: install <EXTENSION_ID> --browser brave
   ```

   If you load the extension from another folder, or Chrome shows another ID, pass that ID explicitly.

2. **Load the extension**: `chrome://extensions`, **Developer mode**, **Load unpacked**, pick the `extension` folder.

3. **Link your workspace**: open it in Slack Web, click the extension icon.

Optional: put the command on your PATH (`install.sh` links it in `~/.local/bin`).

```bash
ln -s "$PWD/bridge/slack_chrome_bridge.py" ~/.local/bin/slack-chrome-bridge
```

## Usage

```bash
# Search: Slack modifiers work as in the Slack search bar
slack-chrome-bridge search 'incident from:me after:2026-10-01' --count 20 --sort timestamp
slack-chrome-bridge search '"post mortem" in:#ops' --page 2

# Read the thread behind a link copied from Slack ("Copy link")
slack-chrome-bridge link 'https://acme.slack.com/archives/C0123ABCD/p1795021500123456'

# Read a thread from its channel ID and parent timestamp
slack-chrome-bridge thread C0123ABCD 1795021500.123456

# Read a channel over a period (Unix timestamps)
slack-chrome-bridge history C0123ABCD --oldest 1793491200 --latest 1794096000 --limit 200

# Download a file shared in a message (its ID is in the "files" field of the output)
slack-chrome-bridge file F0123ABCDEF
```

- Output is JSON on stdout, errors on stderr with exit code 1.
- `--raw` returns the full Slack API answer instead of the compact form.
- Files are saved to `~/.cache/slack-chrome-bridge/files/` (or `--out DIR`), readable by your account only. For PDFs and text files, a `.txt` with the extracted text is saved next to them.

## Use with a coding agent

The [`skills/`](skills) folder contains two ready-made [Claude Code skills](https://docs.claude.com/en/docs/claude-code/skills):

- `slack-search`: turns a question into Slack searches and returns a table of messages with links.
- `slack-thread`: reads a thread from a link, follows attachments, and summarizes decisions and open points.

Copy them into `~/.claude/skills/` and allow the command in your Claude Code settings:

```json
{ "permissions": { "allow": ["Bash(slack-chrome-bridge:*)"] } }
```

Other agents can call the command directly: it is a plain CLI with JSON output.

## Security

Read [SECURITY.md](SECURITY.md) before installing. In short:

- **The extension acts with your Slack session.** It can read what you can read. Only load code you have reviewed, and do not install extensions you do not trust next to it.
- **It cannot write.** Every request is checked twice (in the extension and in the tab) against a list of read-only methods.
- **The token stays in the tab.** It is never sent to the bridge, the terminal or the disk.
- **No network port is opened.** The bridge uses Chrome Native Messaging and named pipes private to your account.
- **This uses Slack Web's internal API**, not the public OAuth flow. It is not endorsed by Slack, may break when Slack changes its web client, and may not be allowed by your workspace policy. You are responsible for checking that.
- **Message content is data.** If you feed results to an AI agent, treat message text as untrusted input (prompt injection).

## Troubleshooting

Run `slack-chrome-bridge doctor` first. Common errors:

| Error | Cause | Fix |
|---|---|---|
| `Chrome bridge unavailable` | The bridge is not running | Open Slack Web and click the extension icon |
| `Specified native messaging host not found` (in the extension's console) | Bridge not registered, or registered for another extension ID | Run `./install.sh` again (or `install <ID shown in chrome://extensions>`), then reload the extension |
| `workspace_not_linked` | No workspace linked yet | Click the extension icon in your Slack tab |
| `slack_tab_missing` | No tab open on the linked workspace | Open it in the same Chrome profile |
| `session_not_found` | Signed out, or Slack changed where it stores its session | Sign in to Slack Web again. If it persists, open an issue |
| `network` | The request was blocked (browser or corporate proxy) | The `hint` field gives the browser's error message |
| `rate_limited` | Slack's rate limit (about 20 searches per minute) | Wait `retry_after` seconds |
| `file_too_large` | File above 30 MB | Download it from Slack directly |

## Uninstall

```bash
python3 bridge/slack_chrome_bridge.py uninstall
rm ~/.local/bin/slack-chrome-bridge
```

Then remove the extension in `chrome://extensions`, and delete `~/.cache/slack-chrome-bridge/` if you want to clear the name cache and downloaded files.

## Development

```bash
make test   # Python unit tests + JavaScript validation tests (Node 18+)
make lint   # syntax checks
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE). Not affiliated with or endorsed by Slack Technologies or Salesforce.
