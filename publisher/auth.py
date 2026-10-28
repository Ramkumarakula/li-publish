"""One-time LinkedIn OAuth 2.0 login (authorization code flow).

Opens your browser to LinkedIn, catches the redirect on the local callback
URL, exchanges the code for an access token, looks up your person URN and
saves LINKEDIN_ACCESS_TOKEN, LINKEDIN_TOKEN_EXPIRES and LINKEDIN_PERSON_URN
into $LI_HOME/.env. Existing keys are left alone. The token, secret and
person URN are never printed.

Usage: python auth.py
"""

import datetime
import http.server
import os
import secrets
import sys
import time
import urllib.parse
import webbrowser
from pathlib import Path

import requests
from dotenv import load_dotenv, set_key

LI_HOME = Path(os.environ.get("LI_HOME") or Path.home() / ".claude" / "linkedin").expanduser()
ENV_PATH = LI_HOME / ".env"

AUTHORIZE_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
SCOPE = "openid profile w_member_social"
LOGIN_TIMEOUT_SECONDS = 300


def require_env(name):
    value = os.getenv(name)
    if not value:
        sys.exit(f"Missing {name} in {ENV_PATH}")
    return value


def wait_for_callback(redirect_uri):
    """Serve the redirect URI locally until LinkedIn sends us back. Returns query params."""
    parsed = urllib.parse.urlparse(redirect_uri)
    result = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            if url.path != parsed.path:
                self.send_response(404)
                self.end_headers()
                return
            result.update({k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()})
            ok = "code" in result
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            msg = "Login received. You can close this tab." if ok else "Login failed. Check the terminal."
            self.wfile.write(msg.encode())

        def log_message(self, *args):
            pass  # keep the code out of the console

    server = http.server.HTTPServer((parsed.hostname, parsed.port or 80), Handler)
    deadline = time.monotonic() + LOGIN_TIMEOUT_SECONDS
    # Stray requests (e.g. /favicon.ico) get a 404 and we keep waiting.
    while not result:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            server.server_close()
            sys.exit("Timed out waiting for the LinkedIn redirect.")
        server.timeout = remaining
        server.handle_request()  # returns after one request or the timeout
    server.server_close()
    return result


def main():
    if not ENV_PATH.exists():
        sys.exit(f"No .env at {ENV_PATH}. Copy .env.example there and fill in your app's keys.")
    load_dotenv(ENV_PATH)
    client_id = require_env("LINKEDIN_CLIENT_ID")
    client_secret = require_env("LINKEDIN_CLIENT_SECRET")
    redirect_uri = require_env("LINKEDIN_REDIRECT_URI")

    # 1. Send the user to LinkedIn with a random state to block CSRF.
    state = secrets.token_urlsafe(24)
    url = AUTHORIZE_URL + "?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": SCOPE,
    })
    print("Opening LinkedIn in your browser. If it does not open, visit:\n" + url)
    webbrowser.open(url)

    # 2. Catch the redirect and check it really came from our request.
    params = wait_for_callback(redirect_uri)
    if "error" in params:
        sys.exit(f"LinkedIn returned an error: {params['error']}: {params.get('error_description', '')}")
    if not secrets.compare_digest(params.get("state", ""), state):
        sys.exit("State mismatch - ignoring this callback.")

    # 3. Exchange the one-time code for an access token.
    resp = requests.post(TOKEN_URL, data={
        "grant_type": "authorization_code",
        "code": params["code"],
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
    }, timeout=30)
    if resp.status_code != 200:
        err = resp.json() if resp.headers.get("Content-Type", "").startswith("application/json") else {}
        sys.exit(f"Token exchange failed ({resp.status_code}): {err.get('error', '')} {err.get('error_description', '')}")
    token_data = resp.json()
    token = token_data["access_token"]
    expires = datetime.date.today() + datetime.timedelta(seconds=int(token_data.get("expires_in", 0)))

    # 4. Look up who we are; the 'sub' claim is the person id.
    me = requests.get(USERINFO_URL, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    if me.status_code != 200:
        sys.exit(f"userinfo failed ({me.status_code}). Check the OpenID Connect product is on the app.")
    info = me.json()
    person_urn = "urn:li:person:" + info["sub"]

    # 5. Save into .env without touching the other keys.
    set_key(str(ENV_PATH), "LINKEDIN_ACCESS_TOKEN", token)
    set_key(str(ENV_PATH), "LINKEDIN_TOKEN_EXPIRES", expires.isoformat())
    set_key(str(ENV_PATH), "LINKEDIN_PERSON_URN", person_urn)

    print(f"Signed in as {info.get('name', '(name not shared)')}")
    print(f"Saved LINKEDIN_ACCESS_TOKEN, LINKEDIN_PERSON_URN and LINKEDIN_TOKEN_EXPIRES={expires.isoformat()} "
          f"to {ENV_PATH}")


if __name__ == "__main__":
    main()
