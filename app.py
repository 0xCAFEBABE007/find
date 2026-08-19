import os
import sqlite3
import uuid
import re
import time
import random
from datetime import datetime
from flask import Flask, request, render_template, redirect, url_for, session, g
 
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "iiitsfindone69")
 
DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "wordpair.db"))
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "naikav@0721")
COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # 1 year
 
# How many students you expect at once. The app makes sure there are enough
# word pairs seeded to cover this many people (2 people per pair), so nobody
# hits "sorry, no words left". Override with the CAPACITY env var if needed.
CAPACITY = int(os.environ.get("CAPACITY", "300"))
 
# Curated, recognizable word pairs. Add/edit as you like — these are used
# first, in this order, before any auto-generated filler pairs.
SEED_PAIRS = [
    
    ("Rock", "Roll"),
    ("Needle", "Thread"),
    ("Lock", "Key"),
    ("Mona", "Lisa"),
    ("Taj", "Mahal"),
    ("Eiffel", "Tower"),
    ("Big", "Ben"),
    ("dead", "lift"),
    ("Niagara", "Falls"),
    ("Golden", "Ratio"),
    ("Jantar", "Mantar"),
    ("6", "7"),
    ("stack", "overflow"),
    ("kuchu", "Puchu"),
    ("Aam", "Adami"),
    ("Jai", "Veeru"),
    ("Mogambo", "Khushhua"),
    ("Tenali", "Raman"),
    ("Sahara", "Desert"),
    ("Jalebi", "Fafda"),
    ("Hong", "Kong"),
    ("Birch", "Reduction"),
    ("Sri", "Lanka"),
    ("New", "Delhi"),
    ("Mahatma", "Gandhi"),
    ("Sherlock", "Holmes"),
    ("Harry", "Potter"),
    ("Genghis", "Khan"),
    ("Robin", "Hood"),
    ("Snow", "White"),
    ("Jack", "Sparrow"),
    ("Sleeping", "Beauty"),
    ("Bhagat", "Singh"),
    ("Abrahan","Lincoln"),
    ("Bhagavat","Geeta"),
    ("Silicon","Valley"),
    ("Milky","Way"),
    ("Panner","Tikka"),
    ("Frech","Fries"),
    ("Bermunda","Triangle"),
    ("Torjan","Horse"),
    ("Marie","Cuire"),
    ("Coca","Cola"),
    ("Periodic","Table"),
    ("Carbon","Dating"),
    ("Tylor","Swift"),
    ("Mini","Peka"),
   ("shrodinger", "cat"),
   ("black", "hole"),
   ("Golden", "Gate"),
   ("neural", "network"),
   ("dire", "wolf"),
   ("raksha","bandhan"),
   ("brain", "wash"),
   ("soviet", "union"),
   ("hanu", "man"),
   ("machine", "learning"),
   ("chole", "kulche"),
   ("breaking", "bad"),
   ("Jadi","Buti"),
   ("Patal","Lok"),
   ("Grass","Hopper"),
   ("Ping","Pong"),
   ("Netflix","&Chill"),
 ("Bonie","Clyde"),
 ("Blue","Print"),
 ("Camou","Flage"),
 ("Do_O","R_Die"),
 ("Lip","Stick"),
 ("Lady","Bug"),
 ("Ghost","Rider"),
 ("Davy","Jones"),
 ("Jack","Sparrow"),
 ("Land","Mine"),
 ("Shutur","Murg"),
 ("Sodium","Chloride"),
 ("Master","Piece"),
 ("Nav","Arambh"),
 ("Saltedfish","Maiden"),
 ("Luv","Kush"),
 ("Meta","Bolism"),
 ("",""),
 ("",""),
 ("",""),
 ("",""),
 ("",""),
 ("",""),
 ("",""),
 ("",""),
 ("",""),
 ("",""),
 ("",""),
 ("",""),
 ("",""),
 ("",""),
 ("",""),
 ("",""),
 ("",""),
 ("",""),
 ("",""),
 ("",""),
 ("","")
 
]
 
 
def build_seed_pairs(capacity):
    """Return enough (word1, word2) tuples to cover `capacity` people,
    starting with the curated SEED_PAIRS and padding with generated
    filler pairs if the curated list isn't big enough."""
    pairs_needed = (capacity + 1) // 2  # 2 people per pair
    pairs = list(SEED_PAIRS)
    n = 1
    while len(pairs) < pairs_needed:
        pairs.append((f"Puzzle {n} - A", f"Puzzle {n} - B"))
        n += 1
    return pairs[:pairs_needed] if pairs_needed > 0 else pairs
 
 
