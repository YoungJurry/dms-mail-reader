"""Microsoft personal-account OAuth2 for Outlook.com IMAP (stdlib + libsecret).

Tokens are kept in the user's Secret Service keyring, never in DMS settings.
The client ID is public; users register their own public client in Entra.
"""

import imaplib
import json
import re
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request


AUTHORITY = "https://login.microsoftonline.com/consumers/oauth2/v2.0"
SCOPE = "https://outlook.office.com/IMAP.AccessAsUser.All offline_access"
CLIENT_ID_PATTERN = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z")


def validate_client_id(client_id):
    if not isinstance(client_id, str) or not CLIENT_ID_PATTERN.fullmatch(client_id):
        raise RuntimeError("Set a valid Outlook Application (client) ID in plugin settings")
    return client_id.lower()


def validate_username(username):
    if (not isinstance(username, str) or not username.strip()
            or "@" not in username or "\r" in username or "\n" in username):
        raise RuntimeError("Set the Outlook email address in plugin settings")
    return username.strip().lower()


def attributes(client_id, username):
    return ["service", "dms-mail-reader-outlook", "client", validate_client_id(client_id),
            "account", validate_username(username)]


def token_request(path, fields):
    request = urllib.request.Request(
        AUTHORITY + path,
        data=urllib.parse.urlencode(fields).encode("ascii"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        # Do not surface response bodies: they may contain user information.
        try:
            error = json.load(exc).get("error", "request_failed")
        except (ValueError, UnicodeError):
            error = "request_failed"
        if not isinstance(error, str) or not re.fullmatch(r"[a-z_]+", error):
            error = "request_failed"
        raise RuntimeError("Microsoft OAuth error: " + error) from None
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError("Cannot reach Microsoft sign-in service") from exc


def load_tokens(client_id, username):
    try:
        result = subprocess.run(
            ["secret-tool", "lookup", *attributes(client_id, username)],
            capture_output=True, text=True, timeout=10, check=True)
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        raise RuntimeError("secret-tool/keyring unavailable; install libsecret-tools and unlock your keyring") from exc
    if not result.stdout.strip():
        raise RuntimeError("Outlook not authorized; run scripts/authorize-outlook.py first")
    try:
        tokens = json.loads(result.stdout)
        if not isinstance(tokens, dict) or not tokens.get("refresh_token"):
            raise ValueError("Missing refresh token")
        return tokens
    except ValueError as exc:
        raise RuntimeError("Invalid Outlook keyring entry; reauthorize the account") from exc


def save_tokens(client_id, username, response, previous=None):
    if not isinstance(response, dict) or not response.get("access_token"):
        raise RuntimeError("Microsoft did not return an access token")
    refresh_token = response.get("refresh_token") or (previous or {}).get("refresh_token")
    if not refresh_token:
        raise RuntimeError("No refresh token returned; reauthorize with offline_access")
    tokens = {
        "access_token": response["access_token"],
        "refresh_token": refresh_token,
        "expires_at": time.time() + max(0, int(response.get("expires_in", 0)))
    }
    try:
        subprocess.run(
            ["secret-tool", "store", "--label=DMS Mail Reader Outlook", *attributes(client_id, username)],
            input=json.dumps(tokens), text=True, capture_output=True,
            timeout=10, check=True)
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        raise RuntimeError("Failed to store Outlook tokens in the unlocked keyring") from exc


def get_access_token(client_id, username):
    tokens = load_tokens(client_id, username)
    if tokens.get("access_token") and float(tokens.get("expires_at", 0)) > time.time() + 60:
        return tokens["access_token"]
    try:
        response = token_request("/token", {
            "client_id": validate_client_id(client_id),
            "scope": SCOPE,
            "refresh_token": tokens["refresh_token"],
            "grant_type": "refresh_token"
        })
    except RuntimeError as exc:
        if "invalid_grant" in str(exc):
            raise RuntimeError("Outlook authorization expired or revoked; run scripts/authorize-outlook.py again") from None
        raise
    save_tokens(client_id, username, response, tokens)
    return response["access_token"]


def validate_mailbox(username, access_token):
    """Avoid saving a token for the wrong signed-in Outlook account."""
    username = validate_username(username)
    conn = None
    try:
        conn = imaplib.IMAP4_SSL(
            "outlook.office365.com", 993, ssl_context=ssl.create_default_context(),
            timeout=20)
        conn.authenticate("XOAUTH2", lambda _: (
            "user=" + username + "\x01auth=Bearer " + access_token + "\x01\x01").encode())
    except imaplib.IMAP4.error:
        raise RuntimeError("Outlook IMAP rejected authorization; check account, consent and IMAP access") from None
    finally:
        if conn is not None:
            try:
                conn.logout()
            except Exception:
                pass


def authorize(client_id, username, output=print, sleep=time.sleep):
    """Device-code sign-in, initiated explicitly in a terminal by the user."""
    client_id = validate_client_id(client_id)
    attributes(client_id, username)
    result = token_request("/devicecode", {"client_id": client_id, "scope": SCOPE})
    output("Open " + result["verification_uri"] + " and enter code: " + result["user_code"])
    output("Sign in with " + username + " and grant IMAP access. Waiting for approval...")
    deadline = time.monotonic() + min(900, int(result["expires_in"]))
    interval = max(5, int(result.get("interval", 5)))
    while time.monotonic() < deadline:
        sleep(interval)
        try:
            response = token_request("/token", {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": client_id,
                "device_code": result["device_code"]
            })
        except RuntimeError as exc:
            if str(exc) == "Microsoft OAuth error: authorization_pending":
                continue
            if str(exc) == "Microsoft OAuth error: slow_down":
                interval += 5
                continue
            raise
        validate_mailbox(username, response["access_token"])
        save_tokens(client_id, username, response)
        output("Authorization saved to your keyring. Refresh Mail Reader in DMS.")
        return
    raise RuntimeError("Outlook authorization timed out; run the command again")
