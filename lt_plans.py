"""The Lithuanian procurement plans: what buyers say they are going to buy.

Not a stream and not a tender. Every contracting authority must publish its annual plan in
CVP IS and republish it within five working days of amending it, so the register is a stock
that keeps being refreshed rather than a day's worth of news. What it buys us is lead time:
an object appears here as a line in a spreadsheet months before it appears anywhere as a
notice.

WHERE IT LIVES, and this is the part that costs a day if taken from the obvious place. The
plan register on `cvpp.eviesiejipirkimai.lt` is FROZEN — the newest publication date
anywhere in it is 2 December 2024. The whole CVPP portal stopped receiving data on that
date. The live register is in EPPS, at `app/viewPublication.do`, paged ten plans at a time.

ONE FILE PER BUYER, ONE SHAPE FOR ALL OF THEM. Each plan is an `.xls` on a mandatory VPT
template: sheets `DUOMENYS` and `TYPES`, a four-line header naming the buyer and the
financial year, then a row per planned procurement. Measured on the whole register on
16 Nov 2026: 1,442 plans, every one an `.xls`, every one readable, 99,249 lines; the walk
takes about 20 seconds and the download about six and a half minutes for 43 MB. The
recall policy that gates notices keeps about a third of the lines.

WHEN THE LEAD TIME IS LONGEST. Buyers file the year's plan by 15 March, and the register
shows it: a spike every March, then a trickle of amendments that grows towards the autumn.
So a plan line for the coming year is months ahead of its notice in spring, and weeks
ahead of it in November.

WHAT THE NIGHT DOES WITH IT. `lt-day.yml` fetches the last harvest back from the drive,
reads only the buyers who resubmitted since (10 to 30 on a working day), and delivers
`lines.jsonl`, `index.json` and `changes/<date>.json` beside the day. See `harvest`.

    python3 lt_plans.py --out work/LT --policy rules.json
"""
import argparse
import html
import json
import os
import re
import sys
import time
import urllib.request

import net

import lt_page

try:
    import policy as policy_mod
except Exception:
    policy_mod = None

REGISTER = lt_page.BASE + "/app/viewPublication.do"
PLAN = lt_page.BASE + "/app/downloadPlanFile.do?submissionId=%s"

_ROW = re.compile(r"(?is)<tr[^>]*>(.*?)</tr>")
_CELL = re.compile(r"(?is)<td[^>]*>(.*?)</td>")
_SUBMISSION = re.compile(r"downloadPlanFile\.do\?submissionId=(\d+)")
_BUYER = re.compile(r"prepareViewCAOrganisation\.do\?id=(\d+)")
# The header block above the table: label in column A, value in column B.
HEADER_ROWS = 4
# The column header is FOUND, never counted to. Buyers save the template with a varying
# number of blank rows above the table — row 4 in one plan, row 6 in the next — and a fixed
# index reads the blanks as column names, filters every row away and reports a buyer with
# no planned procurements. Zero lines is exactly what a buyer who planned nothing looks
# like, so the bug would have been invisible.
FIRST_COLUMN = "pirkimo pavadinimas"


# THE REGISTER IS PAGED, TEN PLANS A PAGE, and the first page alone looks like a complete
# answer: ten rows, no error. Measured 16 Nov 2026: 1,442 plans over 145 pages. The page
# parameter is displaytag's, named after a hash of the table (`d-148516-p` that day), so it
# is read off the page — `writePageSelection("145", "?d-148516-p=", …)` — and never typed in.
_PAGER = re.compile(r'writePageSelection\(\s*"(\d+)"\s*,\s*"\?([\w-]+)="')
# "| Rodomi: 1-10 | 1,442 rezultatai iš viso." — or "results" when EPPS answers in English.
_TOTAL = re.compile(r"(?is)<strong>\s*([\d,.\s]+?)\s*</strong>\s*(?:rezultat|result)")


def _text(fragment):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _page_rows(page):
    out = []
    for fragment in _ROW.findall(page):
        found = _SUBMISSION.search(fragment.replace("&amp;", "&"))
        if not found:
            continue
        cells = [_text(c) for c in _CELL.findall(fragment)]
        if len(cells) < 2:
            continue
        buyer = _BUYER.search(fragment)
        out.append({"submission_id": found.group(1),
                    "buyer": cells[0],
                    # The buyer's own id in EPPS. It is what a plan line is keyed on, so a
                    # buyer whose submission is renumbered keeps its lines' identity.
                    "buyer_id": buyer.group(1) if buyer else None,
                    # The portal's own wall clock, kept as it is printed: it is the only
                    # thing that says a buyer has amended a plan since we last read it.
                    "submitted": cells[1]})
    return out


