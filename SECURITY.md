# Security

This tool gives a command-line program read access to Slack through your browser session. Please read this page before installing it.

## Threat model

**What the extension can do.** It runs code in your Slack Web tab with your session. In principle, code in that position could read anything you can read and act as you. The design keeps it to reading:

- The service worker (`extension/worker.js`) only accepts six operations: `search`, `thread`, `history`, `channel`, `user`, `file`. Parameters are validated (`extension/validate.js`): IDs, timestamps, sizes.
- The function injected into the tab (`extension/slack-api.js`) refuses any Slack method outside `search.messages`, `conversations.replies`, `conversations.history`, `conversations.info`, `users.info`, `files.info`. This second check does not depend on the first.
- File downloads only accept `https://*.slack.com` URLs returned by `files.info`.

**What never leaves the tab.** The session token (`xoxc-…`) is read from the page and sent to Slack only. Any `token` field is removed from API answers before they are returned. The cookie is handled by Chrome and is never readable by the extension code.

**Who can talk to the bridge.**
- Chrome starts the bridge only for the extension ID written in the Native Messaging manifest (`allowed_origins`).
- The command line and the bridge talk through named pipes in `/tmp/slack-chrome-bridge-<uid>/`, a directory that must be owned by you with mode `700`. The bridge refuses to start otherwise.
- No TCP or HTTP port is opened.

**What is stored on disk.**
- `~/.cache/slack-chrome-bridge/users.json`: user IDs and display names (mode `600`). No tokens.
- `~/.cache/slack-chrome-bridge/files/`: files you explicitly downloaded with `file`, and their extracted text (mode `600`).

## Residual risks

- **Any process running as you** can write to the request pipe while the bridge runs, and so read Slack through it. This is the same trust level as your shell: anything running as you could already read your browser profile.
- **A modified copy of the extension** could do much more than read. Only load this code from a source you trust, and review changes before updating.
- **Other extensions** with access to `app.slack.com` share the same tab. This tool does not protect you from them.
- **Internal API.** Slack Web's API is not a public contract. A change on Slack's side can break the tool, or, in theory, change what a method does.
- **Workspace policy.** Using your session programmatically may be against your organization's policy or Slack's terms. Check before you use it on a corporate workspace.
- **Prompt injection.** When results are fed to an AI agent, message text is untrusted input. The provided skills tell the agent never to follow instructions found in messages.

## Reporting a vulnerability

Please do not open a public issue for security problems. Use GitHub's private vulnerability reporting on this repository (Security tab, "Report a vulnerability").
