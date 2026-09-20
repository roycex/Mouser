# HLD — Mouser「按键启动程序」高层设计

> 上游：`docs/sa/prd.md`（F-001 ~ F-014）、`docs/requirements.md`（R-001 ~ R-023）
> 支撑：`docs/preprocess/code-overview.md`（扩展点定位表 H）
> 时间：2026-09-19 ｜ 阶段：Design
> 状态：**待用户评审确认**

---

## 1. 一句话方案

新增第四类动作 **`launch:<target_id>`**：目标定义存 `settings.launch_targets`，执行沿用截图功能已验证的 **"hook 线程 emit 信号 → Qt GUI 线程 Popen"** off-thread 范式；核心逻辑全部落在不依赖 Qt 的 `core/program_launcher.py`。

---

## 2. 为什么这么做：从现有三种动作里选"照抄对象"

| 备选 | 为什么不选 / 为什么选 |
|---|---|
| 照抄 **静态按键组合** | ✗ 目标程序路径是**运行时数据**，塞不进 `keys: [VK...]` |
| 照抄 **Engine 内部动作**（`keys: []` + `_dispatch_action` 拦截） | ✗ 需要在 `engine.py` 增加 if 分支，且会绕过统一的 `execute_action` 兜底路径，破坏"四平台一把梭"的对称性 |
| **照抄 `custom:` 参数化前缀 + 截图 off-thread** | ✅ **选它**。理由：(1) `custom:` 已验证"动作 id 自带数据"可行且 UI 兼容（`actionIndexForId`/`isCustomAction` 就是为它写的）；(2) 启动是**慢操作**，必须走截图的 off-thread 范式；(3) 两个机制都是**模块级共享函数**，一次实现即四平台生效，不需要改 `engine.py` |

**核心洞察**：`launch:` 与 `custom:` 在结构上同构（id 自带数据），在**执行代价**上与截图同构（需转线程）。因此最优解是把两者的既有机制**组合**起来，而不是发明第三套。

---

## 3. 架构与数据流

### 3.1 分层图

```
┌─────────────────────────────────────────────────────────────────┐
│ UI 层（Qt GUI 线程）                                             │
│  MousePage.qml ── ActionChip(picked) ── LaunchTargetDialog.qml   │
│        │                                      │                  │
│        └──────────────┬───────────────────────┘                  │
│                       ▼                                          │
│  ui/backend.py  Backend                                          │
│    • _action_label  ← launch: 分支                               │
│    • _compute_all_actions / _compute_action_categories  ← 目标项  │
│    • addLaunchTarget / updateLaunchTarget / removeLaunchTarget   │
│    • browseLaunchTarget                                          │
└───────────────────────────┬──────────────────────────────────────┘
                            │ 读写
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ 配置层（纯逻辑，无 Qt）                                          │
│  core/config.py                                                  │
│    • DEFAULT_CONFIG version 11 → 12                             │
│    • settings.launch_targets: [...]                             │
│    • _migrate() 追加 v12 步                                      │
│  core/program_launcher.py  ★新建                                 │
│    • id 编解码 / 目标校验 / 参数分词 / argv 构造 / launch_target  │
└───────────────────────────┬──────────────────────────────────────┘
                            │ 被 import
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ 执行层（Hook 线程 → GUI 线程）                                   │
│  core/key_simulator.py（模块级，四平台共享）                     │
│    _launch_action_handler / set_launch_action_handler()           │
│    request_launch_action(action_id)   ← execute_action 前置分支   │
│  ui/program_launch.py  ★新建                                     │
│    ProgramLaunchController(QObject)                              │
│      request_action() ──emit──▶ Qt.QueuedConnection ──▶ _handle   │
│                                        │                         │
│                                        ▼                         │
│                            core.program_launcher.launch_target() │
│                                        │                         │
│                                        ▼  subprocess.Popen        │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 按键触发时序（关键路径）

```
用户按下鼠标按钮
  │
  ├─ Hook 线程：core/mouse_hook_*.py 回调
  │    └─ Engine._make_handler → _dispatch_action("launch:t_1a2b")   [engine.py:1056]
  │         └─ 未命中 if/elif → execute_action("launch:t_1a2b")       [engine.py:1068]
  │              └─ key_simulator.execute_action（4 分支同构）
  │                   └─ request_launch_action("launch:t_1a2b")      ★新增，紧随 request_screenshot_action
  │                        └─ _launch_action_handler(...)  ← 同步调用，内部仅 emit
  │                             ProgramLaunchController.request_action()
  │                               └─ self._requestAction.emit(action_id)   ← 跨线程信号，立即返回 ⏱ O(1)
  │  ◀── Hook 线程在此刻已恢复，鼠标不卡 ──
  │
  └─ Qt GUI 线程（事件循环取出排队信号）
       └─ ProgramLaunchController._handle_request(action_id)   @Slot(str)
            ├─ 解析 target_id = "t_1a2b"
            ├─ 从 config 取目标 → 不存在？→ _emit_status("启动目标已失效…") + return
            ├─ validate_target(target) → 不合法？→ _emit_status(具体原因) + return
            ├─ build_launch_argv(target) → [path, *args] 或 _build_macos_open_argv(...)
            ├─ subprocess.Popen(argv, cwd=..., shell=False)   ← 非阻塞，立即返回
            └─ 成功/失败 → _emit_status(...) → backend.statusMessage.emit → 状态栏