# ---------- Database helpers ----------
 
def _configure_connection(conn):
    conn.row_factory = sqlite3.Row
    # WAL lets reads happen while a write is in progress; busy_timeout makes
    # concurrent writers wait (and retry) instead of failing immediately with
    # "database is locked" when many students hit /login at once.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
 
 
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=30)
        _configure_connection(g.db)
    return g.db
 
 
@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()
 
 
def init_db():
    db = sqlite3.connect(DB_PATH, timeout=30)
    _configure_connection(db)
    db.execute("""
        CREATE TABLE IF NOT EXISTS pairs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            solved INTEGER NOT NULL DEFAULT 0,
            solved_at TEXT
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            pair_id INTEGER NOT NULL,
            assigned_uid TEXT,
            display_id INTEGER UNIQUE,
            FOREIGN KEY (pair_id) REFERENCES pairs(id)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            uid TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            word_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (word_id) REFERENCES words(id)
        )
    """)
    db.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_users_normalized_name
        ON users(normalized_name)
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair_id INTEGER NOT NULL,
            user1_name TEXT NOT NULL,
            user2_name TEXT NOT NULL,
            word1_text TEXT NOT NULL,
            word2_text TEXT NOT NULL,
            matched_at TEXT NOT NULL,
            FOREIGN KEY (pair_id) REFERENCES pairs(id)
        )
    """)
    db.commit()
 
    # Seed pairs only if table empty. Enough pairs are generated to cover
    # CAPACITY people (2 per pair) so a burst of sign-ups never runs out.
    existing = db.execute("SELECT COUNT(*) AS c FROM pairs").fetchone()["c"]
    if existing == 0:
        seed_pairs = build_seed_pairs(CAPACITY)
        internal_ids = []
        for w1, w2 in seed_pairs:
            cur = db.execute("INSERT INTO pairs (solved) VALUES (0)")
            pair_id = cur.lastrowid
            c1 = db.execute("INSERT INTO words (text, pair_id) VALUES (?, ?)", (w1, pair_id))
            internal_ids.append(c1.lastrowid)
            c2 = db.execute("INSERT INTO words (text, pair_id) VALUES (?, ?)", (w2, pair_id))
            internal_ids.append(c2.lastrowid)
        db.commit()
 
        # Hand out random, unique 3-digit public IDs (100-999), independent
        # of insertion/pair order, so seeing your own ID gives no clue about
        # what your partner's ID might be. If more than 900 words are ever
        # needed, fall back to a wider 4-digit range automatically.
        total = len(internal_ids)
        if total <= 900:
            id_pool = random.sample(range(100, 1000), total)
        else:
            id_pool = random.sample(range(1000, 10000), total)
        for internal_id, display_id in zip(internal_ids, id_pool):
            db.execute("UPDATE words SET display_id = ? WHERE id = ?", (display_id, internal_id))
        db.commit()
 
    db.close()
 
 
# ---------- User helpers ----------
 
def get_current_user(db):
    uid = request.cookies.get("uid")
    if not uid:
        return None
    user = db.execute("SELECT * FROM users WHERE uid = ?", (uid,)).fetchone()
    return user
 
 
def assign_word(db, uid, max_retries=25):
    """Assign the next unassigned word in order (lowest ID first) — NOT
    random. Words are stored word1, word2, word1, word2... per pair in
    seed order, so the 1st person to join gets word1 of pair 1, the 2nd
    person gets word2 of pair 1 (completing that pair), the 3rd person
    starts pair 2, and so on.
 
    Safe under concurrent requests (e.g. 300 students scanning a QR code
    at once): the UPDATE only succeeds if the row is still unassigned, so
    two people can never be handed the same word. If someone else grabs
    the row first, we just retry with the next lowest available one.
    """
    for _ in range(max_retries):
        row = db.execute(
            "SELECT id FROM words WHERE assigned_uid IS NULL ORDER BY id ASC LIMIT 1"
        ).fetchone()
        if row is None:
            return None  # no words left at all
 
        word_id = row["id"]
        cur = db.execute(
            "UPDATE words SET assigned_uid = ? WHERE id = ? AND assigned_uid IS NULL",
            (uid, word_id),
        )
        db.commit()
 
        if cur.rowcount == 1:
            return db.execute("SELECT * FROM words WHERE id = ?", (word_id,)).fetchone()
        # Someone else grabbed this exact word between our SELECT and
        # UPDATE — loop and try the next lowest unassigned word instead.
        time.sleep(0.01)
 
    return None
 
 
def parse_combined_id(raw):
    """Parse a combined id string like '345-782', '345,782' into two ints."""
    parts = [p for p in re.split(r"[\s,\-+/]+", raw.strip()) if p]
    ids = []
    for p in parts:
        if p.isdigit():
            ids.append(int(p))
    return ids
 
 
# ---------- Public routes ----------
 
@app.route("/", methods=["GET"])
def index():
    db = get_db()
    user = get_current_user(db)
    if user is None:
        return render_template("login.html")
 
    my_word = db.execute("SELECT * FROM words WHERE id = ?", (user["word_id"],)).fetchone()
    my_pair = db.execute("SELECT * FROM pairs WHERE id = ?", (my_word["pair_id"],)).fetchone()
 
    return render_template("home.html", user=user, my_word=my_word, my_pair=my_pair)
 
 
@app.route("/login", methods=["POST"])
def login():
    name = request.form.get("name", "").strip()
    if not name:
        return render_template("login.html", error="Please enter your name.")
 
    normalized = name.lower()
    db = get_db()
 
    # Recovery case: this name already registered before (e.g. they cleared
    # cookies, switched devices, or re-submitted the form). Log them back
    # into their ORIGINAL word instead of handing out a new one — this is
    # what stops a repeat login from creating a duplicate user and
    # orphaning their first word forever.
    existing = db.execute(
        "SELECT * FROM users WHERE normalized_name = ?", (normalized,)
    ).fetchone()
    if existing:
        resp = redirect(url_for("index"))
        resp.set_cookie("uid", existing["uid"], max_age=COOKIE_MAX_AGE, httponly=True, samesite="Lax")
        return resp
 
    uid = str(uuid.uuid4())
    word = assign_word(db, uid)
    if word is None:
        return render_template("login.html", error="Sorry, all words have been assigned. No slots left.")
 
    try:
        db.execute(
            "INSERT INTO users (uid, name, normalized_name, word_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (uid, name, normalized, word["id"], datetime.utcnow().isoformat()),
        )
        db.commit()
    except sqlite3.IntegrityError:
        # Extremely rare race: someone else with the exact same name
        # registered in the tiny window between our SELECT and INSERT above.
        # Give back the word we grabbed (so it isn't wasted) and recover
        # into whichever registration won the race instead.
        db.execute("UPDATE words SET assigned_uid = NULL WHERE id = ?", (word["id"],))
        db.commit()
        winner = db.execute(
            "SELECT * FROM users WHERE normalized_name = ?", (normalized,)
        ).fetchone()
        uid = winner["uid"] if winner else uid
 
    resp = redirect(url_for("index"))
    resp.set_cookie("uid", uid, max_age=COOKIE_MAX_AGE, httponly=True, samesite="Lax")
    return resp
 
 
@app.route("/guess", methods=["POST"])
def guess():
    db = get_db()
    user = get_current_user(db)
    if user is None:
        return redirect(url_for("index"))
 
    my_word = db.execute("SELECT * FROM words WHERE id = ?", (user["word_id"],)).fetchone()
    my_pair = db.execute("SELECT * FROM pairs WHERE id = ?", (my_word["pair_id"],)).fetchone()
 
    raw = request.form.get("combined_id", "")
    ids = parse_combined_id(raw)
 
    message = None
    success = False
 
    if len(ids) < 1:
        message = "Please enter a valid word ID (yours and your partner's, e.g. '345-782')."
    else:
        # Accept either just the partner's id, or both ids together
        candidate_ids = [i for i in ids if i != my_word["display_id"]]
        if not candidate_ids:
            message = "That's just your own ID — enter your partner's word ID too."
        else:
            partner_id = candidate_ids[0]
            partner_word = db.execute("SELECT * FROM words WHERE display_id = ?", (partner_id,)).fetchone()
 
            if partner_word is None:
                message = f"No word found with ID {partner_id}."
            elif partner_word["pair_id"] != my_word["pair_id"]:
                message = "That's not your match. Keep looking!"
            elif my_pair["solved"]:
                message = "This pair has already been matched and recorded."
            else:
                partner_user = None
                if partner_word["assigned_uid"]:
                    partner_user = db.execute(
                        "SELECT * FROM users WHERE uid = ?", (partner_word["assigned_uid"],)
                    ).fetchone()
                partner_name = partner_user["name"] if partner_user else "Unknown"
 
                now = datetime.utcnow().isoformat()
                db.execute("UPDATE pairs SET solved = 1, solved_at = ? WHERE id = ?", (now, my_pair["id"]))
                db.execute(
                    """INSERT INTO matches (pair_id, user1_name, user2_name, word1_text, word2_text, matched_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (my_pair["id"], user["name"], partner_name, my_word["text"], partner_word["text"], now),
                )
                db.commit()
                success = True
                message = f"🎉 Match found! You ({user['name']}) and {partner_name} are a pair!"
 
    my_pair = db.execute("SELECT * FROM pairs WHERE id = ?", (my_word["pair_id"],)).fetchone()
    return render_template(
        "home.html", user=user, my_word=my_word, my_pair=my_pair, message=message, success=success
    )
 
 