def register(fetch=None, attempts=3):
    """Every published plan: the buyer, when they last submitted, and how to get it.

    Returns `(plans, total)`, where `total` is the count the portal itself prints. They
    differ when a buyer resubmits while the walk is under way: the register is sorted newest
    first, so the resubmitted plan jumps to page one after page one was read, and the walk
    never meets it. That is retried, and a register still short after the retries is
    reported as short rather than passed off as the whole.
    """
    fetch = fetch or lt_page.fetch
    best, total = [], None
    for _ in range(attempts):
        first = fetch(REGISTER)
        # The page also carries a one-page table of plan cycles, with a pager and a count
        # of its own, printed FIRST. The plans are the large one.
        pagers = [(int(n), name) for n, name in _PAGER.findall(first)]
        counts = [int(re.sub(r"\D", "", n)) for n in _TOTAL.findall(first)
                  if re.sub(r"\D", "", n)]
        total = max(counts) if counts else None
        pages = [first]
        if pagers:
            last, name = max(pagers)
            for n in range(2, last + 1):
                pages.append(fetch("%s?%s=%d" % (REGISTER, name, n)))
        plans, seen = [], set()
        for page in pages:
            for entry in _page_rows(page):
                if entry["submission_id"] not in seen:
                    seen.add(entry["submission_id"])
                    plans.append(entry)
        if len(plans) > len(best):
            best = plans
        if total is None or len(best) >= total:
            break
    return best, total


def plan_file(submission_id, timeout=180):
    request = urllib.request.Request(PLAN % submission_id,
                                     headers={"User-Agent": lt_page.UA})
    data, _ = net.open_url(request, timeout=timeout,
                           log=lambda line: print(line, file=sys.stderr))
    if not data[:4] in (b"\xd0\xcf\x11\xe0", b"PK\x03\x04"):
        # OLE2 for the .xls the template is, PK for a buyer who saved it as .xlsx. Anything
        # else is EPPS answering with a page, which it does under 200.
        raise RuntimeError("plan %s did not answer with a workbook (%d bytes)"
                           % (submission_id, len(data)))
    return data


def _iso(value, datemode):
    """An Excel date cell as `YYYY-MM-DD`. The template types its date columns as dates, so
    a planned invitation arrives as a serial number (46121.0) that reads as money if kept."""
    import xlrd
    try:
        return "%04d-%02d-%02d" % xlrd.xldate_as_tuple(value, datemode)[:3]
    except Exception:
        return None


def rows(data):
    """One dict per planned procurement, plus what the header block says about the plan."""
    if data[:4] == b"PK\x03\x04":
        # xlrd 2 reads only the OLE2 .xls the template is; a buyer who resaved it as .xlsx
        # is read by openpyxl, which is already pinned for the documents.
        return _rows_xlsx(data)
    import xlrd                                   # only the plans need it
    book = xlrd.open_workbook(file_contents=data)
    sheet = book.sheet_by_index(0)

    def cell(r, c):
        found = sheet.cell(r, c)
        if found.ctype == xlrd.XL_CELL_DATE:
            return _iso(found.value, book.datemode)
        return found.value

    grid = [[cell(r, c) for c in range(sheet.ncols)] for r in range(sheet.nrows)]
    return _read_grid(grid)


def _rows_xlsx(data):
    import datetime
    import io
    import openpyxl
    sheet = openpyxl.load_workbook(io.BytesIO(data), read_only=True,
                                   data_only=True).worksheets[0]
    grid = []
    for values in sheet.iter_rows(values_only=True):
        grid.append([v.date().isoformat() if isinstance(v, datetime.datetime)
                     else ("" if v is None else v) for v in values])
    return _read_grid(grid)


