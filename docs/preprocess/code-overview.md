# Mouser 代码概览（Preprocess 产出）

> 项目根目录：`D:\WorkSpace\mouser\Mouser`
> 项目类型：**独立完整项目**（非补丁项目，无基线项目）→ `baseline.enabled=false`
> 原型：无（PySide6/QML 桌面应用，非 Web 前端）→ 无 `prototype-extraction.md`
> 产出时间：2026-09-19
> 用途：供 SA / Design / Coder 阶段引用，防止"凭空造组件 / 猜错扩展点"

## 0. 技术栈与规模

| 项 | 值 |
|---|---|
| 语言 / 运行时 | Python 3.10+ |
| UI 框架 | PySide6（Qt6）QML 声明式 UI，`ui/qml/*.qml` |
| 入口 | `main_qml.py`（1446 行） |
| 设备通信 | `hid` / `hidraw`（三平台 HID++ 协议） |
| 测试 | 自带 `unittest` 测试集，`tests/` 下 42 个测试文件（无 pytest 依赖） |
| 打包 | PyInstaller，三份 spec：`Mouser.spec` / `Mouser-mac.spec` / `Mouser-linux.spec` |

核心模块行数（本次相关）：

| 文件 | 行数 | 本次角色 |
|---|---|---|
| `core/key_simulator.py` | 1882 | **动作注册表 + 执行入口（四平台分支）** |
| `core/config.py` | 834 | **配置模型 + 版本迁移** |
| `core/engine.py` | 1644 | Hook → 动作分发 |
| `core/app_catalog.py` | 1040 | **已安装应用发现（可复用）** |
| `ui/backend.py` | 2713 | QML ↔ Python 桥 |
| `ui/qml/MousePage.qml` | 2917 | **动作选择器 UI** |
| `ui/locale_manager.py` | 1118 | 国际化 |
| `ui/windows_screenshot.py` | 258 | **off-thread 执行范式模板** |

---

## A. 按键自定义动作集完整链路

### A.1 动作注册表：四平台分支结构（关键事实）

`core/key_simulator.py` 按 `sys.platform` 分成 **4 个互斥分支**，每个分支**各自持有一份 `ACTIONS` 字典与一份 `execute_action()` 实现**：

| 分支 | 起始行 | `ACTIONS` 定义行 | `execute_action` 行 |
|---|---|---|---|
| `if sys.platform == "win32"` | 155 | 428 | 677–703 |
| `elif sys.platform == "darwin"` | 710 | 1077 | 1360 |
| `elif sys.platform == "linux"` | 1387 | 1579 | 1822–1837 |
| `else`（不支持平台 stub） | 1844 | 1856 | 1851（空实现） |

**这意味着：任何新增动作若需要平台相关执行，必须在 4 个分支各写一次；而"跨分支共享"只能通过模块级（分支之外的）函数实现。**

### A.2 跨分支共享逻辑的既有做法

模块级（分支外，位于 1–152 行）定义了所有跨平台共享函数。`execute_action` 的每个分支都以相同顺序调用它们：

```
execute_action(action_id)
  ├─ action_id.startswith("custom:") → _parse_custom_combo() → send_key_combo()   # 参数化前缀动作
  ├─ is_mouse_button_action()        → inject_mouse_down/up()                     # 鼠标按键动作
  ├─ request_screenshot_action()     → 截图 handler（off-thread）                  # ← 本次要照抄的模式
  └─ ACTIONS.get(action_id)["keys"]  → send_key_combo()                           # 静态按键组合
```

对照 `core/key_simulator.py:677-703`（win32）与 `1822-1837`（linux）：**除 `keys` 的具体编码外，四分支的控制流完全同构**。`_parse_custom_combo`（129–148）与 `request_screenshot_action`（66–77）是模块级函数，因此**一次实现即四平台生效**。

### A.3 三类动作的落地方式差异

| 类型 | 形态 | 执行位置 | 示例 |
|---|---|---|---|
| ① 静态按键组合 | `{"label":..., "keys": [VK...], "category":...}` | `execute_action` 末尾 | `volume_mute`、`alt_tab` |
| ② 参数化前缀动作 | 动作 id 自带数据 `custom:<combo>` | `execute_action` 首部分支 | `custom:ctrl+shift+a` |
| ③ Engine 内部动作 | `{"keys": []}` 占位，不在此执行 | `Engine._dispatch_action`（`core/engine.py:1056-1069`） | `switch_scroll_mode`、`toggle_smart_shift`、`cycle_dpi`、`activate_actions_ring`、`cycle_desktops` |

