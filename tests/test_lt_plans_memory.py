#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The plan register walked to its end, and a harvest that remembers the night before.

Two failures this file holds the line against, and neither raises anything.

The register is paged ten plans at a time, and the first page alone looks like a complete
answer: ten rows, no error. That is exactly what the first version of `register` returned.

And a runner's disk is new every night. A harvest that cannot see the last one re-reads
every plan and calls every line new for ever, which makes "new tonight" mean nothing; a
harvest that skips unchanged buyers without carrying their lines silently loses them.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import deliver_lt
import lt_plans


def register_page(rows, pages=1, total=None):
    """One page of the plan register, with the one-page cycle table printed first."""
    body = ['<script>writePageSelection("1", "?d-148196-p=", this, n, "1")</script>',
            "<strong>3</strong> rezultatai iš viso.",
            "<table><tr><td>1002</td><td>02/01/2025 13:38</td><td></td></tr></table>",
            "<strong>%d</strong> rezultatai iš viso." % (len(rows) if total is None else total),
            '<script>writePageSelection("%d", "?d-148516-p=", this, n, "1")</script>' % pages,
            "<table>"]
    for sid, buyer_id, buyer, submitted in rows:
        body.append('<tr><td><a href="/epps/prepareViewCAOrganisation.do?id=%s">%s</a></td>'
                    "<td> %s </td><td><a href=\"downloadPlanFile.do?submissionId=%s&amp;"
                    'reportType=public">Atsisiųsti</a></td></tr>'
                    % (buyer_id, buyer, submitted, sid))
    body.append("</table>")
    return "\n".join(body)


class TheRegisterIsWalkedToTheEnd(unittest.TestCase):

    def test_every_page_is_read_and_the_plans_pager_is_the_one_followed(self):
        page2 = lt_plans.REGISTER + "?d-148516-p=2"
        page3 = lt_plans.REGISTER + "?d-148516-p=3"
        pages = {
            lt_plans.REGISTER: register_page([("1", "11", "A", "16/11/2026 10:00")], 3, 3),
            page2: register_page([("2", "12", "B &quot;Ežerėlis&quot;", "15/11/2026 10:00")],
                                 3, 3),
            page3: register_page([("3", "13", "C", "14/11/2026 10:00")], 3, 3),
        }
        plans, total = lt_plans.register(fetch=pages.__getitem__)
        self.assertEqual([p["submission_id"] for p in plans], ["1", "2", "3"])
        self.assertEqual(total, 3)
        self.assertEqual(plans[1]["buyer"], 'B "Ežerėlis"')
        self.assertEqual(plans[1]["buyer_id"], "12")

    def test_a_plan_pushed_down_a_page_mid_walk_is_counted_once(self):
        pages = {
            lt_plans.REGISTER: register_page([("1", "11", "A", "x"), ("2", "12", "B", "x")],
                                             2, 3),
            lt_plans.REGISTER + "?d-148516-p=2": register_page(
                [("2", "12", "B", "x"), ("3", "13", "C", "x")], 2, 3),
        }
        plans, _ = lt_plans.register(fetch=pages.__getitem__)
        self.assertEqual([p["submission_id"] for p in plans], ["1", "2", "3"])


def plan_line(title, code="45312100", invites="2027-03-01"):
    return {"Pirkimo pavadinimas": title, "Aprašymas": "", "Pirkimo tipas": "Darbai",
            "Direktyva": "Nacionalinis pagrindas", "Procedūros tipas": "Skelbiama apklausa",
            "BVPŽ kodas": code, "Numatoma pirkimo sutarties vertė": 50000.0,
            "Kvietimo teikti pasiūlymus data": invites}


