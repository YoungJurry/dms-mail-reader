pragma Singleton

import QtQuick
import Quickshell
import Quickshell.Io

Singleton {
    id: root

    // --- Status ---
    readonly property bool configured: imapHost.length > 0 && username.length > 0
    property bool checking: false
    property bool ok: false
    property string lastError: ""
    property int unreadCount: 0
    property var messages: []
    property var lastChecked: null

    // --- Content reading status ---
    property bool readingContent: false
    property bool readOk: false
    property string readError: ""
    property bool currentEmailMarkedSeen: false
    property var currentEmail: null

    // --- Config (set by Widget from pluginData) ---
    property string accountName: ""
    property string imapHost: ""
    property string imapPort: ""
    property string security: "ssl"
    property string username: ""
    property string passwordCommand: ""
    property string folder: "INBOX"
    property int displayLimit: 20
    property int pollInterval: 60
    property bool notifyOnNew: true
    property bool persistentNotification: true
    property bool popoutOpen: false

    // Server UID state gives notifications a stable baseline independent of
    // the number of messages currently shown in the popout.
    property string _uidValidity: ""
    property double _lastUid: 0
    property bool _firstCheck: true
    property string _mailboxKey: ""
    property int _configRevision: 0
    property bool _pendingRefresh: false
    property string _wantedMessageId: ""
    property string _checkStdout: ""
    property string _checkStderr: ""
    property string _readStdout: ""
    property string _readStderr: ""

    readonly property string _scriptPath: decodeURIComponent(
            Qt.resolvedUrl("../scripts/check-mail.py").toString()).replace("file://", "")
    readonly property string _iconPath: decodeURIComponent(
            Qt.resolvedUrl("../assets/mail-notification.png").toString()).replace("file://", "")

    function configure(config) {
        var host = (config.imapHost || "").trim();
        var user = (config.username || "").trim();
        var port = (config.imapPort || "").trim();
        var nextMailboxKey = [host, port, config.security, user, config.folder].join("\n");
        var mailboxChanged = root._mailboxKey !== nextMailboxKey;
        var queryChanged = mailboxChanged
                || root.passwordCommand !== config.passwordCommand
                || root.displayLimit !== config.displayLimit;

        root.accountName = config.accountName;
        root.imapHost = host;
        root.imapPort = port;
        root.security = config.security;
        root.username = user;
        root.passwordCommand = config.passwordCommand;
        root.folder = config.folder;
        root.displayLimit = config.displayLimit;
        root.pollInterval = config.pollInterval;
        root.notifyOnNew = config.notifyOnNew;
        root.persistentNotification = config.persistentNotification;
        root._mailboxKey = nextMailboxKey;

        if (queryChanged)
            root._configRevision++;
        if (mailboxChanged) {
            root._firstCheck = true;
            root._uidValidity = "";
            root._lastUid = 0;
            root.ok = false;
            root.unreadCount = 0;
            root.messages = [];
            root.lastError = "";
            root.cancelRead();
        }

        if (!configured) {
            root.ok = false;
            root.unreadCount = 0;
            root.messages = [];
            root.lastError = "";
            return;
        }
        if (queryChanged)
            refresh(true);
    }

    function refresh(queueIfRunning) {
        if (!configured)
            return;
        if (checkProc.running) {
            if (queueIfRunning === true)
                root._pendingRefresh = true;
            return;
        }
        root.checking = true;
        checkProc.requestRevision = root._configRevision;
        checkProc.running = true;
    }

    onPopoutOpenChanged: if (popoutOpen) refresh()

    function _startRead(messageId) {
        root.readingContent = true;
        readProc.messageId = messageId;
        readProc.requestRevision = root._configRevision;
        readProc.running = true;
    }

    function readMessage(messageId) {
        if (!configured || !messageId)
            return;
        root._wantedMessageId = messageId;
        root.readingContent = true;
        root.readOk = false;
        root.readError = "";
        root.currentEmailMarkedSeen = false;
        root.currentEmail = null;
        if (!readProc.running)
            _startRead(messageId);
    }

    function cancelRead() {
        root._wantedMessageId = "";
        root.readingContent = false;
        root.readOk = false;
        root.readError = "";
        root.currentEmailMarkedSeen = false;
        root.currentEmail = null;
    }

    function openAttachment(path) {
        if (!path || path.length === 0)
            return;
        Quickshell.execDetached(["xdg-open", path]);
    }

    function _processFailure(fallback, stderrText) {
        var detail = (stderrText || "").trim();
        if (detail.length === 0)
            return fallback;
        if (detail.length > 300)
            detail = detail.substring(0, 300);
        return fallback + ": " + detail;
    }

    Timer {
        id: pollTimer
        interval: Math.max(1, root.pollInterval) * 1000
        running: root.configured && root.pollInterval > 0
        repeat: true
        triggeredOnStart: true
        onIntervalChanged: if (running) restart()
        onTriggered: root.refresh()
    }

    Process {
        id: checkProc
        property int requestRevision: 0
        command: ["python3", root._scriptPath]
        running: false
        stdinEnabled: true
        onStarted: {
            root._checkStdout = "";
            root._checkStderr = "";
            // Config goes through stdin so credentials-related settings
            // never show up in the process list.
            var config = {
                action: "list",
                accounts: [{
                    name: root.accountName,
                    host: root.imapHost,
                    port: root.imapPort,
                    security: root.security,
                    username: root.username,
                    passwordCommand: root.passwordCommand,
                    folder: root.folder,
                    displayLimit: root.displayLimit,
                    previousUidValidity: root._uidValidity,
                    lastUid: root._lastUid
                }]
            };
            checkProc.write(JSON.stringify(config) + "\n");
        }
        stdout: StdioCollector {
            onStreamFinished: root._checkStdout = this.text
        }
        stderr: StdioCollector {
            onStreamFinished: root._checkStderr = this.text
        }
        onExited: (code, status) => {
            root._applyResult(root._checkStdout, checkProc.requestRevision);
            root.checking = false;
            if (root._pendingRefresh) {
                root._pendingRefresh = false;
                Qt.callLater(root.refresh);
            }
        }
    }

    Process {
        id: readProc
        property string messageId: ""
        property int requestRevision: 0
        command: ["python3", root._scriptPath]
        running: false
        stdinEnabled: true
        onStarted: {
            root._readStdout = "";
            root._readStderr = "";
            var config = {
                action: "read",
                messageId: readProc.messageId,
                account: {
                    name: root.accountName,
                    host: root.imapHost,
                    port: root.imapPort,
                    security: root.security,
                    username: root.username,
                    passwordCommand: root.passwordCommand,
                    folder: root.folder
                }
            };
            readProc.write(JSON.stringify(config) + "\n");
        }
        stdout: StdioCollector {
            onStreamFinished: root._readStdout = this.text
        }
        stderr: StdioCollector {
            onStreamFinished: root._readStderr = this.text
        }
        onExited: (code, status) => {
            root._applyReadResult(
                    root._readStdout, readProc.messageId, readProc.requestRevision);
            if (root._wantedMessageId.length > 0
                    && (root._wantedMessageId !== readProc.messageId
                        || readProc.requestRevision !== root._configRevision)) {
                Qt.callLater(function() {
                    if (root._wantedMessageId.length > 0 && !readProc.running)
                        root._startRead(root._wantedMessageId);
                });
            } else if (root._wantedMessageId.length === 0) {
                root.readingContent = false;
            }
        }
    }

    function _applyResult(text, requestRevision) {
        root.checking = false;
        if (requestRevision !== root._configRevision)
            return;
        var data = null;
        try {
            data = JSON.parse(text.trim());
        } catch (e) {
            root.ok = false;
            root.lastError = root._processFailure(
                    "Failed to parse checker output", root._checkStderr);
            return;
        }

        var accounts = data.accounts || [];
        if (accounts.length === 0) {
            root.ok = false;
            root.lastError = data.error || "No account configured";
            return;
        }

        var acc = accounts[0];
        root.lastChecked = new Date();
        if (!acc.ok) {
            root.ok = false;
            root.lastError = acc.error || "Check failed";
            return;
        }

        root.ok = true;
        root.lastError = "";
        root.unreadCount = acc.unread;
        root.messages = acc.messages || [];

        var fresh = acc.newMessages || [];
        root._uidValidity = String(acc.uidValidity || "");
        root._lastUid = Number(acc.latestUid || 0);
        if (root._firstCheck) {
            root._firstCheck = false;
            return;
        }
        var newCount = Number(acc.newCount || 0);
        if (root.notifyOnNew && newCount > 0)
            _notify(fresh, newCount);
    }

    function _applyReadResult(text, messageId, requestRevision) {
        if (requestRevision !== root._configRevision
                || messageId !== root._wantedMessageId)
            return;
        root.readingContent = false;
        var data = null;
        try {
            data = JSON.parse(text.trim());
        } catch (e) {
            root.readOk = false;
            root.readError = root._processFailure(
                    "Failed to parse email content", root._readStderr);
            root._wantedMessageId = "";
            return;
        }

        if (!data.ok) {
            root.readOk = false;
            root.readError = data.error || "Failed to read email";
            root._wantedMessageId = "";
            return;
        }

        root.readOk = true;
        root.readError = "";
        root.currentEmailMarkedSeen = data.markedSeen === true;
        root.currentEmail = {
            fromAddress: data.from || "",
            toAddress: data.to || "",
            date: data.date || "",
            subject: data.subject || "",
            body: data.body || "",
            attachments: data.attachments || []
        };
        root._wantedMessageId = "";
        root.refresh(true);
    }

    function displaySender(sender) {
        var m = sender.match(/^\s*"?([^"<]+?)"?\s*<.*>\s*$/);
        return m ? m[1] : sender;
    }

    function _notify(fresh, newCount) {
        var title;
        var body;
        if (newCount === 1) {
            if (fresh.length === 1) {
                title = "New mail from " + displaySender(fresh[0].sender);
                body = fresh[0].subject;
            } else {
                title = "1 new message";
                body = "";
            }
        } else {
            title = newCount + " new messages";
            var lines = [];
            for (var i = 0; i < Math.min(fresh.length, 5); i++)
                lines.push(displaySender(fresh[i].sender) + ": " + fresh[i].subject);
            body = lines.join("\n");
        }
        var icon = root._iconPath || "mail-unread";
        var cmd = [
            "notify-send", "-a", "Mail Reader", "-i", icon
        ];
        if (root.persistentNotification) {
            cmd.push("-t", "0");
            cmd.push("-h", "boolean:resident:true");
        }
        cmd.push(title, body);
        Quickshell.execDetached(cmd);
    }
}
