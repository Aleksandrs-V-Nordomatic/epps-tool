# epps-tool

Downloads every public document of a Lithuanian EPPS procurement and turns it into text.
Deterministically, with no model in the main path, and with every file it could not read
named rather than quietly missing.

**Proprietary. No licence is granted — see [LICENSE](LICENSE).** Issues and pull requests
are closed and unreviewed.

Nothing here decides which procurements matter. The tool fetches what it is pointed at,
extracts it, and says what it could not read; the interest, the destination and the
schedule all arrive from outside as configuration.

## One country

This tool reads one country: Lithuania, from EPPS. `country.py` names it and nothing else,
and `--country` has no default — a run launched without it stops rather than publishing
under a folder the tool guessed, which is a failure that otherwise succeeds quietly.

EPPS is a European Dynamics Java application serving a definition list and one archive per
tender, and it refuses no caller. Everything after the read — the pack, the digests, the
index, the change comparison, the delivery — is deliberately generic, so the shape a reader
sees does not depend on which portal it came from.

## What it does

```
EPPS search  ─walk─→  procurement page  ─fetch─→  one archive  ─extract─→  Markdown
                            │                                                  │
                            └── procurement.json                               └── what could not
                                title · buyer · deadline · value · CPV ·           be read, named with
                                plan reference                                     size and digest
```

EPPS serves a whole tender as a single archive, so there is no per-document negotiation and
no id lottery: the window names the resources, and each resource is one request.

## Use

```bash
python3 eis_tool.py day 2026-08-20 --country LT --out work
python3 eis_tool.py plans --country LT --out work
python3 eis_tool.py doors --country LT --out work
python3 eis_tool.py extract --pack out
```

In CI: **lt-day.yml**, one runner, one pass, and a delivery step behind it.

Lithuania publishes three populations and only the first is a day. `day` takes the window —
tenders and market consultations together, told apart by procedure. `plans` reads the annual
procurement plans buyers file months ahead. `doors` lists the dynamic purchasing and
qualification systems, which are applications rather than bids. The last two are a stock read
on demand, not a stream: a system announced once is no more interesting on the day it appeared
than on any day after.

The day travels with its watch list. `--targets` names resources somebody is still deciding
about; they ride with the window in one pass rather than a second run, because two runs are two
draws at one portal for one date and two answers about what that date contained. The recall gate
does not apply to them — it decides what is worth fetching for the *first* time, and these
already have a card.

Requirements: Python 3.12, `pip install -r requirements.txt` (pinned exactly), plus
`p7zip-full` and LibreOffice for 7z archives and Word 97 attachments.

## What one tender looks like

This is a pack as it sits on the runner, and as it sits inside the delivery below.

```
pack/
  procurement.json    the tender's own facts, read off its page — including the plan
                      reference, the thread back to the register where the same object
                      appeared months earlier as a line in a spreadsheet
  manifest.json       what was downloaded, with sha256 per file
  normalized/         one Markdown document per readable file, plus the audit list
  index.json          what is here and what is worth opening — carries the amendment
                      number that placed each document and the address a person clicks
  llm/                what the decoder could not read, read anyway — local OCR by default,
                      a hosted model only if one is configured. Marked `ocr-fallback` or
                      `llm-fallback` per entry, never merged into `normalized/`, and not
                      delivered: it stays in the pack and the run's artifact.
  summary.json        counts, bytes, digests
```

The directory is named `llm/` for a lane that has not been model-first since Tesseract became
its default. Renaming it would move paths the manifest already hands out, so the name stays and
this note carries the correction.

## Where it lands

```
work/LT/  <date>/{day.json,changes.json}   tenders/<pid>/…
          plans/{index.json,lines.jsonl}   doors/{index.json,doors.jsonl}
```

**`GRAPH_DEST_ROOT` names the folder that CONTAINS the country folders, not one of them.** The
code is appended by the tool. Configuring the full path instead would put the country in two
places that can disagree, and the way that disagreement surfaces is a day of one country's
tenders sitting in the other's folder — uploaded cleanly, indexed validly, with nothing anywhere
saying so. A root already ending in a country code is refused, because `work/LT/LT` is the same
mistake wearing a different hat, and so is a root copied across from the Latvian deployment that
still ends in `/LV`.

**No shards, and none needed.** A shard exists so four runners can draw four addresses at a
portal that refuses a third of them. EPPS refuses none and serves each tender as one archive, so
the day is written directly rather than reconciled from shard indexes — the same two files,
arrived at without the machinery Latvia cannot do without. There is no `probe` step here for the
same reason: a check that can only ever answer yes teaches a reader that the failure it names
does not happen, and it does not.

