#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""The recall gate: which notices are worth fetching, before a single byte moves.

WHY IT IS ITS OWN FILE. This is the one piece of judgement that is not about a country. A
CPV code means the same thing in Riga and in Vilnius, and the terms a caller recalls on are
their business rather than a portal's — so both country tools ran the identical rule, and
the Lithuanian one reached into `batch.py`, the Latvian shard driver, to borrow it. That
import was the only thing keeping the two countries in one repository.

WHAT THIS KNOWS ABOUT THE CALLER'S INTEREST: NOTHING — the same rule deliver_graph.py keeps
about its destination. The terms arrive in the environment, so this file names no industry,
no trade and no target, and a reader of this repository learns the shape of the filter
without learning what anyone points it at.
"""

import json
import os


# THE ONE FILTER ALLOWED BEFORE A DOCUMENT EXISTS.
#
# A title is kept when it contains one of the caller's recall roots. Roots are matched as
# substrings rather than as whole words because the language this runs against inflects
# heavily; precision belongs to the later document-reading step, not to a title.
#
# One guard, and it fails toward fetching: no text at all means no evidence, so the notice is
# fetched.
#
# EXCLUSIONS WIN OVER RECALL, INCLUDING OVER A MATCHING TITLE, AND THAT IS DELIBERATE. This
# paragraph used to claim the opposite in the line above it -- that a classification code never
# vetoes a matching title -- while the code below did what it does now: `hard_exclude_prefixes`
# is tested BEFORE the recall terms and returns. The two sentences stood side by side for
# months. The code was right and the sentence was wrong, and it was settled by measurement
# rather than by preference.
#
# WHAT THE MEASUREMENT SAID. Both orders were run over 5 925 real Latvian notices spanning
# 9 June to 6 September 2026, against the live recall policy: they kept 2 147 each and
# disagreed about none of them. Only four notices in three months reached the contested branch
# at all -- and all four were car-park management systems, CPV 98351000 and 34926000, whose
# titles say `vadības sistēma`, control system, and match the recall terms perfectly. Dropping
# them is the entire reason those prefixes were written.
#
# So the rule that reads well is also the rule that is useless: a code exclusion that could not
# override a matching title could never drop anything, because a notice whose title does not
# match is dropped by the recall test anyway. `hard_exclude_prefixes` exists for exactly the
# notice that matches and is still not ours.
#
# WHICH PUTS THE WHOLE WEIGHT ON HOW NARROWLY A PREFIX IS WRITTEN, and that is the warning this
# paragraph is really for. An exclusion is absolute for a notice carrying no other code. Both
# live policies write theirs four to six digits long -- specific purchases, not divisions -- and
# that is why the branch fires four times a quarter instead of gutting the day. Measured on the
# same corpus, adding one two-digit division would silently drop, out of 2 147 kept notices:
#
#     45  construction works                    591
#     71  architecture and engineering          420
#     50  repair and maintenance services       204
#
# Those are the divisions our own work is filed under. Write a prefix that names a purchase,
# never one that names a division, and reach for `override_prefixes` before widening one.
#
# WHAT THIS KNOWS ABOUT THE CALLER'S INTEREST: NOTHING — the same rule deliver_graph.py
# keeps about its destination. The terms arrive in the environment, so this file names no
# industry, no trade and no target, and a reader of this repository learns the shape of the
# filter without learning what anyone points it at. An absent or unreadable policy means
# fetch everything, which is the only safe direction for a filter that failed to load:
# fetching too much costs time, and dropping silently costs a tender.
POLICY_ENV = "LT_POLICY"

# THE NAME THIS TOOL USED TO READ, checked rather than ignored. The Lithuanian lane was
# split out of the Latvian repository, where the variable was `EIS_POLICY` and the same
# gate served both countries. An environment still carrying only the old name would load
# no policy at all, and no policy means fetch everything -- a whole day drawn from a
# state portal, reported as success. A rename that fails open is worse than no rename.
FORMER_POLICY_ENV = "EIS_POLICY"


def load_policy(source=None):
    """The caller's recall policy, or None. None means no filter — fetch everything.

    `source` is JSON text, a path to a JSON file, or None to read `LT_POLICY` from the
    environment. Tests pass a fixture through it; production passes nothing and the
    environment answers, so no deployment's terms are ever committed here.
    """
    raw = source if source is not None else os.environ.get(POLICY_ENV)
    if source is None and not raw and os.environ.get(FORMER_POLICY_ENV):
        raise EnvironmentError(
            "%s is set but this tool reads %s. Rename it: honouring neither would fetch "
            "the whole day ungated and report success."
            % (FORMER_POLICY_ENV, POLICY_ENV))
    if not raw or not raw.strip():
        return None
    text = raw
    if not raw.lstrip().startswith("{"):              # not JSON, so treat it as a path
        try:
            with open(raw, encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            return None
    try:
        policy = json.loads(text)
    except ValueError:
        return None                       # an unreadable policy must fail open, never drop all
    recall = tuple(t.casefold() for t in (policy.get("recall_title_terms") or ()))
    if not recall:
        return None                       # incomplete policy must fail open, never drop all
    return (recall,
            tuple(policy.get("hard_exclude_prefixes") or ()),
            tuple(t.casefold() for t in (policy.get("hard_exclude_title_terms") or ())),
            # CODES THAT SURVIVE THEIR OWN DIVISION. A purchase can carry a main code
            # inside an excluded division and nothing else — a buyer files it under the
            # service it is bought as rather than the thing it is — and 62% of live
            # procurements carry one code only. Without an override such a notice is
            # dropped before a byte moves, which is the one failure the exclusions are
            # least allowed to cause.
            tuple(policy.get("override_prefixes") or ()),
            # CODES THAT RECALL ON THEIR OWN, because a title is not always the better
            # signal. Recall was title-only, and a code could exclude or rescue from an
            # exclusion but never bring anything in — so a procurement whose title is vague
            # and whose code is exact was dropped before a byte moved. That shape is common:
            # a buyer writes three words and then classifies the purchase precisely, and the
            # gate could hear only the three words. Absent, this changes nothing.
            tuple(policy.get("recall_cpv_prefixes") or ()))

def cpv_codes(notice):
    """Every CPV code a notice carries, however the source spelled them."""
    codes = []
    raw = notice.get("cpv")
    if isinstance(raw, (list, tuple)):
        codes = [str(c.get("code", "")) if isinstance(c, dict) else str(c) for c in raw]
    elif raw:
        codes = [str(raw)]
    if notice.get("cpv_main"):
        codes.append(str(notice["cpv_main"]))
    return [c.strip() for c in codes if c and c.strip()]


def outside_scope(notice, policy):
    """Should this notice be excluded before any documents are fetched?"""
    if not policy:
        return False
    # Older policies carry three fields; the override list is the fourth and optional.
    recall_terms, exclude_prefixes, exclude_title_terms = policy[:3]
    override_prefixes = policy[3] if len(policy) > 3 else ()
    recall_prefixes = policy[4] if len(policy) > 4 else ()

    title = str(notice.get("title") or notice.get("name") or "").casefold()
    if title and any(term in title for term in exclude_title_terms):
        return True

    codes = cpv_codes(notice)
    # An override is read anyway, wherever its division sits. The gate asks what the buyer
    # classified this as; whether the work is ours is a later and different question.
    overridden = bool(override_prefixes) and any(c.startswith(override_prefixes)
                                                 for c in codes)
    if (codes and exclude_prefixes and not overridden
            and all(c.startswith(exclude_prefixes) for c in codes)):
        return True

    # A CODE CAN RECALL, AND IT IS ASKED BEFORE THE TITLE. The exclusions above still
    # bind — an excluded title term or an all-excluded code set has already returned — so
    # this widens what is fetched and can never drop anything the old gate kept.
    if recall_prefixes and any(c.startswith(recall_prefixes) for c in codes):
        return False

    if not title:
        return False                      # missing signal fails open
    return not any(term in title for term in recall_terms)
