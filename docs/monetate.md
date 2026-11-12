# Connecting Monetate (change dates for Monetate clients)

For Monetate clients such as Domino's, winners usually go to 100% in Monetate straight after the test. That
date, not the release date, is the change date. The app can look it up for you.

## What you get

In step 1, after you pick a recipe for a Monetate client, open **"Look up the test and 100% dates in
Monetate"** and search by experience name (e.g. `283`). You'll see each matching experience with its status,
start and end dates, traffic splits, and a **100% experience** flag (one variant getting all traffic).

- If the winner was set live as **its own experience** (e.g. "EXP283 – LIVE 100%"), its start date is the
  change date.
- If the winner was set to 100% by **editing the test experience**, Monetate's API only shows today's split,
  with no history. Use "View Experience History" in Monetate, or `recipes/sql/dominos_experiment_timeline.sql`
  in BigQuery, to find the date.

The API has no results data (sessions, conversions), so nothing else changes.

You can also run it from a terminal:

```
python -m impact_tool.monetate dominos 283 > experiences.csv
```

## One-off setup (Monetate admin)

1. Create a key pair on your machine:

   ```
   openssl genrsa -out monetate_private.pem 2048
   openssl rsa -in monetate_private.pem -pubout -out monetate_public.pem
   ```

2. In Monetate, go to **Settings → Sites → API Keys**, upload `monetate_public.pem`, and note the **API
   username** it shows.
3. Find the **retailer shortname** (it's in Monetate API URLs; ask Monetate support if unsure).
4. Add the details to the app's **Secrets** (hosted app settings), in the format of
   `.streamlit/secrets.toml.example`:

   ```toml
   [monetate.dominos]
   retailer = "..."
   username = "..."
   private_key = """-----BEGIN PRIVATE KEY-----
   ...
   -----END PRIVATE KEY-----"""
   ```

   For GitHub Actions or a terminal, use environment variables instead: `MONETATE_DOMINOS_RETAILER`,
   `MONETATE_DOMINOS_USERNAME`, `MONETATE_DOMINOS_PRIVATE_KEY`.
5. Delete `monetate_private.pem` from your machine once it's stored in Secrets, or keep it in the password
   manager. **Never commit it.** `.gitignore` excludes `*.pem` and `.streamlit/secrets.toml`.

To revoke access, deactivate the key in Monetate.

## Adding another Monetate client

Add `monetate_client: <key>` under `data_source` in the client's recipe file, and a matching
`[monetate.<key>]` block in Secrets.
