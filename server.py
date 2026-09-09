#!/usr/bin/env python3
"""Local web app for the Aladi catalogue (one catalogue per item language).

Serves the static UI plus a small JSON API. Every catalogue endpoint takes an
optional `lang=` (eng | ita, default eng) selecting which per-language dataset
under data/<lang>/ to read:
    GET /api/catalogue?lang=eng   latest snapshot (title/author/pub/year/isbn/bib)
    GET /api/enrichment?lang=eng  {bib: [form, aud, genres, libs]}
    GET /api/snapshots?lang=eng   list of snapshot dates + counts
    GET /api/diffs?lang=eng       list of diff reports (newest first)
    GET /api/languages            catalogues available, with record counts
    GET /api/libraries            branch code -> name (shared across languages)
    GET /api/availability?bib=bX  live per-copy status fetched from aladi.diba.cat
                                  (on-demand only — nothing is bulk-polled)

Run:  python3 server.py   then open http://localhost:8377
Auth: set ALADI_USERS (+ ALADI_SECRET) to require a login — see the Auth block.
      python3 server.py --hash-password   prints a hash for ALADI_USERS.
"""
import base64
import hashlib
import hmac
import html as htmllib
import json
import secrets
import sys
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from http.server import HTTPServer, SimpleHTTPRequestHandler

import langs

PORT = 8377
ROOT = os.path.dirname(os.path.abspath(__file__))
BIND = os.environ.get("ALADI_BIND", "127.0.0.1")
BASE = "https://aladi.diba.cat"
SCOPE = "S171*eng"
UA = {"User-Agent": "Mozilla/5.0 (compatible; personal-catalogue-app)"}

_avail_cache = {}  # bib -> (timestamp, payload)
_avail_lock = threading.Lock()
AVAIL_TTL = 300  # 5 min
# One cache entry per language: lang -> {"mtime", "body"}
_enrich_cache = {}
_enrich_lock = threading.Lock()


# ── Auth ─────────────────────────────────────────────────────────────────
# Enabled when ALADI_USERS is set:  "abraham:pbkdf2$...,fefi:pbkdf2$..."
# (generate a hash with  python3 server.py --hash-password).  ALADI_SECRET
# signs the session cookie; with ALADI_USERS set but no secret, one is made
# per process (sessions then die on restart).  Unset → no login (local dev).
SESSION_COOKIE = "aladi_session"
SESSION_TTL = 30 * 24 * 3600
PBKDF2_ITERS = 200_000
FAIL_LIMIT, FAIL_WINDOW = 6, 15 * 60


def _parse_users(spec):
    users = {}
    for part in filter(None, (p.strip() for p in spec.split(","))):
        name, _, h = part.partition(":")
        if name and h.startswith("pbkdf2$"):
            users[name.strip().lower()] = h
    return users


USERS = _parse_users(os.environ.get("ALADI_USERS", ""))
SECRET = (os.environ.get("ALADI_SECRET") or secrets.token_hex(32)).encode()
AUTH_ON = bool(USERS)
_fails = {}  # ip -> [timestamps]
_fails_lock = threading.Lock()


def hash_password(pw, salt=None, iters=PBKDF2_ITERS):
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), iters)
    return f"pbkdf2${iters}${salt}${dk.hex()}"


def verify_password(pw, stored):
    try:
        _, iters, salt, _ = stored.split("$")
        return hmac.compare_digest(hash_password(pw, salt, int(iters)), stored)
    except ValueError:
        return False


def _sign(msg):
    return hmac.new(SECRET, msg.encode(), hashlib.sha256).hexdigest()[:40]


def make_session(user):
    body = f"{user}|{int(time.time()) + SESSION_TTL}"
    return base64.urlsafe_b64encode(f"{body}|{_sign(body)}".encode()).decode()


def read_session(token):
    """→ username, or None if missing / tampered / expired."""
    try:
        user, exp, sig = base64.urlsafe_b64decode(token.encode()).decode().split("|")
    except Exception:
        return None
    if not hmac.compare_digest(sig, _sign(f"{user}|{exp}")):
        return None
    if int(exp) < time.time() or user not in USERS:
        return None
    return user


def too_many_failures(ip):
    now = time.time()
    with _fails_lock:
        recent = [t for t in _fails.get(ip, []) if now - t < FAIL_WINDOW]
        _fails[ip] = recent
        return len(recent) >= FAIL_LIMIT


def note_failure(ip):
    with _fails_lock:
        _fails.setdefault(ip, []).append(time.time())


