import QtQuick
import qs.Common
import qs.Widgets
import qs.Modules.Plugins
import "./services" as Services

PluginComponent {
    id: root

    readonly property int unread: Services.MailService.unreadCount
    readonly property bool hasMail: unread > 0
    readonly property bool hasError: Services.MailService.configured && !Services.MailService.ok && Services.MailService.lastError.length > 0

    Component.onCompleted: applySettings()
    onPluginDataChanged: applySettings()

    function applySettings() {
        var s = Services.MailService;
        s.accountName = pluginData.accountName || "";
        s.imapHost = pluginData.imapHost || "";
        s.imapPort = pluginData.imapPort || "";
        s.security = pluginData.security || "ssl";
        s.username = pluginData.username || "";
        s.passwordCommand = pluginData.passwordCommand || "";
        s.folder = pluginData.folder || "INBOX";
        s.displayLimit = pluginData.displayLimit !== undefined ? parseInt(pluginData.displayLimit) : 20;
        if (isNaN(s.displayLimit) || s.displayLimit < 0)
            s.displayLimit = 20;
        s.pollInterval = pluginData.pollInterval !== undefined ? parseInt(pluginData.pollInterval) : 60;
        if (isNaN(s.pollInterval) || s.pollInterval < 0)
            s.pollInterval = 60;
        s.notifyOnNew = pluginData.notifyOnNew !== false;
    }

    horizontalBarPill: Component {
        Row {
            spacing: Theme.spacingXS

            Item {
                width: Theme.iconSize - 6
                height: Theme.iconSize - 6
                anchors.verticalCenter: parent.verticalCenter

                DankIcon {
                    anchors.centerIn: parent
                    name: root.hasMail ? "mail" : "drafts"
                    size: Theme.iconSize - 6
                    color: root.hasMail ? Theme.primary : Theme.surfaceText
                }

                Rectangle {
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.rightMargin: -2
                    anchors.topMargin: -2
                    width: 8
                    height: 8
                    radius: 4
                    color: root.hasError ? Theme.error : Theme.primary
                    visible: root.hasMail || root.hasError
                }
            }

            StyledText {
                visible: root.hasMail
                text: root.unread
                font.pixelSize: Theme.fontSizeSmall
                font.weight: Font.Bold
                color: Theme.primary
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }

    verticalBarPill: Component {
        Column {
            spacing: Theme.spacingXS

            Item {
                width: Theme.iconSize - 6
                height: Theme.iconSize - 6
                anchors.horizontalCenter: parent.horizontalCenter

                DankIcon {
                    anchors.centerIn: parent
                    name: root.hasMail ? "mail" : "drafts"
                    size: Theme.iconSize - 6
                    color: root.hasMail ? Theme.primary : Theme.surfaceText
                }

                Rectangle {
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.rightMargin: -2
                    anchors.topMargin: -2
                    width: 8
                    height: 8
                    radius: 4
                    color: root.hasError ? Theme.error : Theme.primary
                    visible: root.hasMail || root.hasError
                }
            }

            StyledText {
                visible: root.hasMail
                text: root.unread
                font.pixelSize: Theme.fontSizeSmall
                font.weight: Font.Bold
                color: Theme.primary
                anchors.horizontalCenter: parent.horizontalCenter
            }
        }
    }

    popoutContent: Component {
        MailReaderPopout {
            maxPopoutHeight: root.popoutHeight
        }
    }
    popoutWidth: 420
    popoutHeight: {
        var h = 220 + Services.MailService.messages.length * 56;
        return Math.min(640, Math.max(280, h));
    }

    ccWidgetIcon: "mail"
    ccWidgetPrimaryText: "Mail"
    ccWidgetSecondaryText: {
        if (!Services.MailService.configured)
            return "Not configured";
        if (root.hasError)
            return "Error";
        return root.unread > 0 ? root.unread + " unread" : "No unread mail";
    }
    ccWidgetIsActive: root.hasMail
    ccWidgetIsToggle: false
    ccDetailHeight: 500
    ccDetailContent: Component {
        MailReaderPopout {
            maxPopoutHeight: root.ccDetailHeight
        }
    }
}
