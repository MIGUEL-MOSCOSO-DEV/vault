import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from cryptography.exceptions import InvalidTag

from vault.backup import History, decrypt, encrypt, restore, snapshot


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "empty").mkdir()
        (self.source / "nested").mkdir()
        (self.source / "nested" / "document.txt").write_bytes(b"private contents" * 10000)
        self.password = "test-only-long-password"

    def tearDown(self):
        self.temporary.cleanup()

    def test_roundtrip_preserves_files_and_empty_directories(self):
        result = snapshot(self.source, self.root / "backups", self.password)
        restored = restore(result["path"], self.root / "restored", self.password)
        self.assertEqual(
            (restored / "nested" / "document.txt").read_bytes(),
            (self.source / "nested" / "document.txt").read_bytes(),
        )
        self.assertTrue((restored / "empty").is_dir())
        self.assertNotIn(b"private contents", Path(result["path"]).read_bytes())

    def test_wrong_password_creates_no_restored_directory(self):
        result = snapshot(self.source, self.root / "backups", self.password)
        with self.assertRaises(InvalidTag):
            restore(result["path"], self.root / "restored", "wrong-password-long")
        self.assertFalse((self.root / "restored").exists())

    def test_tampering_and_truncation_are_detected(self):
        result = snapshot(self.source, self.root / "backups", self.password)
        blob = bytearray(Path(result["path"]).read_bytes())
        blob[-1] ^= 1
        corrupted = self.root / "corrupt.vault"
        corrupted.write_bytes(blob)
        with self.assertRaises(InvalidTag):
            restore(corrupted, self.root / "bad", self.password)
        corrupted.write_bytes(blob[:40])
        with self.assertRaises(ValueError):
            restore(corrupted, self.root / "bad", self.password)

    def test_destination_inside_source_is_rejected(self):
        with self.assertRaises(ValueError):
            snapshot(self.source, self.source / "backups", self.password)

    def test_restore_never_overwrites_existing_directory(self):
        result = snapshot(self.source, self.root / "backups", self.password)
        with self.assertRaises(ValueError):
            restore(result["path"], self.source, self.password)

    def test_archive_traversal_is_rejected(self):
        archive = self.root / "malicious.zip"
        with zipfile.ZipFile(archive, "w") as file:
            file.writestr("../escape.txt", "escape")
        encrypted = self.root / "malicious.vault"
        encrypt(archive, encrypted, self.password)
        with self.assertRaises(ValueError):
            restore(encrypted, self.root / "restored", self.password)
        self.assertFalse((self.root / "escape.txt").exists())

    def test_versions_and_history_are_independent(self):
        history = History(self.root / "history.sqlite")
        first = snapshot(self.source, self.root / "backups", self.password)
        second = snapshot(self.source, self.root / "backups", self.password)
        self.assertNotEqual(first["path"], second["path"])
        history.add(first)
        history.add(second)
        self.assertEqual(len(history.all()), 2)

    def test_multiple_blocks_authenticate_and_restore(self):
        source = self.root / "large.bin"
        source.write_bytes(os.urandom(2 * 1024 * 1024 + 15))
        encrypted = self.root / "large.vault"
        encrypt(source, encrypted, self.password)
        destination = self.root / "decoded.bin"
        decrypt(encrypted, destination, self.password)
        self.assertEqual(source.read_bytes(), destination.read_bytes())

    def test_short_password_is_rejected(self):
        with self.assertRaises(ValueError):
            snapshot(self.source, self.root / "backups", "short")
        self.assertEqual(list((self.root / "backups").glob("*.partial")), [])
