import importlib.util
import os
import ssl
import stat
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "scripts" / "check-mail.py"
SPEC = importlib.util.spec_from_file_location("check_mail", SCRIPT)
check_mail = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_mail)


def header_response(uid, sender=None, subject=None):
    sender = sender or f"Sender {uid} <sender{uid}@example.com>"
    subject = subject or f"Subject {uid}"
    payload = (
        f"From: {sender}\r\n"
        f"Subject: {subject}\r\n"
        "Date: Thu, 10 Sep 2026 12:00:00 +0000\r\n\r\n"
    ).encode()
    metadata = (
        f"1 (UID {uid} BODY[HEADER.FIELDS (FROM SUBJECT DATE)] "
        f"{{{len(payload)}}}"
    ).encode()
    return metadata, payload


class ListConnection:
    def __init__(self, uids=("10", "11", "12"), uid_validity="99"):
        self.uids = [uid.encode() for uid in uids]
        self.uid_validity = uid_validity.encode()
        self.fetch_sets = []
        self.logged_out = False

    def select(self, folder, readonly=False):
        return "OK", [str(len(self.uids)).encode()]

    def response(self, name):
        self.assert_name = name
        return name, [self.uid_validity]

    def uid(self, command, *args):
        if command == "search" and args[-1] == "UNSEEN":
            return "OK", [b"11 12"]
        if command == "search" and args[-1] == "ALL":
            return "OK", [b" ".join(self.uids)]
        if command == "fetch":
            message_set = args[0]
            self.fetch_sets.append(message_set)
            wanted = message_set.split(b",")
            return "OK", [header_response(uid.decode()) for uid in wanted] + [b")"]
        raise AssertionError((command, args))

    def logout(self):
        self.logged_out = True


class ReadConnection:
    def __init__(self, raw_message, declared_size=None):
        self.raw_message = raw_message
        self.declared_size = declared_size if declared_size is not None else len(raw_message)
        self.calls = []

    def select(self, folder, readonly=False):
        self.calls.append(("select", folder, readonly))
        return "OK", [b"1"]

    def uid(self, command, *args):
        self.calls.append((command, *args))
        if command == "fetch" and args[1] == "(RFC822.SIZE)":
            return "OK", [f"1 (UID 42 RFC822.SIZE {self.declared_size})".encode()]
        if command == "fetch" and args[1] == "(BODY.PEEK[])":
            return "OK", [(b"1 (UID 42 BODY[] {1}", self.raw_message), b")"]
        if command == "store":
            return "OK", [b"42 (UID 42 FLAGS (\\Seen))"]
        raise AssertionError((command, args))

    def logout(self):
        self.calls.append(("logout",))