```

**为什么这样就不卡**：Hook 线程上只多做了一次 `Signal.emit()`（Qt 排队连接把参数拷进事件队列，O(1) 且无锁竞争 GUI 线程状态）。所有 I/O、解析、`Popen` 都在 GUI 线程，符合 R-010 / R-020。

### 3.3 目标注册 CRUD 时序

```
用户点「新增启动程序…」
  └─ QML LaunchTargetDialog.open()
       ├─ 列出 backend.knownApps（app_catalog 快照）供搜索选择
       ├─ 或点「浏览…」→ backend.browseLaunchTarget() → QFileDialog（照抄 browseForAppProfile:1920-1954）
       ├─ 填名称 / 参数 / 工作目录
       │    └─ 实时校验参数分词与目录存在性 → 内联错误提示（AC-011/AC-012）
       └─ 点「保存」→ backend.addLaunchTarget(payload)
            ├─ core.program_launcher.make_target() 生成 id、规整字段
            ├─ 写入 cfg["settings"]["launch_targets"] → save_config()（原子写）
            ├─ launchTargetsChanged.emit()
            │    ├─ _invalidate_device_dependent_caches()   ← 清 allActions/actionCategories 缓存
            │    └─ deviceLayoutChanged.emit()              ← 触发 QML 重新求值
            └─ statusMessage.emit("已添加启动目标 …")