def _read_grid(grid):
    def at(r, c):
        return grid[r][c] if c < len(grid[r]) else ""

    head = {}
    for r in range(min(HEADER_ROWS, len(grid))):
        label = str(at(r, 0)).strip().rstrip(":")
        if label:
            head[label] = str(at(r, 1)).strip()
    header_row = None
    for r in range(len(grid)):
        if str(at(r, 0)).strip().casefold() == FIRST_COLUMN:
            header_row = r
            break
    if header_row is None:
        # Said out loud rather than returned as an empty plan: a template we cannot read is
        # a gap in coverage, and it must not look like a buyer with nothing to buy.
        raise ValueError("no column header row: %r not found in column A" % FIRST_COLUMN)
    columns = [str(v).strip() for v in grid[header_row]]
    out = []
    for r in range(header_row + 1, len(grid)):
        row = {}
        for c, name in enumerate(columns):
            if not name:
                continue
            value = at(r, c)
            row[name] = value if isinstance(value, (int, float)) else str(value).strip()
        if not str(row.get("Pirkimo pavadinimas") or "").strip():
            continue                              # a spacer row, of which the template has many
        out.append(row)
    return head, out


# THE TEMPLATE'S OWN COLUMN NAMES, read off the live register on 16 Nov 2026. An earlier
# version of this file expected `Numatoma pirkimo pradžios data`, which no plan carries, so
# every line arrived with no date at all. The date that matters is the invitation: when the
# buyer means to call for tenders. It is filled on about 94% of lines and is what turns a
# plan line into lead time. The deadline and creation dates are almost never filled.
COLUMNS = {
    "title": "Pirkimo pavadinimas",
    "description": "Aprašymas",
    "object_type": "Pirkimo tipas",
    "directive": "Direktyva",
    "procedure": "Procedūros tipas",
    "cpv": "BVPŽ kodas",
    "value": "Numatoma pirkimo sutarties vertė",
    "quantity": "Kiekis",
    "invites": "Kvietimo teikti pasiūlymus data",
    "deadline": "Pasiūlymų pateikimo termino / vokų plėšimo data",
    "duration": "Ketinamos sudaryti pirkimo sutarties trukmė (skaičiais)",
    "duration_unit": "Ketinamos sudaryti pirkimo sutarties trukmė (matavimo vienetas)",
    "created": "Preliminari pirkimo sukūrimo data",
}


def _blank(value):
    return None if value is None or str(value).strip() == "" else value


def as_line(row, head, buyer, submission_id, buyer_id=None):
    """The shape a reader gets, whatever the buyer called their columns."""
    code = re.sub(r"\D", "", str(row.get(COLUMNS["cpv"]) or ""))[:8]
    value = _blank(row.get(COLUMNS["value"]))
    return {
        "buyer": buyer,
        "buyer_id": buyer_id,
        "submission_id": submission_id,
        "year": head.get("Planuojamo pirkimo finansiniai metai") or None,
        "title": row.get(COLUMNS["title"]),
        "description": _blank(row.get(COLUMNS["description"])),
        "object_type": _blank(row.get(COLUMNS["object_type"])),
        "procedure": _blank(row.get(COLUMNS["procedure"])),
        "directive": _blank(row.get(COLUMNS["directive"])),
        "cpv_main": code or None,
        "cpv": [code] if code else [],
        # An estimate in euros. Buyers write 0 or 1 when they will not say.
        "value": value if isinstance(value, (int, float)) else None,
        "quantity": _blank(row.get(COLUMNS["quantity"])),
        "invites": _blank(row.get(COLUMNS["invites"])),
        "deadline": _blank(row.get(COLUMNS["deadline"])),
        "created": _blank(row.get(COLUMNS["created"])),
        "duration": _blank(row.get(COLUMNS["duration"])),
        "duration_unit": _blank(row.get(COLUMNS["duration_unit"])),
    }


# A PLAN LINE HAS NO ID, so it is given one. The template numbers nothing, and a buyer
# amending a plan republishes the whole workbook. The key is the buyer, the title as typed
# and the code, which is what a person would call "the same line"; a second line with the
# same three in one plan takes an ordinal. A buyer who retitles a line therefore shows as
# one line removed and one added, which is what happened.
_FIELDS = ("description", "object_type", "procedure", "directive", "value", "quantity",
           "invites", "deadline", "created", "duration", "duration_unit", "year")