LOGIN_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in · Aladí English Catalogue</title>
<script>try{var t=localStorage.getItem("theme");if(t)document.documentElement.setAttribute("data-theme",t)}catch(e){}</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Inter:wght@400;500;600&family=Playfair+Display:wght@400;500;600;700&display=swap">
<style>
  :root {
    --bg: #fafaf8; --bg-darker: #f0efe8; --chalk: #ffffff; --ink: #0e0e0e; --ink-light: #404040;
    --mid: #6b6b6b; --rule: #d8d8d4; --hi: #f5e642; --on-hi: #0e0e0e;
    --font-display: "Playfair Display", "Iowan Old Style", Georgia, "Times New Roman", serif;
    --font-body: "Inter", system-ui, -apple-system, "Segoe UI", sans-serif;
    --font-mono: "DM Mono", ui-monospace, SFMono-Regular, Menlo, "Courier New", monospace;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #0a0a0a; --bg-darker: #141414; --chalk: #161616;
      --ink: #f0f0f0; --ink-light: #a3a3a3; --mid: #9a9a9a; --rule: #2a2a2a;
    }
  }
  :root[data-theme="dark"] {
    --bg: #0a0a0a; --bg-darker: #141414; --chalk: #161616;
    --ink: #f0f0f0; --ink-light: #a3a3a3; --mid: #9a9a9a; --rule: #2a2a2a;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink); font: 15px/1.55 var(--font-body); -webkit-font-smoothing: antialiased; min-height: 100vh; display: flex; flex-direction: column; }
  .news-nav { display: flex; justify-content: space-between; align-items: center; padding: 13px 24px; border-bottom: 1px solid var(--ink); }
  .news-nav-logo { font-family: var(--font-mono); font-size: 15px; font-weight: 500; letter-spacing: -0.02em; color: var(--ink); text-decoration: none; }
  .news-nav-logo em { font-style: normal; opacity: 0.4; }
  .eyebrow { font-family: var(--font-mono); font-size: 10.5px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.08em; color: var(--mid); }
  main { flex: 1; display: grid; place-items: start center; padding: 56px 24px 64px; }
  .card { width: 100%; max-width: 400px; }
  h1 { font-family: var(--font-display); font-weight: 700; font-size: 38px; line-height: 1.05; letter-spacing: -0.025em; margin: 8px 0 0; text-wrap: balance; }
  .lede { color: var(--mid); font-size: 14px; margin: 12px 0 30px; }
  form { border-top: 1px solid var(--ink); padding-top: 22px; display: grid; gap: 18px; }
  label { display: grid; gap: 7px; }
  input { font-family: var(--font-body); font-size: 15px; color: var(--ink); background: var(--chalk); border: 1px solid var(--rule); border-radius: 0; padding: 10px 12px; width: 100%; }
  input:focus-visible { outline: 2px solid var(--ink); outline-offset: 1px; border-color: var(--ink); }
  .cta-btn { background: var(--hi); color: var(--on-hi); border: none; border-radius: 0; padding: 11px 16px; cursor: pointer; font-family: var(--font-mono); font-size: 11px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.04em; justify-self: start; transition: opacity 0.15s; }
  .cta-btn:hover { opacity: 0.82; }
  .cta-btn:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
  .error { font-family: var(--font-mono); font-size: 11.5px; color: var(--ink); background: var(--hi); padding: 8px 10px; margin: 0; }
  .error[hidden] { display: none; }
  .news-nav-right { display: flex; gap: 10px; align-items: center; }
  .icon-btn { appearance: none; background: none; border: 1px solid var(--rule); border-radius: 0; width: 30px; height: 28px; display: grid; place-items: center; cursor: pointer; color: var(--ink); font-size: 13px; line-height: 1; transition: border-color 0.15s; }
  .icon-btn:hover { border-color: var(--ink); }
  .icon-btn:focus-visible { outline: 2px solid var(--ink); outline-offset: 1px; }
  footer { padding: 14px 24px; border-top: 1px solid var(--rule); }
  @media (max-width: 460px) { h1 { font-size: 30px; } main { padding-top: 36px; } }
</style>
</head>
<body>
<nav class="news-nav"><a class="news-nav-logo" href="/">ALADÍ <em>/ english</em></a><div class="news-nav-right"><span class="eyebrow">private shelf</span><button class="icon-btn" id="themebtn" type="button" title="Toggle light / dark" aria-label="Toggle light or dark theme">◐</button></div></nav>
<main>
  <div class="card">
    <span class="eyebrow">Sign in</span>
    <h1>The shelf is for two readers.</h1>
    <p class="lede">Your session stays open for 30 days on this device.</p>
    <form method="post" action="/login" autocomplete="on">
      <input type="hidden" name="next" value="{{next}}">
      <p class="error" role="alert" {{err_hidden}}>{{error}}</p>
      <label><span class="eyebrow">Name</span><input name="user" autocomplete="username" autocapitalize="none" autofocus required value="{{user}}"></label>
      <label><span class="eyebrow">Password</span><input name="password" type="password" autocomplete="current-password" required></label>
      <button class="cta-btn" type="submit">Open the catalogue</button>
    </form>
  </div>
</main>
<footer><span class="eyebrow">aladi.diba.cat · english-language items · weekly sync</span></footer>
<script>
  document.getElementById("themebtn").addEventListener("click", function () {
    var root = document.documentElement, cur = root.getAttribute("data-theme");
    var isDark = cur ? cur === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    var next = isDark ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try { localStorage.setItem("theme", next); } catch (e) {}
  });
</script>
</body>
</html>
"""


def render_login(error="", user="", nxt="/"):
    page = LOGIN_PAGE
    for k, v in {"error": htmllib.escape(error), "err_hidden": "" if error else "hidden",
                 "user": htmllib.escape(user), "next": htmllib.escape(nxt)}.items():
        page = page.replace("{{%s}}" % k, v)
    return page.encode()


def safe_next(nxt):
    return nxt if nxt.startswith("/") and not nxt.startswith("//") else "/"


def lang_of(parsed):
    """The `lang=` query param, validated against the registry; default eng."""
    q = urllib.parse.parse_qs(parsed.query)
    code = (q.get("lang", [langs.DEFAULT_LANG])[0] or langs.DEFAULT_LANG).strip().lower()
    return code if code in langs.LANGS else None


def snap_dir(code):
    return os.path.join(ROOT, "data", code, "snapshots")


def diff_dir(code):
    return os.path.join(ROOT, "data", code, "diffs")


def enrichment_payload(code):
    """Compact {bib: [form, aud, genres, libs]} for one language (mtime-cached)."""
    path = os.path.join(ROOT, "data", code, "enrichment.jsonl")
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return b"{}"
    with _enrich_lock:
        hit = _enrich_cache.get(code)
        if hit and hit["mtime"] == mtime:
            return hit["body"]
    out = {}
    with open(path) as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if not r.get("miss"):
                out[r["bib"]] = [r.get("form", ""), r.get("aud", ""), r.get("genres", []),
                                 r.get("libs", [])]
    body = json.dumps(out, ensure_ascii=False).encode()
    with _enrich_lock:
        _enrich_cache[code] = {"mtime": mtime, "body": body}
    return body


def latest_snapshot_path(code):
    d = snap_dir(code)
    if not os.path.isdir(d):
        return None
    snaps = sorted(f for f in os.listdir(d) if f.endswith(".json"))
    return os.path.join(d, snaps[-1]) if snaps else None


def languages_payload():
    """Which catalogues exist, with the latest record count for each."""
    out = []
    for code, cfg in langs.LANGS.items():
        p = latest_snapshot_path(code)
        count, date = 0, None
        if p:
            try:
                with open(p) as f:
                    d = json.load(f)
                count, date = d.get("count", 0), d.get("date")
            except Exception:
                pass
        out.append({"code": code, "label": cfg["label"], "native": cfg["native"],
                    "count": count, "date": date, "ready": bool(p)})
    return out


def fetch_availability(bib):
    now = time.time()
    with _avail_lock:
        hit = _avail_cache.get(bib)
        if hit and now - hit[0] < AVAIL_TTL:
            return hit[1]
    url = f"{BASE}/record={bib}~{SCOPE}"
    req = urllib.request.Request(url, headers=UA)
    body = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    copies = []
    m = re.search(r"<table[^>]*bibItems.*?</table>", body, re.S)
    if m:
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(0), re.S):
            cells = [htmllib.unescape(re.sub(r"<[^>]+>|\s+", " ", c)).strip()
                     for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S)]
            if len(cells) >= 3 and cells[0] != "Location":
                copies.append({"location": cells[0], "call": cells[1],
                               "status": cells[2], "notes": cells[3] if len(cells) > 3 else ""})
    payload = {"bib": bib, "url": url, "copies": copies}
    with _avail_lock:
        _avail_cache[bib] = (now, payload)
    return payload


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=os.path.join(ROOT, "app"), **kw)

    def log_message(self, *a):
        pass

    def send_json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ── auth plumbing ──
    def client_ip(self):
        fwd = self.headers.get("X-Forwarded-For", "")
        return fwd.split(",")[0].strip() if fwd else self.client_address[0]

    def current_user(self):
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            k, _, v = part.strip().partition("=")
            if k == SESSION_COOKIE:
                return read_session(v)
        return None

    def cookie_attrs(self):
        secure = "; Secure" if self.headers.get("X-Forwarded-Proto", "") == "https" else ""
        return f"; Path=/; HttpOnly; SameSite=Lax{secure}"

    def redirect(self, location, cookie=None):
        self.send_response(303)
        self.send_header("Location", location)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def send_html(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def require_auth(self, parsed):
        """True if the request may proceed; otherwise the response is sent."""
        if not AUTH_ON or self.current_user():
            return True
        if parsed.path.startswith("/api/"):
            self.send_json({"error": "sign in required"}, 401)
        else:
            nxt = urllib.parse.quote(self.path, safe="/?=&")
            self.redirect(f"/login?next={nxt}")
        return False

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/login":
            return self.send_json({"error": "not found"}, 404)
        length = int(self.headers.get("Content-Length", "0") or 0)
        form = urllib.parse.parse_qs(self.rfile.read(min(length, 8192)).decode(errors="replace"))
        user = form.get("user", [""])[0].strip().lower()
        pw = form.get("password", [""])[0]
        nxt = safe_next(form.get("next", ["/"])[0])
        if not AUTH_ON:
            return self.redirect(nxt)
        ip = self.client_ip()
        if too_many_failures(ip):
            return self.send_html(render_login("Too many attempts. Wait 15 minutes.", user, nxt), 429)
        if user in USERS and verify_password(pw, USERS[user]):
            cookie = f"{SESSION_COOKIE}={make_session(user)}; Max-Age={SESSION_TTL}{self.cookie_attrs()}"
            return self.redirect(nxt, cookie)
        note_failure(ip)
        time.sleep(0.5)
        self.send_html(render_login("That name and password don\u2019t match.", user, nxt), 401)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/login":
            if not AUTH_ON or self.current_user():
                return self.redirect("/")
            nxt = safe_next(urllib.parse.parse_qs(parsed.query).get("next", ["/"])[0])
            return self.send_html(render_login(nxt=nxt))
        if parsed.path == "/logout":
            return self.redirect("/login" if AUTH_ON else "/",
                                 f"{SESSION_COOKIE}=; Max-Age=0{self.cookie_attrs()}")
        if not self.require_auth(parsed):
            return
        # Catalogue endpoints are per item-language; reject unknown codes rather
        # than silently serving English.
        if parsed.path in ("/api/catalogue", "/api/enrichment", "/api/snapshots", "/api/diffs"):
            code = lang_of(parsed)
            if code is None:
                return self.send_json(
                    {"error": f"unknown lang; known: {', '.join(langs.LANGS)}"}, 400)
        if parsed.path == "/api/catalogue":
            p = latest_snapshot_path(code)
            if not p:
                return self.send_json(
                    {"error": f"no {code} snapshot yet — run scraper.py --lang={code}"}, 404)
            with open(p, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif parsed.path == "/api/languages":
            self.send_json(languages_payload())
        elif parsed.path == "/api/libraries":
            with open(os.path.join(ROOT, "data", "libraries.json"), "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif parsed.path == "/api/enrichment":
            data = enrichment_payload(code)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif parsed.path == "/api/snapshots":
            snaps, d0 = [], snap_dir(code)
            if os.path.isdir(d0):
                for f in sorted(os.listdir(d0)):
                    if f.endswith(".json"):
                        with open(os.path.join(d0, f)) as fh:
                            d = json.load(fh)
                        snaps.append({"date": d["date"], "count": d["count"]})
            self.send_json(snaps)
        elif parsed.path == "/api/diffs":
            diffs, d0 = [], diff_dir(code)
            if os.path.isdir(d0):
                for f in sorted(os.listdir(d0), reverse=True):
                    if f.endswith(".json"):
                        with open(os.path.join(d0, f)) as fh:
                            diffs.append(json.load(fh))
            self.send_json(diffs)
        elif parsed.path == "/api/availability":
            q = urllib.parse.parse_qs(parsed.query)
            bib = q.get("bib", [""])[0]
            if not re.fullmatch(r"b\d+", bib):
                return self.send_json({"error": "bad bib id"}, 400)
            try:
                self.send_json(fetch_availability(bib))
            except Exception as e:
                self.send_json({"error": str(e)}, 502)
        else:
            super().do_GET()


if __name__ == "__main__":
    from socketserver import ThreadingMixIn

    if "--hash-password" in sys.argv:
        import getpass
        pw = getpass.getpass("Password: ")
        if pw != getpass.getpass("Again: "):
            sys.exit("passwords differ")
        print(hash_password(pw))
        sys.exit(0)

    class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True

    print(f"Aladi catalogue → {BIND}:{PORT}  auth={'on' if AUTH_ON else 'off'}")
    ThreadingHTTPServer((BIND, PORT), Handler).serve_forever()
