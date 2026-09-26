"""Personal Gmail IMAP OAuth2 for the DMS Mail Reader (stdlib only).

A user-created Google Desktop OAuth client authorizes in the system browser via
PKCE and a loopback callback. Credentials are stored in private local files,
never in DMS settings or process arguments.
"""

import base64
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import imaplib
import json
import re
import secrets
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

import gmail_store


AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://mail.google.com/"
CLIENT_ID_PATTERN = re.compile(r"[A-Za-z0-9-]+\.apps\.googleusercontent\.com\Z")


def validate_client_id(client_id):
    if not isinstance(client_id, str) or not CLIENT_ID_PATTERN.fullmatch(client_id):
        raise RuntimeError("Set a Google Desktop OAuth client ID in plugin settings")
    return client_id


def validate_username(username):
    if (not isinstance(username, str) or not username.strip()
            or "@" not in username or any(ord(ch) < 32 for ch in username)):
        raise RuntimeError("Set the full Gmail address in plugin settings")
    return username.strip().lower()


def token_identity(client_id, username):
    return validate_client_id(client_id) + ":" + validate_username(username)


def load_client_secret(client_id):
    """Google currently requires the Desktop client secret at its token endpoint."""
    secret = gmail_store.load("client", validate_client_id(client_id)).strip()
    if not secret:
        raise RuntimeError("Gmail client secret not found; run scripts/authorize-gmail.py with --client-json")
    return secret


def save_client_secret(client_id, secret):
    if not isinstance(secret, str) or not secret.strip() or any(ord(ch) < 33 for ch in secret):
        raise RuntimeError("Google Desktop client secret is missing or invalid")
    gmail_store.save("client", validate_client_id(client_id), secret)


def token_request(fields):
    request = urllib.request.Request(
        TOKEN_URL, data=urllib.parse.urlencode(fields).encode("ascii"),
        headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        # Do not include the response body: it can contain account information.
        try:
            error = json.load(exc).get("error", "request_failed")
        except (ValueError, UnicodeError):
            error = "request_failed"
        if not isinstance(error, str) or not re.fullmatch(r"[a-z_]+", error):
            error = "request_failed"
        raise RuntimeError("Google OAuth error: " + error) from None
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError("Cannot reach Google sign-in service") from exc


def load_tokens(client_id, username):
    raw = gmail_store.load("tokens", token_identity(client_id, username))
    if not raw.strip():
        raise RuntimeError("Gmail not authorized; run scripts/authorize-gmail.py first")
    try:
        tokens = json.loads(raw)
        if not isinstance(tokens, dict) or not tokens.get("refresh_token"):
            raise ValueError("Missing refresh token")
        return tokens
    except ValueError as exc:
        raise RuntimeError("Invalid Gmail keyring entry; reauthorize the account") from exc


def save_tokens(client_id, username, response, previous=None):
    if not isinstance(response, dict) or not response.get("access_token"):
        raise RuntimeError("Google did not return an access token")
    if response.get("scope") and SCOPE not in response["scope"].split():
        raise RuntimeError("Gmail IMAP permission was not granted")
    refresh_token = response.get("refresh_token") or (previous or {}).get("refresh_token")
    if not refresh_token:
        raise RuntimeError("No refresh token returned; revoke access and authorize again")
    tokens = {
        "access_token": response["access_token"],
        "refresh_token": refresh_token,
        "expires_at": time.time() + max(0, int(response.get("expires_in", 0)))
    }
    gmail_store.save("tokens", token_identity(client_id, username), json.dumps(tokens))


def get_access_token(client_id, username):
    tokens = load_tokens(client_id, username)
    if tokens.get("access_token") and float(tokens.get("expires_at", 0)) > time.time() + 60:
        return tokens["access_token"]
    try:
        response = token_request({
            "client_id": validate_client_id(client_id),
            "client_secret": load_client_secret(client_id),
            "refresh_token": tokens["refresh_token"],
            "grant_type": "refresh_token"
        })
    except RuntimeError as exc:
        if "invalid_grant" in str(exc):
            raise RuntimeError(
                "Gmail authorization expired or revoked; run scripts/authorize-gmail.py again. "
                "If the app is in Testing, tokens expire after 7 days") from None
        raise
    save_tokens(client_id, username, response, tokens)
    return response["access_token"]


def validate_mailbox(username, access_token):
    """Ensure the Google sign-in belongs to the mailbox configured in DMS."""
    username = validate_username(username)
    conn = None
    try:
        conn = imaplib.IMAP4_SSL(
            "imap.gmail.com", 993, ssl_context=ssl.create_default_context(), timeout=20)
        conn.authenticate("XOAUTH2", lambda _: (
            "user=" + username + "\x01auth=Bearer " + access_token + "\x01\x01").encode())
    except imaplib.IMAP4.error:
        raise RuntimeError(
            "Gmail IMAP rejected authorization; check the signed-in address and consent") from None
    finally:
        if conn is not None:
            try:
                conn.logout()
            except Exception:
                pass


def authorize(client_id, username, output=print, open_browser=webbrowser.open,
              client_secret=None):
    """Perform desktop PKCE sign-in with a local-only callback (up to 3 minutes)."""
    client_id = validate_client_id(client_id)
    username = validate_username(username)
    # Desktop client secrets cannot be treated as truly confidential, but
    # Google currently rejects token exchange without one. Never put it in
    # plugin settings, an OAuth URL, or process arguments.
    if client_secret is None:
        client_secret = load_client_secret(client_id)
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    received = {}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            # Never log OAuth query strings (authorization codes).
            pass

        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            if parsed.path != "/" or not hmac.compare_digest(params.get("state", [""])[0], state):
                self.send_error(400, "Invalid OAuth callback")
                return
            if "code" in params and len(params["code"]) == 1:
                received["code"] = params["code"][0]
                message = b"Authorization received. You can close this tab."
            else:
                received["error"] = params.get("error", ["access_denied"])[0]
                message = b"Authorization denied. You can close this tab."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(message)

    with HTTPServer(("127.0.0.1", 0), Callback) as server:
        redirect_uri = f"http://127.0.0.1:{server.server_port}/"
        url = AUTH_URL + "?" + urllib.parse.urlencode({
            "client_id": client_id, "redirect_uri": redirect_uri,
            "response_type": "code", "scope": SCOPE,
            "access_type": "offline", "prompt": "consent",
            "login_hint": username, "code_challenge": challenge,
            "code_challenge_method": "S256", "state": state
        })
        output("Open this URL in a browser and sign in as " + username + ":\n" + url)
        open_browser(url)
        deadline = time.monotonic() + 180
        while not received and time.monotonic() < deadline:
            server.timeout = min(1, max(0.01, deadline - time.monotonic()))
            server.handle_request()

    if "code" not in received:
        if "error" in received:
            raise RuntimeError("Google authorization was denied")
        raise RuntimeError("Gmail authorization timed out; run the command again")
    response = token_request({
        "client_id": client_id, "client_secret": client_secret,
        "code": received["code"], "code_verifier": verifier, "redirect_uri": redirect_uri,
        "grant_type": "authorization_code"
    })
    validate_mailbox(username, response["access_token"])
    save_client_secret(client_id, client_secret)
    save_tokens(client_id, username, response)
    output("Gmail authorization saved locally. Refresh Mail Reader in DMS.")
