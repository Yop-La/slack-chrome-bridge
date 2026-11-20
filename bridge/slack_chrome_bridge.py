#!/usr/bin/env python3
"""Read-only Slack access from the command line, through the Slack Web session open in Chrome.

The command talks to a Chrome extension through a local bridge (Chrome Native Messaging and
named pipes private to your macOS account). The extension runs each request inside your Slack
Web tab, so no Slack token ever reaches the command line or the disk.

Output is JSON on stdout. Errors go to stderr with a non-zero exit code.
"""

from __future__ import annotations

import argparse
import base64
import errno
import fcntl
import json
import os
import re
import select
import shlex
import shutil
import stat
import struct
import subprocess
import sys
import time
import uuid
from pathlib import Path

__version__ = "1.0.0"

HOST_NAME = "io.github.slack_chrome_bridge"
RUNTIME_DIR = Path(f"/tmp/slack-chrome-bridge-{os.getuid()}")
CACHE_DIR = Path(os.environ.get("SLACK_CHROME_BRIDGE_CACHE", Path.home() / ".cache" / "slack-chrome-bridge"))
USER_CACHE = CACHE_DIR / "users.json"
FILES_DIR = CACHE_DIR / "files"
FRAME_SIZE = struct.Struct("=I")
MAX_FRAME_BYTES = 48 * 1024 * 1024  # a base64-encoded file can be several MB
BROWSER_TIMEOUT = 75
CLIENT_TIMEOUT = 90

MENTION = re.compile(r"<@([UW][A-Z0-9]{6,})(?:\|[^>]*)?>")
TEXT_TYPES = {"text", "csv", "markdown", "json", "python", "sql", "yaml", "javascript", "shell"}
TEXT_SUFFIXES = {".txt", ".csv", ".md", ".json", ".py", ".sql", ".yml", ".yaml", ".log"}


class BridgeError(Exception):
    """An error with a message meant for the user."""


# ---------------------------------------------------------------------------
# Message framing (Chrome Native Messaging format: 4-byte length + UTF-8 JSON)
# ---------------------------------------------------------------------------

def read_message(read):
    header = read(FRAME_SIZE.size)
    if not header or len(header) != FRAME_SIZE.size:
        raise EOFError
    (size,) = FRAME_SIZE.unpack(header)
    if not 0 < size <= MAX_FRAME_BYTES:
        raise ValueError("Invalid local message size.")
    data = read(size)
    if not data or len(data) != size:
        raise EOFError
    message = json.loads(data)
    if not isinstance(message, dict):
        raise ValueError("Invalid local message.")
    return message


def frame(message):
    data = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_FRAME_BYTES:
        raise ValueError("Message exceeds the local bridge size limit.")
    return FRAME_SIZE.pack(len(data)) + data


# ---------------------------------------------------------------------------
# Local bridge (named pipes in a directory private to the current user)
# ---------------------------------------------------------------------------

def request_path():
    RUNTIME_DIR.mkdir(mode=0o700, exist_ok=True)
    info = RUNTIME_DIR.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise PermissionError(f"{RUNTIME_DIR} must be a directory private to your account (mode 700).")
    return RUNTIME_DIR / "requests"


def open_fifo(path, mode):
    fd = os.open(path, mode | os.O_NONBLOCK | os.O_NOFOLLOW)
    if not stat.S_ISFIFO(os.fstat(fd).st_mode):
        os.close(fd)
        raise ValueError("Unexpected local channel type.")
    return fd


def reply(path, result):
    try:
        with os.fdopen(open_fifo(path, os.O_WRONLY), "wb", buffering=0) as output:
            pending = memoryview(frame(result))
            deadline = time.monotonic() + 30
            while pending:
                _, writable, _ = select.select([], [output], [], max(0, deadline - time.monotonic()))
                if not writable:
                    return
                written = output.write(pending)
                if written:
                    pending = pending[written:]
    except (OSError, ValueError):
        pass  # the command may have been interrupted while waiting