> 类型 ③ 的判定靠 `keys` 为空列表；`_dispatch_action` 用 `if/elif` 逐 id 匹配，未命中则 `execute_action(action_id)` 兜底（`engine.py:1068-1069`）。

### A.4 特殊哨兵值

| 哨兵 | 定义位置 | 语义 |
|---|---|---|
| `none` | `config.py:1877`（各分支 ACTIONS 亦有） | 直通，不拦截 |
| `gesture_swipe` | `config.py:87` `GESTURE_SWIPE_ACTION` | 按钮进入"按住滑动"手势模式 |
| `activate_actions_ring` | 各分支 `ACTIONS` | 激活 Actions Ring 覆盖层（Engine 拦截） |

### A.5 off-thread 执行模式（本次功能的核心复用点）

**问题背景**：`execute_action` 运行在**鼠标 Hook 回调线程**上，任何阻塞都会卡住整只鼠标。

**截图的解法（必须照抄）**——三步：

1. **注册**：模块保存一个 handler 全局变量
   - `core/key_simulator.py:53` `_screenshot_action_handler = None`
   - `:60-63` `set_screenshot_action_handler(handler)`
   - `:66-77` `request_screenshot_action(action_id)` —— 同步调用 handler，内部捕获所有异常并打印，**返回 bool 表示是否已接管**
2. **接线**（`main_qml.py:1178-1215`）：启动时按平台创建 Qt 控制器并把**控制器的方法**注册进去
   ```python
   screenshot_controller = WindowsScreenshotController(
       status_callback=backend.statusMessage.emit,
       path_factory=backend.next_screenshot_file_path,
       parent=app)
   app._mouser_screenshot_controller = screenshot_controller
   set_screenshot_action_handler(screenshot_controller.request_action)
   ```
   （Windows `:1178-1188`、Linux `:1189-1199`、macOS `:1200-1215`）
3. **线程跳转**（`ui/windows_screenshot.py:169-258` `WindowsScreenshotController`）：
   ```python
   _requestAction = Signal(str)                       # :170  私有信号
   self._requestAction.connect(self._handle_request,
                               Qt.ConnectionType.QueuedConnection)  # :184 排队连接
   def request_action(self, action_id):               # :186-187 hook 线程调用，仅 emit
       self._requestAction.emit(action_id)
   @Slot(str)
   def _handle_request(self, action_id): ...          # :189-212 GUI 线程执行真实工作
   def _emit_status(self, message): ...               # :256-258 状态回传
   ```
   **本质上是一次"hook 线程 → Qt GUI 线程"的线程跳转**：`request_action` 只做一次跨线程信号发射（开销极小、不阻塞），所有实际工作（含异常处理与状态提示）在 GUI 线程完成。

> 本次「启动程序」必须复刻这一模式：`request_action` 侧只 emit，真正的 `subprocess.Popen` 在 GUI 线程执行。

---

## B. 事件与分发链路

```
core/mouse_hook.py（平台选择器，75 行）
  └─ core/mouse_hook_windows.py / _macos.py / _linux.py（785 / 668 / 906 行）
       └─ core/mouse_hook_base.py（657 行，共用事件模型与手势识别胶水）
            └─ 回调 → core/engine.py
                 ├─ _setup_hooks()
                 ├─ _make_handler()        # 生成 hook 回调，运行在 Hook 线程
                 └─ _dispatch_action(action_id, source_key)   # engine.py:1056
                       ├─ Engine 内部动作（if/elif 逐 id）
                       └─ execute_action(action_id)  # → core/key_simulator.py
```

**线程约束（本次设计的硬边界）**：handler 在 Hook 回调线程执行 → 不得阻塞、不得做 GUI 调用、不得做文件/进程 I/O。

### `core/config.py` 按钮命名体系

| 常量 | 行号 | 作用 |
|---|---|---|
| `BUTTON_NAMES` | 37–48 | 10 个基础物理按键 → 显示名 |
| `GESTURE_SWIPE_BUTTONS` | 51–56 | 手势按钮四个滑动方向键 |
| `ACTIONS_RING_SWIPE_BUTTONS` | 58–63 | Sense Panel 四个滑动方向键 |
| `SWIPE_SET_FOR_TAP` | 69–72 | tap 键 → 其四个方向键 |
| `GESTURE_SWIPE_ACTION` / `SWIPE_CAPABLE_BUTTONS` / `OS_MOTION_GESTURE_OWNERS` / `NATIVE_GESTURE_BUTTONS` | 87–93 | 手势模式哨兵与能力集 |
| `GESTURE_SWIPE_TAP_KEYS` / `GESTURE_SWIPE_SEED_KEYS` | 106–114 | 需向每个 profile 播种的手势键 |
| `PROFILE_BUTTON_NAMES` | 163–175 | **UI 用的全集**（基础键 + 方向键 + tap 键） |
| `BUTTON_TO_EVENTS` | 181–202 | 按钮键 → MouseEvent 类型映射 |
| `BUTTON_HOLD_EVENTS` | 206–209 | 长按事件（驱动 Actions Ring 覆盖层） |

