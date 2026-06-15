from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from web_app import storage


class StorageTests(unittest.TestCase):
    def test_parse_supabase_reference(self):
        self.assertEqual(
            storage.parse_supabase_reference("supabase://rhythm-audio/songs/a.wav"),
            ("rhythm-audio", "songs/a.wav"),
        )
        self.assertIsNone(storage.parse_supabase_reference("/tmp/a.wav"))

    def test_materialize_local_audio(self):
        with tempfile.NamedTemporaryFile(suffix=".wav") as audio:
            with storage.materialize_audio(audio.name) as path:
                self.assertEqual(path, Path(audio.name))

    def test_signed_url_supports_current_sdk_response(self):
        class FakeBucket:
            def create_signed_url(self, path, expires_in):
                self.path = path
                self.expires_in = expires_in
                return {"signedUrl": "https://example.test/audio.wav?token=secret"}

        class FakeStorage:
            def __init__(self):
                self.bucket = FakeBucket()

            def from_(self, bucket):
                self.bucket_name = bucket
                return self.bucket

        class FakeClient:
            def __init__(self):
                self.storage = FakeStorage()

        fake_client = FakeClient()
        with patch.object(storage, "supabase_client", return_value=fake_client):
            url = storage.create_signed_url(
                "supabase://rhythm-audio/songs/a.wav"
            )

        self.assertEqual(url, "https://example.test/audio.wav?token=secret")
        self.assertEqual(fake_client.storage.bucket_name, "rhythm-audio")
        self.assertEqual(fake_client.storage.bucket.path, "songs/a.wav")


if __name__ == "__main__":
    unittest.main()
