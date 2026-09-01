#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The Lithuanian delivery, tested without a drive.

Three properties carry this file, and each of them is a thing the Latvian delivery would
have got wrong if it had been pointed at Lithuania instead.

The index that ships is the one the fetch wrote. Lithuania's index carries two facts that
exist nowhere else in the pack — the amendment number that placed each document, and the
portal address a person clicks — and a delivery that rebuilds the index from
`procurement.json` produces a valid-looking index with both of them gone.

The day's verdict comes from the drive. `lt_day` compares against a `state.json` in the
home, which is right on a workstation and empty on a runner, so every procurement would be
`new` every night and the half of the run that reports what moved would have nothing true
to say. The comparison therefore happens at delivery, against what the reader can see.

And a procurement that did not move costs two small files. That is the whole economy of the
arrangement: the home accumulates, a document's name is its digest, and the bytes at that
name cannot have become different bytes.
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
import io

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import changes
import country
import deliver_lt


DATE = "2026-08-20"


class FakeDrive(object):
    """The drive as two dicts: what is already there, and what this run put there.

    Stands in for `deliver_graph`'s Graph client at exactly the two points the delivery
    touches it — reading a JSON file back, and uploading one.
    """

    def __init__(self, existing=None):
        self.existing = dict(existing or {})
        self.uploaded = {}
        self.order = []

    def json_at(self, drive, path, tok):
        if path in self.uploaded:
            return json.loads(self.uploaded[path].decode("utf-8"))
        return self.existing.get(path)

    def upload(self, drive, dest, data, tok):
        self.uploaded[dest] = data
        self.order.append(dest)

    def tender_archive(self, members):
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as zf:
            for rel, data in members:
                zf.writestr(rel, data)
        return out.getvalue()


