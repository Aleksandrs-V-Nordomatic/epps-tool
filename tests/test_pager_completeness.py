# -*- coding: utf-8 -*-
"""A page walk may not end quietly.

WHY THIS EXISTS. `targets_from` walked at most 60 pages of ten rows and returned whatever
it had. Three things could end the walk -- the portal running out of rows, the pager
repeating itself, and the pages running out -- and all three were spelled the same way: the
loop ended and the list was returned. The first two mean the window was answered. The third
means it was not, and it was silent.

Measured on 2026-09-01, against the live portal: August 2026 held 2271 publications and the
walk returned exactly 600; the standing doors are 787 and the walk returned exactly 600.
Neither raised, neither logged, and `lt_doors` has been enumerating 600 of 787 doors on
every run since. A door is the one thing in this tool nobody re-reads tomorrow: qualify
once and every purchase in that category arrives as an invitation, so a door missed is
missed for the life of the system.

The tests below fix the BEHAVIOUR, not the number. Raising the cap alone would have moved
the silence rather than removed it.
"""
import unittest

import lt_targets


STAMP = "Thu Aug 21 10:20:02 EEST 2026"


def row(pid):
    """One results-table row, shaped the way `parse_rows` reads them."""
    cells = ['<a href="prepareViewCfTWS.do?resourceId=%s">open</a>' % pid,
             "Sildymo sistemos priezidra %s" % pid, "", "Buyer", "",
             STAMP, STAMP, "Atviras konkursas", "Skelbiamas"]
    return "<tr>" + "".join("<td>%s</td>" % c for c in cells) + "</tr>"


def page(pids):
    return "<table>" + "".join(row(p) for p in pids) + "</table>"


class Endless(object):
    """A portal with more rows than the walk is allowed to ask for."""

    def __init__(self):
        self.asked = []

    def page(self, criteria, number):
        self.asked.append(number)
        return page(range(number * 10, number * 10 + 10))


class RunsOut(object):
    """A portal with exactly `pages` pages, then an empty one."""

    def __init__(self, pages):
        self.pages = pages

    def page(self, criteria, number):
        if number > self.pages:
            return "<table></table>"
        return page(range(number * 10, number * 10 + 10))


class Repeats(object):
    """A pager that runs past the end and serves the last page again."""

    def __init__(self, pages):
        self.pages = pages

    def page(self, criteria, number):
        return page(range(min(number, self.pages) * 10,
                          min(number, self.pages) * 10 + 10))


class ThePageWalk(unittest.TestCase):

    def test_running_out_of_pages_raises_instead_of_returning_a_short_window(self):
        portal = Endless()
        with self.assertRaises(lt_targets.Truncated) as caught:
            lt_targets.targets_from("01/08/2026", "31/08/2026", None, "tender",
                                    max_pages=3, session=portal)
        said = str(caught.exception)
        self.assertIn("3 pages", said, "the message must name the cap that was hit")
        self.assertIn("30 records", said, "and how much it did get, so the size is visible")
        self.assertEqual(portal.asked, [1, 2, 3], "every allowed page is walked first")

    def test_a_portal_that_runs_out_of_rows_is_an_honest_ending(self):
        rows = lt_targets.targets_from("01/08/2026", "31/08/2026", None, "tender",
                                       max_pages=50, session=RunsOut(4))
        self.assertEqual(len(rows), 40)

    def test_a_pager_that_repeats_itself_is_an_honest_ending(self):
        rows = lt_targets.targets_from("01/08/2026", "31/08/2026", None, "tender",
                                       max_pages=50, session=Repeats(4))
        self.assertEqual(len(rows), 40)

    def test_the_default_cap_clears_the_windows_this_tool_is_asked_for(self):
        """A month, and the doors, both measured against the live portal on 2026-09-01.

        Not a style check. The old cap was 60 and both of these exceeded it, which is how
        the silence was found; a future edit that lowers it should fail here rather than in
        a morning report that quietly says less than the day held.
        """
        self.assertGreaterEqual(lt_targets.PAGE_CAP * 10, 2271, "a month of publications")
        self.assertGreaterEqual(lt_targets.PAGE_CAP * 10, 787, "the standing doors")


if __name__ == "__main__":
    unittest.main()
