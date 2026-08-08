#!/usr/bin/env python3
"""Local web app for the Aladi English-books catalogue.

Serves the static UI plus a small JSON API:
    GET /api/catalogue            latest snapshot (title/author/pub/year/isbn/bib)
    GET /api/snapshots            list of snapshot dates + counts
    GET /api/diffs                list of diff reports (newest first)
    GET /api/availability?bib=bX  live per-copy status fetched from aladi.diba.cat
                                  (on-demand only — nothing is bulk-polled)

Run:  python3 server.py   then open http://localhost:8377
"""
import html as htmllib
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from http.server import HTTPServer, SimpleHTTPRequestHandler

PORT = 8377
ROOT = os.path.dirname(os.path.abspath(__file__))
SNAP_DIR = os.path.join(ROOT, "data", "snapshots")
DIFF_DIR = os.path.join(ROOT, "data", "diffs")
BASE = "https://aladi.diba.cat"
SCOPE = "S171*eng"
UA = {"User-Agent": "Mozilla/5.0 (compatible; personal-catalogue-app)"}

_avail_cache = {}  # bib -> (timestamp, payload)
_avail_lock = threading.Lock()
AVAIL_TTL = 300  # 5 min
ENRICH_JSONL = os.path.join(ROOT, "data", "enrichment.jsonl")
_enrich_cache = {"mtime": 0, "body": None}


def enrichment_payload():
    """Compact {bib: [form, aud, [genres]]} from the enrichment file (mtime-cached)."""
    try:
        mtime = os.path.getmtime(ENRICH_JSONL)
    except OSError:
        return b"{}"
    if _enrich_cache["body"] is None or mtime != _enrich_cache["mtime"]:
        out = {}
        with open(ENRICH_JSONL) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if not r.get("miss"):
                    out[r["bib"]] = [r.get("form", ""), r.get("aud", ""), r.get("genres", [])]
        _enrich_cache["body"] = json.dumps(out, ensure_ascii=False).encode()
        _enrich_cache["mtime"] = mtime
    return _enrich_cache["body"]


def latest_snapshot_path():
    if not os.path.isdir(SNAP_DIR):
        return None
    snaps = sorted(f for f in os.listdir(SNAP_DIR) if f.endswith(".json"))
    return os.path.join(SNAP_DIR, snaps[-1]) if snaps else None


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

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/catalogue":
            p = latest_snapshot_path()
            if not p:
                return self.send_json({"error": "no snapshot yet — run scraper.py"}, 404)
            with open(p, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif parsed.path == "/api/enrichment":
            data = enrichment_payload()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif parsed.path == "/api/snapshots":
            snaps = []
            if os.path.isdir(SNAP_DIR):
                for f in sorted(os.listdir(SNAP_DIR)):
                    if f.endswith(".json"):
                        with open(os.path.join(SNAP_DIR, f)) as fh:
                            d = json.load(fh)
                        snaps.append({"date": d["date"], "count": d["count"]})
            self.send_json(snaps)
        elif parsed.path == "/api/diffs":
            diffs = []
            if os.path.isdir(DIFF_DIR):
                for f in sorted(os.listdir(DIFF_DIR), reverse=True):
                    if f.endswith(".json"):
                        with open(os.path.join(DIFF_DIR, f)) as fh:
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

    class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True

    print(f"Aladi catalogue → http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