**The delivery is its own file.** `deliver_lt.py` ships the index the fetch already wrote,
because Lithuania's index is not derivable from `procurement.json` and the normalized manifest:
it carries the amendment number that placed each document and the address a person clicks, both
read off the EPPS catalogue and both gone by the time `procurement.json` is written.
`deliver_graph.py` is present as the shared Graph client — the token, the retry set, the upload
session, the archive builder — and its sharded `main()` is not wired to anything here.

**The change comparison happens at delivery, against the drive.** `lt_day` compares each
procurement with `state.json` in its own home, which is right on a workstation that keeps `work/`
and worthless on a runner, whose disk is new every night: every procurement would come back
`new`, for ever, and `changes.json` would be a copy of the day. The drive is the only durable
thing in the arrangement, so `deliver_lt` reads the stored state back out of it and rewrites the
day's verdict before uploading it. `compared_against: "drive"` in the delivered `changes.json`
says so.

## What gets published

A tender has one home. A day is a list of what moved. This shape is the tool's own and is what a
reader may rely on:

```
tenders/<pid>/                the tender, complete, whenever each part of it arrived
  procurement.json              its facts, as above
  manifest.json                 what was downloaded, sha256 per file
  doc/<digest>.md               the Markdown, one file per document, named for its source
  normalized/manifest_normalized.json
  structure.json                Word numbering, when the tender had any
  index.json                    what is here and what is worth opening — written LAST
  state.json                    the fingerprint the next run compares against
  seen.json                     when it was first and last looked at
  runs/<date>.json              what that date's run found — one file per date
  <pid>.zip                     the whole tender, one request

<date>/
  changes.json                what moved — read this first
  day.json                    the list, and the proof the day is there to be read
```

**The day folder holds no tender bytes, and no per-tender file.** A day is a statement about what
a run did; the tenders it did it to are addressed from here. `changes.json` and `day.json` answer
everything a consumer asks of a day, and both are small — so a reader takes the two, then fetches
only the tenders they point at.

**A tender delivered again uploads only the documents that were not there before.** Its name is
the digest of the file it came from, so an unchanged document has the same address every day and
there is nothing to re-send; `index.json` in the home goes on naming it, and a reader that wants
the tender whole never has to know which day any part of it arrived on. A superseded document is
not deleted — a digest cannot name two different files, so the previous version stays readable
and `runs/` says which day it stopped being current.

**And a tender that did not move writes only `seen.json` and `runs/<date>.json`.** Nothing else
needs rewriting, because nothing about the tender is different. That is why `state.json` carries
no date and no run id — a fingerprint that moved on its own would have to be rewritten every day
to say so, and it is the second largest file in the home.

**An index that exists was written after everything it names**, and `state.json` is written after
the index. The first is the reader's proof that a home is whole; the second is the next run's
proof of what it may skip, and a fingerprint that landed before the documents it vouches for
would let tomorrow carry over text that is not there. `day.json` goes last of all, and a reader
that lists folders instead of reading it will read the wrong day.

The shape above is this repository's contract. Which tender matters is not: no judgement is made
here and none can be.

## What changed, and how it is known

`changes.json` names every tender the day touched and what moved about it — `new`, `changed` or
`unchanged` — with the values on both sides of each move. A day on which two deadlines shifted is
a few kilobytes; the tenders themselves are not in it.

Everything is compared over sha256 of **original** bytes, never over the Markdown. That is what
keeps the answer honest: `normalize.py` is deterministic for a given version, but two versions of
it may render one unchanged PDF differently, and a diff taken over the text would report that as
the buyer replacing a document. The extractor's own version rides in `state.json`, so *the text
was extracted again* is a different sentence from *the tender changed*.

**The facts have their own version, for the same reason and a different file.** They are read by
`lt_page`, not by the extractor: one more spelling in a label map, or a field that used to come
back null, changes facts across the whole corpus in a night. Compared blind that is an amendment
reported against every buyer in the register, from this side of the wire. So a page read by a
different parser has none of its facts compared, the run is spent refreshing the fingerprint so
the next one compares clean, and no document travels for it. The version stamped is this
country's reader — `country.parser_files` decides that, so an `lt_page` edit can never be
invisible and another country's can never be a false alarm.

Where the previous state comes from is the destination itself. A run remembers nothing: the
runner is new and the previous run's artifact is exactly what a consumer cannot reach, so each
tender's `state.json` is read back off the drive with the credential the delivery already holds.
No cache, no committed file, no second service.

**What that buys, and what it costs.** A delta delivery trusts `state.json` about what is already
on the drive, so a document deleted by hand is not noticed and not replaced. The remedy is one
deletion — remove that tender's `state.json` and the next run delivers it whole.
`runs/<date>.json` is never read by the delivery and there is one per date, so `state.json` can
be rebuilt from the runs if it is ever lost.

## Properties worth knowing before changing anything

**Partial success is failure.** If any expected record or file is missing the run exits non-zero
and writes nothing to the success path. Publishing a partial tender would also record a
fingerprint saying that is what the procurement is, and every later run would agree with it. A
tender that looks downloaded and is not is worse than one that plainly failed, because only the
second gets fixed.