class CheckMailTests(unittest.TestCase):
    def account(self, **overrides):
        account = {
            "name": "Test",
            "host": "imap.example.com",
            "security": "ssl",
            "username": "me@example.com",
            "passwordCommand": "unused",
            "folder": "INBOX",
            "displayLimit": 2,
        }
        account.update(overrides)
        return account

    def test_ssl_connection_uses_verified_context(self):
        connection = mock.Mock()
        with mock.patch.object(check_mail, "get_password", return_value="secret"), \
                mock.patch.object(
                    check_mail.imaplib, "IMAP4_SSL",
                    return_value=connection) as constructor:
            self.assertIs(check_mail.connect_to_imap(self.account()), connection)

        context = constructor.call_args.kwargs["ssl_context"]
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        connection.login.assert_called_once_with("me@example.com", "secret")

    def test_starttls_connection_uses_verified_context(self):
        connection = mock.Mock()
        account = self.account(security="starttls", port="143")
        with mock.patch.object(check_mail, "get_password", return_value="secret"), \
                mock.patch.object(check_mail.imaplib, "IMAP4", return_value=connection):
            self.assertIs(check_mail.connect_to_imap(account), connection)

        context = connection.starttls.call_args.kwargs["ssl_context"]
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_list_batches_headers_and_tracks_new_uids(self):
        connection = ListConnection()
        account = self.account(previousUidValidity="99", lastUid=10)
        with mock.patch.object(check_mail, "connect_to_imap", return_value=connection):
            result = check_mail.check_account_list(account)

        self.assertTrue(result["ok"])
        self.assertEqual(result["uidValidity"], "99")
        self.assertEqual(result["latestUid"], 12)
        self.assertEqual(result["newCount"], 2)
        self.assertEqual([message["id"] for message in result["messages"]], ["12", "11"])
        self.assertEqual([message["id"] for message in result["newMessages"]], ["12", "11"])
        self.assertEqual(connection.fetch_sets, [b"11,12"])
        self.assertTrue(connection.logged_out)

    def test_header_fetch_uses_bounded_batches(self):
        connection = ListConnection(tuple(str(uid) for uid in range(1, 206)))
        check_mail.fetch_headers(connection, connection.uids)
        self.assertEqual(len(connection.fetch_sets), 3)
        self.assertEqual(len(connection.fetch_sets[0].split(b",")), 100)
        self.assertEqual(len(connection.fetch_sets[-1].split(b",")), 5)

    def test_uid_validity_change_resets_new_message_baseline(self):
        connection = ListConnection(uid_validity="100")
        account = self.account(previousUidValidity="99", lastUid=10)
        with mock.patch.object(check_mail, "connect_to_imap", return_value=connection):
            result = check_mail.check_account_list(account)

        self.assertTrue(result["ok"])
        self.assertEqual(result["newCount"], 0)
        self.assertEqual(result["newMessages"], [])

    def test_invalid_mailbox_returns_clear_error(self):
        connection = ListConnection()
        connection.select = mock.Mock(return_value=("NO", [b"Mailbox does not exist"]))
        with mock.patch.object(check_mail, "connect_to_imap", return_value=connection):
            result = check_mail.check_account_list(self.account())
        self.assertFalse(result["ok"])
        self.assertIn("Cannot open mailbox", result["error"])

    def test_attachment_cache_is_private(self):
        message = EmailMessage()
        message["Subject"] = "Attachment"
        message.set_content("Body")
        message.add_attachment(
            b"content", maintype="application", subtype="octet-stream",
            filename="file.bin")

        with tempfile.TemporaryDirectory() as temp_dir, \
                mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": temp_dir}), \
                mock.patch.object(check_mail.tempfile, "gettempdir", return_value=temp_dir):
            attachments = check_mail.save_attachments(message, self.account(), "42")
            attachment = Path(attachments[0]["path"])
            cache_root = attachment.parents[1]
            self.assertEqual(stat.S_IMODE(cache_root.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(attachment.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(attachment.stat().st_mode), 0o600)
            self.assertEqual(attachment.read_bytes(), b"content")

    def test_cache_rejects_symlink_root(self):
        with tempfile.TemporaryDirectory() as temp_dir, \
                mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": temp_dir}), \
                mock.patch.object(check_mail.tempfile, "gettempdir", return_value=temp_dir):
            target = Path(temp_dir) / "target"
            target.mkdir()
            (Path(temp_dir) / "dms-mail-reader-attachments").symlink_to(
                target, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "Unsafe attachment cache"):
                check_mail.secure_cache_root()

    def test_cleanup_removes_expired_cache_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            old_dir = Path(temp_dir) / "old"
            old_dir.mkdir()
            old_time = 1
            os.utime(old_dir, (old_time, old_time))
            check_mail.cleanup_attachment_cache(temp_dir, max_age=1)
            self.assertFalse(old_dir.exists())

    def test_oversized_message_is_rejected_before_body_fetch(self):
        message = EmailMessage()
        message.set_content("Body")
        connection = ReadConnection(
            message.as_bytes(), declared_size=check_mail.MAX_MESSAGE_BYTES + 1)
        with mock.patch.object(check_mail, "connect_to_imap", return_value=connection):
            result = check_mail.read_account_message(self.account(), "42")

        self.assertFalse(result["ok"])
        self.assertIn("too large", result["error"])
        self.assertFalse(any(call[0] == "store" for call in connection.calls))
        self.assertFalse(any(
            call[0] == "fetch" and call[2] == "(BODY.PEEK[])"
            for call in connection.calls))

    def test_message_is_marked_seen_after_attachment_save(self):
        message = EmailMessage()
        message["From"] = "Sender <sender@example.com>"
        message["To"] = "me@example.com"
        message["Subject"] = "Hello"
        message.set_content("Body")
        message.add_attachment(
            b"content", maintype="application", subtype="pdf",
            filename="file.pdf")
        connection = ReadConnection(message.as_bytes())

        with tempfile.TemporaryDirectory() as temp_dir, \
                mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": temp_dir}), \
                mock.patch.object(check_mail.tempfile, "gettempdir", return_value=temp_dir), \
                mock.patch.object(check_mail, "connect_to_imap", return_value=connection):
            result = check_mail.read_account_message(self.account(), "42")

        self.assertTrue(result["ok"])
        self.assertTrue(result["markedSeen"])
        body_fetch_index = next(i for i, call in enumerate(connection.calls)
                                if call[0] == "fetch" and call[2] == "(BODY.PEEK[])")
        store_index = next(i for i, call in enumerate(connection.calls) if call[0] == "store")
        self.assertLess(body_fetch_index, store_index)
        self.assertEqual(result["attachments"][0]["name"], "file.pdf")


if __name__ == "__main__":
    unittest.main()
