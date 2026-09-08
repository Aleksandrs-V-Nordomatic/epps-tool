#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A .rar is an archive, and a reader that cannot open one has to say so.

WHY THIS EXISTS. Lithuanian buyers ship whole technical designs as .rar — a 158 MB
post-expertise design and a complete `Pirkimo dokumentai.rar` among them. The extractor knew
two archive formats, so those files were not archives to it at all: they went to the gap list
as unreadable and the project inside was never read. A backfill of August found the shape of
the loss — the deciding document present, listed, and empty.

RAR IS NOT A 7-ZIP FORMAT HERE, and that is the first part worth remembering. Debian moved
p7zip's RAR codec to non-free and then dropped it, and Ubuntu's `7zip` package is a `+dfsg`
repack with the same decoder stripped — so neither `7z` nor `7zz` opens one, however much a
desktop file manager suggests otherwise. `.rar` takes its own path.

AND ONE READER IS NOT ENOUGH, which is the second part and was learned the expensive way.
Ubuntu ships unar as `1.10.7+ds1+really1.10.1` — 1.10.1 under a newer version string — and
its RAR5 extraction is incomplete: measured on three live Lithuanian archives it read the
RAR4 one and failed both others with `tried to read more data than was available`. lsar
listed all three, which is how we know the limit is in the extraction rather than in the
format. libarchive 3.7 carries a complete RAR5 reader, so bsdtar goes first and unar stays as
the second opinion; an archive is unreadable only when every reader has refused it.

The third part is refusing quietly-empty answers. A listing that comes back with no members
is not an empty archive; it is a format the binary could not read. Extracting that leaves an
empty directory and a tender that looks read, which is the one state this part of the tool
exists to prevent.

No real .rar fixture: one would have to come from a live tender, and buyer documents do not
belong in this tree. What is tested here is what lives in this repository — the signature,
the set `convert` branches on, the routing, the order of the chain, and every refusal.
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

LISTING = b'{"lsarContents": [{"XADFileName": "TS.docx", "XADFileSize": 900}]}'


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


class WhichReaderOpensIt(unittest.TestCase):
    def test_a_rar_goes_to_the_rar_path_and_never_to_the_seven_zip_one(self):
        """p7zip would exit non-zero, or on some builds exit 0 with nothing listed. Neither
        is a reading of the archive, so the routing happens before any binary runs."""
        path = _write(RAR4)
        dest = tempfile.mkdtemp(prefix="eis_rar_")
        which = {"lsar": "/usr/bin/lsar", "bsdtar": "/usr/bin/bsdtar",
                 "unar": "/usr/bin/unar"}
        try:
            with mock.patch.object(normalize.shutil, "which", side_effect=which.get):
                with mock.patch.object(normalize, "_unpack_rar_cli") as rar:
                    with mock.patch.object(normalize, "_unpack_7z_cli") as seven:
                        normalize.unpack(path, dest, ".rar", [10 ** 9])
            self.assertTrue(rar.called, "a .rar must go to the RAR unpacker")
            self.assertFalse(seven.called, "a .rar must never reach the 7z unpacker")
            self.assertEqual("/usr/bin/lsar", rar.call_args[0][0])
            self.assertEqual(["/usr/bin/bsdtar", "/usr/bin/unar"], rar.call_args[0][1],
                             "bsdtar has to be tried before unar")
        finally:
            os.unlink(path)

    def test_unar_alone_is_still_enough(self):
        """The chain is a preference, not a requirement: a machine carrying only unar keeps
        working, and dropping to one reader must not become a refusal."""
        path = _write(RAR4)
        dest = tempfile.mkdtemp(prefix="eis_rar_")
        which = {"lsar": "/usr/bin/lsar", "unar": "/usr/bin/unar"}
        try:
            with mock.patch.object(normalize.shutil, "which", side_effect=which.get):
                with mock.patch.object(normalize, "_unpack_rar_cli") as rar:
                    normalize.unpack(path, dest, ".rar", [10 ** 9])
            self.assertEqual(["/usr/bin/unar"], rar.call_args[0][1])
        finally:
            os.unlink(path)

    def test_with_no_reader_at_all_the_missing_binaries_are_named(self):
        """py7zr reads 7z and nothing else. Falling through to it would raise about a bad 7z
        header, which sends the reader to the archive instead of to the PATH."""
        path = _write(RAR4)
        dest = tempfile.mkdtemp(prefix="eis_rar_")
        try:
            with mock.patch.object(normalize.shutil, "which", return_value=None):
                with self.assertRaises(ValueError) as caught:
                    normalize.unpack(path, dest, ".rar", [10 ** 9])
            self.assertIn("lsar", str(caught.exception))
            self.assertIn("PATH", str(caught.exception))
        finally:
            os.unlink(path)