```

---

## 4. 数据模型

### DM-01：`settings.launch_targets`（全局启动目标注册表）

**位置**：`config.json` → `settings.launch_targets`
**理由**：R-005 要求全局共享；`settings` 段已有 `screenshot_directory`、`actions_ring_use_global` 等全局项先例。

```jsonc
{
  "version": 12,
  "settings": {
    // ...既有字段不动...
    "launch_targets": [
      {
        "id": "t_1758211200000_a3f1",        // str, 唯一, 稳定不变
        "name": "VS Code 工作区",             // str, 用户可见名称, 非空
        "path": "C:/Program Files/Microsoft VS Code/Code.exe",  // str, 绝对路径, 正斜杠规范
        "args": "--new-window --profile work",  // str, 原始文本, 允许空串
        "cwd": "D:/WorkSpace/mouser"            // str, 绝对路径, 允许空串
      }
    ]
  }
}
```

| 字段 | 类型 | 必填 | 约束 | 默认 |
|---|---|---|---|---|
| `id` | `str` | ✅ | `t_` 前缀 + 唯一；生成后不可变 | 自动生成 |
| `name` | `str` | ✅ | 去首尾空白后非空；长度 ≤ 64 | 见 D-06 |
| `path` | `str` | ✅ | 绝对路径；存在性在保存时校验 | — |
| `args` | `str` | ✅ | 原始文本；可为空串；保存时须能通过分词校验 | `""` |
| `cwd` | `str` | ✅ | 绝对路径或空串；非空时须存在 | `""` |

**默认值考量（关键）**：
- `launch_targets` 在 `DEFAULT_CONFIG` 中必须声明为 **`[]`（列表）**，否则 `_validate_types`（`config.py:813-834`）会把用户数据静默重置。
- **不把任何示例目标写进 `DEFAULT_CONFIG`**——那会给所有用户凭空种一个假目标。

### DM-02：启动动作 id

| 项 | 定义 |
|---|---|
| 格式 | `launch:<target_id>`，例如 `launch:t_1758211200000_a3f1` |
| 前缀常量 | `LAUNCH_ACTION_PREFIX = "launch:"` |
| 与 `custom:` 的关系 | 并列，互不干扰；`custom:` 的载荷是组合键语法，`launch:` 的载荷是目标 id |
| 失效判定 | `target_id` 不在 `settings.launch_targets` 中 → 该动作失效 |
| 显示标签 | 优先取目标 `name`；目标不存在时 → `"Launch: <target_id>（已失效）"` 形式（英文 `"Launch: <id> (missing)"`） |
| 与既有哨兵并存 | `none` / `gesture_swipe` / `activate_actions_ring` 语义完全不变 |

**为什么不用 `custom:` 复用**：`custom_action_label`（`key_simulator.py:18-33`）会把载荷按组合键语法 `parse_shortcut_text` 解析并美化（`t_1758...` 会被当键名处理），语义污染严重。新前缀是干净做法。

### DM-03：平台路径形态与启动方式（R-018 的落点）

| 平台 | `app_catalog` 返回的 `path` | 启动方式 | 理由 |
|---|---|---|---|
| Windows | `.exe` **文件** | `Popen([path, *args], cwd=cwd)` | 直接可执行 |
| Linux | 解析后的**真实可执行文件**（`_resolve_linux_exec_path`，`app_catalog.py:769`） | `Popen([path, *args], cwd=cwd)` | 直接可执行 |
| macOS | **`.app` 包目录**（`app_catalog.py:519`） | `Popen(["open", "-a", path, "--args", *args])` | ⚠️ `.app` 是目录，直接 `Popen` 会 `PermissionError`；`open` 走 LaunchServices，是 macOS 的正确语义（Dock 图标、激活行为正确） |
| macOS（非 `.app`，如 `/usr/local/bin/foo`） | 文件 | `Popen([path, *args], cwd=cwd)` | 与 Unix 一致 |
| 其他平台 | — | 由 `key_simulator` 的 `else` stub 兜住，动作不执行 | 保持既有 stub 行为（AC-010） |

**判定规则**（确定性，可单元测试）：
```
_is_macos_bundle(path) := sys.platform == "darwin" and os.path.isdir(path) and path.endswith(".app")
```

> ⚠️ **对 R-018 的修正解读**：需求原文"三平台行为一致"应理解为**用户可感知结果一致**（点按 → 程序启动），而非代码路径一致——因为平台语义客观不同。此结论已在 PRD §3 F-012 与 R-018 核对结论中记录，**需用户在设计评审时确认这一解读**。

### DM-04：启动参数分词规则（D-04 决策）

**决策：不用 `shlex.split`，改用确定性自定义分词器。**

| 方案 | 判定 |
|---|---|
| `shlex.split(text, posix=True)` | ✗ `posix=True` 下反斜杠是转义字符：`--path=C:\foo` → `--path=C:foo`（**Windows 路径被静默破坏**）；`posix=False` 则保留引号，语义更不可预测 |
| 自定义分词器 | ✅ 规则少、无歧义、跨平台一致、易单元测试 |

**规则（共 4 条，稳定可预期）**：

| # | 规则 |
|---|---|
| 1 | 空白字符（空格 / Tab）分隔 token，连续空白视为一个分隔符 |
| 2 | `"..."` 包裹的内容作为一个 token，引号本身不保留；引号内空白不分割 |
| 3 | `'...'` 同规则 2 |
| 4 | **反斜杠 `\` 在任何位置都是普通字符**（不做转义）→ Windows 路径安全 |
| — | 引号内出现同种引号即报错（`LaunchArgsError`）；引号未闭合报错 |

**已知取舍**：规则 4 导致无法在引号内表示引号字符（如 `--msg="say \"hi\""`）。这是**有意接受的限制**，因为：(a) 该场景对本功能极罕见；(b) 可预测性 > 表达力。替代方案（引入 `\"` 转义）会让 `C:\` 的语义重新变得依赖上下文。**需用户在设计评审时确认。**

`parse_launch_args("")` → `[]`（AC-013）。`parse_launch_args("  ")` → `[]`。

### DM-05：动作注册表集成（`allActions` / `actionCategories`）

在既有追加 `__custom__` 的位置，追加 Launch 分类：

