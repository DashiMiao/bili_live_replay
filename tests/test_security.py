import base64
import hashlib
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bili_live_replay as b


class SecurityTests(unittest.TestCase):
    def test_extract_sessdata_discards_other_cookies(self):
        raw = "buvid3=x; SESSDATA=abc%2C123; bili_jct=deadbeef; DedeUserID=1"
        self.assertEqual(b.extract_sessdata(raw), "abc%2C123")

    def test_extract_bare_sessdata(self):
        self.assertEqual(b.extract_sessdata("abc%2C123"), "abc%2C123")

    def test_headers_do_not_contain_cookie(self):
        self.assertNotIn("Cookie", b.api_headers("https://live.bilibili.com/1"))
        self.assertNotIn("Cookie", b.cdn_headers("https://live.bilibili.com/1"))

    def test_cdn_url_allowlist(self):
        hosts = b._build_cdn_hosts([])
        self.assertTrue(b._validate_cdn_url("https://a.bilivideo.com/x.m4s", hosts))
        self.assertFalse(b._validate_cdn_url("http://a.bilivideo.com/x.m4s", hosts))
        self.assertFalse(b._validate_cdn_url("https://evil.example/x.m4s", hosts))
        self.assertFalse(b._validate_cdn_url("https://a.bilivideo.com:8443/x.m4s", hosts))
        self.assertFalse(b._validate_cdn_url("https://user:pass@a.bilivideo.com/x.m4s", hosts))

    def test_extra_cdn_host(self):
        hosts = b._build_cdn_hosts(["*.example.com"])
        self.assertTrue(b._validate_cdn_url("https://cdn.example.com/x.m4s", hosts))

    def test_cookie_jar_is_scoped_to_bilibili(self):
        import requests

        session = b._new_session()
        try:
            session.cookies.set("SESSDATA", "SECRET", domain=".bilibili.com", path="/")
            api_req = session.prepare_request(
                requests.Request("GET", "https://api.bilibili.com/x/web-interface/nav"))
            cdn_req = session.prepare_request(
                requests.Request("GET", "https://a.bilivideo.com/x.m4s"))
            self.assertEqual(api_req.headers.get("Cookie"), "SESSDATA=SECRET")
            self.assertIsNone(cdn_req.headers.get("Cookie"))
        finally:
            session.close()

    def test_cookie_file_permissions(self):
        if os.name == "nt":
            self.skipTest("POSIX permissions only")
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("SESSDATA=x")
            name = f.name
        try:
            os.chmod(name, 0o644)
            with self.assertRaises(SystemExit):
                b.load_cookie("", name, False)
            os.chmod(name, 0o600)
            self.assertEqual(b.load_cookie("", name, False), "SESSDATA=x")
        finally:
            os.unlink(name)

    def test_m3u8_segment_limit(self):
        text = "".join(
            f"#EXTINF:1,\nhttps://a.bilivideo.com/{i}.m4s\n"
            for i in range(b.MAX_SEGMENTS + 1)
        )
        with self.assertRaises(ValueError):
            b.parse_m3u8(text)

    def test_version_parse(self):
        self.assertEqual(b._parse_version("v1.1.0"), (1, 1, 0))
        self.assertGreater(b._parse_version("1.1.0"), b._parse_version("1.0.3"))
        self.assertIsNone(b._parse_version("not-a-version"))
        self.assertTrue(b._is_safe_version("1.1.0"))
        self.assertFalse(b._is_safe_version("1.1.0/../../evil"))
        self.assertFalse(b._is_safe_version("../evil"))

    def test_npm_integrity(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"update-test")
            name = f.name
        try:
            digest = hashlib.sha512(b"update-test").digest()
            integrity = "sha512-" + base64.b64encode(digest).decode()
            self.assertTrue(b._verify_npm_integrity(Path(name), integrity))
            self.assertFalse(b._verify_npm_integrity(Path(name), "sha512-AAAA"))
            self.assertFalse(b._verify_npm_integrity(Path(name), ""))
        finally:
            os.unlink(name)

    def test_old_version_is_blocked_if_update_fails(self):
        original_version = b.VERSION
        original_fetch = b._fetch_registry_json
        original_cache = b._read_update_cache
        original_write = b._write_update_cache
        original_auto = b._auto_update
        old_updated = os.environ.pop("BILI_LIVE_REPLAY_UPDATED", None)
        old_strict = os.environ.pop("BILI_STRICT_UPDATE", None)
        old_allow_offline = os.environ.pop("BILI_ALLOW_OFFLINE", None)
        called = []
        try:
            b.VERSION = "1.0.0"
            b._read_update_cache = lambda: None
            b._write_update_cache = lambda version: None
            b._fetch_registry_json = lambda url: {"version": "1.1.0"}
            b._auto_update = lambda version: called.append(version) or False
            with self.assertRaises(SystemExit):
                b._enforce_latest_version()
            self.assertEqual(called, ["1.1.0"])
        finally:
            b.VERSION = original_version
            b._fetch_registry_json = original_fetch
            b._read_update_cache = original_cache
            b._write_update_cache = original_write
            b._auto_update = original_auto
            if old_updated is not None:
                os.environ["BILI_LIVE_REPLAY_UPDATED"] = old_updated
            if old_strict is not None:
                os.environ["BILI_STRICT_UPDATE"] = old_strict
            if old_allow_offline is not None:
                os.environ["BILI_ALLOW_OFFLINE"] = old_allow_offline

    def test_offline_is_blocked_by_default_even_with_cache(self):
        original_fetch = b._fetch_registry_json
        original_cache = b._read_update_cache
        old_allow_offline = os.environ.pop("BILI_ALLOW_OFFLINE", None)
        old_strict = os.environ.pop("BILI_STRICT_UPDATE", None)
        try:
            b._fetch_registry_json = lambda url: None
            b._read_update_cache = lambda: {
                "checked_at": time.time(), "latest": b.VERSION,
            }
            with self.assertRaises(SystemExit):
                b._enforce_latest_version()
        finally:
            b._fetch_registry_json = original_fetch
            b._read_update_cache = original_cache
            if old_allow_offline is not None:
                os.environ["BILI_ALLOW_OFFLINE"] = old_allow_offline
            if old_strict is not None:
                os.environ["BILI_STRICT_UPDATE"] = old_strict

    def test_allow_offline_uses_cache(self):
        original_fetch = b._fetch_registry_json
        original_cache = b._read_update_cache
        old_allow_offline = os.environ.get("BILI_ALLOW_OFFLINE")
        try:
            os.environ["BILI_ALLOW_OFFLINE"] = "1"
            b._fetch_registry_json = lambda url: None
            b._read_update_cache = lambda: {
                "checked_at": time.time(), "latest": b.VERSION,
            }
            b._enforce_latest_version()
        finally:
            b._fetch_registry_json = original_fetch
            b._read_update_cache = original_cache
            if old_allow_offline is None:
                os.environ.pop("BILI_ALLOW_OFFLINE", None)
            else:
                os.environ["BILI_ALLOW_OFFLINE"] = old_allow_offline


if __name__ == "__main__":
    unittest.main()