**按钮 key 命名体系**：`<btn>`（基础）、`<btn>_tap`（手势模式下点按）、`<btn>_<direction>`（左/右/上/下）。共 **10 基础键 + 8 方向键 + 6 tap 键**。

---

## C. 配置模型与兼容机制

| 机制 | 行号 | 行为 |
|---|---|---|
| `CONFIG_DIR` / `CONFIG_FILE` | 14–23 | Windows `%APPDATA%\Mouser\config.json`；macOS `~/Library/Application Support/Mouser/`；Linux `$XDG_CONFIG_HOME/Mouser/` |
| `DEFAULT_CONFIG` | 227–301 | **`"version": 11`**（`settings` 段 266–300） |
| `load_config()` | 347–361 | `json.load` → `_migrate()` → `_merge_defaults()` → `_validate_types()`；异常则回退默认深拷贝 |
| `_migrate(cfg)` | 601–790 | 线性迁移链 `if version < N:`，每步 `cfg["version"] = N`。**当前最后一步是 `version < 11`（726–731）** |
| `_merge_defaults()` | 793–800 | **递归只补缺失键**，不覆盖已有值 |
| `_validate_types()` | 813–834 | 递归比对默认模板类型，不符则**重置为默认值并打印告警** |
| `_atomic_write_json()` | 364–383 | `mkstemp` → `fsync` → `os.replace`；非 Windows 时 `chmod 0600` |
| `set_mapping()` | 439–449 | 写 `profiles.<p>.mappings.<button>` 并落盘 |
| `create_profile()` | 452–464 | 从 `copy_from` 复制 mappings 与 button_haptic |
| `delete_profile()` | 521–529 | 不允许删除 `default` |

### ⚠️ 本次必须注意的迁移陷阱

1. **`_validate_types` 会按默认模板重置类型不符的值** → 新增配置项必须在 `DEFAULT_CONFIG` 里给出**正确类型的默认值**，否则用户数据会被静默重置。例如新增列表项默认必须是 `[]` 而非 `{}`。
2. **`_merge_defaults` 只补缺失键，不补"已存在但为空"** → 迁移逻辑要自己判断。
3. **迁移步必须写在 `_migrate` 的 `return cfg` 之前**，且沿用 `if version < N:` + `cfg["version"] = N` 的既有写法（`version` 变量在 603 行只读取一次，后续步骤依赖前序步骤已更新 `cfg["version"]`，因此**必须顺序追加在链条末尾**）。

### 测试守卫

`tests/test_config.py` 等 4 个测试文件断言 `migrated["version"] == config.DEFAULT_CONFIG["version"]`（`test_config.py:47/102/176/209/273/330/346`、`test_smart_shift.py:945/1007/1047`）——**对照常量而非硬编码 11，因此版本号升级安全**。

---

## D. UI 层（PySide6 + QML）

### D.1 `ui/backend.py` 关键接口

