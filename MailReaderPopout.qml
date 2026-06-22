import QtQuick
import QtQuick.Layouts
import qs.Common
import qs.Widgets
import qs.Modules.Plugins
import qs.Services
import "./services" as Services

PopoutComponent {
    id: root

    headerText: ""
    detailsText: ""
    showCloseButton: false

    property int maxPopoutHeight: 700
    property real nowMs: Date.now()
    property bool detailMode: false
    property var selectedMessage: null

    Component.onCompleted: Services.MailService.popoutOpen = true
    Component.onDestruction: Services.MailService.popoutOpen = false

    Timer {
        interval: 30000
        repeat: true
        running: true
        onTriggered: root.nowMs = Date.now()
    }

    function fmtAgo(timestamp) {
        if (!timestamp)
            return "";
        var diff = Math.max(0, Math.floor((Date.now() - timestamp * 1000) / 1000));
        if (diff < 60)
            return "now";
        if (diff < 3600)
            return Math.floor(diff / 60) + "m";
        if (diff < 86400)
            return Math.floor(diff / 3600) + "h";
        return Math.floor(diff / 86400) + "d";
    }

    function openMessage(message) {
        root.selectedMessage = message;
        root.detailMode = true;
        Services.MailService.readMessage(message.id);
    }

    function backToList() {
        root.detailMode = false;
        root.selectedMessage = null;
    }

    Item {
        id: bodyContainer
        width: parent.width
        implicitHeight: Math.max(80, Math.min(bodyCol.implicitHeight + Theme.spacingS, root.maxPopoutHeight))
        height: implicitHeight

        DankFlickable {
            id: scroll
            anchors.fill: parent
            contentWidth: width
            contentHeight: bodyCol.implicitHeight
            clip: true

            Column {
                id: bodyCol
                width: scroll.width
                spacing: Theme.spacingM

                Rectangle {
                    width: parent.width
                    radius: Theme.cornerRadius
                    color: Theme.surfaceContainerHigh
                    border.color: Qt.rgba(Theme.outline.r, Theme.outline.g, Theme.outline.b, 0.4)
                    border.width: 1
                    implicitHeight: headerRow.implicitHeight + Theme.spacingM * 2

                    RowLayout {
                        id: headerRow
                        anchors.fill: parent
                        anchors.margins: Theme.spacingM
                        spacing: Theme.spacingM

                        Rectangle {
                            Layout.preferredWidth: 40
                            Layout.preferredHeight: 40
                            radius: 20
                            color: iconMouse.containsMouse ? Theme.surfaceContainerHighest : Theme.surfaceContainer
                            border.color: Qt.rgba(Theme.outline.r, Theme.outline.g, Theme.outline.b, 0.5)
                            border.width: 1

                            DankIcon {
                                anchors.centerIn: parent
                                name: root.detailMode ? "arrow_back" : "mail"
                                size: 22
                                color: Theme.primary
                            }

                            MouseArea {
                                id: iconMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: root.detailMode ? Qt.PointingHandCursor : Qt.ArrowCursor
                                onClicked: if (root.detailMode) root.backToList()
                            }
                        }

                        Column {
                            Layout.fillWidth: true
                            spacing: 2

                            StyledText {
                                width: parent.width
                                text: root.detailMode
                                      ? (root.selectedMessage ? root.selectedMessage.subject : "Mail Content")
                                      : (Services.MailService.accountName || "Mail")
                                font.pixelSize: Theme.fontSizeMedium + 1
                                font.weight: Font.Bold
                                color: Theme.surfaceText
                                elide: Text.ElideRight
                            }

                            StyledText {
                                width: parent.width
                                text: {
                                    if (root.detailMode)
                                        return root.selectedMessage ? Services.MailService.displaySender(root.selectedMessage.sender) : "";
                                    if (!Services.MailService.configured)
                                        return "Not configured";
                                    if (Services.MailService.checking)
                                        return "Checking...";
                                    return Services.MailService.unreadCount + " unread, " + Services.MailService.messages.length + " shown";
                                }
                                font.pixelSize: Theme.fontSizeSmall
                                color: Theme.surfaceVariantText
                                elide: Text.ElideRight
                            }
                        }

                        Rectangle {
                            Layout.preferredWidth: 32
                            Layout.preferredHeight: 32
                            radius: 16
                            color: refreshMouse.containsMouse ? Theme.surfaceContainerHighest : "transparent"
                            visible: !root.detailMode

                            DankIcon {
                                anchors.centerIn: parent
                                name: "refresh"
                                size: 16
                                color: Theme.surfaceText

                                RotationAnimation on rotation {
                                    running: Services.MailService.checking
                                    from: 0
                                    to: 360
                                    duration: 900
                                    loops: Animation.Infinite
                                }
                            }

                            MouseArea {
                                id: refreshMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: Services.MailService.refresh()
                            }
                        }
                    }
                }

                // ---------------- List mode ----------------
                Rectangle {
                    width: parent.width
                    radius: Theme.cornerRadius
                    color: Theme.surfaceContainerHigh
                    visible: !root.detailMode && !Services.MailService.configured
                    implicitHeight: hintText.implicitHeight + Theme.spacingM * 2

                    StyledText {
                        id: hintText
                        anchors.fill: parent
                        anchors.margins: Theme.spacingM
                        text: "Configure your IMAP account in the plugin settings."
                        font.pixelSize: Theme.fontSizeSmall
                        color: Theme.surfaceVariantText
                        wrapMode: Text.WordWrap
                    }
                }

                Rectangle {
                    width: parent.width
                    radius: Theme.cornerRadius
                    color: Theme.errorHover
                    visible: !root.detailMode && Services.MailService.configured && Services.MailService.lastError.length > 0
                    implicitHeight: listErrorText.implicitHeight + Theme.spacingM * 2

                    StyledText {
                        id: listErrorText
                        anchors.fill: parent
                        anchors.margins: Theme.spacingM
                        text: Services.MailService.lastError
                        font.pixelSize: Theme.fontSizeSmall
                        color: Theme.error
                        wrapMode: Text.WordWrap
                    }
                }

                Rectangle {
                    width: parent.width
                    radius: Theme.cornerRadius
                    color: Theme.surfaceContainer
                    border.color: Theme.outline
                    border.width: 1
                    visible: !root.detailMode && Services.MailService.configured && Services.MailService.ok && Services.MailService.messages.length === 0
                    implicitHeight: 56

                    RowLayout {
                        anchors.centerIn: parent
                        spacing: Theme.spacingS

                        DankIcon {
                            name: "mark_email_read"
                            size: 18
                            color: Theme.surfaceVariantText
                        }

                        StyledText {
                            text: "No messages"
                            font.pixelSize: Theme.fontSizeSmall
                            color: Theme.surfaceVariantText
                        }
                    }
                }

                Rectangle {
                    width: parent.width
                    radius: Theme.cornerRadius
                    color: Theme.surfaceContainer
                    border.color: Theme.outline
                    border.width: 1
                    visible: !root.detailMode && Services.MailService.messages.length > 0
                    implicitHeight: msgCol.implicitHeight

                    Column {
                        id: msgCol
                        width: parent.width
                        spacing: 0

                        Repeater {
                            model: Services.MailService.messages
                            delegate: Item {
                                width: msgCol.width
                                height: 58

                                Rectangle {
                                    visible: index > 0
                                    anchors.top: parent.top
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.leftMargin: Theme.spacingM
                                    anchors.rightMargin: Theme.spacingM
                                    height: 1
                                    color: Theme.outline
                                    opacity: 0.25
                                }

                                Rectangle {
                                    anchors.fill: parent
                                    radius: Theme.cornerRadius
                                    color: msgMouse.containsMouse ? Theme.surfaceContainerHigh : "transparent"
                                }

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: Theme.spacingM
                                    anchors.rightMargin: Theme.spacingM
                                    spacing: Theme.spacingS

                                    Column {
                                        Layout.fillWidth: true
                                        spacing: 2

                                        StyledText {
                                            width: parent.width
                                            text: Services.MailService.displaySender(modelData.sender)
                                            font.pixelSize: Theme.fontSizeSmall + 1
                                            font.weight: Font.Bold
                                            color: Theme.surfaceText
                                            elide: Text.ElideRight
                                        }

                                        StyledText {
                                            width: parent.width
                                            text: modelData.subject
                                            font.pixelSize: Theme.fontSizeSmall
                                            color: Theme.surfaceVariantText
                                            elide: Text.ElideRight
                                        }
                                    }

                                    StyledText {
                                        Layout.alignment: Qt.AlignVCenter
                                        text: root.fmtAgo(modelData.timestamp)
                                        font.pixelSize: 10
                                        color: Theme.surfaceVariantText
                                    }
                                }

                                MouseArea {
                                    id: msgMouse
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.openMessage(modelData)
                                }
                            }
                        }
                    }
                }

                // ---------------- Detail mode ----------------
                Rectangle {
                    width: parent.width
                    radius: Theme.cornerRadius
                    color: Theme.surfaceContainer
                    border.color: Theme.outline
                    border.width: 1
                    visible: root.detailMode && Services.MailService.readingContent
                    implicitHeight: 72

                    RowLayout {
                        anchors.centerIn: parent
                        spacing: Theme.spacingS

                        DankIcon {
                            name: "hourglass_top"
                            size: 18
                            color: Theme.primary

                            RotationAnimation on rotation {
                                running: Services.MailService.readingContent
                                from: 0
                                to: 360
                                duration: 900
                                loops: Animation.Infinite
                            }
                        }

                        StyledText {
                            text: "Loading email content..."
                            font.pixelSize: Theme.fontSizeSmall
                            color: Theme.surfaceVariantText
                        }
                    }
                }

                Rectangle {
                    width: parent.width
                    radius: Theme.cornerRadius
                    color: Theme.errorHover
                    visible: root.detailMode && !Services.MailService.readingContent && Services.MailService.readError.length > 0
                    implicitHeight: readErrorText.implicitHeight + Theme.spacingM * 2

                    StyledText {
                        id: readErrorText
                        anchors.fill: parent
                        anchors.margins: Theme.spacingM
                        text: Services.MailService.readError
                        font.pixelSize: Theme.fontSizeSmall
                        color: Theme.error
                        wrapMode: Text.WordWrap
                    }
                }

                Rectangle {
                    width: parent.width
                    radius: Theme.cornerRadius
                    color: Theme.surfaceContainer
                    border.color: Theme.outline
                    border.width: 1
                    visible: root.detailMode && !Services.MailService.readingContent && Services.MailService.readOk && Services.MailService.currentEmail !== null
                    implicitHeight: detailCol.implicitHeight + Theme.spacingM * 2

                    Column {
                        id: detailCol
                        width: parent.width - Theme.spacingM * 2
                        anchors.left: parent.left
                        anchors.top: parent.top
                        anchors.leftMargin: Theme.spacingM
                        anchors.topMargin: Theme.spacingM
                        spacing: Theme.spacingS

                        StyledText {
                            width: parent.width
                            text: Services.MailService.currentEmail ? Services.MailService.currentEmail.subject : ""
                            font.pixelSize: Theme.fontSizeMedium
                            font.weight: Font.Bold
                            color: Theme.surfaceText
                            wrapMode: Text.WordWrap
                        }

                        StyledText {
                            width: parent.width
                            text: Services.MailService.currentEmail ? ("From: " + Services.MailService.currentEmail.fromAddress) : ""
                            font.pixelSize: Theme.fontSizeSmall
                            color: Theme.surfaceVariantText
                            wrapMode: Text.WordWrap
                        }

                        StyledText {
                            width: parent.width
                            text: Services.MailService.currentEmail ? ("To: " + Services.MailService.currentEmail.toAddress) : ""
                            font.pixelSize: Theme.fontSizeSmall
                            color: Theme.surfaceVariantText
                            wrapMode: Text.WordWrap
                        }

                        StyledText {
                            width: parent.width
                            text: Services.MailService.currentEmail ? ("Date: " + Services.MailService.currentEmail.date) : ""
                            font.pixelSize: Theme.fontSizeSmall
                            color: Theme.surfaceVariantText
                            wrapMode: Text.WordWrap
                        }

                        Column {
                            width: parent.width
                            spacing: Theme.spacingXS
                            visible: Services.MailService.currentEmail && Services.MailService.currentEmail.attachments.length > 0

                            StyledText {
                                width: parent.width
                                text: "Attachments"
                                font.pixelSize: Theme.fontSizeSmall
                                font.weight: Font.Bold
                                color: Theme.surfaceVariantText
                            }

                            Repeater {
                                model: Services.MailService.currentEmail ? Services.MailService.currentEmail.attachments : []

                                delegate: Rectangle {
                                    width: parent.width
                                    implicitHeight: 34
                                    radius: Theme.cornerRadius
                                    color: attachmentMouse.containsMouse ? Theme.surfaceContainerHighest : Theme.surfaceContainerHigh
                                    border.color: Qt.rgba(Theme.outline.r, Theme.outline.g, Theme.outline.b, 0.4)
                                    border.width: 1

                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: Theme.spacingS
                                        anchors.rightMargin: Theme.spacingS
                                        spacing: Theme.spacingS

                                        DankIcon {
                                            name: "attach_file"
                                            size: 16
                                            color: Theme.primary
                                        }

                                        StyledText {
                                            Layout.fillWidth: true
                                            text: modelData.name || "attachment"
                                            font.pixelSize: Theme.fontSizeSmall
                                            color: Theme.surfaceText
                                            elide: Text.ElideRight
                                        }

                                        StyledText {
                                            text: modelData.size ? Math.ceil(modelData.size / 1024) + " KB" : ""
                                            font.pixelSize: 10
                                            color: Theme.surfaceVariantText
                                        }
                                    }

                                    MouseArea {
                                        id: attachmentMouse
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: Services.MailService.openAttachment(modelData.path || "")
                                    }
                                }
                            }
                        }

                        Rectangle {
                            width: parent.width
                            radius: Theme.cornerRadius
                            color: Theme.surfaceContainerHigh
                            implicitHeight: Math.min(420, Math.max(120, mailBody.implicitHeight + Theme.spacingM * 2))

                            DankFlickable {
                                anchors.fill: parent
                                anchors.margins: Theme.spacingM
                                contentWidth: width
                                contentHeight: mailBody.implicitHeight
                                clip: true

                                StyledText {
                                    id: mailBody
                                    width: parent.width
                                    text: Services.MailService.currentEmail ? Services.MailService.currentEmail.body : ""
                                    font.pixelSize: Theme.fontSizeSmall
                                    color: Theme.surfaceText
                                    wrapMode: Text.Wrap
                                }
                            }
                        }
                    }
                }

                // footer
                Item {
                    width: parent.width
                    height: 28
                    visible: !root.detailMode

                    StyledText {
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        text: {
                            var t = Services.MailService.lastChecked;
                            if (!t)
                                return "";
                            var diff = Math.max(0, Math.floor((Date.now() - t.getTime()) / 1000));
                            if (diff < 60)
                                return "Checked just now";
                            return "Checked " + Math.floor(diff / 60) + "m ago";
                        }
                        font.pixelSize: 10
                        color: Theme.surfaceVariantText
                    }

                    Rectangle {
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        width: 28
                        height: 28
                        radius: 14
                        color: settingsMouse.containsMouse ? Theme.surfaceContainerHigh : "transparent"

                        DankIcon {
                            anchors.centerIn: parent
                            name: "settings"
                            size: 14
                            color: Theme.surfaceText
                        }

                        MouseArea {
                            id: settingsMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: PopoutService.openSettingsWithTab("Plugins")
                        }
                    }
                }
            }
        }
    }
}