def keyed(lines):
    count = {}
    for line in lines:
        title = re.sub(r"\s+", " ", str(line.get("title") or "")).strip().casefold()
        base = "%s|%s|%s" % (line.get("buyer_id") or line.get("submission_id"), title,
                             line.get("cpv_main") or "")
        count[base] = count.get(base, 0) + 1
        line["key"] = base if count[base] == 1 else "%s|%d" % (base, count[base])
    return lines


def diff(before, after, date):
    """What moved in the plans since the last harvest: new, changed and removed lines.

    `first_seen` is carried from the line's earlier self, so a reader can tell a line that
    appeared last night from one that has sat in the plan since spring.
    """
    old = {line["key"]: line for line in before}
    new, changed = [], []
    for line in after:
        was = old.pop(line["key"], None)
        if was is None:
            line["first_seen"] = date
            line["last_changed"] = date
            new.append(line)
            continue
        line["first_seen"] = was.get("first_seen") or date
        moved = [f for f in _FIELDS if was.get(f) != line.get(f)]
        if moved:
            line["last_changed"] = date
            changed.append({"key": line["key"], "fields": moved,
                            "before": {f: was.get(f) for f in moved}, "line": line})
        else:
            line["last_changed"] = was.get("last_changed") or line["first_seen"]
    return new, changed, list(old.values())


