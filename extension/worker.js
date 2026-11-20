// Service worker: receives requests from the local bridge (Native Messaging), validates them
// against a fixed list of read-only operations, and runs them inside the linked Slack tab.

import { callSlack, downloadSlackFile } from './slack-api.js';
import { validate } from './validate.js';

const APP_URL = 'https://app.slack.com/client/*';
const HOST_NAME = 'io.github.slack_chrome_bridge';
const MAX_FILE_BYTES = 30 * 1024 * 1024;
let bridge;

// The only operations the command line can request. All of them only read.
const OPERATIONS = {
  search: (p) => ['search.messages', {
    query: p.query, count: p.count, page: p.page, sort: p.sort, sort_dir: p.sort_dir, highlight: false,
  }],
  thread: (p) => ['conversations.replies', {
    channel: p.channel, ts: p.ts, limit: p.limit, cursor: p.cursor,
  }],
  history: (p) => ['conversations.history', {
    channel: p.channel, oldest: p.oldest, latest: p.latest, limit: p.limit, cursor: p.cursor, inclusive: true,
  }],
  channel: (p) => ['conversations.info', { channel: p.channel }],
  user: (p) => ['users.info', { user: p.user }],
  file: (p) => ['files.info', { file: p.file }],
};

function workspaceId(url) {
  return /^https:\/\/app\.slack\.com\/client\/([TE][A-Z0-9]+)(?:[/?#]|$)/.exec(url ?? '')?.[1];
}

async function handle(request) {
  const op = request?.op;
  const params = request?.params ?? {};
  if (!Object.hasOwn(OPERATIONS, op) || !validate(op, params)) {
    return { ok: false, error: 'invalid_request' };
  }

  const { workspace } = await chrome.storage.local.get('workspace');
  if (!workspace) {
    return { ok: false, error: 'workspace_not_linked', hint: 'In Slack, click the extension icon.' };
  }
  const tabs = (await chrome.tabs.query({ url: APP_URL })).filter((t) => workspaceId(t.url) === workspace);
  const tab = tabs.find((t) => t.active) ?? tabs[0];
  if (!tab?.id) {
    return { ok: false, error: 'slack_tab_missing', hint: 'Open the linked Slack workspace in this Chrome profile.' };
  }

  const run = async (func, args) => {
    const [execution] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, world: 'MAIN', func, args });
    return execution?.result ?? { ok: false, error: 'no_response_from_tab' };
  };
  const [method, apiParams] = OPERATIONS[op](params);
  const info = await run(callSlack, [method, apiParams, workspace]);
  if (op !== 'file' || info?.ok !== true) return info;

  // Files: metadata first, then download from the tab with the Slack session.
  const f = info.file || {};
  const url = f.url_private_download || f.url_private;
  const meta = { id: f.id, name: f.name, title: f.title, filetype: f.filetype, mimetype: f.mimetype, size: f.size };
  if (!url) return { ok: false, error: 'file_has_no_url', file: meta };
  const data = await run(downloadSlackFile, [url, MAX_FILE_BYTES]);
  if (data?.ok !== true) return { ...data, file: meta };
  return { ok: true, file: meta, content_type: data.content_type, base64: data.base64 };
}

function connect() {
  if (bridge) return;
  const port = chrome.runtime.connectNative(HOST_NAME);
  bridge = port;
  port.onDisconnect.addListener(() => {
    bridge = undefined;
  });
  port.onMessage.addListener(async (request) => {
    let result;
    try {
      result = await handle(request);
    } catch {
      result = { ok: false, error: 'extension_error' };
    }
    if (bridge === port) port.postMessage(result);
  });
}

chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onInstalled.addListener(connect);
chrome.action.onClicked.addListener(async (tab) => {
  const workspace = workspaceId(tab.url);
  if (!workspace) {
    await chrome.action.setBadgeText({ text: '!' });
    await chrome.action.setTitle({ title: 'Open Slack in Chrome and click again.' });
    return;
  }
  await chrome.storage.local.set({ workspace });
  await chrome.action.setBadgeText({ text: 'OK' });
  await chrome.action.setTitle({ title: 'Slack workspace linked. Click to reconnect the command line.' });
  connect();
});
