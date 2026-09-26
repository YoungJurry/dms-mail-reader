import base64
import hashlib
import json
import os
import stat
import sys
import tempfile
import time
import unittest
import urllib.parse
import urllib.request
from pathlib import Path
from threading import Thread
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import gmail_oauth
import gmail_store

CLIENT_ID = "123-abc.apps.googleusercontent.com"
USERNAME = "me@gmail.com"


class GmailOAuthTests(unittest.TestCase):
    def test_invalid_client_id_is_not_used(self):
        with self.assertRaisesRegex(RuntimeError, "client ID"):
            gmail_oauth.validate_client_id("wrong")

    def test_missing_credentials_explain_authorization(self):
        with tempfile.TemporaryDirectory() as temp, \
                mock.patch.dict(os.environ, {"XDG_STATE_HOME": temp}):
            with self.assertRaisesRegex(RuntimeError, "authorize-gmail.py"):
                gmail_oauth.load_tokens(CLIENT_ID, USERNAME)
            with self.assertRaisesRegex(RuntimeError, "--client-json"):
                gmail_oauth.load_client_secret(CLIENT_ID)

    def test_local_credential_files_are_private(self):
        with tempfile.TemporaryDirectory() as temp, \
                mock.patch.dict(os.environ, {"XDG_STATE_HOME": temp}):
            gmail_oauth.save_client_secret(CLIENT_ID, "desktop-secret")
            self.assertEqual(gmail_oauth.load_client_secret(CLIENT_ID), "desktop-secret")
            gmail_oauth.save_tokens(CLIENT_ID, USERNAME, {
                "access_token": "access", "refresh_token": "refresh", "expires_in": 3600})
            self.assertEqual(gmail_oauth.load_tokens(CLIENT_ID, USERNAME)["refresh_token"],
                             "refresh")
            root = gmail_store.storage_root()
            self.assertEqual(stat.S_IMODE(os.stat(root).st_mode), 0o700)
            for entry in os.scandir(root):
                self.assertEqual(stat.S_IMODE(entry.stat().st_mode), 0o600)

    def test_local_store_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as temp, \
                mock.patch.dict(os.environ, {"XDG_STATE_HOME": temp}):
            root = gmail_store.storage_root()
            path = gmail_store.filename("client", CLIENT_ID)
            target = os.path.join(temp, "target")
            with open(target, "w") as handle:
                handle.write("oops")
            os.symlink(target, path)
            with self.assertRaisesRegex(RuntimeError, "Cannot read"):
                gmail_store.load("client", CLIENT_ID)

    def test_reuses_unexpired_access_token(self):
        with mock.patch.object(gmail_oauth, "load_tokens", return_value={
                "access_token": "cached", "refresh_token": "refresh",
                "expires_at": time.time() + 3600}), \
                mock.patch.object(gmail_oauth, "token_request") as request:
            self.assertEqual(gmail_oauth.get_access_token(CLIENT_ID, USERNAME), "cached")
            request.assert_not_called()

    def test_refresh_rotates_token_and_keeps_previous_if_absent(self):
        old = {"refresh_token": "old", "expires_at": 0}
        updated = {"access_token": "new", "expires_in": 3600}
        with mock.patch.object(gmail_oauth, "load_tokens", return_value=old), \
                mock.patch.object(gmail_oauth, "load_client_secret", return_value="client-secret"), \
                mock.patch.object(gmail_oauth, "token_request", return_value=updated) as request, \
                mock.patch.object(gmail_oauth.gmail_store, "save") as store:
            self.assertEqual(gmail_oauth.get_access_token(CLIENT_ID, USERNAME), "new")
        self.assertEqual(request.call_args.args[0]["grant_type"], "refresh_token")
        self.assertEqual(request.call_args.args[0]["client_secret"], "client-secret")
        self.assertEqual(store.call_args.args[0], "tokens")
        saved = json.loads(store.call_args.args[2])
        self.assertEqual(saved["refresh_token"], "old")

    def test_refresh_invalid_grant_explains_testing_expiry(self):
        with mock.patch.object(gmail_oauth, "load_tokens", return_value={"refresh_token": "old"}), \
                mock.patch.object(gmail_oauth, "load_client_secret", return_value="client-secret"), \
                mock.patch.object(gmail_oauth, "token_request", side_effect=RuntimeError(
                    "Google OAuth error: invalid_grant")):
            with self.assertRaisesRegex(RuntimeError, "Testing"):
                gmail_oauth.get_access_token(CLIENT_ID, USERNAME)

    def test_denied_permission_is_not_saved(self):
        with mock.patch.object(gmail_oauth.gmail_store, "save") as store:
            with self.assertRaisesRegex(RuntimeError, "permission"):
                gmail_oauth.save_tokens(CLIENT_ID, USERNAME, {
                    "access_token": "test", "refresh_token": "refresh", "expires_in": 3600,
                    "scope": "profile"})
            store.assert_not_called()

    def test_wrong_gmail_account_is_not_saved(self):
        connection = mock.Mock()
        connection.authenticate.side_effect = gmail_oauth.imaplib.IMAP4.error("no")
        with mock.patch.object(gmail_oauth.imaplib, "IMAP4_SSL", return_value=connection), \
                self.assertRaisesRegex(RuntimeError, "rejected authorization"):
            gmail_oauth.validate_mailbox(USERNAME, "bad-token")
        connection.logout.assert_called_once()

    def test_browser_pkce_callback_and_token_exchange(self):
        messages = []
        seen_urls = []

        def open_browser(url):
            seen_urls.append(url)
            parsed = urllib.parse.urlsplit(url)
            params = urllib.parse.parse_qs(parsed.query)
            redirect_uri = params["redirect_uri"][0]

            def callback():
                # Wrong state must not finish authorization or store credentials.
                try:
                    urllib.request.urlopen(redirect_uri + "?code=evil&state=wrong", timeout=5)
                except urllib.error.HTTPError as exc:
                    with exc:
                        self.assertEqual(exc.code, 400)
                with urllib.request.urlopen(
                        redirect_uri + "?code=good-code&state=" + params["state"][0],
                        timeout=5) as response:
                    self.assertEqual(response.status, 200)

            thread = Thread(target=callback, daemon=True)
            thread.start()
            self.addCleanup(thread.join, 5)
            return True

        with mock.patch.object(gmail_oauth, "token_request", return_value={
                "access_token": "access", "refresh_token": "refresh", "expires_in": 3600
        }) as token_request, mock.patch.object(gmail_oauth, "validate_mailbox") as mailbox, \
                mock.patch.object(gmail_oauth, "save_client_secret") as store_secret, \
                mock.patch.object(gmail_oauth, "save_tokens") as store:
            gmail_oauth.authorize(CLIENT_ID, USERNAME, messages.append, open_browser,
                                  client_secret="desktop-secret")
        self.assertEqual(len(seen_urls), 1)
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(seen_urls[0]).query)
        self.assertEqual(params["scope"], [gmail_oauth.SCOPE])
        self.assertEqual(params["code_challenge_method"], ["S256"])
        fields = token_request.call_args.args[0]
        self.assertEqual(fields["code"], "good-code")
        self.assertEqual(fields["client_secret"], "desktop-secret")
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(fields["code_verifier"].encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(challenge, params["code_challenge"][0])
        mailbox.assert_called_once_with(USERNAME, "access")
        store_secret.assert_called_once_with(CLIENT_ID, "desktop-secret")
        store.assert_called_once()
        self.assertNotIn("desktop-secret", " ".join(messages))


if __name__ == "__main__":
    unittest.main()
