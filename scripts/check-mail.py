#!/usr/bin/env python3
"""IMAP mail checker/reader for the DMS Mail Reader plugin.

Reads a single-line JSON config from stdin and prints a JSON result to
stdout. Listing opens the mailbox read-only. Reading a message fetches it
with BODY.PEEK and then explicitly marks that message as Seen.

Config:
    {"limit": 20, "accounts": [{"name": "...", "host": "...", "port": "993",
     "security": "ssl"|"starttls", "username": "...",
     "passwordCommand": "secret-tool lookup service imap account me",
     "folder": "INBOX", "displayLimit": 0, "pollInterval": 60}],
     "action": "list"|"read", "messageId": "123"}

Result for list:
    {"accounts": [{"name": "...", "ok": true, "error": "", "unread": 3,
     "messages": [{"id": "uid", "sender": "...", "subject": "...",
                   "timestamp": 1765432100}]}]}

Result for read:
    {"ok": true, "error": "", "from": "...", "to": "...", "date": "...",
     "subject": "...", "body": "...", "markedSeen": true,
     "attachments": [{"name": "file.pdf", "path": "/tmp/...", "size": 1234}]}
"""

import hashlib
import html
import imaplib
import json
import os
import re
import subprocess
import sys
import tempfile
from email import policy
from email.header import decode_header, make_header
from email.parser import BytesHeaderParser, BytesParser
from email.utils import parsedate_to_datetime


def decode_mime(value):
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def get_password(account):
    command = (account.get("passwordCommand") or "").strip()
    if not command:
        raise RuntimeError("No password command configured")
    proc = subprocess.run(["sh", "-c", command], capture_output=True,
                          text=True, timeout=15)
    if proc.returncode != 0:
        detail = proc.stderr.strip()[:200]
        raise RuntimeError("Password command failed" +
                           (": " + detail if detail else ""))
    password = proc.stdout.strip()
    if not password:
        raise RuntimeError("Password command returned no output")
    return password


def connect_to_imap(account):
    host = (account.get("host") or "").strip()
    username = (account.get("username") or "").strip()
    if not host:
        raise RuntimeError("No IMAP host configured")
    if not username:
        raise RuntimeError("No username configured")
    password = get_password(account)

    security = account.get("security") or "ssl"
    port = int(account.get("port") or (143 if security == "starttls" else 993))

    conn = None
    if security == "starttls":
        conn = imaplib.IMAP4(host, port, timeout=20)
        conn.starttls()
    else:
        conn = imaplib.IMAP4_SSL(host, port, timeout=20)

    conn.login(username, password)
    return conn


