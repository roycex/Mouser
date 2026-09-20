# LLD — Mouser「按键启动程序」详细设计

> 上游：`docs/design/HLD.md`（DM-01 ~ DM-08、IF-01 ~ IF-09）
> 时间：2026-09-19 ｜ 阶段：Design ｜ 状态：**待用户评审确认**
> 行号基准：`docs/preprocess/code-overview.md` 记录的行号（改动前）

---

## 组件清单

| 组件 | 文件 | 类型 | 预估规模 |
|---|---|---|---|
| COMP-01 | `core/program_launcher.py` | 🆕 新建 | ~270 行 |
| COMP-02 | `core/key_simulator.py` | 🔧 补丁（1 处定义 + 3 处调用） | ~30 行 |
| COMP-03 | `core/config.py` | 🔧 补丁（默认值 + 迁移步） | ~20 行 |
| COMP-04 | `ui/program_launch.py` | 🆕 新建 | ~90 行 |
| COMP-05 | `ui/backend.py` | 🔧 补丁（标签 + 列表 + CRUD + 信号） | ~110 行 |
| COMP-06 | `ui/qml/LaunchTargetDialog.qml` | 🆕 新建 | ~400 行 |
| COMP-07 | `ui/qml/MousePage.qml` | 🔧 补丁（10 处 `onPicked` + 2 个 helper） | ~50 行 |
| COMP-08 | `ui/locale_manager.py` | 🔧 补丁（分类 + 文案） | ~40 行 |
| COMP-09 | `main_qml.py` | 🔧 补丁（控制器接线） | ~10 行 |
| COMP-10 | `tests/test_program_launcher.py`、`tests/test_launch_target_dialog_qml.py` | 🆕 新建 | ~230 行 |
| — | 三份 `.spec`、`tests/test_spec_coverage.py` | ⛔ **零改动**（见 DM-08 约束） | — |

---

## COMP-01 `core/program_launcher.py`（新建）

### 职责
启动目标的**纯逻辑**：id 编解码、目标规范化与校验、参数分词、argv 构造、进程启动。
**硬约束：不得 `import` 任何 Qt 模块**（R-022 / AC-017）。

### 模块级常量

```python
LAUNCH_ACTION_PREFIX = "launch:"
LAUNCH_MISSING_PREFIX = "Launch: "          # 失效目标的标签前缀
MAX_TARGET_NAME_LEN = 64

# 参数分词的最大 token 数（防御性上限，防手改配置塞入超长参数）
MAX_ARG_TOKENS = 64


class LaunchArgsError(ValueError):
    """Raised when a launch-args text cannot be tokenized."""
```

### 公开 API（签名即实现契约）

```python
# ── 动作 id 编解码（DM-02）────────────────────────────────────────────
def launch_action_id(target_id: str) -> str:
    """target_id → 'launch:<target_id>'。空 id 返回 ''。"""

def is_launch_action(action_id: str) -> bool:
    """是否 'launch:' 前缀且载荷非空。"""

def launch_target_id(action_id: str) -> str:
    """'launch:t_1' → 't_1'；非 launch 动作返回 ''。"""

def launch_action_label(action_id: str, targets=()) -> str:
    """动作 id → 显示标签（DM-02 表）。
       命中目标 → 目标 name
       未命中   → 'Launch: <target_id> (missing)'   ← 逐字见下方契约
       非 launch 动作 → 原样返回 action_id
    """

# ── 目标模型（DM-01）────────────────────────────────────────────────
def new_target_id() -> str:
    """生成 't_<毫秒时间戳>_<4位十六进制随机>'，如 't_1758211200000_a3f1'。"""

def normalize_name(text: str) -> str:
    """去首尾空白 + 剥离控制字符（含 \\n \\r \\t）+ 截断到 MAX_TARGET_NAME_LEN。"""

def make_target(path, name="", args="", cwd="", target_id=None) -> dict:
    """构造规范化的目标 dict（DM-01 的五字段，全部为 str）。
       - id 缺省则 new_target_id()
       - name 缺省则 name_from_path(path)
       - path/cwd 统一为绝对路径 + 正斜杠（Windows 上把 '\\\\' 换成 '/'）
    """

def name_from_path(path: str) -> str:
    """默认名称（D-06）：先问 app_catalog.resolve_app_spec(path) 要 label；
       拿不到则取 basename 去扩展名；macOS '.app' 去 '.app' 后缀。"""

def validate_target(target: dict) -> str:
    """返回错误消息（英文，供 UI 翻译），空串表示合法（IF-03）。
       校验顺序与消息见下方「校验契约」。"""

def normalize_targets(raw) -> list[dict]:
    """把配置里读到的任意值规整为合法目标列表。
       - raw 不是 list → []
       - 逐项：不是 dict 跳过；缺 id 跳过；缺 path 跳过
       - 去重（同 id 保留首个）
       容错优先：绝不抛异常（配置可能被手工改坏）。
    """

# ── 参数分词（DM-04）─────────────────────────────────────────────────
def parse_launch_args(text: str) -> list[str]:
    """DM-04 的 4 条规则。空/纯空白 → []。非法引号 → raise LaunchArgsError。"""

def format_launch_args(tokens) -> str:
    """反向：token 列表 → 需要引号包裹的文本（对话框回显用）。
       含空白或为空串的 token 用双引号包裹。"""

# ── argv 构造与启动（DM-03 / IF-02）──────────────────────────────────
def is_macos_bundle(path: str, platform: str | None = None) -> bool:
    """DM-03 判定式：platform == 'darwin' and os.path.isdir(path) and path.endswith('.app')"""

def build_launch_argv(target: dict, platform: str | None = None) -> list[str]:
    """按 DM-03 分叉：
       macOS .app  → ["open", "-a", path, "--args", *args]      (args 为空时省略 --args)
       其他        → [path, *args]
    """

def resolve_launch_cwd(target: dict) -> str:
    """D-05：cwd 非空且存在 → 原值；否则 → 程序自身所在目录
       （macOS .app 取包的父目录，因为 .app 内部执行目录语义不同）。"""

def launch_target(target: dict) -> tuple[bool, str]:
    """校验 → 构造 argv → subprocess.Popen → 返回 (成功, 消息)。
       ⚠️ 绝不抛异常（IF-02）。所有异常转成 (False, 原因)。
       ⚠️ shell=False 强制；禁止字符串命令（R-019）。
    """
```

### 校验契约（`validate_target` 的确定性顺序）