# ---------- Admin routes ----------
 
@app.route("/admin", methods=["GET"])
def admin():
    if not session.get("is_admin"):
        return render_template("admin_login.html")
 
    db = get_db()
    users = db.execute("""
        SELECT users.*, words.display_id AS word_display_id
        FROM users JOIN words ON users.word_id = words.id
        ORDER BY users.created_at DESC
    """).fetchall()
    matches = db.execute("SELECT * FROM matches ORDER BY matched_at DESC").fetchall()
    words = db.execute("""
        SELECT words.*, pairs.solved AS pair_solved
        FROM words JOIN pairs ON words.pair_id = pairs.id
        ORDER BY words.pair_id, words.id
    """).fetchall()
 
    total_pairs = db.execute("SELECT COUNT(*) AS c FROM pairs").fetchone()["c"]
    solved_pairs = db.execute("SELECT COUNT(*) AS c FROM pairs WHERE solved = 1").fetchone()["c"]
    total_words = db.execute("SELECT COUNT(*) AS c FROM words").fetchone()["c"]
    assigned_words = db.execute("SELECT COUNT(*) AS c FROM words WHERE assigned_uid IS NOT NULL").fetchone()["c"]
    total_users = db.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
 
    stats = {
        "total_pairs": total_pairs,
        "solved_pairs": solved_pairs,
        "unsolved_pairs": total_pairs - solved_pairs,
        "total_words": total_words,
        "assigned_words": assigned_words,
        "unassigned_words": total_words - assigned_words,
        "total_users": total_users,
    }
 
    return render_template("admin.html", users=users, matches=matches, words=words, stats=stats)
 
 
@app.route("/admin/login", methods=["POST"])
def admin_login():
    password = request.form.get("password", "")
    if password == ADMIN_PASSWORD:
        session["is_admin"] = True
        return redirect(url_for("admin"))
    return render_template("admin_login.html", error="Incorrect password.")
 
 
@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("admin"))
 
 
# ---------- Startup ----------
 
init_db()
 
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
 