def check_account_list(account, limit):
    """List emails in mailbox."""
    result = {
        "name": account.get("name") or account.get("username", ""),
        "ok": False,
        "error": "",
        "unread": 0,
        "messages": [],
    }
    conn = None
    try:
        conn = connect_to_imap(account)
        conn.select(account.get("folder") or "INBOX", readonly=True)

        # Get unread count
        status, data = conn.uid("search", None, "UNSEEN")
        if status == "OK":
            result["unread"] = len(data[0].split())

        # Get messages
        status, data = conn.uid("search", None, "ALL")
        if status != "OK":
            raise RuntimeError("Search failed")

        uids = data[0].split()

        # Apply display limit (0 = all)
        raw_display_limit = account.get("displayLimit", 20)
        if raw_display_limit is None or raw_display_limit == "":
            display_limit = 20
        else:
            display_limit = int(raw_display_limit)
        if display_limit > 0:
            uids = uids[-display_limit:]

        parser = BytesHeaderParser()
        for uid in reversed(uids):
            status, fetched = conn.uid(
                "fetch", uid,
                "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if status != "OK" or not fetched or not isinstance(fetched[0], tuple):
                continue
            headers = parser.parsebytes(fetched[0][1])
            timestamp = 0
            try:
                timestamp = int(parsedate_to_datetime(
                    headers.get("Date", "")).timestamp())
            except Exception:
                pass
            result["messages"].append({
                "id": uid.decode(),
                "sender": decode_mime(headers.get("From", "")),
                "subject": decode_mime(headers.get("Subject", "")) or "(no subject)",
                "timestamp": timestamp,
            })
        result["ok"] = True
    except Exception as exc:
        result["error"] = str(exc)[:300]
    finally:
        if conn is not None:
            try:
                conn.logout()
            except Exception:
                pass
    return result


def html_to_text(content):
    """Convert HTML to plain text."""
    content = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", content)
    content = re.sub(r"(?i)<br\s*/?>", "\n", content)
    content = re.sub(r"(?i)</p\s*>", "\n", content)
    content = re.sub(r"<[^>]+>", " ", content)
    return html.unescape(content)


def get_part_content(part):
    """Get content from a MIME part."""
    try:
        content = part.get_content()
        return content if isinstance(content, str) else str(content)
    except Exception:
        payload = part.get_payload(decode=True) or b""
        charset = part.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")


def extract_body(message):
    """Extract body from email message."""
    plain_parts = []
    html_parts = []

    if message.is_multipart():
        parts = message.walk()
    else:
        parts = [message]

    for part in parts:
        if part.is_multipart():
            continue
        filename = part.get_filename()
        disposition = (part.get_content_disposition() or "").lower()
        if filename or disposition == "attachment":
            continue

        content_type = part.get_content_type()
        content = get_part_content(part)
        if content_type == "text/plain":
            plain_parts.append(content)
        elif content_type == "text/html":
            html_parts.append(html_to_text(content))

    body = "\n\n".join(part for part in plain_parts if part.strip())
    if not body.strip():
        body = "\n\n".join(part for part in html_parts if part.strip())
    if not body.strip():
        return "[No text content available]"
    return body


def safe_filename(value):
    """Decode and sanitize a MIME filename."""
    filename = decode_mime(value or "").strip()
    filename = os.path.basename(filename)
    filename = re.sub(r"[\\/\x00-\x1f]", "_", filename)
    return filename or "attachment"


def save_attachments(message, account, message_id):
    """Save attachments to a temporary directory and return metadata."""
    if not message.is_multipart():
        return []

    user_key = account.get("username") or account.get("name") or "account"
    digest = hashlib.sha256(f"{user_key}:{message_id}".encode()).hexdigest()[:16]
    base_dir = os.path.join(tempfile.gettempdir(), "mailReader-attachments", digest)
    os.makedirs(base_dir, exist_ok=True)

    attachments = []
    used_names = set()
    for index, part in enumerate(message.walk(), start=1):
        if part.is_multipart():
            continue
        filename = part.get_filename()
        disposition = (part.get_content_disposition() or "").lower()
        if not filename and disposition != "attachment":
            continue

        name = safe_filename(filename or f"attachment-{index}")
        root_name, ext = os.path.splitext(name)
        final_name = name
        suffix = 2
        while final_name in used_names:
            final_name = f"{root_name}-{suffix}{ext}"
            suffix += 1
        used_names.add(final_name)

        payload = part.get_payload(decode=True)
        if payload is None:
            continue

        path = os.path.join(base_dir, final_name)
        with open(path, "wb") as handle:
            handle.write(payload)

        attachments.append({
            "name": final_name,
            "path": path,
            "size": len(payload),
            "contentType": part.get_content_type(),
        })
    return attachments


def format_date(value):
    """Format date string."""
    if not value:
        return ""
    try:
        return parsedate_to_datetime(value).isoformat(sep=" ")
    except Exception:
        return str(value)


def read_account_message(account, message_id):
    """Read a single email message."""
    result = {
        "ok": False,
        "error": "",
        "from": "",
        "to": "",
        "date": "",
        "subject": "",
        "body": "",
        "attachments": [],
        "markedSeen": False,
    }
    conn = None
    try:
        conn = connect_to_imap(account)
        # Open read-write so clicking a message can behave like a normal mail
        # client and mark it as read on the server.
        conn.select(account.get("folder") or "INBOX", readonly=False)

        # Fetch full message without implicitly setting Seen. We explicitly set
        # Seen afterwards so the behavior is deliberate and easy to change.
        uid = message_id.encode()
        status, fetched = conn.uid("fetch", uid, "(BODY.PEEK[])")
        if status != "OK" or not fetched or not isinstance(fetched[0], tuple):
            raise RuntimeError("Cannot fetch message")

        raw = fetched[0][1]
        message = BytesParser(policy=policy.default).parsebytes(raw)

        store_status, _ = conn.uid("store", uid, "+FLAGS.SILENT", "(\\Seen)")
        result["markedSeen"] = store_status == "OK"

        result["from"] = decode_mime(message.get("From", ""))
        result["to"] = decode_mime(message.get("To", ""))
        result["date"] = format_date(message.get("Date", ""))
        result["subject"] = decode_mime(message.get("Subject", "")) or "(no subject)"
        result["body"] = extract_body(message)
        result["attachments"] = save_attachments(message, account, message_id)
        result["ok"] = True
    except Exception as exc:
        result["error"] = str(exc)[:300]
    finally:
        if conn is not None:
            try:
                conn.logout()
            except Exception:
                pass
    return result


def main():
    try:
        config = json.loads(sys.stdin.readline())
    except Exception:
        print(json.dumps({"error": "Invalid config", "accounts": []}))
        return

    action = config.get("action") or "list"
    limit = max(1, int(config.get("limit") or 20))

    if action == "read":
        # Read single message
        account = config.get("account") or {}
        message_id = config.get("messageId") or ""
        if not account:
            print(json.dumps({"ok": False, "error": "No account configured"}))
            return
        if not message_id:
            print(json.dumps({"ok": False, "error": "No message ID"}))
            return
        result = read_account_message(account, message_id)
        print(json.dumps(result))
    else:
        # List emails
        accounts = [check_account_list(a, limit) for a in config.get("accounts", [])]
        print(json.dumps({"accounts": accounts}))


if __name__ == "__main__":
    main()
