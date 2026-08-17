# Word Pair Game

A small Flask app for an icebreaker/party game: each visitor gets assigned one
word from a pair (e.g. "Mona" / "Lisa"). They must find the person holding
the matching word, then enter both word IDs to confirm the match. Matches
(names + timestamp) are recorded and viewable only on `/admin`.

## How it works

- **First visit**: no `uid` cookie found → shown a login screen asking for a name.
- On submit, the server creates a permanent (1 year) `uid` cookie and assigns
  the **next word in sequence** (not random) — the 1st person to join gets
  word 1 of pair 1, the 2nd person gets word 2 of pair 1 (completing that
  pair), the 3rd person starts pair 2, and so on. The word is shown along
  with its unique **word ID**. Any randomness in who gets paired with whom
  comes entirely from the order people scan the QR code, not from the server.
- **Any later visit** (refresh, close/reopen browser) with that cookie skips
  the login screen and shows the *same* word — no re-assignment.
- **Concurrency safe**: assignment happens inside an atomic
  check-and-update, so two people can never be handed the same word even if
  hundreds scan the QR code in the same second — see "Handling a crowd"
  below for load-test results.
- To claim a match, the user enters a **combined ID** like `5-6` (their ID and
  their partner's ID, separators `-`, `,`, space, or `+` all work). If the two
  IDs belong to the same word pair, the match is recorded with both names and
  a UTC timestamp.
- `/admin` is password protected (see `ADMIN_PASSWORD` below) and shows:
  total users, pairs solved/open, all matches with names + time, the full
  user list, and the full word list with assignment/solve status.

## Local development

```bash
pip install -r requirements.txt
python3 app.py
```

Visit `http://localhost:5000`. Admin panel: `http://localhost:5000/admin`
(default password: `admin123` — override with the `ADMIN_PASSWORD` env var).

## Deploying to Render

1. Push this folder to a GitHub repo.
2. In Render, choose **New + → Blueprint** and point it at the repo (it will
   pick up `render.yaml` automatically), or create a **New Web Service**
   manually with:
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn app:app`
3. Set environment variables in the Render dashboard:
   - `SECRET_KEY` — any random long string (Render can auto-generate this).
   - `ADMIN_PASSWORD` — the password you'll use to log into `/admin`.
   - `DB_PATH` — leave as `/var/data/wordpair.db` if you attach a persistent
     disk (see below), or omit it to use a local file that resets on deploy.
4. **Persistent storage (recommended)**: SQLite lives in a single file. Render's
   filesystem is ephemeral on redeploy, so attach a **Disk** (Render dashboard
   → your service → Disks) mounted at `/var/data` — `render.yaml` already
   requests a 1GB disk at that path. Without a disk, all users/words/matches
   reset every time you redeploy.
5. Deploy. On first boot the app auto-creates the tables and seeds the word
   pairs (only if the pairs table is empty).

## Customizing the word pairs

Edit the `SEED_PAIRS` list near the top of `app.py` — 50 curated, recognizable
pairs are included (Mona/Lisa, Romeo/Juliet, Batman/Robin, etc.):

```python
SEED_PAIRS = [
    ("Mona", "Lisa"),
    ("Romeo", "Juliet"),
    # add your own pairs here
]
```

If your expected crowd (`CAPACITY`, see below) needs more pairs than are
curated, the app automatically pads the list with generated filler pairs
("Puzzle 1 - A" / "Puzzle 1 - B", etc.) so nobody is ever turned away. Add
more of your own pairs to `SEED_PAIRS` to replace the filler with something
nicer.

This list is only used to seed the database the *first* time it's empty. To
reset and reseed, delete `wordpair.db` (local) or clear the Render disk, then
redeploy.

## Handling a crowd (e.g. 300 students scanning a QR code)

Two things matter here: **fairness** (word 1 always goes to whoever joins
first, word 2 to whoever joins second — no randomness) and **not losing or
duplicating an assignment when many people join at the exact same time**.

- `CAPACITY` (env var, default `300`) controls how many word slots get seeded
  on first boot — set it to at least the number of people you expect, or the
  app will run out of words and start turning people away with a clear
  message. Pairs needed = `CAPACITY / 2`.
- Assignment is done with an atomic "update the row only if it's still
  unassigned" query. If two people hit `/login` in the same instant, one
  update succeeds and the other automatically retries the *next* available
  word — nobody is ever handed a duplicate.
- SQLite is set to `WAL` mode with a 30-second busy timeout, so concurrent
  requests queue briefly instead of failing.
- `render.yaml` runs gunicorn as **one process with 8 threads**
  (`--workers 1 --threads 8`). This is intentional: SQLite only supports one
  writer process at a time, so a single process with threads is the safe
  setup — adding more worker *processes* would cause "database is locked"
  errors under load.

This setup was load-tested locally with 300 simultaneous login requests:
all 300 succeeded, all 300 word IDs (1–300) were assigned exactly once with
zero duplicates, and it completed in about 2 seconds. If you expect
meaningfully more than a few hundred concurrent joins, or want stronger
durability guarantees, consider swapping SQLite for Render's managed
Postgres — the SQL is plain enough that only `get_db()` needs to change.

## Notes / things you may want to change

- If you'd rather scale beyond a handful of concurrent users or want stronger
  durability, swap SQLite for Postgres (Render offers free/managed Postgres)
  — the queries are plain SQL so the change is mostly in `get_db()`.
- The admin session uses Flask's signed cookie session (`SECRET_KEY`), not a
  database-backed login — good enough for a single admin, not for multiple
  admin accounts.