| 序 | 条件 | 返回消息（英文原文，进 `_ACTION_TR`/状态提示翻译） |
|---|---|---|
| 1 | `target` 不是 dict | `"Invalid target"` |
| 2 | `path` 为空 | `"Program path is required"` |
| 3 | `path` 非绝对路径 | `"Program path must be absolute"` |
| 4 | `path` 不存在 | `"Program not found: <path>"` |
| 5 | `name` 为空 | `"Name is required"` |
| 6 | `args` 分词失败 | `"Invalid arguments: <分词器原因>"` |
| 7 | `cwd` 非空但不存在 | `"Working directory not found: <cwd>"` |
| — | 全部通过 | `""` |

> 校验**不**检查可执行权限（跨平台语义不一致，且 `Popen` 会给准确报错）。

### 参数分词契约（`parse_launch_args` 具体算法）

```
posix = False; tokens = []; cur = []; quote = None; saw_char = False
for ch in text:
    if quote:                       # 引号内
        if ch == quote: quote = None          # 闭引号，不写入
        else: cur.append(ch)
        saw_char = True
    elif ch in ('"', "'"):          # 开引号
        quote = ch; saw_char = True
    elif ch in (' ', '\t'):         # 分隔符
        if cur or saw_char: tokens.append(''.join(cur)); cur = []
        saw_char = False
    else:
        cur.append(ch); saw_char = True
if quote: raise LaunchArgsError("unclosed quote")           # 未闭合
if cur or saw_char: tokens.append(''.join(cur))
if len(tokens) > MAX_ARG_TOKENS: raise LaunchArgsError("too many arguments")
return tokens
```

**行为样例（同时作为单测用例）**：

| 输入 | 输出 |
|---|---|
| `""` | `[]` |
| `"   "` | `[]` |
| `"--new-window"` | `["--new-window"]` |
| `"--a  --b"` | `["--a", "--b"]`（连续空白合并） |
| `'--path="C:\\Program Files\\x"'` | `["--path=C:\\Program Files\\x"]` ⭐ 反斜杠保住 |
| `'--path=C:\\foo'` | `["--path=C:\\foo"]` ⭐ 反斜杠保住 |
| `'"a b" c'` | `["a b", "c"]` |
| `"''"` | `[""]`（显式空 token） |
| `'"unclosed'` | `raise LaunchArgsError` |
| `'"a"b'` | `["ab"]`（相邻引号与字符拼接） |

### `launch_target` 实现契约

```python
_recent_processes = deque(maxlen=16)     # RK-10：保留引用，避免 ResourceWarning


def _prune_recent():
    while _recent_processes:
        proc = _recent_processes[0]
        if proc.poll() is None:          # 仍在运行 → 停止清理
            break
        _recent_processes.popleft()


def launch_target(target):
    error = validate_target(target)
    if error:
        return False, error
    try:
        argv = build_launch_argv(target)
    except LaunchArgsError as exc:
        return False, f"Invalid arguments: {exc}"

    cwd = resolve_launch_cwd(target) or None
    kwargs = {"shell": False}
    if cwd:
        kwargs["cwd"] = cwd
    if sys.platform != "win32":
        kwargs["start_new_session"] = True   # 脱离 Mouser 的会话

    try:
        _prune_recent()
        _recent_processes.append(subprocess.Popen(argv, **kwargs))
    except FileNotFoundError:
        return False, f"Program not found: {target.get('path', '')}"
    except PermissionError:
        return False, f"Permission denied: {target.get('path', '')}"
    except OSError as exc:
        return False, f"Launch failed: {exc}"
    return True, target.get("name", "")
```

> ⚠️ **禁止**：`shell=True`、`os.system`、字符串拼接命令、`subprocess.call` / `run(...check=True)`（会阻塞 GUI 线程）。
> **注意**：`cwd` 为空时**不传** `cwd` 参数给 `Popen`（`resolve_launch_cwd` 已保证非空时才有意义）。

---

## COMP-02 `core/key_simulator.py`（补丁）

### 2.1 模块级新增（插入 `request_screenshot_action` 之后，约 78 行处）

**严格对齐截图同族函数的写法**：

```python
# ==================================================================
# Program launch helpers (shared across platforms)
# ==================================================================

_launch_action_handler = None


def set_launch_action_handler(handler):
    """Register a callable that launches programs off the hook thread."""
    global _launch_action_handler
    _launch_action_handler = handler


def request_launch_action(action_id):
    """Hand a launch action to the registered controller.

    Runs on the hook thread: the handler must only hand off (Qt queued
    signal) and return immediately.  Returns True when the action was a
    launch action (handled or not), False when it is not ours.
    """
    from core import program_launcher
    if not program_launcher.is_launch_action(action_id):
        return False
    if _launch_action_handler is None:
        print(f"[KeySimulator] launch action unavailable: {action_id}")
        return False
    try:
        _launch_action_handler(action_id)
    except Exception as exc:
        print(f"[KeySimulator] launch action handler failed: {exc}")
        import traceback; traceback.print_exc()
    return True
```

> **为什么 `from core import program_launcher` 放在函数内**：`key_simulator` 是热点模块，且 `program_launcher` 需要 `os`/`subprocess`（Go 无副作用），函数内导入可避免 import 顺序耦合、并保证 `key_simulator` 在无 `program_launcher` 的极端裁剪场景下仍可导入。

### 2.2 三处 `execute_action` 前置分支（RK-01：必须全改）

**位置与插入点**（均紧随 `request_screenshot_action` 之后，保持"越便宜越靠前"的顺序——launch 判定只是一次字符串前缀比较）：

| # | 分支 | 文件行号 | 插入位置 |
|---|---|---|---|
| 1 | `win32` | `690-691` | `if request_screenshot_action(action_id): return` 之后 |
| 2 | `darwin` | `execute_action` @1360 区（同结构） | 同上 |
| 3 | `linux` | `1832-1833` | 同上 |
| 4 | `else` stub | `1851` | ⛔ **不改**（不支持平台，`execute_action` 为空实现，AC-010） |

**插入代码（三处完全一致）**：

```python
            if request_launch_action(action_id):
                return
```

**Tester 校验方式**：
```bash
# 必须输出 4（1 处定义 + 3 处调用）
grep -c "request_launch_action" core/key_simulator.py
```

---

## COMP-03 `core/config.py`（补丁）

### 3.1 `DEFAULT_CONFIG`（`config.py:227-301`）

