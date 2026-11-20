# Architecture

## Components

| Component | File | Runs in | Role |
|---|---|---|---|
| Command line | `bridge/slack_chrome_bridge.py` | your terminal | Builds requests, shapes answers (names, compact JSON), saves files |
| Bridge (Native Messaging host) | same file, `_native` mode | a process started by Chrome | Forwards requests from the pipe to the extension and back |
| Service worker | `extension/worker.js` | the extension | Validates requests, finds the Slack tab, injects the API call |
| Validation | `extension/validate.js` | the extension | Checks operation names and parameters |
| Injected functions | `extension/slack-api.js` | your Slack Web tab (MAIN world) | Reads the session, calls the Slack Web API, downloads files |

## A request, step by step

1. `slack-chrome-bridge search 'foo'` creates a reply pipe `reply-<uuid>` and writes `{"id": "<uuid>", "op": "search", "params": {...}}` to the `requests` pipe, using the Native Messaging framing (4-byte little-endian length + UTF-8 JSON).
2. The bridge reads the request, checks the ID format and that the reply pipe exists, and writes the request (without the ID) to Chrome on stdout.
3. The service worker validates the operation and its parameters, looks up the linked workspace in `chrome.storage.local`, and finds an `app.slack.com/client/<workspace>` tab.
4. It runs `callSlack(method, params, workspace)` in that tab with `chrome.scripting.executeScript({world: 'MAIN'})`.
5. `callSlack` reads `localStorage.localConfig_v2.teams[<workspace>].token`, posts a form to `https://<workspace host>/api/<method>` (falling back to `https://app.slack.com/api/<method>`), and returns the JSON answer without any `token` field.
6. For `file`, the worker then runs `downloadSlackFile(url_private_download)` in the tab and returns the content base64-encoded (30 MB max).
7. The answer goes back to the bridge on stdin, then to the reply pipe, then to the command, which resolves user names and prints JSON.

## Timeouts and limits

| Limit | Value |
|---|---|
| Search query length | 500 characters |
| Results per search page | 100 |
| Replies per thread call | 1000 (the CLI asks for 200) |
| File size | 30 MB |
| Bridge frame size | 48 MB |
| Bridge waiting for Chrome | 75 s |
| Command waiting for the bridge | 90 s |

## Why Native Messaging and pipes

- Native Messaging is the only way for an extension to talk to a local program without opening a network port, and Chrome enforces which extension may start which host.
- Chrome starts the host itself, so the command line cannot speak Native Messaging directly. The long-lived bridge process holds the Chrome side, and named pipes let short-lived commands reach it.
- The pipes live in a per-user directory checked for ownership and mode `700`.

## Slack Web internals this relies on

- The session is stored in `localStorage` under `localConfig_v2`, per team ID, as a `xoxc-` token.
- Slack Web calls `https://<workspace>.slack.com/api/<method>` with the token in a form field, and the `d` session cookie.
- Files are served from `files.slack.com` and require the same cookie.

If Slack changes any of these, `extension/slack-api.js` is the only file to adapt.