**`_compute_action_categories()`（`backend.py:538` 之后）**
```python
result.append({"category": "Launch", "actions": [
    *({"id": launch_action_id(t["id"]), "label": t["name"]} for t in targets),
    {"id": "__launch__", "label": "Add Program…"},
]})
```

**`_compute_all_actions()`（`backend.py:569` 之前）**
```python
for t in targets:
    result.append({"id": launch_action_id(t["id"]), "label": t["name"], "category": "Launch"})
result.append({"id": "__launch__", "label": "Add Program…", "category": "Launch"})
```

**顺序**：`none` 置顶 → 各分类 → `Custom` → **`Launch`**（保持 `__custom__` 位置不变，避免既有下标语义变动）。

**QML 兼容性（已逐项核对 `docs/preprocess/code-overview.md` §D.2）**：

| QML 表达式 | 对 `launch:<id>` | 对 `__launch__` |
|---|---|---|
| `actionLabel: modelData.id === "__custom__" && isCustomAction(...) ? ... : (lm.strings, lm.trAction(modelData.label))` | ✅ 走 else，`trAction("VS Code 工作区")` 查不到 → **原样返回**（`locale_manager.py:1106-1108`） | ✅ 走 else，返回翻译后的 "添加启动程序…" |
| `isCurrent: modelData.id === "__custom__" ? ... : modelData.id === selectedActionId` | ✅ 走 else，与映射 id 直接比较 → 正确高亮 | ✅ 恒为 false（哨兵本身不是已选动作） |
| `actionIndexForId(actionId)` | ✅ 在 `allActions` 中查得到 → 返回正确下标 | ✅ 查得到 |
| `onPicked` | ✅ 直接 `backend.setProfileMapping(...)`，**无需改动** | ❌ **必须新增拦截分支** |

**→ 结论：`launch:<id>` 目标动作零改动即可工作；仅 `__launch__` 哨兵需要在 10 处 `onPicked` 加 3–4 行。**

### DM-06：线程模型契约

| 约束 | 要求 |
|---|---|
| `execute_action` 上下文 | Hook 回调线程 |
| `request_launch_action(action_id)` | **必须同步返回且 O(1)**：只允许一次 `handler(action_id)` 调用，handler 内部只做 `Signal.emit` |
| 禁止 | 在 handler 中做任何文件 I/O、`subprocess`、Qt 控件操作、`sleep`、锁等待 |
| 异常边界 | `request_launch_action` 内部 `try/except Exception` 全捕获并打印（对齐 `request_screenshot_action:72-77`），**绝不让异常穿到 Hook 线程** |
| 排队连接 | `_requestAction.connect(self._handle_request, Qt.ConnectionType.QueuedConnection)` **必须显式指定**，否则默认直连会在 hook 线程执行 |
| 状态回传 | 通过 `status_callback` → `backend.statusMessage.emit`（`main_qml.py:1183` 既有写法） |

### DM-07：国际化条目

| 表 | 位置 | 新增条目 |
|---|---|---|
| `_CATEGORY_TR` | `locale_manager.py:866-887` | `"Launch"` → `zh_CN: "\u542f\u52a8\u7a0b\u5e8f"`（启动程序）／`zh_TW: "\u555f\u52d5\u7a0b\u5f0f"` |
| `_ACTION_TR` | `:892` 起 | `"Add Program…"`、对话框标题 / 字段 / 按钮 / 校验消息 / 状态提示等 |

**关键规则**：目标名称（用户数据）**不进翻译表**，靠 `trAction` 查不到时原样返回的特性透传（AC-019）。

### DM-08：打包一致性（R-023）

| 改动 | 是否需同步 spec |
|---|---|
| 新增 `core/program_launcher.py`、`ui/program_launch.py` | ❌ 由 PyInstaller 依赖分析自动收集（走静态 `import`） |
| 新增 `ui/qml/LaunchTargetDialog.qml` | ❌ `ui/qml` 以**整目录**形式进 `datas` |
| 新 QML 若 `import` 新的 `Qt*` 模块 | ✅ **必须**同步 `QML_IMPORT_TO_QT_LIBS`/`QML_IMPORT_TO_QML_DIRS`（`test_spec_coverage.py:40-64`）+ Windows `_qt_keep`/`_keep_qml`/`_keep_qtquick` + `build_support.LINUX_QT_KEEP` |
| 新增动态/条件导入 | ✅ 必须加 `REQUIRED_HIDDENIMPORTS` 与对应 spec |