```python
DEFAULT_CONFIG = {
    "version": 12,                              # ← 11 → 12
    # ...profiles 不动...
    "settings": {
        # ...既有字段不动...
        "launch_targets": [],                   # ← 新增。⚠️ 必须是 [] 而非 {}（RK-04）
    },
}
```

> **不要**在此处放任何示例目标（会污染所有新用户）。
> 位置放在 `settings` 段末尾（`actions_ring_slots` 之后），减少 diff 冲突面。

### 3.2 `_migrate()` 追加 v12 步

**插入位置**：`if version < 11:` 块结束后、`cfg.setdefault("settings", {})`（`config.py:733`）**之前**，即紧接第 731 行之后。

```python
    if version < 12:
        # v11 -> v12: user-registered program launch targets.
        #
        # Targets live in settings (global, shared by every profile) while the
        # button bindings stay per-profile -- same split as
        # screenshot_directory / actions_ring_use_global.  Nothing is seeded:
        # an empty list keeps the feature invisible until the user adds a
        # target, and existing configs are otherwise untouched.
        settings = cfg.setdefault("settings", {})
        if not isinstance(settings.get("launch_targets"), list):
            settings["launch_targets"] = []
        cfg["version"] = 12
```

**为什么用 `if not isinstance(..., list)`**：手改坏的配置里可能是 `{}` 或 `null`；这一层防御保证迁移后类型一定正确，避免后续 `_validate_types` 之外的隐式错误。

### 3.3 类型安全自检（新增单测，见 COMP-10）

```python
def test_launch_targets_default_is_list(self):
    self.assertIsInstance(config.DEFAULT_CONFIG["settings"]["launch_targets"], list)
    self.assertEqual(config.DEFAULT_CONFIG["settings"]["launch_targets"], [])

def test_v11_config_migrates_to_v12_without_losing_data(self):
    old = {"version": 11, "settings": {"dpi": 1234}, "profiles": {...}}
    migrated = config._migrate(copy.deepcopy(old))
    self.assertEqual(migrated["version"], config.DEFAULT_CONFIG["version"])
    self.assertEqual(migrated["settings"]["launch_targets"], [])
    self.assertEqual(migrated["settings"]["dpi"], 1234)   # 既有值不被改
```

---

## COMP-04 `ui/program_launch.py`（新建）

照抄 `ui/windows_screenshot.py:169-258` 的控制器骨架。**与截图不同：跨平台单控制器，不需要三份。**

```python
"""Program launch controller for Mouser.

The mouse hook can invoke actions from a non-Qt thread.  This module exposes a
Qt controller whose public request method only emits a queued signal; the actual
subprocess launch then runs on the GUI thread, so the hook thread never blocks
while an application starts up.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Qt, Signal, Slot

from core.program_launcher import launch_target


class ProgramLaunchController(QObject):
    _requestAction = Signal(str)

    def __init__(
        self,
        status_callback: Callable[[str], None] | None = None,
        target_provider: Callable[[str], dict | None] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._status_callback = status_callback
        self._target_provider = target_provider
        # Queued delivery is load-bearing: without it the launch would run on
        # the mouse-hook thread and stall the pointer.  See HLD DM-06.
        self._requestAction.connect(
            self._handle_request, Qt.ConnectionType.QueuedConnection)

    def request_action(self, action_id: str) -> None:
        """Hook-thread entry point -- emits only, never launches inline."""
        self._requestAction.emit(action_id)

    @Slot(str)
    def _handle_request(self, action_id: str) -> None:
        from core.program_launcher import launch_target_id

        target_id = launch_target_id(action_id)
        if not target_id:
            return
        if self._target_provider is None:
            self._emit_status("Launch target unavailable")
            return
        target = self._target_provider(target_id)
        if not target:
            self._emit_status("Launch target is missing; reassign this button")
            return
        ok, message = launch_target(target)
        if ok:
            self._emit_status(f"Launched {message}")
        else:
            self._emit_status(f"Launch failed: {message}")

    def _emit_status(self, message: str) -> None:
        if self._status_callback is not None:
            self._status_callback(message)
```

**关键契约**：
- `_requestAction` 必须是**私有驼峰信号**（与截图一致）
- `connect(..., Qt.ConnectionType.QueuedConnection)` **不可省**（RK-03）
- `_handle_request` 内 `launch_target()` 全程不抛异常（COMP-01 已保证）
- 顶层 `import launch_target` + 函数内 `import launch_target_id` 均可；为可读性统一顶层导入亦可——**但 `_handle_request` 内不得做阻塞 I/O 之外的额外工作**

---

## COMP-05 `ui/backend.py`（补丁）

### 5.1 新增 import

```python
from core import program_launcher                              # 顶部现有 core 导入区
from core.program_launcher import (                            # 或按现有风格逐个导入
    is_launch_action, launch_action_id, launch_action_label,
    launch_target_id, make_target, normalize_targets,
    validate_target, parse_launch_args, LaunchArgsError, MAX_TARGET_NAME_LEN,
)
```

### 5.2 `_action_label()` 扩展（`backend.py:80-85`）

```python
def _action_label(action_id, launch_targets=()):
    if action_id.startswith("custom:"):
        return custom_action_label(action_id)
    if is_launch_action(action_id):
        return launch_action_label(action_id, launch_targets)
    if action_id == GESTURE_SWIPE_ACTION:
        return "Gesture Swipe"
    return ACTIONS.get(action_id, {}).get("label", "Do Nothing")
```

> 新增可选参数 → **所有既有调用点行为不变**（兼容）。
> 调用方 `actionLabelFor`（`:1995`）改为传 `self._launch_targets()`。

### 5.3 新增信号与初始化连线

```python
    # 信号区（与 knownAppsChanged 等并列）
    launchTargetsChanged = Signal()

    # __init__ 中，紧邻 knownAppsChanged 的连线（backends.py:385 附近）
    self.launchTargetsChanged.connect(self._invalidate_launch_targets)
```

```python
    def _invalidate_launch_targets(self):
        """Targets feed the action list, so drop the action caches and let
        the QML pickers rebind (same idiom as knownAppsChanged)."""
        self._invalidate_device_dependent_caches()
        self.deviceLayoutChanged.emit()
```

### 5.4 目标访问 helper

```python
    def _launch_targets(self):
        """Normalized view of settings.launch_targets (never raises)."""
        raw = self._cfg.get("settings", {}).get("launch_targets", [])
        return normalize_targets(raw)

    def _find_launch_target(self, target_id):
        for target in self._launch_targets():
            if target["id"] == target_id:
                return target
        return None
```

