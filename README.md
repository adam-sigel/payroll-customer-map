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

# 3. Re-encrypt into index.html (prompts for the password)
python3 encrypt.py
```

`map.source.html` and `build/map_data.csv` are gitignored — they hold customer
names, addresses, and contact emails in the clear, which is the reason
`index.html` is gated in the first place. Only the ciphertext is committed.

## Cohort

Payroll-Live restaurant locations within **6 mi of Toast HQ** (333 Summer St) or
**3 mi of home** (East Arlington). The home radius is kept so the "Near home"
filter stays populated — home is ~7 mi from the office.

## Encryption

`index.html` is a password gate: PBKDF2-SHA256 (100,000 iterations, 32-byte key)
→ AES-CBC, then `document.write` of the decrypted map. `encrypt.py` reuses the
existing `index.html` as its gate template and swaps only the `PAYLOAD` line, so
the two cannot drift apart. Losing the password means rebuilding from step 1 —
it is not recoverable from the ciphertext.

## Caveats baked into the map

- **Auto Payroll enrollment is not tracked in Snowflake.** The two "Enabled"
  customers are hand-curated (`AP_YES` in `build/gen_map.py`); everything else
  defaults to "Not enabled".
- **"Tax tasks complete" is a proxy** — no tax-task table exists, so it checks
  whether every active FEIN has posted tax rows this quarter (~82% agreement
  with the previously hand-collected values).
- **pNPS coverage is thin** (66 of 353 locations) — most pins are grey "No NPS".
- **"Last processed payroll"** is the user on the most recent successful payroll
  *open* event, resolved via Estratex email → Toastweb name (215 of 217
  customers with any open event).