| 接口 | 行号 | 说明 |
|---|---|---|
| `_action_label(action_id)` | 80–85 | 动作 id → 显示标签。**已处理 `custom:` 前缀，是 `launch:` 标签的插入点** |
| `Backend` 类 / 信号区 | 226 / 230–269 | `statusMessage = Signal(str)`（:234）；私有跨线程请求信号族 `_xxxRequest`（:255–269） |
| `_statusMessageRequest` | 262 | 排队信号 → GUI 线程状态提示（:352 连接） |
| `buttons`（缓存属性） | 443–458 | `@Property(list, notify=mappingsChanged)` |
| `_invalidate_device_dependent_caches()` | 488–495 | 一次性清空 `_buttons_cache` / `_action_categories_cache` / `_all_actions_cache` |
| `_hidden_actions()` | 497–506 | 按设备能力隐藏动作（无 `mode_shift` 则藏 `switch_scroll_mode`/`toggle_smart_shift`；darwin 藏 `win_d`/`task_view`） |
| `actionCategories` / `_compute_action_categories()` | 508–541 | 按 category 分组；**末尾固定追加 `{"category": "Custom", "actions": [{"id": "__custom__", ...}]}`（:538–540）** |
| `allActions` / `_compute_all_actions()` | 543–571 | 扁平列表（`none` 置顶）；**末尾追加 `__custom__`（:569–570）** |
| `knownApps` | 1105–1130 | `@Property(list, notify=knownAppsChanged)`；app_catalog 快照 + 图标 |
| `next_screenshot_file_path()` | 1182–1186 | 「计算落盘路径」的既有范式 |
| `setMapping` / `setProfileMapping` | 1483–1489 / 1492–1500 | 写映射 → `reload_mappings()` → 发信号 → `statusMessage.emit("Saved")` |
| `browseForAppProfile()` | 1920–1954 | **现成的 `QFileDialog.getOpenFileName` 三平台分支写法**（可照抄做"浏览程序"） |
| `getProfileMappings(profileName)` | 1972–1993 | 按设备过滤后的映射列表 |
| `actionLabelFor(actionId)` | 1995–1996 | QML 调用 `_action_label` 的出口 |

**缓存失效既有惯例**（`__init__:385`）：`self.knownAppsChanged.connect(self._invalidate_known_apps_cache)` —— 新功能可照此把 `launchTargetsChanged` 接到 `_invalidate_device_dependent_caches` 上。

### D.2 `ui/qml/MousePage.qml` 动作选择器

**页面级 helper 函数**（445–500）：

| 函数 | 行号 | 作用 |
|---|---|---|
| `actionFor(key)` | 445–450 | 取动作显示标签（经 `lm.trAction`） |
| `actionFor_id(key)` | 452–457 | 取动作 id |
| `actionIndexForId(actionId)` | 459–466 | id → `allActions` 下标；**找不到时若 `custom:` 前缀则回退到末尾哨兵下标** |
| `customLabel(actionId)` | 468–471 | `custom:` → `backend.actionLabelFor` |
| `isCustomAction(actionId)` | 473–475 | `startswith("custom:")` |
| `gestureSummary` / `hotspotSublabel` | 477–500 | 手势摘要与热点副标题 |

**`__custom__` 哨兵出现的全部位置（共 10 个 picker 站点）**：

| 站点 | `onPicked` 拦截行 | 按钮 key | `actionIndexForId` 行 |
|---|---|---|---|
| 水平滚动左 | 1346 | `"hscroll_left"` | — |
| 水平滚动右 | 1380 | `"hscroll_right"` | — |
| 滑动 tap 动作 | 1418 | `selectedButton + "_tap"` | 1412 |
| 滑动方向 左 | 1518 | `selectedButton + "_left"` | 1512 |
| 滑动方向 右 | 1553 | `selectedButton + "_right"` | 1547 |
| 滑动方向 上 | 1588 | `selectedButton + "_up"` | 1582 |
| 滑动方向 下 | 1623 | `selectedButton + "_down"` | 1617 |
| **主选择器（分类分组）** | **1702** | `selectedButton` | — |
| 手势模式 tap | 1772 | `gsTapKey` | 1766 |
| Actions Ring 槽位 | 1850 | `modelData.aid` | 1843 |

**单个站点的标准写法**（以 `MousePage.qml:1693-1711` 主选择器为例）：

```qml
delegate: ActionChip {
    actionId: modelData.id
    actionLabel: modelData.id === "__custom__" && isCustomAction(selectedActionId)
                 ? customLabel(selectedActionId)
                 : (lm.strings, lm.trAction(modelData.label))
    isCurrent: modelData.id === "__custom__"
               ? isCustomAction(selectedActionId)
               : modelData.id === selectedActionId
    onPicked: function(aid) {
        if (aid === "__custom__") {                      // ← 唯一需要新增分支的位置
            keyCaptureDialog.open(selectedProfile, selectedButton)
            return
        }
        backend.setProfileMapping(selectedProfile, selectedButton, aid)
        selectedActionId = aid
    }
}
```

**重要结论（设计依据）**：
- `actionLabel` 与 `isCurrent` 两个表达式**天然兼容非哨兵的新动作**（走 `else` 分支即可）
- 新哨兵（如 `__launch__`）**只需在每个站点的 `onPicked` 内加一处拦截**（10 处，每处 3–4 行，机械改动）
- 主选择器用 `actionCategories`（分类 + Flow/ActionChip），其余站点用 `allActions`（扁平）

