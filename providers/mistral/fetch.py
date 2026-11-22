"""Read Vibe's existing key and monthly allowance; emit no credentials.

Schema: mistralai/mistral-vibe vibe/app_server/_billing.py.
No redirects, credential writes, token refresh or browser cookies.
"""
import datetime
import json
import math
import os
from pathlib import Path
import re
import subprocess
import urllib.error
import urllib.request

SERVER = "https://api.mistral.ai/v1"

class Failure(Exception):
    def __init__(self, code):
        self.code = code

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def credential():
    token = os.environ.get("MISTRAL_API_KEY", "").strip()
    if token:
        return token
    # Python keyring's SecretService attributes, including Vibe's legacy service.
    for service in ("ai.mistral.vibe", "vibe"):
        try:
            result = subprocess.run(
                ["secret-tool", "lookup", "service", service, "username", "MISTRAL_API_KEY"],
                capture_output=True, text=True, timeout=3, check=False)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    path = Path(os.environ.get("VIBE_HOME", "~/.vibe")).expanduser() / ".env"
    try:
        content = path.read_text()
    except FileNotFoundError:
        raise Failure("not_configured") from None
    except OSError:
        raise Failure("auth") from None
    # Accept the single-line dotenv syntax Vibe writes; never execute a shell.
    token = ""
    for line in content.splitlines():
        match = re.fullmatch(r"\s*(?:export\s+)?MISTRAL_API_KEY\s*=\s*(.*?)\s*", line)
        if match:
            value = match[1]
            if value.startswith(("'", '"')):
                quoted = re.fullmatch(r"(['\"])(.*?)\1\s*(?:#.*)?", value)
                if not quoted:
                    raise Failure("parse")
                value = quoted[2]
            else:
                value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
            token = value
    if not token:
        raise Failure("not_configured")
    return token

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
    if "vibe_budget" not in data:
        raise Failure("parse")
    budget = data["vibe_budget"]
    if budget is None:
        raise Failure("no_plan")
    if not isinstance(budget, dict):
        raise Failure("parse")
    percent = amount(budget.get("usage_percentage"))
    initial = amount(budget.get("initial_budget"))
    if initial == 0:
        raise Failure("no_plan")
    reset = budget.get("reset_at")
    return {"usedPercent": min(100, percent),
            "resetsAt": unix(reset) if reset is not None else None}


def fetch(opener=None):
    token = credential()
    if any(c in token for c in "\r\n"):
        raise Failure("auth")
    request = urllib.request.Request(SERVER + "/billing/budget", headers={
        "Authorization": "Bearer " + token, "Accept": "application/json",
        "User-Agent": "headroom-noctalia/0.5.0"})
    client = opener or urllib.request.build_opener(NoRedirect())
    try:
        with client.open(request, timeout=15) as response:
            data = json.load(response)
    except urllib.error.HTTPError as error:
        code = {401: "auth", 403: "auth", 429: "rate_limited"}.get(error.code, "server")
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
