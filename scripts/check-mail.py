#!/usr/bin/env python3
"""IMAP mail checker/reader for the DMS Mail Reader plugin.

Reads a single-line JSON config from stdin and prints a JSON result to
stdout. Listing opens the mailbox read-only. Reading a message fetches it
with BODY.PEEK and then explicitly marks that message as Seen.

Config:
    {"accounts": [{"name": "...", "host": "...", "port": "993",
     "security": "ssl"|"starttls", "username": "...",
     "passwordCommand": "secret-tool lookup service imap account me",
     "folder": "INBOX", "displayLimit": 20,
     "previousUidValidity": "123", "lastUid": 456}],
     "action": "list"|"read", "messageId": "123"}

Result for list:
    {"accounts": [{"name": "...", "ok": true, "error": "", "unread": 3,
     "uidValidity": "123", "latestUid": 456, "newCount": 1,
     "messages": [{"id": "uid", "sender": "...", "subject": "...",
                   "timestamp": 1765432100}], "newMessages": [...]}]}

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
import shutil
import ssl
import stat
import subprocess
import sys
import tempfile
import time
from email import policy
from email.header import decode_header, make_header
from email.parser import BytesHeaderParser, BytesParser
from email.utils import parsedate_to_datetime


MAX_MESSAGE_BYTES = 50 * 1024 * 1024
ATTACHMENT_CACHE_MAX_AGE = 24 * 60 * 60
HEADER_FETCH_BATCH_SIZE = 100


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

    security = str(account.get("security") or "ssl").strip().lower()
    if security not in ("ssl", "starttls"):
        raise RuntimeError("Connection security must be ssl or starttls")
    try:
        port = int(account.get("port") or (143 if security == "starttls" else 993))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("IMAP port must be a number") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("IMAP port must be between 1 and 65535")

    context = ssl.create_default_context()
    conn = None
    try:
        if security == "starttls":
            conn = imaplib.IMAP4(host, port, timeout=20)
            conn.starttls(ssl_context=context)
        else:
            conn = imaplib.IMAP4_SSL(
                host, port, ssl_context=context, timeout=20)

        conn.login(username, password)
        return conn
    except Exception:
        if conn is not None:
            try:
                conn.shutdown()
            except Exception:
                pass
        raise


def select_mailbox(conn, folder, readonly):
    """Select a mailbox and turn a failed SELECT into a useful error."""
    status, data = conn.select(folder or "INBOX", readonly=readonly)
    if status == "OK":
        return
    detail = ""
    if data and data[0]:
        raw = data[0]
        detail = raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw)
    raise RuntimeError("Cannot open mailbox" + (": " + detail if detail else ""))


def selected_uid_validity(conn):
    """Return UIDVALIDITY for the currently selected mailbox."""
    _, data = conn.response("UIDVALIDITY")
    if not data or not data[0]:
        return ""
    raw = data[0]
    return raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw)


def fetch_headers(conn, uids):
    """Fetch and parse headers in bounded batches of UIDs."""
    parser = BytesHeaderParser()
    messages = {}
    for offset in range(0, len(uids), HEADER_FETCH_BATCH_SIZE):
        batch = uids[offset:offset + HEADER_FETCH_BATCH_SIZE]
        message_set = b",".join(batch)
        status, fetched = conn.uid(
            "fetch", message_set,
            "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
        if status != "OK":
            raise RuntimeError("Cannot fetch message headers")

        for item in fetched or []:
            if not isinstance(item, tuple) or len(item) < 2:
                continue
            metadata, payload = item[0], item[1]
            if not isinstance(metadata, bytes) or not isinstance(payload, bytes):
                continue
            match = re.search(rb"\bUID\s+(\d+)\b", metadata, re.IGNORECASE)
            if not match:
                continue
            uid = match.group(1).decode("ascii")
            headers = parser.parsebytes(payload)
            timestamp = 0
            try:
                timestamp = int(parsedate_to_datetime(
                    headers.get("Date", "")).timestamp())
            except Exception:
                pass
            messages[uid] = {
                "id": uid,
                "sender": decode_mime(headers.get("From", "")),
                "subject": decode_mime(headers.get("Subject", "")) or "(no subject)",
                "timestamp": timestamp,
            }
    return messages


def check_account_list(account):
    """List emails and report stable UID metadata for notifications."""
    result = {
        "name": account.get("name") or account.get("username", ""),
        "ok": False,
        "error": "",
        "unread": 0,
        "messages": [],
        "newMessages": [],
        "newCount": 0,
        "uidValidity": "",
        "latestUid": 0,
    }
    conn = None
    try:
        conn = connect_to_imap(account)
        select_mailbox(conn, account.get("folder") or "INBOX", readonly=True)
        result["uidValidity"] = selected_uid_validity(conn)

        status, data = conn.uid("search", None, "UNSEEN")
        if status != "OK":
            raise RuntimeError("Unread search failed")
        result["unread"] = len((data[0] or b"").split())

        status, data = conn.uid("search", None, "ALL")
        if status != "OK":
            raise RuntimeError("Message search failed")
        all_uids = (data[0] or b"").split()
        result["latestUid"] = int(all_uids[-1]) if all_uids else 0

        try:
            display_limit = int(account.get("displayLimit", 20))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Display limit must be a number") from exc
        if display_limit < 0:
            raise RuntimeError("Display limit cannot be negative")
        display_uids = all_uids[-display_limit:] if display_limit > 0 else all_uids

        previous_validity = str(account.get("previousUidValidity") or "")
        try:
            last_uid = int(account.get("lastUid") or 0)
        except (TypeError, ValueError):
            last_uid = 0
        new_uids = []
        if result["uidValidity"] and previous_validity == result["uidValidity"]:
            new_uids = [uid for uid in all_uids if int(uid) > last_uid]
        result["newCount"] = len(new_uids)

        # Fetch the visible list plus up to five new-message summaries in one
        # round trip. The latter keeps notification counts independent of the
        # display limit without loading unbounded header data.
        wanted_uids = list(dict.fromkeys(display_uids + new_uids[-5:]))
        by_uid = fetch_headers(conn, wanted_uids)
        result["messages"] = [
            by_uid[uid.decode("ascii")]
            for uid in reversed(display_uids)
            if uid.decode("ascii") in by_uid
        ]
        result["newMessages"] = [
            by_uid[uid.decode("ascii")]
            for uid in reversed(new_uids[-5:])
            if uid.decode("ascii") in by_uid
        ]
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
    """Decode and sanitize a MIME filename for a Linux filesystem."""
    filename = decode_mime(value or "").strip()
    filename = os.path.basename(filename)
    filename = re.sub(r"[\\/\x00-\x1f\x7f]", "_", filename)
    if filename in ("", ".", ".."):
        filename = "attachment"

    # Leave room for duplicate-name suffixes and stay below common NAME_MAX.
    encoded = filename.encode("utf-8")
    if len(encoded) > 220:
        stem, ext = os.path.splitext(filename)
        ext_bytes = ext.encode("utf-8")[:40]
        stem_budget = max(1, 220 - len(ext_bytes))
        stem = stem.encode("utf-8")[:stem_budget].decode("utf-8", "ignore")
        ext = ext_bytes.decode("utf-8", "ignore")
        filename = (stem or "attachment") + ext
    return filename


def secure_cache_root():
    """Return an owner-only attachment cache directory."""
    # Remove cache files created by versions that used world-readable modes.
    legacy_root = os.path.join(tempfile.gettempdir(), "mailReader-attachments")
    try:
        legacy_info = os.lstat(legacy_root)
        if stat.S_ISDIR(legacy_info.st_mode) and legacy_info.st_uid == os.getuid():
            shutil.rmtree(legacy_root)
    except (FileNotFoundError, OSError):
        pass

    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir and os.path.isdir(runtime_dir):
        root = os.path.join(runtime_dir, "dms-mail-reader-attachments")
    else:
        root = os.path.join(
            tempfile.gettempdir(), f"dms-mail-reader-{os.getuid()}-attachments")

    try:
        os.mkdir(root, 0o700)
    except FileExistsError:
        pass

    info = os.lstat(root)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise RuntimeError("Unsafe attachment cache directory")
    os.chmod(root, 0o700)
    return root


def cleanup_attachment_cache(root, max_age=ATTACHMENT_CACHE_MAX_AGE):
    """Remove attachment directories older than max_age seconds."""
    cutoff = time.time() - max_age
    for entry in os.scandir(root):
        try:
            info = entry.stat(follow_symlinks=False)
            if info.st_mtime >= cutoff:
                continue
            if entry.is_dir(follow_symlinks=False):
                shutil.rmtree(entry.path)
            else:
                os.unlink(entry.path)
        except (FileNotFoundError, OSError):
            continue


def save_attachments(message, account, message_id):
    """Save attachments to a private, short-lived cache."""
    cache_root = secure_cache_root()
    cleanup_attachment_cache(cache_root)
    if not message.is_multipart():
        return []

    user_key = account.get("username") or account.get("name") or "account"
    digest = hashlib.sha256(f"{user_key}:{message_id}".encode()).hexdigest()[:16]
    base_dir = os.path.join(cache_root, digest)
    if os.path.lexists(base_dir):
        if os.path.islink(base_dir) or not os.path.isdir(base_dir):
            raise RuntimeError("Unsafe attachment cache entry")
        shutil.rmtree(base_dir)
    os.mkdir(base_dir, 0o700)

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
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags, 0o600)
        with os.fdopen(fd, "wb") as handle:
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


def fetch_message_size(conn, uid):
    """Fetch RFC822.SIZE for a UID before downloading the full message."""
    status, data = conn.uid("fetch", uid, "(RFC822.SIZE)")
    if status != "OK":
        raise RuntimeError("Cannot determine message size")
    for item in data or []:
        raw = item[0] if isinstance(item, tuple) else item
        if not isinstance(raw, bytes):
            continue
        match = re.search(rb"RFC822\.SIZE\s+(\d+)", raw, re.IGNORECASE)
        if match:
            return int(match.group(1))
    raise RuntimeError("Cannot determine message size")


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
        select_mailbox(
            conn, account.get("folder") or "INBOX", readonly=False)

        # Fetch full message without implicitly setting Seen. Reject unusually
        # large messages before loading them into memory or filling the cache.
        uid = message_id.encode()
        message_size = fetch_message_size(conn, uid)
        if message_size > MAX_MESSAGE_BYTES:
            raise RuntimeError(
                f"Message is too large to open ({message_size // (1024 * 1024)} MB; "
                f"limit {MAX_MESSAGE_BYTES // (1024 * 1024)} MB)")

        status, fetched = conn.uid("fetch", uid, "(BODY.PEEK[])")
        if status != "OK" or not fetched or not isinstance(fetched[0], tuple):
            raise RuntimeError("Cannot fetch message")

        raw = fetched[0][1]
        message = BytesParser(policy=policy.default).parsebytes(raw)

        result["from"] = decode_mime(message.get("From", ""))
        result["to"] = decode_mime(message.get("To", ""))
        result["date"] = format_date(message.get("Date", ""))
        result["subject"] = decode_mime(message.get("Subject", "")) or "(no subject)"
        result["body"] = extract_body(message)
        result["attachments"] = save_attachments(message, account, message_id)

        # Mark Seen only after parsing and attachment extraction succeeded.
        store_status, _ = conn.uid("store", uid, "+FLAGS.SILENT", "(\\Seen)")
        result["markedSeen"] = store_status == "OK"
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

    if not isinstance(config, dict):
        print(json.dumps({"error": "Invalid config", "accounts": []}))
        return

    action = config.get("action") or "list"

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
        message_id = str(message_id)
        if not re.fullmatch(r"[1-9]\d*", message_id):
            print(json.dumps({"ok": False, "error": "Invalid message ID"}))
            return
        result = read_account_message(account, message_id)
        print(json.dumps(result))
    elif action == "list":
        raw_accounts = config.get("accounts", [])
        if not isinstance(raw_accounts, list):
            print(json.dumps({"error": "Accounts must be a list", "accounts": []}))
            return
        accounts = [
            check_account_list(account)
            for account in raw_accounts
            if isinstance(account, dict)
        ]
        print(json.dumps({"accounts": accounts}))
    else:
        print(json.dumps({"error": "Unknown action", "accounts": []}))


if __name__ == "__main__":
    main()