**Nothing is dropped on a guess about importance.** Usefulness is never judged — that would need
a model. Each file is classified only by whether a decoder recovered characters from it.
Everything readable is extracted in full; everything else is listed by name, size and digest, so
a gap is visible instead of silent.

**Same bytes in, same text out.** Dependencies are pinned exactly, walk orders are sorted. No OCR
and no table detection in the main path: table text is already in the text layer, so detection
cost a great deal of time, recovered nothing plain extraction had missed, and emitted rotated
text backwards.

**An empty window is reported as broken, not as quiet.** Lithuania publishes on the order of a
hundred resources a working day and thirteen on a Sunday; zero is not something EPPS does. What
produces zero is the crawl breaking — the results table gaining a column, the displaytag page
parameter changing under a redeploy — and each of those returns an empty list rather than an
error. So `day.json` carries `discovery_failed` and refuses to call itself complete, because the
alternative is a green run, a complete day, an empty morning, and nothing to tell it from a
holiday.

**A hole in the watch is not the day arriving short.** The day is the window; a watched card is a
standing question asked of it. A watched resource no view will serve is counted in
`coverage.watch_holes` and named in `lost`, and it leaves `complete` alone — otherwise every
night would be incomplete until somebody edited the board, and a flag that is always on is one
nobody reads on the night it starts meaning something.

**One retry policy, and it lives in `net.py`.** Every request this tool makes goes through it:
the honest exception set — `OSError` and `http.client.HTTPException`, because a reset arrives as
`RemoteDisconnected` and that is neither a `URLError` nor a `TimeoutError` — a budget that
outlasts a portal hiccup, `Retry-After`, and the parse inside the retry because a portal under
load answers 200 with an error page. Call sites do not get a vote on it. A rule that has to be
re-derived at each call site is a rule that gets written wrong again.

## The recall gate

Which notices are worth fetching is not decided here. `policy.py` holds the rule and nothing
else: recall terms and CPV prefixes arrive from the environment as JSON, so this repository names
no industry, no trade and no target, and a reader learns the shape of the filter without learning
what anyone points it at.

**The gate has two ways in, and a code is one of them.** Recall used to be title-only: a CPV code
could exclude a notice or rescue one from an exclusion, but never bring anything in, so the
gate's whole sensitivity rested on a buyer choosing words somebody had guessed in advance.
The failure that produces is common and needs no example: a buyer writes three vague words and
then classifies the purchase exactly, so the gate can hear only the three words.
`recall_cpv_prefixes` closes that. Exclusions still bind, so the clause can only widen what is
fetched, and this repository goes on naming no industry, no trade and no target.

**The gate is required, not optional, in the scheduled lane.** `policy.load_policy` fails open by
design: an unreadable policy returns `None` rather than dropping everything. Inside a library
that is right; for an unattended night it would mean fetching every archive the window holds from
a state portal because a secret was misspelt. `lt-day.yml` therefore checks that the policy
parses before the portal is touched, and stops if it does not.

**And the policy comes from the secret or the run does not happen.** `lt_policy.example.json` is a
deliberately unrelated illustration — office printing — so that this repository discloses nothing
about what any deployment actually hunts for. It exists to be copied into `LT_POLICY` and to
document the shape, never to be run against. A scheduled night with no secret stops rather than
falling back: run against the example it would fetch almost nothing, deliver a valid day and
report success, and an empty morning reads exactly like a quiet one.

## Scans, and the account this does not need

There is no model in extraction. `assist.py` is a quarantined fallback that reads **only** the
files the deterministic extractor already listed as unreadable — scans with no text layer — and
writes **only** into `llm/`, cached by content digest so a re-run costs nothing and returns
identical bytes. Drawings are never sent. Consumers treat that text as grounds to look, never as
a located quote.

**The default reader is Tesseract on the runner: no account, no API key, no billing relationship,
nothing to migrate.** That is deliberate. An automation whose credential belongs to a private
sign-up is a dependency nobody owns, and it fails at the worst possible moment. The volume argues
for it too: the deterministic extractor reads most tenders whole, which leaves this lane an
ordinarily empty queue.

A hosted model is available for the day a scan defeats OCR — `--provider gemini` with
`GEMINI_API_KEY` — and adding another is one entry in `PROVIDERS`. Each result records which
reader produced it: `ocr-fallback` or `llm-fallback`, never merged.

Nothing this lane does may fail a tender, and the guard around it catches every exception rather
than one class.

## Tests

```bash
python3 -m unittest discover -s tests -t tests
```

Everything is offline. The parsers are pure functions over saved HTML, so a test never needs the
portal, and the recall-policy check embedded in `lt-day.yml` is extracted from the real workflow
and executed — a guard that is itself unguarded is how two nights were lost once.