class TheExtractorChain(unittest.TestCase):
    def test_the_second_reader_rescues_what_the_first_refused(self):
        """The whole point of the chain, and it is not hypothetical: of three live archives
        lsar listed, one reader took one and refused two."""
        path = _write(RAR5)
        dest = tempfile.mkdtemp(prefix="eis_rar_")
        calls = [_Proc(stdout=LISTING),
                 _Proc(returncode=1, stdout=b"bsdtar: cannot read"),
                 _Proc(returncode=0)]
        try:
            with mock.patch("subprocess.run", side_effect=calls) as run:
                normalize._unpack_rar_cli("/usr/bin/lsar",
                                          ["/usr/bin/bsdtar", "/usr/bin/unar"],
                                          path, dest, [10 ** 9])
            self.assertEqual(3, run.call_count, "both extractors have to be tried")
        finally:
            os.unlink(path)

    def test_when_every_reader_refuses_each_one_is_named(self):
        path = _write(RAR5)
        dest = tempfile.mkdtemp(prefix="eis_rar_")
        calls = [_Proc(stdout=LISTING),
                 _Proc(returncode=1, stdout=b"bsdtar: Damaged RAR archive"),
                 _Proc(returncode=1, stdout=b"unar: tried to read more data")]
        try:
            with mock.patch("subprocess.run", side_effect=calls):
                with self.assertRaises(ValueError) as caught:
                    normalize._unpack_rar_cli("/usr/bin/lsar",
                                              ["/usr/bin/bsdtar", "/usr/bin/unar"],
                                              path, dest, [10 ** 9])
            said = str(caught.exception)
            self.assertIn("bsdtar", said)
            self.assertIn("unar", said)
            self.assertIn("Damaged RAR archive", said,
                          "the head of the message is what names the format")
        finally:
            os.unlink(path)

    def test_the_diagnostic_keeps_its_head_not_its_tail(self):
        """The first version kept the last 160 characters, so the ledger recorded
        `...ta than was available)` — a sentence fragment pointing nowhere."""
        path = _write(RAR5)
        dest = tempfile.mkdtemp(prefix="eis_rar_")
        noise = b"Pirkimo dokumentai.rar: RAR 5 " + b"x" * 400 + b"TAIL"
        calls = [_Proc(stdout=LISTING), _Proc(returncode=1, stdout=noise)]
        try:
            with mock.patch("subprocess.run", side_effect=calls):
                with self.assertRaises(ValueError) as caught:
                    normalize._unpack_rar_cli("/usr/bin/lsar", ["/usr/bin/unar"],
                                              path, dest, [10 ** 9])
            said = str(caught.exception)
            self.assertIn("Pirkimo dokumentai.rar: RAR 5", said)
            self.assertNotIn("TAIL", said)
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
                    normalize._unpack_rar_cli("lsar", ["unar"], path, dest, [10 ** 9])
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
                            return_value=_Proc(stdout=b"7-Zip ERRORS Cannot open")):
                with self.assertRaises(ValueError) as caught:
                    normalize._unpack_7z_cli("7z", path, dest, [10 ** 9])
            self.assertIn("no members", str(caught.exception))
            self.assertEqual([], os.listdir(dest))
        finally:
            os.unlink(path)

    def test_a_real_listing_still_passes_the_budget_check(self):
        """The refusal must not swallow the case it was added beside: a listing with members
        goes on to the size budget, and a bomb still fails there — before an extractor runs."""
        path = _write(RAR4)
        dest = tempfile.mkdtemp(prefix="eis_rar_")
        listing = (b'{"lsarContents": [{"XADFileName": "TS.docx", "XADFileSize": 900}, '
                   b'{"XADFileName": "sub", "XADIsDirectory": true}]}')
        try:
            with mock.patch("subprocess.run", return_value=_Proc(stdout=listing)) as run:
                with self.assertRaises(ValueError) as caught:
                    normalize._unpack_rar_cli("lsar", ["unar"], path, dest, [100])
            self.assertIn("past the limit", str(caught.exception))
            self.assertEqual(1, run.call_count,
                             "no extractor may run once the budget has failed")
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
