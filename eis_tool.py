#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
One Lithuanian tender, end to end: find it, download it, read it, say what could not be read.

    python3 eis_tool.py day 2026-08-20 --country LT --out work   # the published day
    python3 eis_tool.py plans --country LT --out work            # buyers' annual plans
    python3 eis_tool.py doors --country LT --out work            # DPS and qualification systems
    python3 eis_tool.py extract --pack out                       # deterministic text

WHY A SINGLE ENTRY POINT. The steps existed already but only as separate scripts glued
together inside one workflow file, which meant the sequence lived in YAML, where it could
not be tested and could not be run anywhere else. A VPS, a laptop and a runner now execute
the identical thing.

WHY THERE IS NO `probe` HERE. The Latvian tool asks its portal for permission before it
builds anything, because EIS refuses part of the cloud address space at the TCP layer and a
failed fetch there is evidence about the address rather than about the tender. EPPS refuses
none of them, so the same gate would be a request that always answers yes — and a check
that cannot fail teaches a reader that the failure it names does not happen here. It does
not; that is why this tool has one road and Latvia's has four shards and three draws.

ONE COUNTRY, AND IT STILL HAS TO BE NAMED. `--country LT` is not decoration and there is no
default: the destination folder is derived from it, and a tool that assumes its own country
is a tool that cannot say when it was pointed at the wrong drive. See country.py.
"""

import argparse
import country
import json
import os
import re
import sys

from console import utf8_streams


def extract(pack, with_images=False, keep_unpacked=False):
    """Deterministic text. Imported rather than shelled out, so a failure is a traceback."""
    import normalize
    argv = ["--in", pack, "--out", os.path.join(pack, "normalized")]
    if with_images:
        argv.append("--with-images")
    # The scan lane runs after this and can only read what still exists: a file that came
    # out of an archive has no downloaded original to fall back on.
    if keep_unpacked:
        argv.append("--keep-unpacked")
    return normalize.main(argv)


def read_scans(pack, model=None, limit=None, provider=None):
    """The fallback lane over files no decoder could read. Never fails the run.

    Defaults to local OCR, which needs no account and no key — so this step works out of
    the box on any machine that has Tesseract, and degrades to a printed note rather than
    an error on one that does not. A pack whose scans stay unread is exactly as complete
    as it was before this lane existed.
    """
    import assist as assist_mod
    provider = provider or os.environ.get("ASSIST_PROVIDER", assist_mod.DEFAULT_PROVIDER)
    _, needs_key, _, _ = assist_mod.PROVIDERS.get(
        provider, assist_mod.PROVIDERS[assist_mod.DEFAULT_PROVIDER])
    api_key = os.environ.get("%s_API_KEY" % provider.upper()) or \
        os.environ.get("ASSIST_API_KEY")
    if needs_key and not api_key:
        print("scan lane skipped — %s_API_KEY not set (the pack is complete without it)"
              % provider.upper())
        return 0
    # EVERY exception, not one class of them. This lane reads files the deterministic
    # extractor already listed as unreadable, and a pack whose scans stay unread is exactly
    # as complete as it was before the lane existed — so nothing it does may fail a tender.
    # Guarding only RuntimeError made that promise depend on which class a dependency
    # happened to raise: PyMuPDF raises its own hierarchy, so rasterising one oversized page
    # threw `code=5: Overly large image` straight past this handler and marked a tender with
    # 20 records, 50 files and 1.4 million extracted characters as a failure.
    try:
        doc = assist_mod.run(pack, model=model, api_key=api_key, provider=provider,
                             limit=limit)
    except Exception as exc:
        print("scan lane skipped — %s" % str(exc)[:200])
        return 0
    print("%s lane · %d read · %d deferred · %d skipped"
          % (doc["provider"], doc["read"], doc["deferred"], doc["skipped"]))
    return 0


def read_targets(source):
    """Ids from a file or from the argument itself, in the order they were given.

    Both spellings because both callers are real: a workflow writes its multi-line input to
    a file, and a person on a terminal types two ids separated by a comma. Deduplicated
    while keeping order, because a list naming the same procurement twice would fetch it
    twice and count the day wrong.
    """
    if not source:
        return []
    raw = source
    if os.path.exists(source):
        with open(source, encoding="utf-8") as fh:
            raw = fh.read()
    out, seen = [], set()
    for token in re.split(r"[\s,]+", raw.strip()):
        # `EPPS:9320336` is how the board spells a key; the id is what the portal answers to.
        token = token.split(":")[-1].strip()
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    return out


def main(argv=None):
    utf8_streams()

    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("extract", help="turn a downloaded pack into text")
    p.add_argument("--pack", required=True)
    p.add_argument("--with-images", action="store_true")

    # ONE COMMAND, ONE DAY. It names a country and a date and gets the delivery shape every
    # country tool produces — the same `day.json` beside the same folders, so a reader that
    # knows one country's layout knows them all. That shape is the contract between the
    # tools, and it is the reason each country can be its own repository without the reader
    # having to learn a second one.
    p = sub.add_parser("day", help="fetch one country's published day into the delivery shape")
    p.add_argument("date", help="YYYY-MM-DD")
    p.add_argument("--out", default="work")
    p.add_argument("--limit", type=int, default=None, help="stop after this many, for a trial")
    p.add_argument("--policy", default=None,
                   help="recall policy: JSON, a path to one, or EIS_POLICY from the "
                        "environment. Absent means fetch everything.")
    # THE WATCH LIST TRAVELS WITH THE WINDOW, never in a run of its own. Two runs are two
    # draws at one portal for one date, and two answers about what that date contained.
    # These are ids somebody is still deciding about, so the recall gate does not apply:
    # it decides what is worth fetching for the FIRST time, and these already have a card.
    p.add_argument("--targets", default=None,
                   help="ids to re-read whatever the gate would say — a file of them, one "
                        "per line, or the ids themselves separated by commas or spaces")
    country.add_argument(p)

    # The two standing populations. Neither is a day and neither is a tender: a plan says
    # what a buyer intends to buy months ahead, and a door is a system to qualify into
    # rather than a competition to enter. Both are read as a stock, on demand.
    for name, help_text in (("plans", "the annual procurement plans buyers have published"),
                            ("doors", "dynamic purchasing and qualification systems")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--out", default="work")
        p.add_argument("--policy", default=None)
        p.add_argument("--limit", type=int, default=None)
        country.add_argument(p)

    args = ap.parse_args(argv)

    if args.command in ("plans", "doors"):
        try:
            code = country.resolve(args.country, os.environ)
        except country.Mismatch as exc:
            print("%s: %s" % (args.command, exc), file=sys.stderr)
            return 2
        # No second branch here on purpose. `country.resolve` already refuses every code
        # this repository has no source for, with a sentence naming what it does have —
        # a check that lives in one place instead of being restated at each caller.
        out = os.path.join(args.out, code)
        if args.command == "plans":
            import lt_plans
            prior = os.path.join(out, "plans", "index.json")
            seen = {}
            if os.path.exists(prior):
                with open(prior, encoding="utf-8") as fh:
                    seen = json.load(fh).get("seen") or {}
            index, _ = lt_plans.harvest(out, args.policy, args.limit, seen)
            print("plans: %d published, %d read, %d unchanged, %d line(s), %d gated"
                  % (index["published_plans"], index["buyers_read"],
                     index["buyers_unchanged"], index["lines_kept"], index["lines_gated"]))
        else:
            import lt_doors
            index, _ = lt_doors.harvest(out, args.policy, limit=args.limit)
            for which, c in sorted(index["counts"].items()):
                print("%s: %d open, %d ours" % (which.upper(), c.get("open", 0),
                                                c.get("ours", 0)))
        return 0

    if args.command == "day":
        try:
            code = country.resolve(args.country, os.environ)
        except country.Mismatch as exc:
            # A stack trace here would be the tool blaming the caller for a question it
            # simply has to be asked.
            print("day: %s" % exc, file=sys.stderr)
            return 2
        # The destination carries the country for the same reason the source does: one run
        # is one country, and neither half is configured where the other cannot see it.
        out = os.path.join(args.out, code)
        import lt_day
        day, _ = lt_day.run(args.date, out, args.limit, policy=args.policy,
                            watch=read_targets(args.targets))
        print("%s %s: %d/%d delivered, %d document(s) -> %s"
              % (code, day["date"], day["coverage"]["delivered"],
                 day["coverage"]["targets"], day["counts"]["documents"], out))
        # NAMED, NOT COUNTED. "5 of 41" is also what a heavily gated day looks like, so a
        # short day that only reported a number would be indistinguishable from a normal
        # one. The exit code says the day is short; these lines say which procurements and
        # why, which is the part a person can act on.
        for row in day.get("lost", []):
            print("  lost %s (%s): %s" % (row.get("pid"), row.get("kind") or "?",
                                          row.get("reason")), file=sys.stderr)
        return 0 if day["complete"] else 1

    if args.command == "extract":
        return extract(os.path.abspath(args.pack), args.with_images)

    raise AssertionError("unreachable: argparse rejects any other command")


if __name__ == "__main__":
    sys.exit(main())
