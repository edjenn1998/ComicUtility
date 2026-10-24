import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from audit_linux_abi import audit


class AbiAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        header = bytearray(20)
        header[:4] = b"\x7fELF"
        header[5] = 1
        header[18:20] = struct.pack("<H", 183)
        (self.root / "library.so").write_bytes(header)

    def tearDown(self):
        self.temp.cleanup()

    def test_architecture_and_maximum_symbol(self):
        with patch("audit_linux_abi.subprocess.run", return_value=SimpleNamespace(
            stdout="Name: GLIBC_2.17\nName: GLIBC_2.35\n"
        )):
            report = audit(self.root)
        self.assertEqual(report["architecture"], "aarch64")
        self.assertEqual(report["minimum_glibc"], "2.35")
        self.assertEqual(report["elf_files_checked"], 1)
        self.assertFalse(report["errors"])

    def test_failed_inspection_is_reported(self):
        with patch("audit_linux_abi.subprocess.run", side_effect=subprocess.CalledProcessError(1, "readelf")):
            report = audit(self.root)
        self.assertEqual(report["elf_files_checked"], 0)
        self.assertEqual(report["errors"][0]["file"], "library.so")
