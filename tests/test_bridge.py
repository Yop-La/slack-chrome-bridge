"""Unit tests for the command-line side. No browser, no network: run with `python3 -m unittest`."""

import importlib.util
import io
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bridge", ROOT / "bridge" / "slack_chrome_bridge.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class FramingTest(unittest.TestCase):
    def test_round_trip(self):
        message = {"op": "search", "params": {"query": "déploiement"}}
        data = bridge.frame(message)
        self.assertEqual(struct.unpack("=I", data[:4])[0], len(data) - 4)
        self.assertEqual(bridge.read_message(io.BytesIO(data).read), message)

    def test_rejects_oversized_header(self):
        data = struct.pack("=I", bridge.MAX_FRAME_BYTES + 1) + b"{}"
        with self.assertRaises(ValueError):
            bridge.read_message(io.BytesIO(data).read)

    def test_rejects_non_object(self):
        payload = b"[1,2]"
        with self.assertRaises(ValueError):
            bridge.read_message(io.BytesIO(struct.pack("=I", len(payload)) + payload).read)

    def test_truncated_message(self):
        with self.assertRaises(EOFError):
            bridge.read_message(io.BytesIO(struct.pack("=I", 10) + b"{}").read)


class PermalinkTest(unittest.TestCase):
    def test_message_link(self):
        self.assertEqual(
            bridge.parse_permalink("https://acme.slack.com/archives/C0123ABCD/p1731000000123456"),
            ("C0123ABCD", "1731000000.123456"),
        )

    def test_reply_link_uses_parent(self):
        url = "https://acme.slack.com/archives/C0123ABCD/p1731000999654321?thread_ts=1731000000.123456&cid=C0123ABCD"
        self.assertEqual(bridge.parse_permalink(url), ("C0123ABCD", "1731000000.123456"))

    def test_bad_link(self):
        with self.assertRaises(bridge.BridgeError):
            bridge.parse_permalink("https://example.com/not-slack")


class SimplifyTest(unittest.TestCase):
    def test_search(self):
        raw = {"messages": {"total": 1, "paging": {"page": 1, "pages": 1}, "matches": [{
            "ts": "1731000000.123456", "user": "U01ABCDEF", "text": "hello",
            "channel": {"name": "general"}, "permalink": "https://acme.slack.com/archives/C1/p1",
            "files": [{"id": "F0123ABCDE", "name": "spec.pdf", "filetype": "pdf", "permalink": "https://x"}],
        }]}}
        out = bridge.simplify("search", raw)
        self.assertEqual(out["total"], 1)
        message = out["messages"][0]
        self.assertEqual(message["channel"], "general")
        self.assertEqual(message["files"][0], {"id": "F0123ABCDE", "name": "spec.pdf", "type": "pdf", "link": "https://x"})

    def test_thread(self):
        raw = {"messages": [{"ts": "1731000000.123456", "user": "U01ABCDEF", "text": "hi"}],
               "has_more": False, "response_metadata": {"next_cursor": ""}}
        out = bridge.simplify("thread", raw)
        self.assertEqual(len(out["messages"]), 1)
        self.assertIsNone(out["next_cursor"])


class ResolveNamesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        bridge.USER_CACHE = Path(self.tmp.name) / "users.json"
        bridge.time.sleep = lambda _s: None

    def tearDown(self):
        self.tmp.cleanup()

    def test_authors_and_mentions(self):
        result = {"messages": [{"user": "U01ABCDEF", "text": "ping <@U02GHIJKL> please"}]}
        names = {"U01ABCDEF": "Ada Lovelace", "U02GHIJKL": "Alan Turing"}
        lookup = lambda uid: {"ok": True, "user": {"profile": {"real_name": names[uid]}}}
        out = bridge.resolve_names(result, lookup)
        self.assertEqual(out["messages"][0]["user"], "Ada Lovelace")
        self.assertEqual(out["messages"][0]["text"], "ping @Alan Turing please")
        cache = json.loads(bridge.USER_CACHE.read_text())
        self.assertEqual(cache, names)
        self.assertEqual(bridge.USER_CACHE.stat().st_mode & 0o777, 0o600)

    def test_unknown_user_kept(self):
        result = {"messages": [{"user": "U09ZZZZZZ", "text": "x"}]}
        out = bridge.resolve_names(result, lambda uid: {"ok": False, "error": "user_not_found"})
        self.assertEqual(out["messages"][0]["user"], "U09ZZZZZZ")


class FilesTest(unittest.TestCase):
    def test_safe_name(self):
        self.assertEqual(bridge.safe_name("../../etc/passwd"), "_.._etc_passwd")
        self.assertEqual(bridge.safe_name(""), "file")

    def test_extract_plain_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.csv"
            path.write_text("a,b\n1,2\n")
            self.assertEqual(bridge.extract_text(path, "csv"), "a,b\n1,2\n")

    def test_binary_not_extracted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "image.png"
            path.write_bytes(b"\x89PNG")
            self.assertIsNone(bridge.extract_text(path, "png"))


class InstallTest(unittest.TestCase):
    def test_unpacked_extension_id(self):
        extension_id = bridge.unpacked_extension_id("/Users/someone/slack-chrome-bridge/extension")
        self.assertRegex(extension_id, r"^[a-p]{32}$")
        self.assertEqual(extension_id, bridge.unpacked_extension_id("/Users/someone/slack-chrome-bridge/extension"))
        self.assertNotEqual(extension_id, bridge.unpacked_extension_id("/Users/other/extension"))

    def test_rejects_bad_extension_id(self):
        with self.assertRaises(bridge.BridgeError):
            bridge.install_host("not-an-id")

    @unittest.skipUnless(sys.platform == "darwin", "macOS only")
    def test_install_and_uninstall(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_home = os.environ.get("HOME")
            os.environ["HOME"] = tmp
            try:
                info = bridge.install_host("a" * 32)
                manifest = json.loads(Path(info["installed"]).read_text())
                self.assertEqual(manifest["name"], bridge.HOST_NAME)
                self.assertEqual(manifest["allowed_origins"], [f"chrome-extension://{'a' * 32}/"])
                self.assertEqual(Path(info["launcher"]).stat().st_mode & 0o777, 0o700)
                self.assertEqual(len(bridge.uninstall_host()["removed"]), 2)
            finally:
                os.environ["HOME"] = old_home


if __name__ == "__main__":
    unittest.main()
