# Payroll Customer Map — Spec

How this map should work going forward. Supersedes the eligibility/Auto-Payroll
framing of the original build; see `README.md` for the mechanical rebuild
steps (those stay the same, just with different SQL/fields).

## Cohort

Payroll-Live restaurant locations within **15 mi of Toast HQ** (333 Summer St).
Validated against live Snowflake data (2026-09-25): 502 locations / 342
customers, up from 353/228 today. The home pin (East Arlington) stays on the
map as a reference point only — no separate home-radius filter or cohort
inclusion.

## Map & customer card

**Kept as today:** pin per location colored by NPS, badge for multi-location
customers, click-to-open popup card, location name, address, home/office
distance, location count, pNPS, care tickets (12mo), first payroll date,
last-processed-payroll (name + email), and the Payroll/Scheduling/Tips Manager
chips.

**Removed:** Auto Payroll toggle, chip, and ring icon; the Auto Payroll
Eligibility section and 8-criteria grid in the card; the Eligibility filter;
the Area filter (home/office radius toggle — moot now that the cohort is a
single 15mi radius).

**Added to the card:**
- **Most recent payroll run date** — `EC_CUSTOMER.MOST_RECENT_CHECK_DATE`.
  Fully populated; ~1.8% of rows platform-wide are future-dated (pre-entered
  runs) — shown as-is, footnoted, not filtered out.
- **Bounced in last 6 months** (Yes/No badge) — `SOURCE_EC.BOUNCED_PAYPERIOD_CURRENT`.
  Validated: ~12% of live customers (3,391/28,258) bounced in the window —
  believable prevalence.
- **Active employee count** — `EC_CORE.EC_EMPLOYEE` where
  `EC_EMPLOYMENT_STATUS = 'Active'`, grouped by customer. Validated: median 20,
  average 34.7, only 47/28,258 live customers show zero.
- **Outreach status** — last emailed date, last visited date (see below).

## Filters

- **NPS:** All / Promoters / Passives / Detractors / No NPS — unchanged.
- **Emailed:** All / Emailed / Not emailed — new.
- **Visited:** All / Visited / Not visited — new.

(Auto Payroll, Eligibility, and Area filters removed — see above.)

## Data pipeline changes

`build/map_build.sql`:
- Cohort filter becomes `dist_office <= 15` only (drop the `dist_home`
  inclusion; keep computing `dist_home` for the card's info line).
- Drop the `AP_YES` hardcoded set and all 8 `elig_*` CTEs / `e_*` output
  columns — nothing in this file should reference "eligibility" anymore.
- Add an `EC_EMPLOYEE`-based active-employee-count CTE.
- Repurpose the bounce CTE into a plain `bounced_6mo` Y/N output column
  (today it's inverted into an eligibility pass/fail — same underlying data,
  different framing).
- Add `most_recent_check_date` to the output (already computed on `ecs` for
  the existing `QUALIFY`, just wasn't selected).

`build/gen_map.py`:
- Drop `ELIG`, `eligHtml`, `CRIT_LABELS`, and the Auto Payroll chip/ring/filter/
  legend entries.
- Add `mostRecentRun`, `activeEmployees`, `bouncedRecently` to each row and to
  the popup card.
- Add an `outreach` block per row (`lastEmailed`, `lastVisited`), left-joined
  from the new outreach log by company code (`cc`).
- Add Emailed/Visited filter buttons alongside the existing NPS group.

## Outreach tracking

**Storage:** a new git-tracked file, `build/outreach_log.csv`, columns
`cc, last_emailed, last_visited`. ~350 rows, contains only company codes and
dates — safe to commit (no names/emails/addresses). `gen_map.py` left-joins it
onto the Snowflake extract by `cc`.

**"Emailed" — inferred automatically, on demand.** No new credentials or
backend needed. When asked (e.g. "sync the outreach log"), Claude:
1. Reads `poster_email` for every customer in the current extract (already in
   `map_data.csv`).
2. Runs one bulk, paginated Gmail search over Sent mail via the `gws` CLI —
   `gws gmail users messages list --params '{"userId":"me","q":"in:sent after:2025/01/01"}' --page-all`
   — not one query per customer.
3. Builds a `recipient_email → most_recent_sent_date` map from the results.
4. Joins that against each customer's `poster_email` and writes
   `last_emailed` into `outreach_log.csv`.
5. Reruns `gen_map.py` → `encrypt.py` → commits and pushes `index.html`.

Caveat: only catches customers with a `poster_email` on file (215/217 in the
current extract, per the existing README caveat) and only when the email is
sent to that exact address.

**"Visited" — manual, on demand.** Tell Claude Code directly, e.g. "mark
Foxglove Terrace visited on 9/20," and it updates `outreach_log.csv` and
pushes. (Calendar-based inference was considered and rejected — restaurant
visits don't reliably show up as distinguishable calendar events.)

**Drafting outreach emails — a Claude Code action, drafts only, never sends.**
Not an in-map button — the map is a static page with no Gmail access. Instead,
ask Claude Code to draft outreach for one or more customers (by name, or e.g.
"everyone not-yet-emailed within 5 miles"). Claude:
1. Looks up each customer's `poster_name` / `poster_email` from the current
   extract.
2. Fills the template below with `{first_name}` and `{next_month}` (computed
   as the next calendar month).
3. Creates a **Gmail draft** via `gws gmail users drafts create` — left in
   your Drafts folder, unsent.
4. You review, edit, and send manually from Gmail.

Once sent, the next outreach-log sync picks it up automatically via the Gmail
Sent-folder scan — no separate "mark as emailed" step needed.

Template (from your 2026-09-25 example, fields in `{braces}`):

> Hi {first_name},
>
> I'm Adam and I'm on the R&D team for Toast Payroll. Every month I like to
> get out from behind my desk to meet with customers and see how they run
> their payroll playbook and get feedback on some upcoming features we're
> considering. Are you open to a visit sometime next month?
>
> I'm looking to come onsite for about 90 minutes, ideally on a Monday or
> Tuesday when you're running payroll. There's no extra prep on your end; I'd
> just ride shotgun while you run payroll exactly where and how you always do,
> asking a few questions and taking some notes along the way. The parts where
> you work outside of or around Toast are especially useful to see.
>
> This is research, not a sales call. Our objective is to make payroll—and
> any other related aspect of labor management—as seamless and reliable as
> possible.
>
> What does your schedule look like in {next_month}? Happy to work around
> your calendar.
>
> Thanks,
> Adam

## Refresh cadence

- **Snowflake data** (cohort, NPS, tickets, employee count, bounce, payroll
  dates): manual, on demand, roughly monthly. No GitHub Action, no stored
  Snowflake service-account credentials — the repo is public and this pull
  touches customer PII, so keeping it tied to your own authenticated `snow`
  session is the safer default. Trigger: ask Claude Code to refresh the map;
  it runs the existing three-step pipeline (`map_build.sql` → `gen_map.py` →
  `encrypt.py`) and commits/pushes `index.html`.
- **Outreach log** (emailed/visited): on demand, independent of the Snowflake
  refresh — no Snowflake query involved, much cheaper, same rebuild+push tail
  end.

## Open items

- Gmail search lookback window for the "emailed" sync is proposed at 12
  months — adjustable.
- If a company code (`cc`) is ever reassigned, its outreach history in
  `outreach_log.csv` goes stale silently (shows as "not emailed" until
  re-synced). Rare enough not to design around now.