def home(root, pid, docs, deadline="2026-09-15", amendment="3"):
    """A finished Lithuanian home, small but the real shape.

    `docs` is [(name, text, sha)] — the digest is given rather than computed so a test can
    say "the buyer replaced this document" by passing a different one.
    """
    path = os.path.join(root, "tenders", pid)
    os.makedirs(os.path.join(path, "doc"), exist_ok=True)
    os.makedirs(os.path.join(path, "normalized"), exist_ok=True)

    notice = {"pid": pid, "title": "Alfa objektas", "buyer": "Vilniaus miestas",
              "deadline": deadline, "cpv_main": "45331000",
              "link": "https://viesiejipirkimai.lt/epps/cft/prepareViewCfTWS.do?resourceId=%s" % pid}
    records, normalized_docs, index_docs = [], [], []
    for i, (name, text, sha) in enumerate(docs):
        source = "actual/%s" % name
        records.append({"id": "r%d" % i, "publish_date": "2026-08-19",
                        "title": name, "type_code": amendment, "section": "current",
                        "files": [{"sha256": sha, "original_name": name,
                                   "filename": name, "bytes": len(text)}]})
        normalized_docs.append({"source": source, "markdown_path": "%s/document.md" % i,
                                "markdown_chars": len(text), "section": "actual",
                                "original_sha256": sha, "original_file": name,
                                "record_id": "r%d" % i, "record_title": name})
        key = changes.document_key(sha, source)
        with open(os.path.join(path, "doc", "%s.md" % key), "w", encoding="utf-8") as fh:
            fh.write(text)
        index_docs.append({
            "id": "r%d" % i, "name": name, "sha256": sha, "bytes": len(text),
            # The two facts that must survive delivery, and the pointer that must not.
            "original": "originals/%s" % name,
            "amendment": amendment,
            "catalogued": True,
            "download": "https://viesiejipirkimai.lt/epps/downloadDoc.do?id=%d" % i,
            "doc": "doc/%s.md" % key,
        })

    manifest = {"pid": pid, "documents": records, "withheld_records": []}
    normalized = {"documents": normalized_docs, "unreadable_files": []}
    index = {"schema": "index/1", "pid": pid, "country": "LT", "kind": "tender",
             "source": "EPPS", "link": notice["link"], "title": notice["title"],
             "buyer": notice["buyer"], "deadline": deadline,
             "documents": index_docs}

    for name, payload in (("procurement.json", notice), ("manifest.json", manifest),
                          ("index.json", index)):
        with open(os.path.join(path, name), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
    with open(os.path.join(path, "normalized", "manifest_normalized.json"), "w",
              encoding="utf-8") as fh:
        json.dump(normalized, fh, ensure_ascii=False)

    state = changes.fingerprint(pid, notice, manifest, normalized,
                                tool="t1",
                                parser=changes.parser_version(
                                    files=country.parser_files("LT")))
    with open(os.path.join(path, "state.json"), "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False)
    return state


def day(root, pids):
    """The two files `lt_day` writes, with the local guess this delivery must overrule."""
    os.makedirs(os.path.join(root, DATE), exist_ok=True)
    tenders = [{"pid": p, "kind": "tender", "status": "new", "home": "tenders/%s" % p,
                "documents": 1, "bytes": 10, "title": "Alfa objektas"}
               for p in pids]
    with open(os.path.join(root, DATE, "day.json"), "w", encoding="utf-8") as fh:
        json.dump({"schema": "day/1", "date": DATE, "country": "LT", "source": "EPPS",
                   "tenders": tenders, "complete": True, "lost": [],
                   "coverage": {"targets": len(pids), "delivered": len(pids),
                                "gated": 0, "failed": 0}}, fh)
    with open(os.path.join(root, DATE, "changes.json"), "w", encoding="utf-8") as fh:
        json.dump({"schema": "day-changes/1", "date": DATE, "country": "LT",
                   "counts": {"new": len(pids)}, "gated": [], "complete": True,
                   "tenders": [dict(t, moved=[]) for t in tenders]}, fh)


class DeliverLithuania(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "work", "LT")
        os.makedirs(self.root, exist_ok=True)
        self.drive = FakeDrive()
        self._graph = deliver_lt.graph
        deliver_lt.graph = self.drive

    def tearDown(self):
        deliver_lt.graph = self._graph

    def deliver(self):
        return deliver_lt.deliver(self.root, DATE, "run-1", "drive", "work/LT", "tok")

    # ---- the index that ships ------------------------------------------------------

    def test_the_amendment_number_and_the_portal_link_survive_delivery(self):
        home(self.root, "9320336", [("TS.docx", "specifikacija", "aa")], amendment="3")
        day(self.root, ["9320336"])
        self.deliver()

        index = json.loads(self.drive.uploaded["work/LT/tenders/9320336/index.json"])
        entry = index["documents"][0]
        self.assertEqual(entry["amendment"], "3")
        self.assertIn("viesiejipirkimai.lt", entry["download"])
        # And nothing Latvian was invented in its place.
        self.assertNotIn("eis.gov.lv", json.dumps(index))

    def test_the_pointer_to_files_that_did_not_travel_is_dropped(self):
        home(self.root, "9320336", [("TS.docx", "specifikacija", "aa")])
        day(self.root, ["9320336"])
        self.deliver()

        index = json.loads(self.drive.uploaded["work/LT/tenders/9320336/index.json"])
        self.assertNotIn("original", index["documents"][0])

    def test_the_archive_holds_exactly_what_the_folder_holds(self):
        home(self.root, "9320336", [("TS.docx", "specifikacija", "aa")])
        day(self.root, ["9320336"])
        self.deliver()

        blob = self.drive.uploaded["work/LT/tenders/9320336/9320336.zip"]
        inside = set(zipfile.ZipFile(io.BytesIO(blob)).namelist())
        loose = {p.split("tenders/9320336/", 1)[1]
                 for p in self.drive.uploaded
                 if p.startswith("work/LT/tenders/9320336/")
                 and not p.endswith(".zip")
                 and not p.endswith("state.json")
                 and not p.endswith("seen.json")
                 and "runs/" not in p}
        self.assertEqual(inside, loose)

    def test_the_index_is_written_after_the_documents_it_names(self):
        home(self.root, "9320336", [("TS.docx", "specifikacija", "aa")])
        day(self.root, ["9320336"])
        self.deliver()

        paths = [p for p in self.drive.order if p.startswith("work/LT/tenders/9320336/")]
        docs = [i for i, p in enumerate(paths) if "/doc/" in p]
        index = paths.index("work/LT/tenders/9320336/index.json")
        self.assertTrue(docs and index > max(docs))
        # And the state file, which is tomorrow's licence to skip, after the index.
        self.assertGreater(paths.index("work/LT/tenders/9320336/state.json"), index)

    # ---- the verdict comes from the drive -------------------------------------------

    def test_a_procurement_already_on_the_drive_is_not_new_however_the_disk_guessed(self):
        state = home(self.root, "9320336", [("TS.docx", "specifikacija", "aa")])
        day(self.root, ["9320336"])
        # The same procurement, delivered before. `lt_day` on a fresh runner said "new".
        self.drive.existing["work/LT/tenders/9320336/state.json"] = state
        self.deliver()

        delivered = json.loads(self.drive.uploaded["work/LT/%s/changes.json" % DATE])
        self.assertEqual(delivered["tenders"][0]["status"], "unchanged")
        self.assertEqual(delivered["counts"]["unchanged"], 1)
        self.assertEqual(delivered["compared_against"], "drive")
        # And the day agrees with the change file about the same procurement.
        served = json.loads(self.drive.uploaded["work/LT/%s/day.json" % DATE])
        self.assertEqual(served["tenders"][0]["status"], "unchanged")

    def test_a_replaced_document_is_reported_as_changed(self):
        home(self.root, "9320336", [("TS.docx", "senas", "aa")])
        day(self.root, ["9320336"])
        was = json.load(open(os.path.join(self.root, "tenders", "9320336", "state.json"),
                             encoding="utf-8"))
        # Same procurement, one document replaced by the buyer.
        home(self.root, "9320336", [("TS.docx", "naujas", "bb")])
        self.drive.existing["work/LT/tenders/9320336/state.json"] = was
        self.deliver()

        delivered = json.loads(self.drive.uploaded["work/LT/%s/changes.json" % DATE])
        self.assertEqual(delivered["tenders"][0]["status"], "changed")

    # ---- what an unchanged procurement costs ----------------------------------------

    def test_an_unchanged_procurement_writes_only_the_two_small_per_run_files(self):
        state = home(self.root, "9320336", [("TS.docx", "specifikacija", "aa")])
        day(self.root, ["9320336"])
        self.drive.existing["work/LT/tenders/9320336/state.json"] = state
        self.deliver()

        wrote = {p.split("tenders/9320336/", 1)[1] for p in self.drive.uploaded
                 if "tenders/9320336/" in p}
        self.assertEqual(wrote, {"seen.json", "runs/%s.json" % DATE})

    def test_the_day_is_written_after_the_changes_it_vouches_for(self):
        home(self.root, "9320336", [("TS.docx", "specifikacija", "aa")])
        day(self.root, ["9320336"])
        self.deliver()

        self.assertGreater(self.drive.order.index("work/LT/%s/day.json" % DATE),
                           self.drive.order.index("work/LT/%s/changes.json" % DATE))

    def test_a_home_that_never_arrived_is_taken_out_of_the_day(self):
        """A day may be short. It may not be wrong.

        Left in, `day.json` would name a home that is not on the drive, carry the local guess
        of `new` for it, and still call itself complete — so a reader would ask the drive for
        an archive nobody uploaded and get a 404 in the middle of a night that reported
        success.
        """
        home(self.root, "9320336", [("TS.docx", "specifikacija", "aa")])
        day(self.root, ["9320336", "8888888"])          # the second was never fetched
        self.deliver()

        served = json.loads(self.drive.uploaded["work/LT/%s/day.json" % DATE])
        self.assertEqual([t["pid"] for t in served["tenders"]], ["9320336"])
        self.assertFalse(served["complete"])
        self.assertEqual([l["pid"] for l in served["lost"]], ["8888888"])
        self.assertEqual(served["coverage"]["undelivered"], 1)

        moved = json.loads(self.drive.uploaded["work/LT/%s/changes.json" % DATE])
        self.assertEqual([t["pid"] for t in moved["tenders"]], ["9320336"])
        self.assertFalse(moved["complete"])

    def test_a_whole_day_keeps_saying_it_is_whole(self):
        home(self.root, "9320336", [("TS.docx", "specifikacija", "aa")])
        day(self.root, ["9320336"])
        self.deliver()

        served = json.loads(self.drive.uploaded["work/LT/%s/day.json" % DATE])
        self.assertTrue(served["complete"])
        self.assertNotIn("undelivered", served.get("coverage", {}))

    def test_only_what_the_day_names_is_delivered(self):
        home(self.root, "9320336", [("TS.docx", "specifikacija", "aa")])
        home(self.root, "1111111", [("Kita.docx", "senas", "cc")])   # months old, on disk
        day(self.root, ["9320336"])
        self.deliver()

        self.assertFalse([p for p in self.drive.uploaded if "1111111" in p])


class TheParserFollowsTheCountry(unittest.TestCase):
    """A page reader improving is not a buyer amending, and the two must not be confused.

    The version stamped in a fingerprint decides that. Stamped with Latvia's digest, an
    `lt_page` improvement changes facts across the whole Lithuanian corpus in one night and
    every one of them reaches a card as an amendment.
    """

    def test_this_country_names_its_own_page_reader(self):
        self.assertEqual(country.parser_files("LT"), ("lt_page.py",))

    def test_a_country_this_tool_does_not_fetch_names_no_reader_at_all(self):
        # Rather than falling back to some default reader, which is how a Latvian digest
        # came to be stamped on a Lithuanian fingerprint in the first place.
        with self.assertRaises(country.Mismatch):
            country.parser_files("LV")

    def test_the_default_is_this_repositorys_reader(self):
        # Every caller written before the country flag existed meant "this tool's parser",
        # and in a single-country repository that is the only thing it can mean.
        self.assertEqual(changes.parser_version(),
                         changes.parser_version(files=country.parser_files("LT")))

    def test_the_version_moves_when_the_reader_does(self):
        self.assertIsNotNone(changes.parser_version(files=country.parser_files("LT")))


class AskingTheDestinationBeforeTheNight(unittest.TestCase):
    """`--check` exists so a dead credential costs one request instead of a whole night.

    The delivery is the LAST step of the run, so without this the answer to "can we deliver
    at all" arrives after the portal has been walked and a day's archives downloaded. A
    client secret expires on a date nobody has in their calendar.

    What each test holds is the part a person acts on: which of the five secrets to go and
    look at. A check that only said "failed" would send them to all five.
    """

    def setUp(self):
        self._graph = deliver_lt.graph
        self.addCleanup(setattr, deliver_lt, "graph", self._graph)
        for name, value in (("GRAPH_DRIVE_ID", "drive"),
                            ("GRAPH_DEST_ROOT", "project/work"),
                            ("EIS_COUNTRY", "LT")):
            self.addCleanup(os.environ.pop, name, None)
            os.environ[name] = value

    def stub(self, token=None, item=None):
        outer = self

        class Graph(object):
            @staticmethod
            def env(name):
                return os.environ[name]

            @staticmethod
            def graph_token():
                if isinstance(token, BaseException):
                    raise token
                return token or "tok"

            @staticmethod
            def item_at(drive, path, tok):
                outer.asked = path
                if isinstance(item, BaseException):
                    raise item
                return item

        deliver_lt.graph = Graph

    def run_check(self):
        err = io.StringIO()
        out = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            code = deliver_lt.main(["--check", "--country", "LT"])
        return code, out.getvalue() + err.getvalue()

    def test_a_reachable_destination_passes_and_delivers_nothing(self):
        self.stub(item={"folder": {"childCount": 10}})
        code, said = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn("10 item(s)", said)

    def test_it_says_where_it_looked_in_counts_and_never_in_paths(self):
        # The same rule the delivery itself keeps: the destination is a secret.
        self.stub(item={"folder": {"childCount": 3}})
        _, said = self.run_check()
        self.assertNotIn("project/work", said)
        self.assertNotIn("drive", said.replace("delivery credentials", ""))

    def test_a_dead_credential_names_the_credential(self):
        self.stub(token=RuntimeError("invalid_client"))
        code, said = self.run_check()
        self.assertEqual(code, 2)
        self.assertIn("client secret", said)

    def test_a_drive_that_will_not_answer_names_the_drive(self):
        self.stub(item=SystemExit("read failed: HTTP 403"))
        code, said = self.run_check()
        self.assertEqual(code, 2)
        self.assertIn("GRAPH_DRIVE_ID", said)

    def test_a_missing_country_folder_names_the_root(self):
        # The misconfiguration this catches is GRAPH_DEST_ROOT pointing at the country
        # folder instead of the one containing it.
        self.stub(item=None)
        code, said = self.run_check()
        self.assertEqual(code, 2)
        self.assertIn("GRAPH_DEST_ROOT", said)

    def test_the_country_folder_is_the_one_asked_about(self):
        self.stub(item={"folder": {"childCount": 1}})
        self.run_check()
        self.assertTrue(self.asked.endswith("/LT"), self.asked)

    def test_a_delivery_without_check_still_requires_a_date(self):
        self.stub(item={"folder": {"childCount": 1}})
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
            deliver_lt.main(["--country", "LT"])
        self.assertIn("--date", err.getvalue())


class TheLaneRefusesEveryOtherCountry(unittest.TestCase):
    """Latvia is now simply a country this repository has no source for, and that is the
    point of the split: a stale command line or a secret copied across from the Latvian
    deployment is refused here rather than quietly served."""

    def test_latvia_is_refused_like_any_country_this_tool_does_not_fetch(self):
        self.assertEqual(deliver_lt.main(["--date", DATE, "--country", "LV"]), 2)

    def test_a_country_with_no_source_is_refused(self):
        self.assertEqual(deliver_lt.main(["--date", DATE, "--country", "EE"]), 2)


if __name__ == "__main__":
    unittest.main()
