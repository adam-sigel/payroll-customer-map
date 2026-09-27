# Payroll Customer Map — Boston Area

Leaflet map of payroll-Live Toast customers near the office and home, served as a
single password-gated `index.html`.

## Rebuilding

```bash
# 1. Refresh the extract from Snowflake (writes build/map_data.csv)
snow sql -q "ALTER SESSION SET QUERY_TAG='claude-code:query-snowflake'; $(cat build/map_build.sql)" \
  -c toast --format CSV > build/map_data.csv

# 2. Generate the plaintext map (writes map.source.html)
python3 build/gen_map.py

# 3. Re-encrypt into index.html
python3 encrypt.py
```

Step 3 reads the password from `MAP_PASSWORD` in a gitignored `.env` file if
present, falling back to an interactive prompt otherwise.

`map.source.html` and `build/map_data.csv` are gitignored — they hold customer
names, addresses, and contact emails in the clear, which is the reason
`index.html` is gated in the first place. Only the ciphertext is committed.

## Cohort

Payroll-Live restaurant locations within **15 mi of Toast HQ** (333 Summer St).
Home (East Arlington) stays on the map as a reference pin only — there's no
separate home-radius filter or inclusion.

## Encryption

`index.html` is a password gate: PBKDF2-SHA256 (100,000 iterations, 32-byte key)
→ AES-CBC, then `document.write` of the decrypted map. `encrypt.py` reuses the
existing `index.html` as its gate template and swaps only the `PAYLOAD` line, so
the two cannot drift apart. Losing the password means rebuilding from step 1 —
it is not recoverable from the ciphertext.

## Outreach tracking

`build/outreach_log.csv` (`cc, last_emailed, last_visited`) is git-tracked —
just company codes and dates, no PII. `gen_map.py` left-joins it onto the
Snowflake extract by `cc`.

- **Emailed** is synced from Gmail on demand: ask Claude Code to "sync the
  outreach log" — it does one bulk Sent-mail search via the `gws` CLI, matches
  recipients against each customer's `poster_email`, and updates the log. Only
  catches customers with a `poster_email` on file, and only if you emailed
  that exact address.
- **Visited** is manual — tell Claude Code, e.g. "mark Foxglove Terrace
  visited on 9/20."
- **Drafting outreach emails** is a Claude Code action, not an in-map button:
  ask it to draft for a customer (or a filtered set) and it fills
  `build/outreach_template.txt` and creates an unsent Gmail draft via
  `gws gmail users drafts create`. Nothing is ever sent automatically.

See `MAP_SPEC.md` for the full spec.

## Caveats baked into the map

- **pNPS coverage is thin** — most pins are grey "No NPS".
- **"Last processed payroll"** is the user on the most recent successful payroll
  *open* event, resolved via Estratex email → Toastweb name.
- **"Last payroll run"** (`MOST_RECENT_CHECK_DATE`) can occasionally show a
  future date — a small share of rows platform-wide are pre-entered runs.