### 5.5 动作列表集成（DM-05）

**`_compute_action_categories()` —— 在 `:538-540` 的 `result.append({"category": "Custom", ...})` 之后追加：**

```python
        launch_actions = [
            {"id": launch_action_id(t["id"]), "label": t["name"]}
            for t in self._launch_targets()
        ]
        launch_actions.append({"id": "__launch__", "label": "Add Program\u2026"})
        result.append({"category": "Launch", "actions": launch_actions})
```

**`_compute_all_actions()` —— 在 `:569-570` 的 `__custom__` append 之前插入目标项，之后追加哨兵：**

```python
        for target in self._launch_targets():
            result.append({"id": launch_action_id(target["id"]),
                           "label": target["name"],
                           "category": "Launch"})
        result.append({"id": "__custom__", "label": "Custom Shortcut\u2026",
                       "category": "Custom"})
        result.append({"id": "__launch__", "label": "Add Program\u2026",
                       "category": "Launch"})
        return result
```

### 5.6 新增 QML slots（放在 `getProfileMappings` / `browseForAppProfile` 附近）

```python
    @Slot(result=str)
    def browseLaunchTargetPath(self):
        """Open a file picker for a program; '' when cancelled.
        Path filter mirrors browseForAppProfile (:1920-1954)."""
        from PySide6.QtWidgets import QFileDialog
        if sys.platform == "darwin":
            f = "Applications (*.app)"
            start = "/Applications"
        elif sys.platform == "linux":
            f = "Applications (*)"          # 或留空，Linux 可执行文件无固定后缀
            start = os.path.expanduser("~")
        else:
            f = "Executables (*.exe)"
            start = os.environ.get("ProgramFiles", "C:\\Program Files")
        path, _ = QFileDialog.getOpenFileName(None, "Select Program", start, f)
        if not path:
            return ""
        return os.path.realpath(path) if sys.platform == "linux" else os.path.normpath(path)

    @Slot(str, result=str)
    def suggestLaunchTargetName(self, path):
        """Default display name for a picked path (D-06)."""
        from core.program_launcher import name_from_path
        return name_from_path(path) if path else ""

    @Slot(str, result=str)
    def launchTargetName(self, actionId):
        """Display name for a launch action id; '' when missing."""
        target = self._find_launch_target(launch_target_id(actionId))
        return target["name"] if target else ""

    @Slot(str, result=str)
    def validateLaunchTarget(self, path, name, args, cwd):   # 注意 @Slot(str,str,str,str,result=str)
        """Inline validation for the dialog; '' when valid."""
        from core.program_launcher import make_target, validate_target as _v
        return _v(make_target(path, name=name, args=args, cwd=cwd))

    @Slot(str, str, str, str, str, result=str)
    def addLaunchTarget(self, path, name, args, cwd, targetId=""):
        """Create a target; returns its id, or '' on failure."""
        return self._save_launch_target(None, path, name, args, cwd, targetId)

    @Slot(str, str, str, str, str, result=str)
    def updateLaunchTarget(self, targetId, path, name, args, cwd):
        return self._save_launch_target(targetId, path, name, args, cwd, targetId)

    @Slot(str, result=bool)
    def removeLaunchTarget(self, targetId):
        """Delete a target and unbind every button referencing it (AC-005)."""
        targets = [t for t in self._launch_targets() if t["id"] != targetId]
        self._cfg.setdefault("settings", {})["launch_targets"] = targets
        unbound = self._unbind_launch_action(launch_action_id(targetId))
        save_config(self._cfg)
        if self._engine:
            self._engine.cfg = self._cfg
            self._engine.reload_mappings()
        self.launchTargetsChanged.emit()
        self.mappingsChanged.emit()
        self.profilesChanged.emit()
        self.statusMessage.emit(f"Launch target removed ({unbound} button(s) unbound)")
        return True
```

**内部辅助（非 Slot）**：

```python
    def _save_launch_target(self, target_id, path, name, args, cwd, reuse_id):
        from core.program_launcher import make_target, validate_target
        if not path:
            self.statusMessage.emit("Program path is required")
            return ""
        target = make_target(path, name=name, args=args, cwd=cwd,
                             target_id=reuse_id or None)
        error = validate_target(target)
        if error:
            self.statusMessage.emit(error)     # 具体原因（AC-004 / AC-011 / AC-012）
            return ""
        targets = self._launch_targets()
        replaced = False
        for i, existing in enumerate(targets):
            if existing["id"] == target["id"]:
                targets[i] = target; replaced = True; break
        if not replaced:
            targets.append(target)
        self._cfg.setdefault("settings", {})["launch_targets"] = targets
        save_config(self._cfg)
        if self._engine:
            self._engine.cfg = self._cfg
            self._engine.reload_mappings()
        self.launchTargetsChanged.emit()
        self.statusMessage.emit(f"Launch target saved: {target['name']}")
        return target["id"]

    def _unbind_launch_action(self, action_id):
        """Reset every mapping (all profiles) that points at action_id."""
        count = 0
        for pdata in self._cfg.get("profiles", {}).values():
            mappings = pdata.get("mappings", {})
            for key, value in list(mappings.items()):
                if value == action_id:
                    mappings[key] = "none"; count += 1
        return count
```

> ⚠️ 注意：`_save_launch_target` 的 `args` 校验由 `validate_target` 覆盖（第 6 条），但**分词错误消息需要翻译**——`validate_target` 返回英文原文，UI 侧通过 `LaunchArgsError` 前缀匹配走翻译表（COMP-06）。为简化，对话框在**输入时**就调用 `parseLaunchArgs` 做前置校验并给出内联提示（AC-011）。

### 5.7 需要一并新增的公开 slot（供对话框做前置校验）

```python
    @Slot(str, result=str)
    def validateLaunchArgs(self, argsText):
        """'' when tokenizable, else the reason (unclosed quote / too many)."""
        from core.program_launcher import parse_launch_args, LaunchArgsError
        try:
            parse_launch_args(argsText)
        except LaunchArgsError as exc:
            return str(exc)
        return ""
```

### 5.8 `actionLabelFor` 改动（`:1995-1996`）

```python
    @Slot(str, result=str)
    def actionLabelFor(self, actionId):
        return _action_label(actionId, self._launch_targets())
```

---

## COMP-06 `ui/qml/LaunchTargetDialog.qml`（新建）

**强制 import 约束（DM-08）**——只允许这三行，多一个都会触发 spec 守卫失败：