def _policy_print(rules):
    """A fingerprint of the policy the lines were gated with, never the policy itself:
    the policy is a secret and the index is delivered."""
    import hashlib
    if rules is None:
        return None
    return hashlib.sha256(json.dumps([sorted(map(str, part)) for part in rules],
                                     ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def harvest(out_root, policy=None, limit=None, previous=None, previous_lines=None,
            date=None, fetch_register=None, fetch_plan=None):
    """The register into `plans/`, gated, with only the amended buyers re-read.

    `previous` is the last harvest's `index.json` and `previous_lines` its kept lines, both
    from wherever the last harvest was delivered. On a runner that is the drive: its disk
    is new every night, and without them every buyer would be re-read and every line
    would be `new` for ever.

    A BUYER WHO DID NOT MOVE KEEPS ITS LINES. An unchanged plan is not downloaded, so its
    lines come from `previous_lines`; a buyer who left the register takes its lines with
    it. If the policy changed since the last harvest every buyer is re-read, because lines
    kept under the old gate say nothing about the new one.
    """
    date = date or time.strftime("%Y-%m-%d", time.gmtime())
    rules = policy_mod.load_policy(policy) if policy_mod is not None else None
    fingerprint = _policy_print(rules)
    previous = previous or {}
    before = list(previous_lines or [])
    seen = dict(previous.get("seen") or {})
    if previous.get("policy") != fingerprint:
        seen = {}                                 # a different gate: read everything again
    published, total = (fetch_register or register)()
    if limit:
        published = published[:limit]
    fetch_plan = fetch_plan or plan_file

    base = os.path.join(out_root, "plans")
    os.makedirs(os.path.join(base, "changes"), exist_ok=True)

    carried_from = {}
    for line in before:
        carried_from.setdefault(str(line.get("submission_id")), []).append(line)

    after, buyers, skipped, failed, unchanged = [], 0, 0, [], 0
    now_seen = {}
    for entry in published:
        sid = entry["submission_id"]
        # A buyer who has not resubmitted since the last harvest has the same plan, and the
        # register's timestamp is the portal saying so. Re-downloading 1,442 workbooks to
        # learn that takes most of an hour.
        if seen.get(sid) == entry["submitted"]:
            unchanged += 1
            now_seen[sid] = entry["submitted"]
            after.extend(dict(line) for line in carried_from.get(sid, []))
            continue
        try:
            head, table = rows(fetch_plan(sid))
        except Exception as exc:
            # A plan that could not be read keeps the lines it had and is not marked seen
            # at its new time, so the next night tries it again.
            failed.append({"submission_id": sid, "buyer": entry["buyer"],
                           "reason": str(exc)[:160]})
            after.extend(dict(line) for line in carried_from.get(sid, []))
            if sid in seen:
                now_seen[sid] = seen[sid]
            continue
        buyers += 1
        now_seen[sid] = entry["submitted"]
        lines = []
        for row in table:
            line = as_line(row, head, entry["buyer"], sid, entry.get("buyer_id"))
            if rules is not None and policy_mod.outside_scope(line, rules):
                skipped += 1
                continue
            lines.append(line)
        after.extend(keyed(lines))

    # A REGISTER WALKED SHORT DOES NOT REMOVE ANYONE. A plan the walk missed — resubmitted
    # mid-walk and jumped to page one behind it — is still published, so its lines stay.
    if total is not None and len(published) < total and not limit:
        walked = {e["submission_id"] for e in published}
        for sid, lines in carried_from.items():
            if sid not in walked:
                after.extend(dict(line) for line in lines)
                if sid in seen:
                    now_seen[sid] = seen[sid]

    new, changed, removed = diff(before, after, date)
    # A trial run reads a slice of the register, so "removed" would name every buyer it
    # did not reach. It says nothing about removals rather than something false.
    if limit:
        removed = []

    with open(os.path.join(base, "lines.jsonl"), "w", encoding="utf-8") as fh:
        for line in after:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")

    changes = {
        "schema": "plan-changes/1", "country": "LT", "date": date,
        "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        # On the first harvest every line is new, and a reader should not take that as news.
        "first_harvest": not before,
        "counts": {"new": len(new), "changed": len(changed), "removed": len(removed)},
        "new": new, "changed": changed,
        "removed": [{"key": l["key"], "buyer": l.get("buyer"), "title": l.get("title"),
                     "cpv_main": l.get("cpv_main")} for l in removed],
    }
    with open(os.path.join(base, "changes", "%s.json" % date), "w", encoding="utf-8") as fh:
        json.dump(changes, fh, ensure_ascii=False, indent=1)

    index = {
        "schema": "plans/2", "country": "LT", "source": "EPPS",
        "date": date,
        "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "register": REGISTER,
        "published_plans": len(published),
        # The count the portal prints. Fewer walked than this is a register read short.
        "register_total": total,
        "complete": not failed and not limit and (total is None or len(published) >= total),
        "buyers_read": buyers,
        "buyers_unchanged": unchanged,
        "lines_kept": len(after),
        "lines_gated": skipped,
        "policy": fingerprint,
        "failed": failed,
        "seen": now_seen,
        "lines_path": "plans/lines.jsonl",
        "changes_path": "plans/changes/%s.json" % date,
    }
    with open(os.path.join(base, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=2)
    return index, after, changes


def read_lines(path):
    out = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                if raw.strip():
                    out.append(json.loads(raw))
    return out


def harvest_local(out_root, policy=None, limit=None, date=None):
    """One harvest against whatever the last one left in `out_root/plans/`.

    On a workstation that is the last local run. On a runner it is what
    `deliver_lt.py --plans-prior` fetched back from the drive a moment earlier.
    """
    base = os.path.join(out_root, "plans")
    previous = {}
    try:
        with open(os.path.join(base, "index.json"), encoding="utf-8") as fh:
            previous = json.load(fh)
    except (OSError, ValueError):
        previous = {}
    before = read_lines(os.path.join(base, "lines.jsonl"))
    return harvest(out_root, policy, limit, previous=previous, previous_lines=before,
                   date=date)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Lithuanian annual procurement plans.")
    ap.add_argument("--out", default="work/LT")
    ap.add_argument("--policy", default=None)
    ap.add_argument("--limit", type=int, default=None,
                    help="stop after this many buyers, for a trial")
    ap.add_argument("--date", default=None, help="the night this harvest is filed under")
    args = ap.parse_args(argv)

    index, kept, changes = harvest_local(args.out, args.policy, args.limit, args.date)
    print("plans: %d published, %d buyer(s) read, %d unchanged, %d line(s) kept, %d gated"
          % (index["published_plans"], index["buyers_read"], index["buyers_unchanged"],
             index["lines_kept"], index["lines_gated"]))
    print("since the last harvest: %(new)d new, %(changed)d changed, %(removed)d removed"
          % changes["counts"])
    for line in changes["new"][:12]:
        print("  %-10s %-34s %s" % (line["cpv_main"] or "—", (line["buyer"] or "")[:34],
                                    (line["title"] or "")[:58]))
    if index["failed"]:
        print("%d plan(s) could not be read, every one named:" % len(index["failed"]))
        for gap in index["failed"][:10]:
            print("   %s  %s" % (gap["submission_id"], gap["reason"][:70]))
    return index


if __name__ == "__main__":
    main()