class ThePlansRememberTheLastNight(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.reg = [{"submission_id": "1", "buyer_id": "11", "buyer": "A",
                     "submitted": "01/11/2026 10:00"},
                    {"submission_id": "2", "buyer_id": "12", "buyer": "B",
                     "submitted": "01/11/2026 11:00"}]
        self.plans = {"1": [plan_line("Šildymo sistemos atnaujinimas")],
                      "2": [plan_line("Pastato automatikos įrengimas", "45315000")]}

    def tearDown(self):
        self.tmp.cleanup()

    def night(self, date, register=None, policy=None, failing=(), total=None):
        """One harvest against what the last one left on disk, with the portal replaced."""
        register = self.reg if register is None else register
        downloaded = []

        def fetch_plan(sid):
            downloaded.append(sid)
            if sid in failing:
                raise RuntimeError("EPPS answered with a page")
            return sid

        def fake_rows(sid):
            return {"Planuojamo pirkimo finansiniai metai": "2027"}, self.plans[sid]

        def fake_register():
            return list(register), len(register) if total is None else total

        with mock.patch.object(lt_plans, "rows", fake_rows), \
                mock.patch.object(lt_plans, "register", fake_register), \
                mock.patch.object(lt_plans, "plan_file", fetch_plan):
            index, lines, changes = lt_plans.harvest_local(self.tmp.name, policy, date=date)
        self.downloaded = downloaded
        return index, lines, changes

    def test_the_first_night_calls_every_line_new_and_says_it_is_the_first(self):
        index, _, changes = self.night("2026-11-16")
        self.assertTrue(changes["first_harvest"])
        self.assertEqual(changes["counts"]["new"], 2)
        self.assertTrue(index["complete"])

    def test_a_buyer_who_did_not_resubmit_is_not_downloaded_and_keeps_its_lines(self):
        self.night("2026-11-16")
        index, lines, changes = self.night("2026-11-17")
        self.assertEqual(self.downloaded, [])
        self.assertEqual(index["buyers_unchanged"], 2)
        self.assertEqual(len(lines), 2)
        self.assertEqual(changes["counts"], {"new": 0, "changed": 0, "removed": 0})
        self.assertFalse(changes["first_harvest"])

    def test_an_amended_plan_says_which_lines_are_new_and_which_changed(self):
        self.night("2026-11-16")
        self.reg[0]["submitted"] = "17/11/2026 09:00"
        self.plans["1"] = [plan_line("Šildymo sistemos atnaujinimas", invites="2027-05-01"),
                           plan_line("Vėdinimo sistemos įrengimas", "45331210")]
        _, lines, changes = self.night("2026-11-17")
        self.assertEqual(self.downloaded, ["1"])
        self.assertEqual([l["title"] for l in changes["new"]], ["Vėdinimo sistemos įrengimas"])
        self.assertEqual(changes["changed"][0]["fields"], ["invites"])
        self.assertEqual(changes["changed"][0]["before"], {"invites": "2027-03-01"})
        by_title = {l["title"]: l for l in lines}
        self.assertEqual(by_title["Šildymo sistemos atnaujinimas"]["first_seen"], "2026-11-16")
        self.assertEqual(by_title["Šildymo sistemos atnaujinimas"]["last_changed"],
                         "2026-11-17")
        self.assertEqual(by_title["Vėdinimo sistemos įrengimas"]["first_seen"], "2026-11-17")
        self.assertEqual(by_title["Pastato automatikos įrengimas"]["first_seen"], "2026-11-16")

    def test_a_line_dropped_from_a_plan_is_removed(self):
        self.night("2026-11-16")
        self.reg[1]["submitted"] = "17/11/2026 09:00"
        self.plans["2"] = []
        _, lines, changes = self.night("2026-11-17")
        self.assertEqual([r["title"] for r in changes["removed"]],
                         ["Pastato automatikos įrengimas"])
        self.assertEqual(len(lines), 1)

    def test_a_plan_that_could_not_be_read_keeps_its_lines_and_is_tried_again(self):
        self.night("2026-11-16")
        self.reg[0]["submitted"] = "17/11/2026 09:00"
        index, lines, changes = self.night("2026-11-17", failing=("1",))
        self.assertFalse(index["complete"])
        self.assertEqual(changes["counts"]["removed"], 0)
        self.assertEqual(len(lines), 2)
        self.assertEqual(index["seen"]["1"], "01/11/2026 10:00")       # not the new time
        self.night("2026-11-18")
        self.assertEqual(self.downloaded, ["1"])

    def test_a_register_walked_short_removes_nobody(self):
        self.night("2026-11-16")
        index, lines, changes = self.night("2026-11-17", register=self.reg[:1], total=2)
        self.assertFalse(index["complete"])
        self.assertEqual(changes["counts"]["removed"], 0)
        self.assertEqual(len(lines), 2)

    def test_a_renumbered_submission_keeps_the_identity_of_its_lines(self):
        self.night("2026-11-16")
        self.reg[1] = dict(self.reg[1], submission_id="9", submitted="17/11/2026 09:00")
        self.plans["9"] = self.plans["2"]
        _, _, changes = self.night("2026-11-17")
        self.assertEqual(changes["counts"], {"new": 0, "changed": 0, "removed": 0})

    def test_a_different_policy_reads_every_plan_again(self):
        self.night("2026-11-16")
        policy = json.dumps({"recall_title_terms": ["automatik"],
                             "hard_exclude_title_terms": [], "hard_exclude_prefixes": []})
        index, lines, _ = self.night("2026-11-17", policy=policy)
        self.assertEqual(sorted(self.downloaded), ["1", "2"])
        self.assertEqual([l["title"] for l in lines], ["Pastato automatikos įrengimas"])
        self.assertEqual(index["lines_gated"], 1)


class ThePlansTravelThroughTheDrive(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_index_is_delivered_last(self):
        plans = os.path.join(self.out, "plans")
        os.makedirs(os.path.join(plans, "changes"))
        for rel in ("changes/2026-11-16.json", "lines.jsonl", "index.json"):
            with open(os.path.join(plans, rel), "w") as fh:
                fh.write("{}")
        sent = []
        result = deliver_lt.deliver_plans(self.out, "2026-11-16", "drive", "root", "tok",
                                          upload=lambda d, dest, path, t: sent.append(dest))
        self.assertEqual(sent, ["root/plans/changes/2026-11-16.json", "root/plans/lines.jsonl",
                                "root/plans/index.json"])
        self.assertEqual(result["files"], 3)

    def test_a_harvest_that_left_nothing_is_refused_not_delivered_half(self):
        with self.assertRaises(SystemExit):
            deliver_lt.deliver_plans(self.out, "2026-11-16", "drive", "root", "tok",
                                     upload=lambda *a: None)

    def test_the_drive_is_the_memory_and_a_local_copy_it_lacks_is_dropped(self):
        plans = os.path.join(self.out, "plans")
        os.makedirs(plans)
        with open(os.path.join(plans, "lines.jsonl"), "w") as fh:
            fh.write("{}\n")
        drive = {"root/plans/index.json": b'{"seen": {}}'}
        found = deliver_lt.plans_prior(self.out, "drive", "root", "tok",
                                       fetch=lambda d, path, t: drive.get(path))
        self.assertEqual(found, 1)
        self.assertTrue(os.path.exists(os.path.join(plans, "index.json")))
        self.assertFalse(os.path.exists(os.path.join(plans, "lines.jsonl")))


if __name__ == "__main__":
    unittest.main()
