import json
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import outlook_oauth

CLIENT_ID = "01234567-89ab-cdef-0123-456789abcdef"
USERNAME = "me@outlook.com"


class OutlookOAuthTests(unittest.TestCase):
    def test_missing_keyring_entry_explains_authorization(self):
        with mock.patch.object(outlook_oauth.subprocess, "run",
                               return_value=mock.Mock(stdout="")):
            with self.assertRaisesRegex(RuntimeError, "authorize-outlook.py"):
                outlook_oauth.load_tokens(CLIENT_ID, USERNAME)

    def test_reuses_unexpired_access_token(self):
        with mock.patch.object(outlook_oauth, "load_tokens", return_value={
                "access_token": "cached", "refresh_token": "refresh",
                "expires_at": time.time() + 3600}), \
                mock.patch.object(outlook_oauth, "token_request") as request:
            self.assertEqual(outlook_oauth.get_access_token(CLIENT_ID, USERNAME), "cached")
            request.assert_not_called()

    def test_refresh_uses_scope_and_rotates_token(self):
        old = {"refresh_token": "old", "expires_at": 0}
        updated = {"access_token": "new", "refresh_token": "rotated", "expires_in": 3600}
        with mock.patch.object(outlook_oauth, "load_tokens", return_value=old), \
                mock.patch.object(outlook_oauth, "token_request", return_value=updated) as request, \
                mock.patch.object(outlook_oauth.subprocess, "run") as store:
            self.assertEqual(outlook_oauth.get_access_token(CLIENT_ID, USERNAME), "new")
        self.assertEqual(request.call_args.args[1]["scope"], outlook_oauth.SCOPE)
        saved = json.loads(store.call_args.kwargs["input"])
        self.assertEqual(saved["refresh_token"], "rotated")
        self.assertEqual(store.call_args.args[0][0:2], ["secret-tool", "store"])
        self.assertNotIn("rotated", " ".join(store.call_args.args[0]))

    def test_device_authorization_polls_until_approved(self):
        challenge = {"verification_uri": "https://microsoft.com/devicelogin",
                     "user_code": "ABCDEF", "device_code": "secret-code",
                     "expires_in": 60, "interval": 5}
        with mock.patch.object(outlook_oauth, "token_request", side_effect=[
                challenge, RuntimeError("Microsoft OAuth error: authorization_pending"),
                {"access_token": "access", "refresh_token": "refresh", "expires_in": 3600}
        ]) as request, mock.patch.object(outlook_oauth, "save_tokens") as store, \
                mock.patch.object(outlook_oauth, "validate_mailbox") as check:
            messages = []
            outlook_oauth.authorize(CLIENT_ID, USERNAME, messages.append, lambda _: None)
        self.assertEqual(request.call_count, 3)
        self.assertIn("offline_access", request.call_args_list[0].args[1]["scope"])
        self.assertIn("ABCDEF", messages[0])
        check.assert_called_once_with(USERNAME, "access")
        store.assert_called_once()

    def test_wrong_outlook_account_is_not_saved(self):
        connection = mock.Mock()
        connection.authenticate.side_effect = outlook_oauth.imaplib.IMAP4.error("no")
        with mock.patch.object(outlook_oauth.imaplib, "IMAP4_SSL", return_value=connection), \
                self.assertRaisesRegex(RuntimeError, "rejected authorization"):
            outlook_oauth.validate_mailbox(USERNAME, "bad-token")
        connection.logout.assert_called_once()

    def test_invalid_client_id_is_not_used(self):
        with self.assertRaisesRegex(RuntimeError, "client"):
            outlook_oauth.validate_client_id("not-a-guid")


if __name__ == "__main__":
    unittest.main()
