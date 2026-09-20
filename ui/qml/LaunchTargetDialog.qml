import QtQuick
import QtQuick.Controls.Material
import "Theme.js" as Theme

/*  Modal dialog for registering a program launch target.

    A target is four strings -- program path, display name, launch arguments
    and working directory -- stored globally in settings.launch_targets.  The
    dialog doubles as the target manager: the registered list at the bottom
    edits and deletes entries in place.

    Two entry points for the path: pick an installed application from the
    searchable catalog, or browse the filesystem.  Launch arguments are
    validated on every keystroke so an unclosed quote is reported before the
    user tries to save.  */

Rectangle {
    id: dialog
    readonly property var theme: Theme.palette(uiState.darkMode)
    property var s: lm.strings

    // "" = create mode, non-empty = editing that target id.
    property string targetId: ""
    property string pathText: ""
    property string nameText: ""
    property string argsText: ""
    property string cwdText: ""
    property string errorText: ""
    property string searchText: ""
    property var filteredApps: []

    readonly property bool editing: targetId !== ""

    signal saved(string targetId)
    signal cancelled()

    visible: false
    anchors.fill: parent
    color: "#80000000"
    z: 100
    focus: visible

    Keys.onEscapePressed: dialog.close()

    onVisibleChanged: {
        if (visible)
            dialog.refreshFilter()
    }

    function open() {
        openNew()
    }

    function openNew() {
        dialog.targetId = ""
        dialog.pathText = ""
        dialog.nameText = ""
        dialog.argsText = ""
        dialog.cwdText = ""
        dialog.errorText = ""
        dialog.searchText = ""
        searchField.text = ""
        pathField.text = ""
        nameField.text = ""
        argsField.text = ""
        cwdField.text = ""
        dialog.refreshFilter()
        dialog.visible = true
        pathField.forceActiveFocus()
    }

    function openEdit(id) {
        var targets = backend.launchTargets
        for (var i = 0; i < targets.length; i++) {
            if (targets[i].id !== id)
                continue
            dialog.targetId = targets[i].id
            dialog.pathText = targets[i].path
            dialog.nameText = targets[i].name
            dialog.argsText = targets[i].args
            dialog.cwdText = targets[i].cwd
            dialog.errorText = ""
            dialog.searchText = ""
            searchField.text = ""
            pathField.text = targets[i].path
            nameField.text = targets[i].name
            argsField.text = targets[i].args
            cwdField.text = targets[i].cwd
            dialog.refreshFilter()
            dialog.visible = true
            return
        }
        openNew()
    }

    function close() {
        dialog.visible = false
    }

    // ── installed application catalog ──────────────────────────
    function refreshFilter() {
        var query = dialog.searchText.trim().toLowerCase()
        var apps = backend.knownApps
        var out = []
        for (var i = 0; i < apps.length; i++) {
            if (query === "" || dialog.appMatches(apps[i], query))
                out.push(apps[i])
        }
        dialog.filteredApps = out
    }

    function appMatches(app, query) {
        var candidates = [app.label || "", app.id || "", app.path || ""]
        var aliases = app.aliases || []
        for (var k = 0; k < aliases.length; k++)
            candidates.push(aliases[k])
        for (var c = 0; c < candidates.length; c++) {
            if (String(candidates[c]).toLowerCase().indexOf(query) >= 0)
                return true
        }
        return false
    }

    function applyPath(path) {
        if (!path || path === "")
            return
        dialog.pathText = path
        pathField.text = path
        if (dialog.nameText === "") {
            var suggested = backend.suggestLaunchTargetName(path)
            if (suggested !== "") {
                dialog.nameText = suggested
                nameField.text = suggested
            }
        }
    }

    function browsePath() {
        applyPath(backend.browseLaunchTargetPath())
    }

    function browseCwd() {
        var directory = backend.browseLaunchDirectory()
        if (directory && directory !== "") {
            dialog.cwdText = directory
            cwdField.text = directory
        }
    }

    // ── save / delete ──────────────────────────────────────────
    function save() {
        dialog.errorText = ""
        var argError = backend.validateLaunchArgs(dialog.argsText)
        if (argError !== "") {
            dialog.errorText = argError
            return
        }
        var problem = backend.validateLaunchTarget(
                    dialog.pathText, dialog.nameText,
                    dialog.argsText, dialog.cwdText)
        if (problem !== "") {
            dialog.errorText = problem
            return
        }
        var id = dialog.editing
                ? backend.updateLaunchTarget(dialog.targetId, dialog.pathText,
                                             dialog.nameText, dialog.argsText,
                                             dialog.cwdText)
                : backend.addLaunchTarget(dialog.pathText, dialog.nameText,
                                          dialog.argsText, dialog.cwdText)
        if (id === "") {
            dialog.errorText = s["launch_target.save_failed"]
            return
        }
        dialog.saved(id)
        dialog.close()
    }

    function removeTarget(id) {
        if (!backend.removeLaunchTarget(id))
            return
        if (id === dialog.targetId)
            dialog.close()
    }

    // Block clicks from reaching elements underneath
    MouseArea { anchors.fill: parent; onClicked: {} }

    Rectangle {
        id: panel
        width: 660
        height: 566
        anchors.centerIn: parent
        radius: 16
        color: dialog.theme.bgCard
        border.width: 1
        border.color: dialog.theme.border

        readonly property int pad: 24

        Text {
            id: title
            anchors { left: parent.left; top: parent.top; margins: panel.pad }
            text: dialog.editing ? s["launch_target.title_edit"]
                                 : s["launch_target.title_new"]
            font { family: uiState.fontFamily; pixelSize: 16; bold: true }
            color: dialog.theme.textPrimary
        }

        Row {
            id: content
            anchors {
                left: parent.left; right: parent.right; top: title.bottom
                leftMargin: panel.pad; rightMargin: panel.pad; topMargin: 14
            }
            height: 300
            spacing: 18

            // ── left: installed applications ───────────────────
            Column {
                width: 250
                height: parent.height
                spacing: 8

                Text {
                    text: s["launch_target.installed"]
                    font { family: uiState.fontFamily; pixelSize: 11; bold: true }
                    color: dialog.theme.textSecondary
                }

                TextField {
                    id: searchField
                    width: parent.width
                    height: 34
                    placeholderText: s["launch_target.search"]
                    font { family: uiState.fontFamily; pixelSize: 12 }
                    selectByMouse: true
                    inputMethodHints: Qt.ImhNoPredictiveText
                    Material.accent: dialog.theme.accent
                    onTextChanged: {
                        dialog.searchText = text
                        dialog.refreshFilter()
                    }
                }

                Rectangle {
                    width: parent.width
                    height: parent.height - y
                    radius: 10
                    color: dialog.theme.bgInput
                    border.width: 1
                    border.color: dialog.theme.border

                    ListView {
                        id: appList
                        anchors.fill: parent
                        anchors.margins: 4
                        clip: true
                        spacing: 2
                        model: dialog.filteredApps

                        delegate: Rectangle {
                            width: appList.width
                            height: 34
                            radius: 6
                            color: appRow.containsMouse ? dialog.theme.bgSubtle
                                                        : "transparent"

                            Row {
                                anchors {
                                    left: parent.left; right: parent.right
                                    verticalCenter: parent.verticalCenter
                                    leftMargin: 8; rightMargin: 8
                                }
                                spacing: 8

                                Image {
                                    width: 20
                                    height: 20
                                    anchors.verticalCenter: parent.verticalCenter
                                    source: modelData.iconSource || ""
                                    visible: (modelData.iconSource || "") !== ""
                                    fillMode: Image.PreserveAspectFit
                                }

                                Text {
                                    width: parent.width - 28
                                    text: modelData.label || ""
                                    elide: Text.ElideRight
                                    font { family: uiState.fontFamily; pixelSize: 12 }
                                    color: dialog.theme.textPrimary
                                }
                            }

                            MouseArea {
                                id: appRow
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: dialog.applyPath(modelData.path || "")
                            }
                        }
                    }
                }
            }

            // ── right: target fields ───────────────────────────
            Column {
                width: content.width - 250 - content.spacing
                height: parent.height
                spacing: 8

                Text {
                    text: s["launch_target.path"]
                    font { family: uiState.fontFamily; pixelSize: 11; bold: true }
                    color: dialog.theme.textSecondary
                }

                Row {
                    width: parent.width
                    spacing: 8

                    TextField {
                        id: pathField
                        width: parent.width - browsePathButton.width - parent.spacing
                        height: 34
                        font { family: uiState.fontFamily; pixelSize: 12 }
                        selectByMouse: true
                        inputMethodHints: Qt.ImhNoPredictiveText
                        Material.accent: dialog.theme.accent
                        onTextChanged: dialog.pathText = text
                        onAccepted: dialog.save()
                    }

                    Rectangle {
                        id: browsePathButton
                        width: 96
                        height: 34
                        radius: 10
                        color: browsePathMa.containsMouse ? dialog.theme.bgSubtle
                                                          : "transparent"
                        border.width: 1
                        border.color: dialog.theme.border

                        Text {
                            anchors.centerIn: parent
                            text: s["launch_target.browse"]
                            font { family: uiState.fontFamily; pixelSize: 11 }
                            color: dialog.theme.textSecondary
                        }

                        MouseArea {
                            id: browsePathMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: dialog.browsePath()
                        }
                    }
                }

                Text {
                    text: s["launch_target.name"]
                    font { family: uiState.fontFamily; pixelSize: 11; bold: true }
                    color: dialog.theme.textSecondary
                }

                TextField {
                    id: nameField
                    width: parent.width
                    height: 34
                    font { family: uiState.fontFamily; pixelSize: 12 }
                    selectByMouse: true
                    inputMethodHints: Qt.ImhNoPredictiveText
                    Material.accent: dialog.theme.accent
                    onTextChanged: dialog.nameText = text
                    onAccepted: dialog.save()
                }

                Text {
                    text: s["launch_target.args"]
                    font { family: uiState.fontFamily; pixelSize: 11; bold: true }
                    color: dialog.theme.textSecondary
                }

                TextField {
                    id: argsField
                    width: parent.width
                    height: 34
                    font { family: uiState.fontFamily; pixelSize: 12 }
                    selectByMouse: true
                    inputMethodHints: Qt.ImhNoPredictiveText
                    Material.accent: dialog.theme.accent
                    onTextChanged: {
                        dialog.argsText = text
                        dialog.errorText = backend.validateLaunchArgs(text)
                    }
                    onAccepted: dialog.save()
                }

                Text {
                    width: parent.width
                    text: dialog.errorText
                    wrapMode: Text.WordWrap
                    visible: dialog.errorText !== ""
                    font { family: uiState.fontFamily; pixelSize: 11 }
                    color: "#E5484D"
                }

                Text {
                    text: s["launch_target.cwd"]
                    font { family: uiState.fontFamily; pixelSize: 11; bold: true }
                    color: dialog.theme.textSecondary
                }

                Row {
                    width: parent.width
                    spacing: 8

                    TextField {
                        id: cwdField
                        width: parent.width - browseCwdButton.width - parent.spacing
                        height: 34
                        font { family: uiState.fontFamily; pixelSize: 12 }
                        selectByMouse: true
                        inputMethodHints: Qt.ImhNoPredictiveText
                        Material.accent: dialog.theme.accent
                        onTextChanged: dialog.cwdText = text
                        onAccepted: dialog.save()
                    }

                    Rectangle {
                        id: browseCwdButton
                        width: 96
                        height: 34
                        radius: 10
                        color: browseCwdMa.containsMouse ? dialog.theme.bgSubtle
                                                         : "transparent"
                        border.width: 1
                        border.color: dialog.theme.border

                        Text {
                            anchors.centerIn: parent
                            text: s["launch_target.choose_cwd"]
                            font { family: uiState.fontFamily; pixelSize: 11 }
                            color: dialog.theme.textSecondary
                        }

                        MouseArea {
                            id: browseCwdMa
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: dialog.browseCwd()
                        }
                    }
                }
            }
        }

        Text {
            id: existingHeading
            anchors {
                left: parent.left; top: content.bottom
                leftMargin: panel.pad; topMargin: 16
            }
            text: s["launch_target.existing"]
            font { family: uiState.fontFamily; pixelSize: 11; bold: true }
            color: dialog.theme.textSecondary
        }

        Rectangle {
            id: existingBox
            anchors {
                left: parent.left; right: parent.right; top: existingHeading.bottom
                leftMargin: panel.pad; rightMargin: panel.pad; topMargin: 8
            }
            height: 92
            radius: 10
            color: dialog.theme.bgInput
            border.width: 1
            border.color: dialog.theme.border

            Text {
                anchors.centerIn: parent
                text: s["launch_target.empty"]
                visible: existingList.count === 0
                font { family: uiState.fontFamily; pixelSize: 11 }
                color: dialog.theme.textDim
            }

            ListView {
                id: existingList
                anchors.fill: parent
                anchors.margins: 4
                clip: true
                spacing: 2
                model: backend.launchTargets

                delegate: Rectangle {
                    width: existingList.width
                    height: 34
                    radius: 6
                    color: rowHover.containsMouse ? dialog.theme.bgSubtle
                                                  : "transparent"

                    MouseArea {
                        id: rowHover
                        anchors.fill: parent
                        hoverEnabled: true
                        acceptedButtons: Qt.NoButton
                    }

                    Text {
                        anchors {
                            left: parent.left; verticalCenter: parent.verticalCenter
                            leftMargin: 8
                        }
                        width: parent.width - editButton.width - deleteButton.width - 32
                        text: modelData.name
                        elide: Text.ElideRight
                        font { family: uiState.fontFamily; pixelSize: 12 }
                        color: dialog.theme.textPrimary
                    }

                    Row {
                        anchors {
                            right: parent.right; verticalCenter: parent.verticalCenter
                            rightMargin: 4
                        }
                        spacing: 4

                        Rectangle {
                            id: editButton
                            width: 56
                            height: 26
                            radius: 8
                            color: editMa.containsMouse ? dialog.theme.bgSubtle
                                                        : "transparent"

                            Text {
                                anchors.centerIn: parent
                                text: s["launch_target.edit"]
                                font { family: uiState.fontFamily; pixelSize: 11 }
                                color: dialog.theme.textSecondary
                            }

                            MouseArea {
                                id: editMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: dialog.openEdit(modelData.id)
                            }
                        }

                        Rectangle {
                            id: deleteButton
                            width: 56
                            height: 26
                            radius: 8
                            color: deleteMa.containsMouse ? dialog.theme.dangerBg
                                                          : "transparent"

                            Text {
                                anchors.centerIn: parent
                                text: s["launch_target.delete"]
                                font { family: uiState.fontFamily; pixelSize: 11 }
                                color: dialog.theme.danger
                            }

                            MouseArea {
                                id: deleteMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: dialog.removeTarget(modelData.id)
                            }
                        }
                    }
                }
            }
        }

        Row {
            anchors {
                right: parent.right; bottom: parent.bottom
                rightMargin: panel.pad; bottomMargin: panel.pad
            }
            spacing: 10

            Rectangle {
                width: 80
                height: 34
                radius: 10
                color: cancelMa.containsMouse ? dialog.theme.bgSubtle : "transparent"

                Text {
                    anchors.centerIn: parent
                    text: s["launch_target.cancel"]
                    font { family: uiState.fontFamily; pixelSize: 12 }
                    color: dialog.theme.textSecondary
                }

                MouseArea {
                    id: cancelMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        dialog.cancelled()
                        dialog.close()
                    }
                }
            }

            Rectangle {
                width: 96
                height: 34
                radius: 10
                visible: dialog.editing
                color: deleteTargetMa.containsMouse ? dialog.theme.dangerBg
                                                    : "transparent"
                border.width: 1
                border.color: dialog.theme.danger

                Text {
                    anchors.centerIn: parent
                    text: s["launch_target.delete"]
                    font { family: uiState.fontFamily; pixelSize: 12 }
                    color: dialog.theme.danger
                }

                MouseArea {
                    id: deleteTargetMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: dialog.removeTarget(dialog.targetId)
                }
            }

            Rectangle {
                width: 96
                height: 34
                radius: 10
                color: saveMa.containsMouse ? dialog.theme.accentHover
                                            : dialog.theme.accent

                Text {
                    anchors.centerIn: parent
                    text: s["launch_target.save"]
                    font { family: uiState.fontFamily; pixelSize: 12; bold: true }
                    color: dialog.theme.accentDim
                }

                MouseArea {
                    id: saveMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: dialog.save()
                }
            }
        }
    }
}
