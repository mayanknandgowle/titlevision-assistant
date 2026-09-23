import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from dataclasses import replace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source"))
from appmeta import UPDATE_REPOSITORY
from updates import (UpdateError, parse_release, check_update, download_update,
                     safe_url, version_tuple, trusted_installer)


PAYLOAD = b"synthetic installer, never executed"


def metadata():
    return {"tag_name": "v0.3.0", "draft": False, "prerelease": False, "assets": [{
        "name": "TitleVisionAssistant-Setup-0.3.0.exe", "size": len(PAYLOAD),
        "digest": "sha256:" + hashlib.sha256(PAYLOAD).hexdigest(),
        "browser_download_url": f"https://github.com/{UPDATE_REPOSITORY}/releases/download/v0.3.0/TitleVisionAssistant-Setup-0.3.0.exe"}]}


class UpdateTests(unittest.TestCase):
    def test_numeric_version_comparison(self):
        self.assertGreater(version_tuple("1.10.0"), version_tuple("1.9.9"))
        for value in ("../1", "v1.2.3-beta", "1.02.3", None):
            with self.assertRaises(UpdateError):
                version_tuple(value)

    def test_stable_new_release(self):
        self.assertEqual(parse_release(metadata(), current="0.2.0").version, "0.3.0")

    def test_no_downgrade_or_same_version(self):
        self.assertIsNone(parse_release(metadata(), current="0.3.0"))
        self.assertIsNone(parse_release(metadata(), current="1.0.0"))

    def test_drafts_and_prereleases_blocked(self):
        for field in ("draft", "prerelease"):
            data = metadata()
            data[field] = True
            with self.assertRaises(UpdateError):
                parse_release(data)

    def test_missing_duplicate_or_wrong_asset_blocked(self):
        for assets in ([], metadata()["assets"] * 2, [{"name": "other.exe"}]):
            data = metadata()
            data["assets"] = assets
            with self.assertRaises(UpdateError):
                parse_release(data)

    def test_no_digest_or_unexpected_url_or_invalid_size_blocked(self):
        for field, value in (("digest", ""), ("browser_download_url", "https://github.com/other/project/setup.exe"),
                             ("size", 0), ("size", True), ("size", 2**40)):
            data = metadata()
            data["assets"][0][field] = value
            with self.assertRaises(UpdateError):
                parse_release(data)

    def test_redirect_hosts_restricted(self):
        self.assertEqual(safe_url("https://release-assets.githubusercontent.com/example"),
                         "https://release-assets.githubusercontent.com/example")
        for url in ("http://github.com/a", "https://evil.example/a", "https://github.com.evil.example/a",
                    "https://name:password@github.com/a", "https://github.com:8443/a"):
            with self.assertRaises(UpdateError):
                safe_url(url)

    def test_metadata_response_is_bounded(self):
        with self.assertRaises(UpdateError):
            check_update(opener=lambda u: io.BytesIO(b"x" * (2 * 1024 * 1024 + 1)))

    def test_invalid_json_is_readable_error(self):
        with self.assertRaises(UpdateError):
            check_update(opener=lambda u: io.BytesIO(b"not json"))

    def test_download_and_hash_verified(self):
        release = parse_release(metadata())
        with tempfile.TemporaryDirectory() as folder:
            path = download_update(release, folder, opener=lambda u: io.BytesIO(PAYLOAD))
            self.assertEqual(path.read_bytes(), PAYLOAD)
            self.assertEqual(list(Path(folder).glob('*.part')), [])

    def test_corrupt_short_and_oversize_downloads_not_saved(self):
        for body in (b"z" * len(PAYLOAD), PAYLOAD[:-1], PAYLOAD + b"x"):
            with self.subTest(body=body), tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(UpdateError):
                    download_update(parse_release(metadata()), folder, opener=lambda u: io.BytesIO(body))
                self.assertEqual(list(Path(folder).iterdir()), [])

    def test_cancelled_download_not_saved(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(UpdateError):
                download_update(parse_release(metadata()), folder, opener=lambda u: io.BytesIO(PAYLOAD), cancelled=lambda: True)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_path_traversal_metadata_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(UpdateError):
                download_update(replace(parse_release(metadata()), filename='../setup.exe'), folder)

    def test_only_matching_trusted_publishers_can_install(self):
        release = parse_release(metadata())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / release.filename
            path.write_bytes(PAYLOAD)
            valid = lambda p: {'status': 'Valid', 'thumbprint': 'publisher'}
            self.assertTrue(trusted_installer(path, release, installed='current.exe', signature_reader=valid))
            for data in ({}, {'status':'NotSigned', 'thumbprint':''}, {'status':'HashMismatch', 'thumbprint':'publisher'}):
                self.assertFalse(trusted_installer(path, release, installed='current.exe', signature_reader=lambda p: data))
            self.assertFalse(trusted_installer(path, release, installed='current.exe',
                signature_reader=lambda p: {'status':'Valid', 'thumbprint':str(p)}))

    def test_tampering_after_download_blocks_install(self):
        release = parse_release(metadata())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / release.filename
            path.write_bytes(b"z" * len(PAYLOAD))
            with self.assertRaises(UpdateError):
                trusted_installer(path, release, installed='current.exe')


if __name__ == '__main__':
    unittest.main()