**对话框实例化**（`MousePage.qml:2905-2916`）：

```qml
KeyCaptureDialog {
    id: keyCaptureDialog
    onCaptured: function(comboString) {
        backend.setProfileMapping(keyCaptureDialog.targetProfile,
                                  keyCaptureDialog.targetButton,
                                  "custom:" + comboString)
        refreshSelectedProfileMappings()
        selectedActionId = "custom:" + comboString
    }
}
```

### D.3 `ui/qml/ActionChip.qml`（53 行）

```qml
Rectangle {
    property string actionId: ""
    property string actionLabel: ""
    property bool isCurrent: false
    signal picked(string aid)          // 唯一对外信号
    // 鼠标点击与 Enter/Space 均触发 picked(actionId)
}
```
传入 `actionId = "__custom__"` 或 `"launch:<tid>"` 即可复用，无需改动。

### D.4 `ui/qml/KeyCaptureDialog.qml`（397 行）——新对话框的范式模板

| 要素 | 行号 | 说明 |
|---|---|---|
| `import QtQuick` / `QtQuick.Controls.Material` / `"Theme.js"` | 1–3 | 所需 import（**均已在 spec 白名单内**） |
| `readonly property var theme: Theme.palette(uiState.darkMode)` | 17 | 主题取用方式 |
| `property var s: lm.strings` | 18 | 国际化字符串表 |
| 传参属性 `targetButton` / `targetProfile` | 20–21 | 由调用方 `open()` 注入 |
| `signal captured(string)` / `signal cancelled()` | 35–36 | 对外结果信号 |
| `visible: false; anchors.fill: parent; color: "#80000000"; z: 100` | 38–41 | **模态遮罩实现方式（不用 Popup，直接铺满 + 半透明 + z 层级）** |
| `function open(profile, button)` | 43–53 | 打开时重置状态并 `visible = true` |
| `function close()` | 55–59 | `visible = false` |

### D.5 `ui/qml/Main.qml` 与主题

- `Main.qml`（707 行）组织页面切换；`ui/qml/Theme.js`（65 行）导出 `Theme.palette(darkMode)`，提供 `accent` / `bgCard` / `bgCardHover` / `textPrimary` / `textDim` / `border` 等色值。
- 新对话框**必须**沿用 `Theme.palette` + `uiState.fontFamily`，否则在深色/浅色切换下会不一致。

---

## E. 国际化

`ui/locale_manager.py`（1118 行）：

| 表 | 行号 | 结构 |
|---|---|---|
| `_BUTTON_TR` | 822–863 | `{lang: {english_button_name: translated}}` |
| `_CATEGORY_TR` | 866–887 | `{lang: {category: translated}}`，现有 8 个分类 |
| `_ACTION_TR` | 892–1088 | `{lang: {exact_english_label: translated}}`，键为 `key_simulator.py`/`backend.py` 返回的**精确英文标签** |

访问器（1090–1113）：

```python
def tr(self, key): ...                                        # :1096
def trButton(self, english_name):
    return _BUTTON_TR.get(self._language, {}).get(english_name, english_name)   # :1101
def trAction(self, english_label):
    return _ACTION_TR.get(self._language, {}).get(english_label, english_label) # :1106
def trCategory(self, english_cat):
    return _CATEGORY_TR.get(self._language, {}).get(english_cat, english_cat)   # :1111
```

**关键结论**：`trAction` 查找失败时**原样返回入参** → 用户自定义的目标名称（如「VS Code 工作区」）会原样透传，不会被翻译破坏。这是把目标名当作动作 label 的可行性依据。

**书写风格**：两套语言表为 `zh_CN` 与 `zh_TW`；中文一律用 `\uXXXX` 转义书写（如 `"\u622a\u56fe"` = 截图），**新增条目必须沿用此风格**。

---

## F. 可复用资产清单（禁止重复造轮子）

### F.1 `core/app_catalog.py` —— 三平台已安装应用发现

| 能力 | 行号 |
|---|---|
| `WINDOWS_APP_SPECS` / `MAC_APP_SPECS` / `ALL_APP_SPECS` | 30 / 267 / 326 |
| `get_app_catalog(refresh=False)` | 865 |
| `resolve_app_spec(spec)` | 996 |
| `get_app_aliases(spec)` / `get_app_label(spec)` / `get_legacy_icon(spec)` | 1026 / 1033 / 1038 |

`entry` 字段（`_make_entry`，:395）：`id`、`label`、`path`、`aliases`、`legacy_icon`。