```qml
import QtQuick
import QtQuick.Controls.Material
import "Theme.js" as Theme
```

### 结构契约（照抄 `KeyCaptureDialog.qml` 的模态范式）

```qml
Rectangle {
    id: dialog
    readonly property var theme: Theme.palette(uiState.darkMode)
    property var s: lm.strings

    property string targetId: ""        // "" = 新增模式，非空 = 编辑模式
    property string pathText: ""
    property string nameText: ""
    property string argsText: ""
    property string cwdText: ""
    property string errorText: ""

    signal saved(string targetId)
    signal cancelled()

    visible: false
    anchors.fill: parent
    color: "#80000000"
    z: 100

    function openNew() { targetId = ""; pathText = ""; nameText = ""
                        argsText = ""; cwdText = ""; errorText = ""
                        visible = true }
    function openEdit(id) { /* 从 backend.launchTargets 回填五字段 */ }
    function close() { visible = false }
    function open() { visible = true }   // 保持与 KeyCaptureDialog.open() 名字一致
```

### 交互要素

| 区域 | 控件 | 数据来源 / 行为 |
|---|---|---|
| **已安装应用列表** | 带 `TextField` 搜索的 `ListView` | `model: backend.knownApps`（`:1117-1128` 提供 `id/label/aliases/path/iconSource`）；点击行 → 回填 `pathText` + `nameText` |
| **浏览按钮** | `Button` | `backend.browseLaunchTargetPath()` → 回填 `pathText`；再 `backend.suggestLaunchTargetName(path)` → 回填 `nameText` |
| **名称** | `TextField` | `nameText`，空时用路径建议名兜底 |
| **启动参数** | `TextField` | `onTextChanged` → `backend.validateLaunchArgs(argsText)` → 非空则设 `errorText`（AC-011 内联提示） |
| **工作目录** | `TextField` + 浏览按钮 | 目录可用 `QFileDialog.getExistingDirectory`（后端加一个 `browseLaunchDirectory()` slot，实现同 5.6 风格） |
| **校验区** | `Text`（`visible: errorText !== ""`） | 红色 `#E5484D` |
| **保存 / 取消** | 两个 `Button` | 保存 → `backend.addLaunchTarget(...)` 或 `updateLaunchTarget(...)`，返回非空 id 则 `saved(id)` + `close()`；返回空则把 `backend` 状态消息作为 `errorText` 展示 |
| **删除**（仅编辑模式） | `Button`（危险色） | `backend.removeLaunchTarget(targetId)` → `close()` |
| **已有目标列表** | `ListView` | `model: backend.launchTargets`，每行「编辑 / 删除」 |

### 关键实现细节

1. **名称默认值**：`pathText` 变化时若 `nameText === ""` 则自动填 `backend.suggestLaunchTargetName(pathText)`。
2. **保存前二次校验**：先 `backend.validateLaunchArgs` 再 `backend.add/updateLaunchTarget`（后者内部还会做完整 `validate_target`）。
3. **键盘可达**：保存按钮 `Keys.onReturnPressed`，`Escape` → `close()`（对齐既有对话框交互）。
4. **主题**：所有颜色取 `theme.*`，字体取 `uiState.fontFamily`。
5. **文案**：全部走 `s["launch_target.*"]`，由 COMP-08 提供。

---

## COMP-07 `ui/qml/MousePage.qml`（补丁）

### 7.1 helper 函数（插入到 `isCustomAction`（`:473-475`）之后）

```qml
    function sentinelIndex(sentinelId) {
        var actions = backend.allActions
        for (var i = 0; i < actions.length; i++)
            if (actions[i].id === sentinelId) return i
        return 0
    }

    function launchLabel(actionId) {
        return backend.launchTargetName(actionId)
    }
```

### 7.2 `actionIndexForId` 改造（`:459-466`）——消除下标魔法值

**改动前**：
```qml
    function actionIndexForId(actionId) {
        var actions = backend.allActions
        for (var i = 0; i < actions.length; i++)
            if (actions[i].id === actionId) return i
        // Custom shortcut: point to the __custom__ sentinel at the end
        if (actionId.startsWith("custom:")) return actions.length - 1
        return 0
    }
```

**改动后**：
```qml
    function actionIndexForId(actionId) {
        var actions = backend.allActions
        for (var i = 0; i < actions.length; i++)
            if (actions[i].id === actionId) return i
        // Not a concrete action: fall back to the sentinel that owns the
        // prefix, so the picker points at the right entry instead of
        // silently showing "Do Nothing".
        if (actionId.startsWith("custom:")) return sentinelIndex("__custom__")
        if (actionId.startsWith("launch:")) return sentinelIndex("__launch__")
        return 0
    }
```

> **为什么必须改**：原实现用 `actions.length - 1` 假设 `__custom__` 恒为末项。新增 `__launch__` 后会变成末项 → **既有 `custom:` 快捷方式绑定会错误高亮成「添加启动程序…」**。改为按 id 查找后与顺序解耦，属**必需的正确性修复**，不是可选优化。

### 7.3 十处 `onPicked` / `onActivated` 新增拦截

**统一模式**（chips 站点）：
```qml
                                            onPicked: function(aid) {
                                                if (aid === "__custom__") {
                                                    keyCaptureDialog.open(selectedProfile, "hscroll_left")
                                                    return
                                                }
                                                if (aid === "__launch__") {                    // ★新增
                                                    launchTargetDialog.open()                  // ★新增
                                                    return                                     // ★新增
                                                }
                                                backend.setProfileMapping(
                                                    selectedProfile, "hscroll_left", aid)
                                            }
```

**统一模式**（ComboBox 站点）：
```qml
                                    onActivated: function(index) {
                                        var aid = backend.allActions[index].id
                                        if (aid === "__custom__") {
                                            keyCaptureDialog.open(selectedProfile, selectedButton)
                                            return
                                        }
                                        if (aid === "__launch__") {                    // ★新增
                                            launchTargetDialog.open()                  // ★新增
                                            return                                     // ★新增
                                        }
                                        backend.setProfileMapping(selectedProfile, selectedButton, aid)
                                        selectedActionId = aid
                                    }
```

**逐处清单（RK-02：10 处，一处都不能漏）**：