def serve_chrome(browser_input, browser_output):
    """Native Messaging host: started by Chrome, forwards requests from the pipe to the extension."""
    path = request_path()
    with (RUNTIME_DIR / "bridge.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path.unlink(missing_ok=True)
        os.mkfifo(path, 0o600)
        try:
            with os.fdopen(open_fifo(path, os.O_RDWR), "rb", buffering=0) as requests:
                while True:
                    ready, _, _ = select.select([requests, browser_input], [], [])
                    if browser_input in ready:
                        # Chrome only speaks in answer to a request: anything else means it closed.
                        return
                    try:
                        request = read_message(requests.read)
                    except (OSError, EOFError, ValueError, struct.error):
                        continue
                    request_id = request.pop("id", "")
                    if not isinstance(request_id, str) or not re.fullmatch(r"[0-9a-f]{32}", request_id):
                        continue
                    response_path = RUNTIME_DIR / f"reply-{request_id}"
                    if not response_path.exists():
                        continue
                    browser_output.write(frame(request))
                    browser_output.flush()
                    ready, _, _ = select.select([browser_input], [], [], BROWSER_TIMEOUT)
                    result = read_message(browser_input.read) if ready else {
                        "ok": False,
                        "error": "chrome_timeout",
                        "hint": "Chrome did not answer. Click the extension icon in the Slack tab.",
                    }
                    reply(response_path, result)
                    if not ready:
                        return
        finally:
            path.unlink(missing_ok=True)


def call(op, params):
    """Sends one operation to the extension and returns its JSON answer."""
    path = request_path()
    request_id = uuid.uuid4().hex
    response_path = RUNTIME_DIR / f"reply-{request_id}"
    os.mkfifo(response_path, 0o600)
    try:
        with os.fdopen(open_fifo(response_path, os.O_RDWR), "rb", buffering=0) as response:
            request = frame({"id": request_id, "op": op, "params": params})
            with os.fdopen(open_fifo(path, os.O_WRONLY), "wb", buffering=0) as requests:
                if len(request) > os.fpathconf(requests.fileno(), "PC_PIPE_BUF"):
                    raise BridgeError("Request too long for the local bridge. Shorten it.")
                if requests.write(request) != len(request):
                    raise BridgeError("The local bridge is busy. Try again in a few seconds.")

            deadline = time.monotonic() + CLIENT_TIMEOUT

            def read_exact(size):
                data = bytearray()
                while len(data) < size:
                    ready, _, _ = select.select([response], [], [], max(0, deadline - time.monotonic()))
                    if not ready:
                        raise TimeoutError
                    chunk = response.read(size - len(data))
                    if chunk:
                        data.extend(chunk)
                return data

            return read_message(read_exact)
    except OSError as error:
        if error.errno not in {errno.ENOENT, errno.ENXIO}:
            raise
        raise BridgeError("Chrome bridge unavailable. Click the extension icon in your Slack tab.") from error
    finally:
        response_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Installation of the Native Messaging host
# ---------------------------------------------------------------------------

BROWSER_HOST_DIRS = {
    "chrome": "Library/Application Support/Google/Chrome/NativeMessagingHosts",
    "chrome-beta": "Library/Application Support/Google/Chrome Beta/NativeMessagingHosts",
    "chromium": "Library/Application Support/Chromium/NativeMessagingHosts",
    "brave": "Library/Application Support/BraveSoftware/Brave-Browser/NativeMessagingHosts",
    "edge": "Library/Application Support/Microsoft Edge/NativeMessagingHosts",
}


def host_dir(browser):
    return Path.home() / BROWSER_HOST_DIRS[browser]


def unpacked_extension_id(folder):
    """ID Chrome gives an unpacked extension: SHA-256 of its absolute path, first 32 hex digits mapped to a-p."""
    import hashlib
    digest = hashlib.sha256(str(Path(folder).resolve()).encode("utf-8")).hexdigest()[:32]
    return "".join(chr(ord("a") + int(c, 16)) for c in digest)


def default_extension_dir():
    return Path(__file__).resolve().parent.parent / "extension"


def install_host(extension_id, browser="chrome"):
    if sys.platform != "darwin":
        raise BridgeError("Installation is only supported on macOS for now.")
    if not re.fullmatch(r"[a-p]{32}", extension_id):
        raise BridgeError("Invalid extension ID. Copy it from chrome://extensions.")
    directory = host_dir(browser)
    directory.mkdir(parents=True, exist_ok=True)
    launcher = directory / f"{HOST_NAME}.sh"
    executable = shlex.join([sys.executable, str(Path(__file__).resolve()), "_native"])
    manifest = {
        "name": HOST_NAME,
        "description": "Slack Chrome Bridge (read-only local bridge)",
        "path": str(launcher),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{extension_id}/"],
    }
    launcher.write_text(f'#!/bin/sh\nexec {executable} "$@"\n', encoding="utf-8")
    launcher.chmod(0o700)
    (directory / f"{HOST_NAME}.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {"installed": str(directory / f"{HOST_NAME}.json"), "launcher": str(launcher)}


def uninstall_host(browser="chrome"):
    removed = []
    for name in (f"{HOST_NAME}.json", f"{HOST_NAME}.sh"):
        path = host_dir(browser) / name
        if path.exists():
            path.unlink()
            removed.append(str(path))
    return {"removed": removed}


def doctor(browser="chrome"):
    """Checks each link of the chain and says what to fix."""
    checks = []
    manifest = host_dir(browser) / f"{HOST_NAME}.json"
    checks.append({"check": "native host manifest", "ok": manifest.exists(), "path": str(manifest),
                   "fix": None if manifest.exists() else "Run: install <EXTENSION_ID>"})
    try:
        request_path()
        pipe_ok = (RUNTIME_DIR / "requests").exists()
    except PermissionError as error:
        pipe_ok = False
        checks.append({"check": "runtime directory", "ok": False, "fix": str(error)})
    checks.append({"check": "bridge running (pipe present)", "ok": pipe_ok,
                   "fix": None if pipe_ok else "Open Slack Web in Chrome and click the extension icon."})
    if pipe_ok:
        try:
            answer = call("search", {"query": "a", "count": 1})
            ok = answer.get("ok") is True
            checks.append({"check": "Slack API call from the tab", "ok": ok,
                           "fix": None if ok else f"{answer.get('error')}: {answer.get('hint', '')}".strip(": ")})
        except (BridgeError, TimeoutError, EOFError, OSError) as error:
            checks.append({"check": "Slack API call from the tab", "ok": False, "fix": str(error)})
    checks.append({"check": "pdftotext (optional, PDF text)", "ok": shutil.which("pdftotext") is not None,
                   "fix": None if shutil.which("pdftotext") else "brew install poppler"})
    return {"ok": all(c["ok"] for c in checks if not c["check"].startswith("pdftotext")), "checks": checks}


# ---------------------------------------------------------------------------
# Output shaping
# ---------------------------------------------------------------------------

def parse_permalink(url):
    """https://<ws>.slack.com/archives/C123/p1731000000123456?thread_ts=... -> (channel, parent ts)."""
    match = re.search(r"/archives/([A-Z0-9]+)/p(\d{10})(\d{6})", url)
    if not match:
        raise BridgeError("Unrecognized Slack permalink.")
    thread_ts = re.search(r"[?&]thread_ts=(\d{10}\.\d{6})", url)
    return match.group(1), thread_ts.group(1) if thread_ts else f"{match.group(2)}.{match.group(3)}"


def _message(m, channel=None):
    out = {
        "ts": m.get("ts"),
        "date": time.strftime("%Y-%m-%d %H:%M", time.localtime(float(m["ts"]))) if m.get("ts") else None,
        "user": m.get("username") or m.get("user"),
        "text": m.get("text"),
    }
    if channel:
        out["channel"] = channel
    for key in ("permalink", "thread_ts", "reply_count"):
        if m.get(key):
            out[key] = m[key]
    if m.get("files"):
        out["files"] = [
            {"id": f.get("id"), "name": f.get("name") or f.get("title"), "type": f.get("filetype"),
             "link": f.get("permalink")}
            for f in m["files"] if isinstance(f, dict)
        ]
    return out


def simplify(op, data):
    """Compact answer: only the fields useful for reading."""
    if op == "search":
        block = data.get("messages") or {}
        paging = block.get("paging") or {}
        return {
            "total": block.get("total"),
            "page": paging.get("page"),
            "pages": paging.get("pages"),
            "messages": [_message(m, (m.get("channel") or {}).get("name")) for m in block.get("matches") or []],
        }
    return {
        "messages": [_message(m) for m in data.get("messages") or []],
        "has_more": data.get("has_more"),
        "next_cursor": (data.get("response_metadata") or {}).get("next_cursor") or None,
    }


def _load_cache():
    try:
        return json.loads(USER_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_cache(cache):
    USER_CACHE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    USER_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    USER_CACHE.chmod(0o600)


def resolve_names(result, lookup=None):
    """Replaces user IDs (authors and mentions) with display names. The cache stores names only."""
    lookup = lookup or (lambda uid: call("user", {"user": uid}))
    messages = result.get("messages") or []
    ids = set()
    for m in messages:
        if re.fullmatch(r"[UW][A-Z0-9]{6,}", str(m.get("user") or "")):
            ids.add(m["user"])
        ids.update(MENTION.findall(m.get("text") or ""))
    cache = _load_cache()
    changed = False
    for uid in sorted(ids - cache.keys()):
        try:
            data = lookup(uid)
        except (BridgeError, OSError, ValueError, EOFError, TimeoutError):
            continue
        user = data.get("user") or {}
        if data.get("ok") is True and user:
            profile = user.get("profile") or {}
            cache[uid] = profile.get("real_name") or user.get("real_name") or user.get("name") or uid
            changed = True
        time.sleep(0.3)
    if changed:
        _save_cache(cache)
    for m in messages:
        if m.get("user") in cache:
            m["user"] = cache[m["user"]]
        if m.get("text"):
            m["text"] = MENTION.sub(lambda g: "@" + cache.get(g.group(1), g.group(1)), m["text"])
    return result


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def safe_name(name):
    return re.sub(r"[^A-Za-z0-9._ -]", "_", name or "").strip(" .") or "file"


def extract_text(path, filetype):
    """Readable text of a file when possible (PDF through pdftotext, plain text otherwise)."""
    if filetype == "pdf" or path.suffix.lower() == ".pdf":
        tool = shutil.which("pdftotext")
        if not tool:
            return None
        out = subprocess.run([tool, "-layout", str(path), "-"], capture_output=True, timeout=60, check=False)
        return out.stdout.decode("utf-8", errors="replace") if out.returncode == 0 else None
    if filetype in TEXT_TYPES or path.suffix.lower() in TEXT_SUFFIXES:
        return path.read_text(encoding="utf-8", errors="replace")
    return None


def download_file(ref, out=None):
    """Downloads a Slack file through the tab (Chrome session) and saves it locally."""
    match = re.search(r"\b(F[A-Z0-9]{8,14})\b", ref)
    if not match:
        raise BridgeError("Unrecognized Slack file ID (expected F... or a /files/... link).")
    result = call("file", {"file": match.group(1)})
    if result.get("ok") is not True:
        raise BridgeError(_error_text(result))
    meta = result.get("file") or {}
    folder = Path(out).expanduser() if out else FILES_DIR
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = folder / f"{meta.get('id')}_{safe_name(meta.get('name') or meta.get('id'))}"
    path.write_bytes(base64.b64decode(result["base64"]))
    path.chmod(0o600)
    summary = {"file": meta, "path": str(path), "bytes": path.stat().st_size}
    text = extract_text(path, meta.get("filetype") or "")
    if text is not None:
        text_path = Path(f"{path}.txt")
        text_path.write_text(text, encoding="utf-8")
        text_path.chmod(0o600)
        summary["text_path"] = str(text_path)
        summary["text_preview"] = text[:1500]
    return summary


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def _error_text(result):
    hint = f" ({result['hint']})" if result.get("hint") else ""
    return f"Slack error: {result.get('error', 'unknown')}{hint}"


def build_parser():
    parser = argparse.ArgumentParser(prog="slack-chrome-bridge", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    install = commands.add_parser("install", help="Register the local bridge with Chrome")
    install.add_argument("extension_id", nargs="?",
                         help="ID shown in chrome://extensions (default: computed from the extension folder)")
    install.add_argument("--browser", choices=sorted(BROWSER_HOST_DIRS), default="chrome")

    uninstall = commands.add_parser("uninstall", help="Remove the local bridge registration")
    uninstall.add_argument("--browser", choices=sorted(BROWSER_HOST_DIRS), default="chrome")

    check = commands.add_parser("doctor", help="Check the installation end to end")
    check.add_argument("--browser", choices=sorted(BROWSER_HOST_DIRS), default="chrome")

    search = commands.add_parser("search", help="Search messages (Slack search modifiers accepted)")
    search.add_argument("query")
    search.add_argument("--count", type=int, default=20, help="Results per page, 1 to 100")
    search.add_argument("--page", type=int, default=1)
    search.add_argument("--sort", choices=["score", "timestamp"], default="timestamp")
    search.add_argument("--raw", action="store_true", help="Raw API answer")

    thread = commands.add_parser("thread", help="Read a thread (channel ID and parent message ts)")
    thread.add_argument("channel")
    thread.add_argument("ts")
    thread.add_argument("--limit", type=int, default=200)
    thread.add_argument("--raw", action="store_true")

    history = commands.add_parser("history", help="Read a channel's history")
    history.add_argument("channel")
    history.add_argument("--oldest", help="Unix timestamp, start")
    history.add_argument("--latest", help="Unix timestamp, end")
    history.add_argument("--limit", type=int, default=100)
    history.add_argument("--raw", action="store_true")

    link = commands.add_parser("link", help="Read the thread behind a Slack permalink")
    link.add_argument("url")
    link.add_argument("--raw", action="store_true")

    file_cmd = commands.add_parser("file", help="Download a Slack file (F... ID or /files/... link)")
    file_cmd.add_argument("file")
    file_cmd.add_argument("--out", help=f"Destination folder (default: {FILES_DIR})")
    return parser


def run(args):
    if args.command == "install":
        extension_id = args.extension_id or unpacked_extension_id(default_extension_dir())
        result = install_host(extension_id, args.browser)
        result.update({"extension_id": extension_id, "extension_folder": str(default_extension_dir())})
        return result
    if args.command == "uninstall":
        return uninstall_host(args.browser)
    if args.command == "doctor":
        return doctor(args.browser)
    if args.command == "file":
        return download_file(args.file, args.out)
    if args.command == "search":
        op, params = "search", {"query": args.query.strip(), "count": args.count, "page": args.page,
                                "sort": args.sort, "sort_dir": "desc"}
    elif args.command == "thread":
        op, params = "thread", {"channel": args.channel, "ts": args.ts, "limit": args.limit}
    elif args.command == "history":
        params = {"channel": args.channel, "limit": args.limit}
        for key in ("oldest", "latest"):
            if getattr(args, key):
                params[key] = getattr(args, key)
        op = "history"
    else:
        channel, ts = parse_permalink(args.url)
        op, params = "thread", {"channel": channel, "ts": ts, "limit": 200}
    result = call(op, params)
    if result.get("ok") is not True:
        raise BridgeError(_error_text(result))
    return result if args.raw else resolve_names(simplify(op, result))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["_native"]:
        try:
            serve_chrome(sys.stdin.buffer, sys.stdout.buffer)
        except EOFError:
            pass
        except (OSError, ValueError, struct.error) as error:
            print(error, file=sys.stderr)
            return 1
        return 0

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        output = run(args)
    except (EOFError, TimeoutError):
        print("The Chrome bridge did not answer. Click the extension icon and try again.", file=sys.stderr)
        return 1
    except (BridgeError, OSError, ValueError, struct.error) as error:
        print(error, file=sys.stderr)
        return 1
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if output.get("ok", True) is not False else 1


if __name__ == "__main__":
    sys.exit(main())
