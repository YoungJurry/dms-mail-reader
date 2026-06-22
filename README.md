# Mail Reader for DankMaterialShell

An IMAP mail reader plugin for [DankMaterialShell](https://github.com/AvengeMedia/DankMaterialShell) with built-in email content viewer. Read your emails directly inside the shell without opening a separate mail client.

Forked from [Rocho's mailChecker](https://github.com/Rocho-EL-Locho/dms-mail-checker) with significant enhancements.

![screenshot](assets/screenshot.png)

## Features

- **Bar indicator** with unread mail count
- **Popout message list** with sender, subject, and relative time
- **Built-in email content viewer** — click any message to read its full content (Subject, From, To, Date, Attachments, Body) directly inside the plugin
- **Desktop notifications** for new mail
- **Configurable display count** — show all messages or only the latest N
- **Flexible polling** — auto-check every N seconds, or set to 0 for manual-only refresh
- **Read-only** — messages are fetched with `BODY.PEEK` so they are never marked as read
- **Password via command** — credentials are never stored in settings

## Dependencies

- `python3` (with `imaplib` — included in standard library)
- A Wayland compositor supported by DMS (Hyprland, Niri, etc.)

## Installation

### Via DMS CLI

```bash
dms plugins install mailReader
```

### Manual

Clone this repository into your plugins folder:

```bash
cd ~/.config/DankMaterialShell/plugins
git clone https://github.com/smithyyang/dms-mail-reader.git mailReader
```

Then restart DMS:

```bash
dms restart
```

## Configuration

Open DMS Settings → Plugins → Mail Reader and configure:

| Setting | Description |
|---------|-------------|
| Account Name | Display name (e.g. "Work", "Personal") |
| IMAP Host | Your IMAP server hostname |
| IMAP Port | Default: 993 (SSL) or 143 (STARTTLS) |
| Connection Security | SSL/TLS or STARTTLS |
| Username | Your email address |
| Password Command | Shell command that prints the password |
| Folder | Mailbox folder (default: INBOX) |
| Display Mail Count | Number of messages to show. `0` = all, `x` = latest x |
| Check Interval | Auto-check interval in seconds. `0` = manual only (refresh on open) |
| Notifications | Enable/disable desktop notifications |

### Password Command Examples

Using `pass`:
```bash
pass show email/password
```

Using `secret-tool`:
```bash
secret-tool lookup service imap account you@example.com
```

Inline password (not recommended for production):
```bash
sh -c 'echo "your-password"'
```

## How It Works

- Uses Python's built-in `imaplib` to connect to your IMAP server
- All communication happens via stdin/stdout (credentials never appear in process list)
- Messages are fetched read-only with `BODY.PEEK[]` — your mailbox state is never modified
- The plugin polls for new mail at the configured interval, or manually when `Check Interval = 0`

## Acknowledgements

This plugin is forked from [mailChecker](https://github.com/Rocho-EL-Locho/dms-mail-checker) by [Rocho](https://github.com/Rocho-EL-Locho). The original plugin provides IMAP unread counting and desktop notifications. This fork adds:

- Built-in email content viewer (click to read full message)
- Configurable display count (0 = all, x = latest x)
- Manual-only refresh mode (Check Interval = 0)
- Removed mail client launch dependency

## License

MIT — see [LICENSE](LICENSE)
