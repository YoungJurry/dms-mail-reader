import QtQuick
import qs.Common
import qs.Modules.Plugins
import qs.Widgets

PluginSettings {
    id: root
    pluginId: "mailReader"

    StyledText {
        width: parent.width
        text: "Mail Reader"
        font.pixelSize: Theme.fontSizeLarge
        font.weight: Font.Bold
        color: Theme.surfaceText
    }

    StyledText {
        width: parent.width
        text: "Lists an IMAP mailbox without changing message state. Opening a message displays its content here and marks it as read on the server."
        font.pixelSize: Theme.fontSizeSmall
        color: Theme.surfaceVariantText
        wrapMode: Text.WordWrap
    }

    StringSetting {
        settingKey: "accountName"
        label: "Account Name"
        description: "Display name for this account (e.g. Personal)"
        defaultValue: ""
        placeholder: "Personal"
    }

    StringSetting {
        settingKey: "imapHost"
        label: "IMAP Host"
        description: "Hostname of your IMAP server"
        defaultValue: ""
        placeholder: "imap.example.com"
    }

    StringSetting {
        settingKey: "imapPort"
        label: "IMAP Port"
        description: "Leave empty for the default port (993 for SSL/TLS, 143 for STARTTLS)"
        defaultValue: ""
        placeholder: "993"
    }

    SelectionSetting {
        settingKey: "security"
        label: "Connection Security"
        description: "How to secure the IMAP connection"
        defaultValue: "ssl"
        options: [
            { label: "SSL/TLS (implicit, port 993)", value: "ssl" },
            { label: "STARTTLS (port 143)", value: "starttls" }
        ]
    }

    StringSetting {
        settingKey: "username"
        label: "Username"
        description: "IMAP login, usually your e-mail address"
        defaultValue: ""
        placeholder: "you@example.com"
    }

    StringSetting {
        settingKey: "passwordCommand"
        label: "Password Command"
        description: "Shell command that prints the password. Use a secret manager such as secret-tool or pass; do not place the password directly in this field."
        defaultValue: ""
        placeholder: "secret-tool lookup service imap account you@example.com"
    }

    StringSetting {
        settingKey: "folder"
        label: "Folder"
        description: "Mailbox folder to check"
        defaultValue: "INBOX"
        placeholder: "INBOX"
    }

    StringSetting {
        settingKey: "displayLimit"
        label: "Display Mail Count"
        description: "How many messages to show. 0 = show all messages, x = show latest x messages."
        defaultValue: "20"
        placeholder: "20"
    }

    SliderSetting {
        settingKey: "pollInterval"
        label: "Check Interval"
        description: "How often to check for new mail in seconds. 0 = no automatic polling; refresh only when opening the widget or pressing refresh."
        defaultValue: 60
        minimum: 0
        maximum: 900
        unit: "sec"
        leftIcon: "schedule"
    }

    ToggleSetting {
        settingKey: "notifyOnNew"
        label: "Notifications"
        description: "Send a desktop notification when new mail arrives"
        defaultValue: true
    }

    ToggleSetting {
        settingKey: "notifyOnStartup"
        label: "Notify on Startup if Unread"
        description: "Notify immediately upon login if there are unread emails from while the computer was off"
        defaultValue: true
    }

    ToggleSetting {
        settingKey: "persistentNotification"
        label: "Persistent Notifications"
        description: "Keep mail notifications on screen until manually closed"
        defaultValue: true
    }
}