| # | 行号 | 形态 | 站点 | 按钮 key |
|---|---|---|---|---|
| 1 | **1346** | chips | 水平滚动左 | `"hscroll_left"` |
| 2 | **1380** | chips | 水平滚动右 | `"hscroll_right"` |
| 3 | **1418** | ComboBox | 滑动 tap | `selectedButton + "_tap"`（推断） |
| 4 | **1518** | ComboBox | 滑动 左 | `selectedButton + "_left"` |
| 5 | **1553** | ComboBox | 滑动 右 | `selectedButton + "_right"` |
| 6 | **1588** | ComboBox | 滑动 上 | `selectedButton + "_up"` |
| 7 | **1623** | ComboBox | 滑动 下 | `selectedButton + "_down"` |
| 8 | **1702** | chips | **主选择器** | `selectedButton` |
| 9 | **1772** | ComboBox | 手势模式 tap | `gsTapKey` |
| 10 | **1850** | ComboBox | Actions Ring 槽位 | `modelData.aid` |

**Tester 校验方式**：
```bash
# 必须 >= 10
grep -c '"__launch__"' ui/qml/MousePage.qml
```

### 7.4 对话框实例化（在 `:2905-2916` 的 `KeyCaptureDialog` 之后）

```qml
    // ── Program launch target dialog ──────────────────────────
    LaunchTargetDialog {
        id: launchTargetDialog
        onSaved: function(id) {
            refreshSelectedProfileMappings()
        }
    }
```

> `onSaved` 只需刷新映射视图（动作列表由 `launchTargetsChanged` → `deviceLayoutChanged` 自动驱动）。

### 7.5 无需改动的地方（已核对，避免过度改动）

| 位置 | 为什么不用改 |
|---|---|
| 10 处 `actionLabel` 表达式 | `launch:<id>` 走 `else` → `trAction(目标名)` 查不到 → 原样返回（`locale_manager.py:1106`）；`__launch__` 走 `else` → 返回翻译后的 label |
| 10 处（7 处 ComboBox）`displayText` | 同上；`currentText` 已是正确 label |
| `isCurrent` 表达式 | `modelData.id === selectedActionId` 天然正确；`__launch__` 恒 false |
| `customLabel` / `isCustomAction` | 仅服务 `custom:` 前缀，语义独立 |
| `hotspotSublabel` / `gestureSummary` | 经 `actionFor` → `lm.trAction(mapping.actionLabel)`，`mapping.actionLabel` 由 backend 给出正确标签 |

---

## COMP-08 `ui/locale_manager.py`（补丁）

### 8.1 `_CATEGORY_TR`（`:866-887`）

```python
_CATEGORY_TR = {
    "zh_CN": {
        # ...既有不动...
        "Launch":     "\u542f\u52a8\u7a0b\u5e8f",          # 启动程序
    },
    "zh_TW": {
        # ...既有不动...
        "Launch":     "\u555f\u52d5\u7a0b\u5f0f",          # 啟動程式
    },
}
```

### 8.2 `_ACTION_TR`（`:892` 起，两套表各加）

| 键（英文原文） | zh_CN | zh_TW |
|---|---|---|
| `"Add Program…"` | `"\u6dfb\u52a0\u542f\u52a8\u7a0b\u5e8f\u2026"` | `"\u65b0\u589e\u555f\u52d5\u7a0b\u5f0f\u2026"` |
| `"Launch: "`（前缀，用于失效标签拼接） | `"\u542f\u52a8\uff1a"` | `"\u555f\u52d5\uff1a"` |
| `"Program path is required"` | `"\u8bf7\u9009\u62e9\u7a0b\u5e8f\u8def\u5f84"` | `"\u8acb\u9078\u64c7\u7a0b\u5f0f\u8def\u5f91"` |
| `"Program not found: "` | `"\u672a\u627e\u5230\u7a0b\u5e8f\uff1a"` | `"\u627e\u4e0d\u5230\u7a0b\u5f0f\uff1a"` |
| `"Working directory not found: "` | `"\u5de5\u4f5c\u76ee\u5f55\u4e0d\u5b58\u5728\uff1a"` | `"\u5de5\u4f5c\u76ee\u9304\u4e0d\u5b58\u5728\uff1a"` |
| `"Invalid arguments: "` | `"\u542f\u52a8\u53c2\u6570\u65e0\u6548\uff1a"` | `"\u555f\u52d5\u53c3\u6578\u7121\u6548\uff1a"` |
| `"Permission denied: "` | `"\u6743\u9650\u4e0d\u8db3\uff1a"` | `"\u6b0a\u9650\u4e0d\u8db3\uff1a"` |
| `"Launch failed: "` | `"\u542f\u52a8\u5931\u8d25\uff1a"` | `"\u555f\u52d5\u5931\u6557\uff1a"` |
| `"Launch target is missing; reassign this button"` | `"\u542f\u52a8\u76ee\u6807\u5df2\u5931\u6548\uff0c\u8bf7\u91cd\u65b0\u6307\u5b9a\u6309\u952e\u52a8\u4f5c"` | `"\u555f\u52d5\u76ee\u6a19\u5df2\u5931\u6548\uff0c\u8acb\u91cd\u65b0\u6307\u5b9a\u6309\u9375\u52d5\u4f5c"` |
| `"Lanched "` / `"Launched "` 前缀 | `"\u5df2\u542f\u52a8\uff1a"` | `"\u5df2\u555f\u52d5\uff1a"` |

> ⚠️ **`Launch: ` / `Program not found: ` 等带尾随冒号的键**：`launch_action_label` 与 `validate_target` 生成的是 **前缀 + 动态内容** 的拼接串，`_ACTION_TR` 是按**精确整串**查找的，因此拼接后必然查不到 → 走原样返回。
> **因此这两类状态提示不做表驱动的整串翻译**。可接受的取舍：状态提示保持英文（与既有多数 `statusMessage` 一致，如 `"Saved"` / `"Profile created"`）。**若用户要求状态提示也中文化，需要在 `backend`/`program_launch` 侧改为「结构化错误码 + 前端拼接」**——这是一个明确的设计分叉点，见 §待确认决策 Q-03。
> 上表**必做**的只有三项：`"Launch"`（分类）、`"Add Program…"`（哨兵标签）、以及**对话框内的静态文案**（走 `s["launch_target.*"]`，属 `strings` 表而非 `_ACTION_TR`）。

### 8.3 对话框文案表

`LaunchTargetDialog` 使用 `s["launch_target.xxx"]`，需在 `ui/locale_manager.py` 的 **strings 表**（`zh_CN` / `zh_TW` / 默认英文）中新增键：

