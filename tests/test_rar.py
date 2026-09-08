#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A .rar is an archive, and a binary that cannot read one has to say so.

WHY THIS EXISTS. Lithuanian buyers ship whole technical designs as .rar — a 158 MB
post-expertise design and a complete `Pirkimo dokumentai.rar` among them. The extractor knew
two archive formats, so those files were not archives to it at all: they went to the gap list
as unreadable and the project inside was never read. A backfill of August found the shape of
the loss — the deciding document present, listed, and empty.

RAR IS NOT A 7-ZIP FORMAT HERE, and that is the part worth remembering. Debian moved p7zip's
RAR codec to non-free and then dropped it, and Ubuntu's `7zip` package is a `+dfsg` repack
with the same decoder stripped — so neither `7z` nor `7zz` opens one, however much a desktop
file manager suggests otherwise. unar carries its own free implementation and reads RAR5 as
well as RAR4, which is why the image installs it and why `.rar` takes its own path.

The second half is refusing quietly-empty answers. A listing that comes back with no members
is not an empty archive; it is a format the binary could not read. Extracting that leaves an
empty directory and a tender that looks read, which is the one state this part of the tool
exists to prevent.

No real .rar fixture: one would have to come from a live tender, and buyer documents do not
belong in this tree. What is tested here is what lives in this repository — the signature,
the set `convert` branches on, which binary a .rar is routed to, and both refusals.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import normalize


# Written as byte values rather than escapes so the fixture cannot be mangled by whatever
# rewrites this file next. RAR 1.5-4.x ends its signature 0x00; RAR 5 ends 0x01 0x00.
RAR4 = bytes([0x52, 0x61, 0x72, 0x21, 0x1A, 0x07, 0x00])
RAR5 = bytes([0x52, 0x61, 0x72, 0x21, 0x1A, 0x07, 0x01, 0x00])


def _write(blob, suffix=".rar"):
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as fh:
        fh.write(blob + b"padding so the file is not merely a header")
    return path


class _Proc(object):
    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class ARarIsAnArchive(unittest.TestCase):
    def test_the_rar4_signature_is_recognised(self):
        path = _write(RAR4)
        try:
            self.assertEqual(normalize.sniff(path), ".rar")
        finally:
            os.unlink(path)

    def test_the_rar5_signature_is_recognised(self):
        path = _write(RAR5)
        try:
            self.assertEqual(normalize.sniff(path), ".rar")
        finally:
            os.unlink(path)

    def test_a_rar_named_anything_is_still_a_rar(self):
        """Sniffing is by content, so a buyer's misnamed attachment still lands."""
        path = _write(RAR4, suffix=".txt")
        try:
            self.assertEqual(normalize.sniff(path), ".rar")
        finally:
            os.unlink(path)

    def test_rar_is_in_the_set_the_extractor_unpacks(self):
        """The signature is worth nothing on its own: `convert` branches on this set, and
        without the entry a recognised .rar would still be filed as an opaque blob."""
        self.assertIn(".rar", normalize.ARCHIVES)


class WhichBinaryOpensIt(unittest.TestCase):
    def test_a_rar_goes_to_unar_and_never_to_the_seven_zip_path(self):
        """p7zip would exit non-zero, or on some builds exit 0 with nothing listed. Neither
        is a reading of the archive, so the routing has to happen before the binary does."""
        path = _write(RAR4)
        dest = tempfile.mkdtemp(prefix="eis_rar_")
        which = {"lsar": "/usr/bin/lsar", "unar": "/usr/bin/unar"}
        try:
            with mock.patch.object(normalize.shutil, "which", side_effect=which.get):
                with mock.patch.object(normalize, "_unpack_rar_cli") as rar:
                    with mock.patch.object(normalize, "_unpack_7z_cli") as seven:
                        normalize.unpack(path, dest, ".rar", [10 ** 9])
            self.assertTrue(rar.called, "a .rar must go to the RAR unpacker")
            self.assertFalse(seven.called, "a .rar must never reach the 7z unpacker")
            self.assertEqual(("/usr/bin/lsar", "/usr/bin/unar"), rar.call_args[0][:2])
        finally:
            os.unlink(path)

    def test_without_unar_the_missing_binary_is_named(self):
        """py7zr reads 7z and nothing else. Falling through to it would raise about a bad 7z
        header, which sends the reader to the archive instead of to the PATH."""
        path = _write(RAR4)
        dest = tempfile.mkdtemp(prefix="eis_rar_")
        try:
            with mock.patch.object(normalize.shutil, "which", return_value=None):
                with self.assertRaises(ValueError) as caught:
                    normalize.unpack(path, dest, ".rar", [10 ** 9])
            self.assertIn("unar", str(caught.exception))
            self.assertIn("PATH", str(caught.exception))
        finally:
            os.unlink(path)


class AnEmptyListingIsARefusal(unittest.TestCase):
    def test_lsar_listing_nothing_is_not_an_empty_archive(self):
        path = _write(RAR4)
        dest = tempfile.mkdtemp(prefix="eis_rar_")
        try:
            with mock.patch("subprocess.run",
                            return_value=_Proc(stdout=b'{"lsarContents": []}')):
                with self.assertRaises(ValueError) as caught:
                    normalize._unpack_rar_cli("lsar", "unar", path, dest, [10 ** 9])
            self.assertIn("no members", str(caught.exception))
            self.assertEqual([], os.listdir(dest), "nothing may be left behind")
        finally:
            os.unlink(path)

    def test_the_same_holds_on_the_seven_zip_path(self):
        """The guard is not RAR-specific: any binary that lists nothing has failed to read
        the archive, and extracting anyway would report success over an empty directory."""
        path = _write(RAR4, suffix=".7z")
        dest = tempfile.mkdtemp(prefix="eis_7z_")
        try:
            with mock.patch("subprocess.run",
                            return_value=_Proc(stdout=b"7-Zip\n\nERRORS:\nCannot open\n")):
                with self.assertRaises(ValueError) as caught:
                    normalize._unpack_7z_cli("7z", path, dest, [10 ** 9])
            self.assertIn("no members", str(caught.exception))
            self.assertEqual([], os.listdir(dest))
        finally:
            os.unlink(path)

    def test_a_real_listing_still_passes_the_budget_check(self):
        """The refusal must not swallow the case it was added beside: a listing with members
        goes on to the size budget, and a bomb still fails there."""
        path = _write(RAR4)
        dest = tempfile.mkdtemp(prefix="eis_rar_")
        listing = (b'{"lsarContents": [{"XADFileName": "TS.docx", "XADFileSize": 900}, '
                   b'{"XADFileName": "sub", "XADIsDirectory": true}]}')
        try:
            with mock.patch("subprocess.run", return_value=_Proc(stdout=listing)):
                with self.assertRaises(ValueError) as caught:
                    normalize._unpack_rar_cli("lsar", "unar", path, dest, [100])
            self.assertIn("past the limit", str(caught.exception))
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
