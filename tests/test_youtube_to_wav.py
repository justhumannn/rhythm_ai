from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from youtube_to_wav import (
    requires_youtube_authentication,
    resolve_cookie_file,
    temporary_cookie_file,
)


class YoutubeCookieTests(unittest.TestCase):
    def test_missing_cookie_file_is_optional(self):
        with patch.dict(
            os.environ,
            {"YOUTUBE_COOKIES_FILE": "/tmp/does-not-exist-cookies.txt"},
        ):
            self.assertIsNone(resolve_cookie_file())

    def test_accepts_netscape_cookie_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cookies.txt"
            path.write_text(
                "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tx\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"YOUTUBE_COOKIES_FILE": str(path)}):
                self.assertEqual(resolve_cookie_file(), path)

    def test_rejects_non_netscape_cookie_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cookies.txt"
            path.write_text("SID=x\n", encoding="utf-8")
            with patch.dict(os.environ, {"YOUTUBE_COOKIES_FILE": str(path)}):
                with self.assertRaises(ValueError):
                    resolve_cookie_file()

    def test_detects_youtube_bot_message(self):
        self.assertTrue(
            requires_youtube_authentication(
                "Sign in to confirm you're not a bot. Use --cookies-from-browser"
            )
        )

    def test_copies_secret_cookie_to_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "cookies.txt"
            contents = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tx\n"
            source.write_text(contents, encoding="utf-8")

            with temporary_cookie_file(source) as temporary:
                self.assertIsNotNone(temporary)
                self.assertNotEqual(temporary, source)
                self.assertEqual(temporary.read_text(encoding="utf-8"), contents)
                self.assertEqual(temporary.stat().st_mode & 0o777, 0o600)
                temporary_name = temporary

            self.assertFalse(temporary_name.exists())


if __name__ == "__main__":
    unittest.main()