```
launch_target.title_new      添加启动程序 / 新增啟動程式 / Add Program
launch_target.title_edit     编辑启动程序 / 編輯啟動程式 / Edit Program
launch_target.search         搜索已安装应用 / 搜尋已安裝應用 / Search installed apps
launch_target.browse         浏览… / 瀏覽… / Browse…
launch_target.name           名称 / 名稱 / Name
launch_target.path           程序路径 / 程式路徑 / Program path
launch_target.args           启动参数 / 啟動參數 / Arguments
launch_target.cwd            工作目录（留空则用程序所在目录） / 工作目錄（留空則用程式所在目錄） / Working directory (blank = program folder)
launch_target.save           保存 / 儲存 / Save
launch_target.delete         删除 / 刪除 / Delete
launch_target.cancel         取消 / 取消 / Cancel
launch_target.empty          还没有启动目标 / 還沒有啟動目標 / No launch targets yet
```

> **书写风格强制**：所有中文以 `\uXXXX` 转义写入（沿用 `locale_manager.py` 既有风格，例如 `"\u622a\u56fe"`）。任务清单中列为独立验收项。

---

## COMP-09 `main_qml.py`（补丁）

**插入位置**：截图接线块（`:1178-1215`）**之后**，`# ── QML Engine ─────`（`:1217`）之前。

```python
    # ── Program launch controller (cross-platform, single instance) ──
    from core.key_simulator import set_launch_action_handler
    from ui.program_launch import ProgramLaunchController

    program_launcher_controller = ProgramLaunchController(
        status_callback=backend.statusMessage.emit,
        target_provider=backend.findLaunchTargetForLaunch,
        parent=app,
    )
    # Keep a strong reference: the controller would otherwise be collected and
    # launch actions would silently stop working.
    app._mouser_program_launcher = program_launcher_controller
    set_launch_action_handler(program_launcher_controller.request_action)
```

**配套（COMP-05）**：需要一个公开的 target 解析入口给控制器用（`_find_launch_target` 是私有）：

```python
    def findLaunchTargetForLaunch(self, target_id):
        """Public bridge for ProgramLaunchController (runs on the GUI thread)."""
        return self._find_launch_target(target_id)
```

> **注意**：此处**不需要** `if sys.platform == ...` 分叉（与截图不同，启动逻辑跨平台统一，平台差异已由 `build_launch_argv` 内部消化）。

---

## COMP-10 新增测试（新建）

### 10.1 `tests/test_program_launcher.py`（纯逻辑，**本机可直接运行**）

| 测试类 | 覆盖 |
|---|---|
| `ActionIdTests` | `launch_action_id` / `is_launch_action` / `launch_target_id` 的往返与边界（空串、`none`、`custom:ctrl+a`） |
| `ParseArgsTests` | §参数分词契约的全部样例（含 ⭐ 反斜杠用例、未闭合引号抛错、`MAX_ARG_TOKENS`） |
| `TargetModelTests` | `new_target_id` 唯一性；`normalize_name` 剥离控制字符与截断；`make_target` 的路径规范化；`normalize_targets` 对 `{}`/`None`/坏项容错 |
| `ValidateTargetTests` | 校验契约 7 条的逐条命中与通过 |
| `BuildArgvTests` | **macOS `.app` 分叉（RK-05）**：`monkeypatch` `os.path.isdir` → True 且 platform=`darwin` → `["open","-a",path,"--args",...]`；args 为空省略 `--args`；非 `.app` 走 `[path, *args]` |
| `ResolveCwdTests` | D-05：空 cwd → 程序目录；macOS `.app` → 包的父目录 |
| `LaunchTargetTests` | 用 `unittest.mock.patch("subprocess.Popen")`：校验失败不调用 Popen；成功返回 `(True, name)`；`FileNotFoundError`/`PermissionError` → `(False, 原因)`；**断言 `shell=False` 且 argv 为列表**（R-019） |

### 10.2 `tests/test_launch_target_dialog_qml.py`（源码级守卫，**本机可直接运行**）

仿 `test_key_capture_dialog_qml.py` 的写法：

```python
class LaunchTargetDialogQmlTests(unittest.TestCase):
    def test_only_mapped_qml_imports(self):        # DM-08 / AC-018
        imports = re.findall(r"^import\s+([\w.]+)", DIALOG, re.M)
        for name in imports:
            if name.startswith("Qt"):
                self.assertIn(name, MAPPED)        # 与 test_spec_coverage 同集合
    def test_modal_overlay_conventions(self):
        for token in ('anchors.fill: parent', 'color: "#80000000"', 'z: 100'):
            self.assertIn(token, DIALOG)
    def test_exposes_open_close(self):
        self.assertIn("function open()", DIALOG)
        self.assertIn("function close()", DIALOG)
    def test_uses_theme_palette(self):
        self.assertIn("Theme.palette(uiState.darkMode)", DIALOG)
    def test_no_hardcoded_chinese(self):           # 强制 \uXXXX 风格
        # 断言文件中不存在 CJK 字符
        self.assertFalse(re.search(r"[\u4e00-\u9fff]", DIALOG))
```

### 10.3 `tests/test_launch_wiring.py`（源码级守卫，覆盖 RK-01 / RK-02 / RK-03）

```python
class LaunchWiringTests(unittest.TestCase):
    def test_all_platform_branches_handle_launch(self):     # RK-01 / AC-020
        src = read("core/key_simulator.py")
        self.assertEqual(src.count("request_launch_action"), 4)   # 1 定义 + 3 调用

    def test_picker_sites_intercept_the_sentinel(self):     # RK-02
        src = read("ui/qml/MousePage.qml")
        self.assertGreaterEqual(src.count('"__launch__"'), 10)

    def test_controller_uses_queued_connection(self):       # RK-03
        src = read("ui/program_launch.py")
        self.assertIn("Qt.ConnectionType.QueuedConnection", src)
        self.assertNotIn("shell=True", read("core/program_launcher.py"))

    def test_config_default_is_a_list(self):                # RK-04
        import core.config as config
        self.assertEqual(config.DEFAULT_CONFIG["settings"]["launch_targets"], [])
        self.assertEqual(config.DEFAULT_CONFIG["version"], 12)

    def test_no_inline_launch_on_hook_thread(self):
        """request_launch_action must not reach subprocess directly."""
        src = read("core/key_simulator.py")
        self.assertNotIn("subprocess", src)
```

---

## 数据契约汇总（`contracts`）

### 动作 id 契约