**设计约束（强制）**：`LaunchTargetDialog.qml` **只允许** `import QtQuick` / `import QtQuick.Controls.Material` / `import "Theme.js" as Theme` —— 三者均已映射 → spec 与守卫测试全部零改动。

---

## 5. 接口设计（IF-XX）

| 编号 | 接口 | 方向 | 说明 |
|---|---|---|---|
| IF-01 | `core.program_launcher.parse_launch_args(text) -> list[str]` | 纯函数 | DM-04；抛 `LaunchArgsError` |
| IF-02 | `core.program_launcher.launch_target(target) -> tuple[bool, str]` | 纯逻辑 + I/O | 校验 + 构造 argv + `Popen`；返回 `(成功, 消息)`；**不抛异常** |
| IF-03 | `core.program_launcher.validate_target(target) -> str` | 纯函数 | 返回错误消息，空串表示合法 |
| IF-04 | `Backend.browseLaunchTarget() -> dict` | QML → Python | 打开 `QFileDialog`，返回 `{path, name}` 或空 dict |
| IF-05 | `Backend.addLaunchTarget(payload) / updateLaunchTarget(id, payload) / removeLaunchTarget(id)` | QML → Python | CRUD；写盘 + 发信号 + 状态提示 |
| IF-06 | `Backend.launchTargets`（`@Property(list)`）/ `Backend.launchTargetName(actionId) -> str` | Python → QML | 目标列表与标签解析 |
| IF-07 | `core.config` 的 v12 迁移 | 内部 | 追加 `if version < 12:` 步 |
| IF-08 | `core.key_simulator.set_launch_action_handler(handler)` / `request_launch_action(action_id) -> bool` | 模块级 | 四平台共享，对齐截图同族函数 |
| IF-09 | `ui.program_launch.ProgramLaunchController(status_callback, target_provider)` | Qt | `request_action(action_id)` 公开方法供注册 |

详细签名与实现契约见 `docs/design/LLD.md`。

---

## 6. 风险预演（"上线后最可能挂在哪"）

| # | 风险 | 触发场景 | 影响 | 缓解 |
|---|---|---|---|---|
| **RK-01** | **四平台分支漏改** | `key_simulator.py` 的 win32/darwin/linux 三个 `execute_action` 只改了部分 | 某平台按键完全无响应（**直接违反 R-018**） | 任务清单把 3 处改动拆成**独立可勾选任务**并标注行号；Tester 阶段用 `grep` 计数校验 `request_launch_action` 出现次数 ≥ 4（3 处调用 + 1 处定义） |
| **RK-02** | **QML 10 处 `onPicked` 漏改** | 只改了主选择器，忘了水平滚动/滑动方向 | 从该处无法新增目标（已有目标仍可选） | 任务清单逐处列出**行号**；Tester 用脚本统计 `"__launch__"` 在 `MousePage.qml` 中出现次数，必须 ≥ 10 |
| **RK-03** | **队列连接写成默认直连** | `connect()` 未传 `Qt.ConnectionType.QueuedConnection` | `Popen` 在 hook 线程执行 → **鼠标卡顿/卡死**，且可能违反 Qt 线程安全 | LLD 中原样给出带 `QueuedConnection` 的代码；Tester 用源码级 grep 守卫（仿 `test_key_capture_dialog_qml.py` 风格） |
| **RK-04** | **新增配置键类型错误** | `DEFAULT_CONFIG` 里 `launch_targets` 写成 `{}` | `_validate_types` 静默把用户列表重置为 `{}` → **用户注册目标全部消失** | LLD 明确写 `[]`；新增单测 `test_config.py` 风格断言 `isinstance(DEFAULT_CONFIG["settings"]["launch_targets"], list)` |
| **RK-05** | **macOS `.app` 直接 Popen** | 未做 DM-03 分叉 | macOS 上所有从应用清单选的程序**全部启动失败** | DM-03 明确 + 单测覆盖 `_build_argv` 对 `.app` 目录的分叉（用 monkeypatch `sys.platform`/`os.path.isdir`） |
| **RK-06** | **控制器被 GC** | `ProgramLaunchController` 未保存强引用 | 随机时点启动功能失效（"有时候好有时候不好"） | 照抄 `app._mouser_screenshot_controller` 写法，存为 `app._mouser_program_launcher` |
| **RK-07** | **缓存未失效** | 新增目标后 `allActions` 仍返回旧缓存 | 新目标不出现，用户以为没保存成功 | `launchTargetsChanged` → `_invalidate_device_dependent_caches()` + `deviceLayoutChanged.emit()`；照抄 `knownAppsChanged` 惯例（`backend.py:385`） |
| **RK-08** | **目标名含特殊字符破坏 QML** | 名称里含 `"` 或换行 | QML 文本渲染异常 | `make_target()` 中对 `name` 做控制字符剥离 + 长度截断 |
| **RK-09** | **启动参数注入** | 参数里塞 `; rm -rf /` | 无影响（`shell=False` + 列表参数） | 已由 R-019 的 `shell=False` 列表形式天然免疫；LLD 明确禁止 `os.system`/`shell=True` |
| **RK-10** | **Popen 对象被回收产生 ResourceWarning** | 启动后立即丢弃返回对象 | 仅噪音，无功能影响 | 用模块级 `deque(maxlen=16)` 保留引用并清理已退出进程 |
| **RK-11** | **翻译表遗漏** | 只加 `zh_CN` 未加 `zh_TW`，或中文写成明文而非 `\uXXXX` | 繁体用户看到英文；编码风格不一致 | 任务清单要求两套表同时新增；Tester 校验新增行不含非 ASCII 字符 |

