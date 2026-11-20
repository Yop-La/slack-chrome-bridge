// Functions injected by Chrome into the Slack Web tab (MAIN world), so requests are made
// exactly like Slack Web makes them. Chrome serializes each function on its own: they must
// stay self-contained and cannot use anything else from this module.
//
// The session token never leaves the tab: it is read, used for the request, and the response
// is returned without it.

// Calls one read-only Slack Web API method with the tab's session.
export async function callSlack(method, params, workspace) {
  const READ_ONLY = [
    'search.messages',
    'conversations.replies',
    'conversations.history',
    'conversations.info',
    'users.info',
    'files.info',
  ];
  if (!READ_ONLY.includes(method)) {
    return { ok: false, error: 'method_not_allowed' };
  }
  if (location.origin !== 'https://app.slack.com') {
    return { ok: false, error: 'tab_not_on_slack' };
  }

  // Slack Web keeps the configuration of signed-in workspaces in localStorage.localConfig_v2.
  let config;
  try {
    config = JSON.parse(localStorage.getItem('localConfig_v2') || '{}');
  } catch {
    return { ok: false, error: 'slack_config_unreadable' };
  }
  const team = config?.teams?.[workspace];
  const token = team?.token;
  if (typeof token !== 'string' || !token.startsWith('xoxc-')) {
    return { ok: false, error: 'session_not_found', hint: 'Sign in to Slack Web again in this Chrome profile.' };
  }
  const base = typeof team.url === 'string' && /^https:\/\/[a-z0-9-]+(\.enterprise)?\.slack\.com\/$/.test(team.url)
    ? team.url
    : 'https://app.slack.com/';

  const body = new FormData();
  body.append('token', token);
  for (const [key, value] of Object.entries(params || {})) {
    if (value !== undefined && value !== null && value !== '') body.append(key, String(value));
  }

  // Try the workspace host first, then the page's own origin (app.slack.com).
  // credentials: 'include' lets Chrome attach the session cookie, as for Slack Web.
  const hosts = [...new Set([base, 'https://app.slack.com/'])];
  const failures = [];
  let response;
  for (const host of hosts) {
    try {
      response = await fetch(`${host}api/${method}`, { method: 'POST', body, credentials: 'include' });
      break;
    } catch (e) {
      failures.push(`${new URL(host).hostname}: ${e?.name || 'Error'} ${e?.message || ''}`.trim());
    }
  }
  if (!response) {
    return { ok: false, error: 'network', hint: failures.join(' | ') };
  }
  if (response.status === 429) {
    return { ok: false, error: 'rate_limited', retry_after: Number(response.headers.get('Retry-After')) || 30 };
  }
  let data;
  try {
    data = await response.json();
  } catch {
    return { ok: false, error: `unreadable_response_http_${response.status}` };
  }
  if (data && typeof data === 'object') delete data.token;
  return data;
}

// Downloads a Slack file with the tab's session and returns it base64-encoded.
// Only accepts Slack file URLs (the url_private returned by files.info).
export async function downloadSlackFile(url, maxBytes) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return { ok: false, error: 'invalid_url' };
  }
  const host = parsed.hostname;
  const slackHost = host === 'files.slack.com' || host.endsWith('.slack.com');
  if (parsed.protocol !== 'https:' || !slackHost) {
    return { ok: false, error: 'url_not_on_slack' };
  }
  let response;
  try {
    response = await fetch(parsed.href, { credentials: 'include' });
  } catch (e) {
    return { ok: false, error: 'network', hint: `${e?.name || 'Error'} ${e?.message || ''}`.trim() };
  }
  if (!response.ok) {
    return { ok: false, error: `http_${response.status}` };
  }
  const type = response.headers.get('Content-Type') || '';
  if (type.startsWith('text/html')) {
    return { ok: false, error: 'login_page', hint: 'Slack returned a web page instead of the file.' };
  }
  const buffer = await response.arrayBuffer();
  if (buffer.byteLength > maxBytes) {
    return { ok: false, error: 'file_too_large', size: buffer.byteLength };
  }
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  }
  return { ok: true, content_type: type, size: bytes.length, base64: btoa(binary) };
}