三平台解析差异：

| 平台 | 发现方式 | `path` 形态 |
|---|---|---|
| Windows | 静态 spec 表 + **注册表 Uninstall 扫描**（`WINDOWS_UNINSTALL_KEYS`:327、`_iter_windows_uninstall_entries`:588）+ 路径 hint 展开（`_expand_windows_path_hint`:534，支持 `*` glob） | `.exe` **文件**路径 |
| macOS | 遍历 `~/Applications`、`/Applications` 等（`_mac_app_dirs`:451）+ 读 `Info.plist`（:482） | **`.app` 包目录**路径（:519 `path=app_path`）⚠️ |
| Linux | 遍历 `*.desktop`（`_iter_linux_desktop_files`:724）+ 解析 `Exec=`（`_extract_linux_exec_command`:741、`_resolve_linux_exec_path`:769） | 解析后的**真实可执行文件**路径 |

> ⚠️ **本次设计的关键约束**：macOS 的 `path` 是目录而非可执行文件，`subprocess.Popen(["/Applications/X.app"])` **会失败**（`PermissionError`/`OSError`）。三平台必须分叉处理。

### F.2 图标获取

| 能力 | 位置 |
|---|---|
| `get_icon_for_exe(exe_name)` → `image://systemicons/<url-encoded-path>` | `core/config.py:325-340` |
| `SystemIconProvider` 图像提供者注册 | `main_qml.py:1220` `qml_engine.addImageProvider("systemicons", SystemIconProvider())` |
| `AppIconProvider`（repo 内置图标） | `main_qml.py:1219` |

### F.3 目录/路径处理范式

| 能力 | 位置 |
|---|---|
| `ui/screenshot_common.py`（104 行） | `screenshots_dir` / `screenshot_file_path` —— "有自定义目录则用之，否则用默认目录"的既有写法 |
| `_normalize_directory_path(path)` | `ui/backend.py:217-225` —— 目录路径规整 |
| `_configured_screenshot_directory()` + `hasCustomScreenshotDirectory` | `ui/backend.py:1182-1192` / `:878` —— 设置项存取范式 |

---

## G. 工程守卫与测试

### G.1 `tests/` 组织

42 个测试文件，全部基于标准库 `unittest`。风格有三种：

1. **行为测试**：直接 import 被测模块并断言（如 `test_config.py`、`test_key_simulator.py`）
2. **源码级守卫测试**：读源码文本并 `assertIn`（如 `test_key_capture_dialog_qml.py` 断言 `KeyCaptureDialog.qml` 含指定字符串；`test_spec_coverage.py` 用 `ast` 解析 spec）
3. **`sys.modules` 打桩测试**：mock 掉硬件/平台依赖

**依赖 PySide6 的测试**（本机无 PySide6 → 不能跑）：
`test_backend.py`、`test_main_qml_shortcuts.py`、`test_main_qml_policy.py`、`test_macos_app_shell.py`、`test_macos_build_script.py`、`test_build_app_icon.py`、`test_locale_manager.py`（部分）

**可脱离 PySide6 运行**（本次可用于回归）：
`test_config.py`、`test_key_simulator.py`、`test_button_gestures.py`、`test_key_registry.py`、`test_key_capture.py`、`test_spec_coverage.py`、`test_build_support.py`、`test_gesture_recognizer.py`、`test_app_detector.py`

### G.2 `tests/test_spec_coverage.py`（374 行）—— 必须同步的守卫

| 校验类 | 行号 | 规则 | 本次是否受影响 |
|---|---|---|---|
| `SpecStructureTests` | 203–245 | 三份 spec 均须 `Analysis(["main_qml.py"])`，`datas` 含 `ui/qml`、`images`、`BUILD_INFO_DATA`；Linux 须打包 `packaging/linux` 全部文件 | **否**（`ui/qml` 整目录打包，新增 QML 文件自动覆盖） |
| `HiddenImportTests` | 248–261 | `REQUIRED_HIDDENIMPORTS`（:30–34）逐平台必须声明 | **否**（`subprocess`/`shlex` 为标准库，PyInstaller 静态可见；不加动态导入即无需改） |
| `ExcludesConsistencyTests` | 264–286 | 任何 spec 都不得 exclude 应用代码实际 import 的模块 | **否** |
| `QmlCoverageTests` | 289–359 | **每个 QML import 必须在 `QML_IMPORT_TO_QT_LIBS`（:40–52）/ `QML_IMPORT_TO_QML_DIRS`（:55–64）中映射**，且 Windows `_qt_keep`/`_keep_qml`/`_keep_qtquick`、Linux `build_support.LINUX_QT_KEEP` 等白名单须覆盖；macOS `UNWANTED_PATTERNS` 不得过滤所需库 | **⚠️ 新增 QML 文件若引入新 `import Qt*` 会直接失败** |
| `RequiredAssetTests` | 362–370 | `REQUIRED_ASSETS`（:77–83）逐项存在 | **否** |

