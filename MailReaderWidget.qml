import QtQuick
import qs.Common
import qs.Widgets
import qs.Modules.Plugins
import "./services" as Services

PluginComponent {
    id: root

    readonly property int unread: Services.MailService.unreadCount
    readonly property bool hasMail: Services.MailService.ok && unread > 0
    readonly property bool hasError: Services.MailService.configured && !Services.MailService.ok && Services.MailService.lastError.length > 0

    Component.onCompleted: applySettings()
    onPluginDataChanged: applySettings()

    function applySettings() {
        var displayLimit = pluginData.displayLimit !== undefined
                ? parseInt(pluginData.displayLimit) : 20;
        if (isNaN(displayLimit) || displayLimit < 0)
            displayLimit = 20;
        var pollInterval = pluginData.pollInterval !== undefined
                ? parseInt(pluginData.pollInterval) : 60;
        if (isNaN(pollInterval) || pollInterval < 0)
            pollInterval = 60;

        Services.MailService.configure({
            accountName: pluginData.accountName || "",
            imapHost: pluginData.imapHost || "",
            imapPort: pluginData.imapPort || "",
            security: pluginData.security || "ssl",
            username: pluginData.username || "",
            passwordCommand: pluginData.passwordCommand || "",
            folder: pluginData.folder || "INBOX",
            displayLimit: displayLimit,
            pollInterval: pollInterval,
            notifyOnNew: pluginData.notifyOnNew !== false,
            notifyOnStartup: pluginData.notifyOnStartup !== false,
            persistentNotification: pluginData.persistentNotification !== false
        });
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
                    name: root.hasError ? "mail_off" : (root.hasMail ? "mail" : "drafts")
                    size: Theme.iconSize - 6
                    color: root.hasError ? Theme.error : (root.hasMail ? Theme.primary : Theme.surfaceText)
                }

                Rectangle {
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.rightMargin: -2
                    anchors.topMargin: -2
                    width: 8
                    height: 8
                    radius: 4
                    color: Theme.primary
                    visible: root.hasMail
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
                    name: root.hasError ? "mail_off" : (root.hasMail ? "mail" : "drafts")
                    size: Theme.iconSize - 6
                    color: root.hasError ? Theme.error : (root.hasMail ? Theme.primary : Theme.surfaceText)
                }

                Rectangle {
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.rightMargin: -2
                    anchors.topMargin: -2
                    width: 8
                    height: 8
                    radius: 4
                    color: Theme.primary
                    visible: root.hasMail
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
