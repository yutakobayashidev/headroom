"""Read OpenCode 2's active Console OAuth session without exporting credentials.

Stdlib only. The credential stays in this process and is sent only to the
OpenCode Console. No refresh, writes, browser cookies, legacy keys or redirects.
"""
from contextlib import closing
import datetime
import json
import math
import os
from pathlib import Path
import sqlite3
import time
import urllib.error
import urllib.request

SERVER = "https://opencode.ai/console"

class Failure(Exception):
    def __init__(self, code):
        self.code = code

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def database_path():
    explicit = os.environ.get("OPENCODE_DB")
    if explicit:
        return Path(explicit).expanduser().absolute()
    data = Path(os.environ.get("XDG_DATA_HOME", "~/.local/share")).expanduser()
    if not data.is_absolute():
        data = Path.home() / ".local/share"
    return data / "opencode/opencode.db"

def credential(path, now):
    if not path.is_file():
        raise Failure("not_configured")
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
            row = db.execute("SELECT value FROM credential WHERE integration_id = 'opencode' AND active = 1 ORDER BY time_updated DESC LIMIT 1").fetchone()
    except sqlite3.Error:
        raise Failure("parse") from None
    if row is None:
        raise Failure("not_configured")
    try:
        value = json.loads(row[0])
    except (ValueError, TypeError):
        raise Failure("parse") from None
    if not isinstance(value, dict) or value.get("type") != "oauth":
        raise Failure("not_configured")
    access, expires, meta = value.get("access"), value.get("expires"), value.get("metadata")
    if not isinstance(access, str) or not access.strip() or not isinstance(meta, dict):
        raise Failure("parse")
    if not isinstance(expires, (int, float)) or not math.isfinite(expires):
        raise Failure("parse")
    if expires <= now * 1000:
        raise Failure("expired")
    # Never forward a token to an arbitrary URL from a modified credential DB.
    server = meta.get("server", SERVER).rstrip("/")
    if server == "https://console.opencode.ai":
        server = SERVER
    if server != SERVER:
        raise Failure("auth")
    org = meta.get("orgID")
    if not isinstance(org, str) or not org or any(c in org for c in "\r\n"):
        raise Failure("parse")
    return access, org

def unix(value):
    if not isinstance(value, str):
        raise Failure("parse")
    try:
        dt = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError()
        return dt.timestamp()
    except (ValueError, OverflowError):
        raise Failure("parse") from None

def amount(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise Failure("parse")
    try:
        number = float(value)
    except ValueError:
        raise Failure("parse") from None
    if not math.isfinite(number) or number < 0:
        raise Failure("parse")
    return number

def normalize(data):
    if not isinstance(data, dict):
        raise Failure("parse")
    access = data.get("access")
    if access is None:
        raise Failure("no_plan")
    if not isinstance(access, dict) or not isinstance(access.get("meters"), dict):
        raise Failure("parse")
    windows = []
    for slot, kind, seconds in [("fiveHour", "session", 18000), ("week", "weekly", 604800), ("month", "monthly", None)]:
        meter = access["meters"].get(slot)
        if not isinstance(meter, dict):
            raise Failure("parse")
        limit, used = amount(meter.get("limitMicroCents")), amount(meter.get("usedMicroCents"))
        percent = min(100, used / limit * 100) if limit else (100 if used else 0)
        resets = unix(meter.get("resetsAt") or access.get("endsAt"))
        windows.append({"id": slot, "kind": kind, "usedPercent": percent, "resetsAt": resets, "periodSeconds": seconds})
    return {"windows": windows}

def fetch(path=None, now=None, opener=None):
    token, org = credential(path or database_path(), time.time() if now is None else now)
    request = urllib.request.Request(SERVER + "/api/go/status", headers={
        "Authorization": "Bearer " + token, "x-org-id": org,
        "Accept": "application/json", "User-Agent": "headroom-noctalia/0.4.0"})
    client = opener or urllib.request.build_opener(NoRedirect())
    try:
        with client.open(request, timeout=20) as response:
            data = json.load(response)
    except urllib.error.HTTPError as error:
        code = {401: "auth", 403: "auth", 404: "no_plan", 429: "rate_limited"}.get(error.code, "server")
        error.close()
        raise Failure(code) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise Failure("network") from None
    except (ValueError, UnicodeError):
        raise Failure("parse") from None
    return normalize(data)

def main():
    try:
        result = fetch()
    except Failure as failure:
        result = {"error": failure.code}
    except Exception:
        # Never print exceptions or upstream response bodies: they may contain credentials.
        result = {"error": "parse"}
    print(json.dumps(result, allow_nan=False))

if __name__ == "__main__":
    main()
