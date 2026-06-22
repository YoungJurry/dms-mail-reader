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
    property bool popoutOpen: false

    // Track which unread UIDs were already seen so notifications only
    // fire for genuinely new mail (and not on the first check after start).
    property var _seenIds: ({})
    property bool _firstCheck: true

    readonly property string _scriptPath: Qt.resolvedUrl("../scripts/check-mail.py").toString().replace("file://", "")

    function refresh() {
        if (!configured || checkProc.running)
            return;
        root.checking = true;
        checkProc.running = true;
    }

    onPopoutOpenChanged: if (popoutOpen) refresh()

    onConfiguredChanged: {
        root._firstCheck = true;
        root._seenIds = {};
        if (configured)
            refresh();
        else {
            root.ok = false;
            root.unreadCount = 0;
            root.messages = [];
            root.lastError = "";
        }
    }

    function readMessage(messageId) {
        if (!configured || readProc.running)
            return;
        root.readingContent = true;
        root.readOk = false;
        root.readError = "";
        root.currentEmailMarkedSeen = false;
        root.currentEmail = null;
        readProc.messageId = messageId;
        readProc.running = true;
    }

    function openAttachment(path) {
        if (!path || path.length === 0)
            return;
        attachmentProc.command = ["xdg-open", path];
        attachmentProc.running = true;
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
        command: ["python3", root._scriptPath]
        running: false
        stdinEnabled: true
        onStarted: {
            // Config goes through stdin so credentials-related settings
            // never show up in the process list.
            var config = {
                action: "list",
                limit: 20,
                accounts: [{
                    name: root.accountName,
                    host: root.imapHost,
                    port: root.imapPort,
                    security: root.security,
                    username: root.username,
                    passwordCommand: root.passwordCommand,
                    folder: root.folder,
                    displayLimit: root.displayLimit
                }]
            };
            checkProc.write(JSON.stringify(config) + "\n");
        }
        stdout: StdioCollector {
            onStreamFinished: root._applyResult(this.text)
        }
        onExited: (code, status) => {
            root.checking = false;
        }
    }

    Process {
        id: readProc
        property string messageId: ""
        command: ["python3", root._scriptPath]
        running: false
        stdinEnabled: true
        onStarted: {
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
            onStreamFinished: root._applyReadResult(this.text)
        }
        onExited: (code, status) => {
            root.readingContent = false;
        }
    }

    Process {
        id: notifyProc
        running: false
    }

    Process {
        id: attachmentProc
        running: false
    }

    function _applyResult(text) {
        root.checking = false;
        var data = null;
        try {
            data = JSON.parse(text.trim());
        } catch (e) {
            root.ok = false;
            root.lastError = "Failed to parse checker output";
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

        var fresh = [];
        var seen = root._seenIds;
        var nextSeen = {};
        for (var i = 0; i < root.messages.length; i++) {
            var m = root.messages[i];
            nextSeen[m.id] = true;
            if (!seen[m.id])
                fresh.push(m);
        }
        root._seenIds = nextSeen;

        if (root._firstCheck) {
            root._firstCheck = false;
            return;
        }
        if (root.notifyOnNew && fresh.length > 0)
            _notify(fresh);
    }

    function _applyReadResult(text) {
        root.readingContent = false;
        var data = null;
        try {
            data = JSON.parse(text.trim());
        } catch (e) {
            root.readOk = false;
            root.readError = "Failed to parse email content";
            return;
        }

        if (!data.ok) {
            root.readOk = false;
            root.readError = data.error || "Failed to read email";
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
        root.refresh();
    }

    function displaySender(sender) {
        var m = sender.match(/^\s*"?([^"<]+?)"?\s*<.*>\s*$/);
        return m ? m[1] : sender;
    }

    function _notify(fresh) {
        var title;
        var body;
        if (fresh.length === 1) {
            title = "New mail from " + displaySender(fresh[0].sender);
            body = fresh[0].subject;
        } else {
            title = fresh.length + " new messages";
            var lines = [];
            for (var i = 0; i < Math.min(fresh.length, 5); i++)
                lines.push(displaySender(fresh[i].sender) + ": " + fresh[i].subject);
            body = lines.join("\n");
        }
        notifyProc.command = ["notify-send", "-a", "Mail Checker", "-i", "mail-unread", title, body];
        notifyProc.running = true;
    }
}