**结论**：本次新增 `ui/qml/LaunchTargetDialog.qml` **只要仅使用 `QtQuick` + `QtQuick.Controls.Material` + `Theme.js`（均已映射），则三份 spec 与 `test_spec_coverage.py` 全部无需改动**。这是最小化打包风险的关键设计约束。

### G.3 打包机制

- 三份 spec：`Mouser.spec`（331 行，Windows）、`Mouser-mac.spec`（317）、`Mouser-linux.spec`（218）
- `build_support.py`（116 行）提供 `LINUX_QT_KEEP` / `LINUX_KEEP_QML_TOP` / `LINUX_KEEP_QTQUICK` 等白名单，被 `test_spec_coverage.py` 引用
- 新增 `core/`、`ui/` 下的**普通 import 模块**由 PyInstaller 依赖分析自动收集，**无需改 spec**

### G.4 基线

`baseline.enabled=false` → 不做基线组件验证。

---

## H. 本次需求扩展点定位表（供 Design 直接引用）

| # | 文件 | 目标位置 | 改动性质 | 风险点 |
|---|---|---|---|---|
| 1 | `core/program_launcher.py` | **新建**（约 260 行） | 纯逻辑：动作 id 编解码、目标校验、参数分词、argv 构造、`Popen` 启动 | 无（新文件，不碰既有代码） |
| 2 | `core/key_simulator.py` | 模块级区（1–152 行内）新增 `_launch_action_handler` / `set_launch_action_handler()` / `request_launch_action()`；**4 个分支的 `execute_action` 各加 1 处前置分支**（:690 前后、:1360 区、:1832 前后、stub 无需） | 仿 `request_screenshot_action` | **4 分支必须同步改**，漏改某平台会导致该平台按键无响应（直接违反 R-018）。`else` stub 分支不需要改（不支持平台） |
| 3 | `core/config.py` | `DEFAULT_CONFIG`（:228 `version` → 12；:266–300 `settings` 增 `launch_targets`）；`_migrate()` 末尾追加 `if version < 12:` 步（:731 之后、:790 `return cfg` 之前） | 迁移 | **新增键默认值类型必须正确**，否则 `_validate_types` 静默重置；迁移步必须顺序追加 |
| 4 | `core/engine.py` | `_dispatch_action`（:1056-1069）**无需改动**（`launch:` 走 `else` → `execute_action` 兜底） | 无改动 | 无 |
| 5 | `ui/program_launch.py` | **新建**（约 70 行） | `ProgramLaunchController(QObject)`，照抄 `ui/windows_screenshot.py:169-258` 的排队信号范式；**跨平台单控制器**（不像截图那样分三份） | 必须用 `Qt.ConnectionType.QueuedConnection`，否则仍在 hook 线程执行 |
| 6 | `ui/backend.py` | `_action_label()`（:80-85）增 `launch:` 分支；`_compute_action_categories()`（:538 后）与 `_compute_all_actions()`（:569 前）追加 Launch 分类与目标项；新增 `launchTargetsChanged` 信号并在 `__init__` 接到 `_invalidate_device_dependent_caches`；新增 CRUD slots（add/update/remove/browseLaunchTarget 等） | 扩展 | `allActions`/`actionCategories` 的 notify 是 `deviceLayoutChanged`，**新增信号必须显式触发失效 + 发 `deviceLayoutChanged`**，否则 QML 列表不刷新 |
| 7 | `ui/qml/LaunchTargetDialog.qml` | **新建**（约 380 行） | 照抄 `KeyCaptureDialog.qml` 的模态范式 | 只能用已映射的 QML import（见 G.2） |
| 8 | `ui/qml/MousePage.qml` | **10 处 `onPicked`**（:1346/1380/1418/1518/1553/1588/1623/1702/1772/1850）各加 3–4 行拦截；`actionIndexForId`（:459-466）加 `launch:` 失效回退；实例化 `LaunchTargetDialog`（:2905 旁） | 机械扩展 | **本次唯一有回归风险的改动**：10 处必须全改，漏改则从该处无法新增目标。缓解：改动完全同构，可用 grep 计数校验 |
| 9 | `ui/locale_manager.py` | `_CATEGORY_TR`（:866-887）加 `"Launch"`；`_ACTION_TR`（:892 起）加分类/对话框文案 | 新增条目 | 两套语言（`zh_CN`+`zh_TW`）都要加；中文必须用 `\uXXXX` 风格 |
| 10 | `main_qml.py` | 在截图接线块（:1178-1215）之后新增启动控制器接线（**三平台共用一份**，无需 `if sys.platform` 分叉） | 仿写 | 需保存强引用（仿 `app._mouser_screenshot_controller`），否则被 GC |
| 11 | 三份 `.spec` + `tests/test_spec_coverage.py` | **无需改动**（前提：新 QML 不引入新 import；新 Python 模块走静态 import） | 无改动 | 若违反前提，`QmlCoverageTests.test_every_qml_import_is_mapped` 会失败 |
| 12 | 新增测试 | `tests/test_program_launcher.py`（纯逻辑，可跑）、`tests/test_launch_target_dialog_qml.py`（源码级守卫，可跑） | 新增 | 本机无 pytest，但 `unittest` 可直接跑 |