| 输入 | `is_launch_action` | `launch_target_id` | `launch_action_label` |
|---|---|---|---|
| `""` | False | `""` | `""` |
| `"none"` | False | `""` | `none` |
| `"custom:ctrl+a"` | False | `""` | `"Ctrl + A"` |
| `"launch:"` | **False**（载荷空） | `""` | `launch:` |
| `"launch:t_1"`（目标存在） | True | `"t_1"` | 目标 `name` |
| `"launch:t_x"`（目标不存在） | True | `"t_x"` | `"Launch: t_x (missing)"` |

### 配置读写契约

| 操作 | 写入位置 | 落盘 | 触发的信号 |
|---|---|---|---|
| 新增/更新目标 | `settings.launch_targets[i]` | `save_config()`（原子写 + 0600） | `launchTargetsChanged` → 缓存失效 + `deviceLayoutChanged`；`statusMessage` |
| 删除目标 | 从列表移除 + 全 profile 引用置 `"none"` | 同上 | 同上 + `mappingsChanged` + `profilesChanged` |
| 绑定按钮 | `profiles.<p>.mappings.<btn> = "launch:<id>"` | `set_mapping()` 内部落盘 | `profilesChanged` + `mappingsChanged` + `statusMessage("Saved")` |

### 错误消息契约（执行侧 → UI）

| 场景 | `launch_target` 返回 | UI 呈现 |
|---|---|---|
| 目标 id 不在注册表 | controller 侧拦截 | `"Launch target is missing; reassign this button"` |
| 路径为空 / 非绝对 / 不存在 | `(False, "Program not found: <path>")` | `"Launch failed: Program not found: <path>"` |
| 工作目录不存在 | `(False, "Working directory not found: <cwd>")` | 同上格式 |
| 参数非法 | `(False, "Invalid arguments: <原因>")` | 同上格式 |
| 权限不足 | `(False, "Permission denied: <path>")` | 同上格式 |
| 其它 OSError | `(False, "Launch failed: <exc>")` | 同上格式 |
| 成功 | `(True, "<name>")` | `"Launched <name>"` |

---

## 待确认决策（随设计评审一并确认）

| 编号 | 决策项 | 本设计倾向 | 若选另一方案的代价 |
|---|---|---|---|
| **Q-01** | R-018「三平台行为一致」的解读 | 解读为**用户可感知结果一致**（点按 → 启动），允许平台代码路径不同 | 若坚持"代码路径一致"，macOS 上 `.app` 只能用 `Contents/MacOS/<exe>` 直接 `Popen`，会**丢失 LaunchServices 语义**（Dock 图标、单实例激活行为异常） |
| **Q-02** | 参数分词的"反斜杠始终字面量"规则 | 采用（DM-04）。代价：引号内无法表示引号字符 | 若改用 `shlex(posix=True)`，`--path=C:\foo` 会被静默破坏 |
| **Q-03** | 状态提示是否也做中文化 | **不做**（与既有 `statusMessage` 如 `"Saved"` / `"Profile created"` 保持一致的英文风格）；只翻译分类、哨兵标签与对话框静态文案 | 若要求中文化，需把错误改成「错误码 + 参数」结构再由前端拼接，`backend`/`program_launch`/`locale` 三处都要改，工作量 +约 60 行 |
| **Q-04** | R-016「失效标识」的实现方式 | **删除目标时主动解除全部引用绑定** + 状态提示（AC-005）；对残留失效 id 靠 `actionIndexForId` 回退到 `__launch__` 下标做防御性降级 | 若要求"UI 显式显示⚠️失效"，需新增一个失效哨兵 chip 并在 10 处 `actionLabel`/`isCurrent` 加分支，改动面翻倍 |
| **Q-05** | 参数与工作目录的默认值规则 | 参数默认空串；工作目录默认**程序自身所在目录**（D-05） | 若改为"用户主目录"，需在 `resolve_launch_cwd` 换成 `os.path.expanduser("~")`，一行改动 |
| **Q-06** | 是否提供"目标管理"独立入口页 | **不提供**，全部经选择器的「新增启动程序…」入口（对话框内含已有目标列表，可编辑/删除） | 若要在设置页加独立区块，需改 `ui/qml/Main.qml` + 新增设置页段落，工作量 +约 120 行 |

---

## 设计-需求覆盖自检

| 需求 | 覆盖组件 | 状态 |
|---|---|---|
| R-001 | COMP-01 `make_target`/`validate_target`、COMP-05 `browseLaunchTargetPath`/`addLaunchTarget`、COMP-06 | ✅ |
| R-002 | DM-01 `args`、COMP-01 `parse_launch_args`、COMP-03 默认值 | ✅ |
| R-003 | DM-01 `cwd`、COMP-01 `resolve_launch_cwd` | ✅ |
| R-004 | COMP-05 `updateLaunchTarget`/`removeLaunchTarget`、COMP-06 | ✅ |
| R-005 | DM-01（`settings` 段） | ✅ |
| R-006 | COMP-05 §5.5、COMP-06 | ✅ |
| R-007 | DM-05（`launch:<id>` 是普通动作 id）、COMP-07 §7.3 | ✅ |
| R-008 | DM-02 标签规则、COMP-05 §5.2/5.8 | ✅ |
| R-009 | COMP-05（走既有 `set_mapping`） | ✅ |
| R-010 | DM-06、COMP-02、COMP-04 | ✅ |
| R-011 | COMP-01 `build_launch_argv`/`resolve_launch_cwd` | ✅ |
| R-012 | COMP-01 错误返回、COMP-04 `_emit_status`、COMP-06 内联校验 | ✅ |
| R-013 | COMP-01（无去重逻辑，每次 `Popen`） | ✅ |
| R-014 | DM-01 + `save_config` | ✅ |
| R-015 | COMP-03 | ✅ |
| R-016 | COMP-05 `removeLaunchTarget` + `actionIndexForId` 回退（Q-04） | ✅ |
| R-017 | COMP-08 | ✅ |
| R-018 | DM-03、COMP-01 `is_macos_bundle`/`build_launch_argv` | ✅ |
| R-019 | COMP-01 `shell=False` 强制 + 测试断言 | ✅ |
| R-020 | DM-06（hook 线程仅 emit） | ✅ |
| R-021 | COMP-03（只加不删）、`_action_label` 可选参数 | ✅ |
| R-022 | COMP-01 无 Qt 依赖、COMP-10 §10.1 可脱离 PySide6 运行 | ✅ |
| R-023 | DM-08 约束、COMP-06 import 白名单、COMP-10 §10.2 | ✅ |