---

## 7. 备选方案与取舍（记录了"为什么不那样做"）

### 备选 A：动作 id 内联完整路径（`launch:C:/path/to/app.exe`）
- **优点**：改动最小，约 4 处
- **缺点**：无法携带参数与工作目录（**P0 需求直接不满足**）；程序升级换路径后绑定失效；`config.json` 可读性差
- **结论**：✗ 不满足 R-002 / R-003

### 备选 B：目标注册表放 `profiles.<name>.launch_targets`（per-profile）
- **优点**：与 per-app profile 语义一致
- **缺点**：同一程序要在多个 profile 重复注册；删 profile 时清理逻辑复杂
- **结论**：✗ 用户已确认走全局（R-005）

### 备选 C：把「启动程序」做成 Engine 内部动作（`keys: []` + `_dispatch_action` 拦截）
- **优点**：不用碰 `key_simulator.py` 的四平台分支（**RK-01 直接消失**）
- **缺点**：需要在 `engine.py` 增加 `elif action_id.startswith("launch:")` 分支，并把 `ProgramLaunchController` 注入 Engine；`Engine._dispatch_action` 的 handler 同样在 Hook 线程，仍需 emit 跳线程——**线程问题没消失，只是换了地方**；且 `launch:` 动作无法被 `allActions` 自动收录（因为 `_compute_all_actions` 从 `ACTIONS` 读，Engine 内部动作是靠显式写进 `ACTIONS` 占位的），仍需改 `backend`
- **结论**：✗ 收益（省 3 处改动）小于代价（破坏"执行入口唯一"的对称性 + 仍需改 backend）

### 备选 D：参数用 `shlex.split`
- **结论**：✗ 见 DM-04（Windows 路径被静默破坏）

---

## 8. 自检清单（对照专家工作流 5 问）

| 问题 | 答案 |
|---|---|
| **为什么做** | 现有三类动作都止步于"模拟输入"，无法启动程序；用户需求真实且高频（一键进工作区） |
| **做什么** | 第四类动作 `launch:<target_id>` + 目标注册表 + 选择器集成 + off-thread 执行 + 配置迁移 + 国际化 |
| **怎么做** | 组合既有两大机制：`custom:` 的参数化前缀（id 自带数据）+ 截图的 off-thread handler（线程跳转）；核心逻辑抽到无 Qt 依赖新模块 |
| **最大风险** | RK-01（四平台分支漏改）与 RK-03（队列连接写错）——都在 LLD 里给了原样可抄的代码 + Tester 的 grep 守卫 |
| **怎么验证** | 本机无 PySide6/pytest → 静态验证（`compileall` + 纯逻辑单测 + 源码级 grep 守卫）+ 产出「需用户本机手动验证」清单 |

---

## 9. 设计交付边界

| 项 | 本文档 | `docs/design/LLD.md` | `docs/design/tasks.md` |
|---|---|---|---|
| 内容 | 架构、数据模型、接口清单、风险、备选取舍 | 逐组件签名与实现契约、迁移代码、QML 改动点 | 可勾选任务拆解 + 依赖 + 验收 |