---

## I. 与 `docs/requirements.md` 的冲突/实现风险核对

| 需求 | 核对结论 |
|---|---|
| R-001 | ✅ 可复用 `app_catalog.get_app_catalog()` + `backend.browseForAppProfile` 的 `QFileDialog` 三平台写法 |
| R-002 / R-003 | ✅ 纯数据模型，无技术障碍 |
| R-005 | ✅ `settings` 段现有 `actions_ring_use_global` / `screenshot_directory` 等全局项先例 |
| R-007 | ✅ `PROFILE_BUTTON_NAMES` 覆盖全部可配置键；`launch:` 是普通动作 id，天然可绑任意按钮 |
| R-010 | ✅ 照抄截图 off-thread 范式 |
| R-015 | ✅ 迁移链写法明确；测试对照常量，版本升级安全 |
| R-016 | ⚠️ **存在实现分歧**：`actionIndexForId` 找不到 id 会返回 0（显示为 "Do Nothing"）。需在设计中明确"失效目标"的 UI 表达方式（详见 Design 的 D-07 决策） |
| R-018 | ⚠️ **存在真实平台差异（必须处理）**：macOS `app_catalog` 返回 `.app` **目录**，不能直接 `Popen`；Linux 返回真实可执行文件；Windows 返回 `.exe`。三平台启动方式必须分叉 → "行为一致"应理解为**用户可感知结果一致（点按后程序启动）**，而非代码路径一致 |
| R-019 | ✅ `subprocess.Popen([...], shell=False)` 满足 |
| R-022 | ✅ 核心逻辑放 `core/program_launcher.py`，不 import Qt |
| R-023 | ✅ 无需改 spec（前提见 G.2） |

**原型提取清单**：本项目不适用（无 HTML 原型）。

---

## 附：关键文件行号速查

```
core/key_simulator.py    53/60/66     _screenshot_action_handler / set_ / request_
                         129-148      _parse_custom_combo
                         155/710/1387/1844   四平台分支
                         677-703/1360/1822-1837/1851  execute_action
core/config.py           228           "version": 11
                         266-300       settings 段
                         601-790       _migrate（末尾 726-731 为 v11 步）
                         793-834       _merge_defaults / _validate_types
core/engine.py           1056-1069     _dispatch_action
core/app_catalog.py      519           macOS path = .app 目录  ⚠️
                         865/996/1026/1033/1038   catalog / resolve / aliases / label / icon
ui/backend.py            80-85         _action_label
                         488-495       _invalidate_device_dependent_caches
                         538-540/569-570   哨兵追加点
                         1920-1954     browseForAppProfile（QFileDialog 范式）
ui/qml/MousePage.qml     459-475       actionIndexForId / customLabel / isCustomAction
                         10 处 onPicked  :1346 1380 1418 1518 1553 1588 1623 1702 1772 1850
                         2905-2916     KeyCaptureDialog 实例化
ui/windows_screenshot.py 169-258       off-thread 控制器范式模板
ui/locale_manager.py     866-887 / 892-1088 / 1106-1113   _CATEGORY_TR / _ACTION_TR / trAction
main_qml.py              1178-1215     截图控制器接线
tests/test_spec_coverage.py  40-52/55-64/289-359    QML import 映射守卫
```
