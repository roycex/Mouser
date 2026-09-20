# TASK — Mouser「按键启动程序」任务拆解

> 上游：`docs/design/HLD.md`、`docs/design/LLD.md`
> 时间：2026-09-19 ｜ 状态：**待用户确认后启动编码**
> 规则：**只实现本清单范围内的功能，不擅自添加**；完成一项勾选一项

---

## 依赖图

```
T-01 (program_launcher 纯逻辑)
  ├─▶ T-02 (config v12 迁移)  ──▶ T-05 (backend CRUD)
  ├─▶ T-03 (key_simulator 接线)
  └─▶ T-04 (program_launch 控制器) ──▶ T-09 (main_qml 接线) ──▶ T-12 (端到端静态校验)

T-06 (QML 对话框) ──▶ T-07 (MousePage 接线) ──▶ T-12
T-08 (i18n)      ──▶ T-06 / T-07（并行，但 T-06 依赖其文案键）
T-10 (新增测试)  ──▶ T-11 (Tester 阶段)
```

**关键路径**：T-01 → T-02 → T-05 → T-06 → T-07 → T-12

---

## 阶段 A：核心纯逻辑（无 UI 依赖，可独立验证）

### [ ] T-01 新建 `core/program_launcher.py`

**依赖**：无
**依据**：LLD COMP-01

**交付**：
- [ ] 模块级常量 `LAUNCH_ACTION_PREFIX` / `LAUNCH_MISSING_PREFIX` / `MAX_TARGET_NAME_LEN` / `MAX_ARG_TOKENS` / `LaunchArgsError`
- [ ] id 编解码 4 函数：`launch_action_id` / `is_launch_action` / `launch_target_id` / `launch_action_label`
- [ ] 目标模型 5 函数：`new_target_id` / `normalize_name` / `make_target` / `name_from_path` / `normalize_targets`
- [ ] `validate_target`（7 条校验契约，顺序固定）
- [ ] 分词 2 函数：`parse_launch_args`（DM-04 的 4 条规则）/ `format_launch_args`
- [ ] 平台层 3 函数：`is_macos_bundle` / `build_launch_argv`（DM-03 分叉）/ `resolve_launch_cwd`（D-05）
- [ ] `launch_target`（`subprocess.Popen`，`shell=False`，`_recent_processes` deque 防 RK-10）

**验收标准**：
- [ ] AC-011 未闭合引号 → `LaunchArgsError`
- [ ] AC-013 空参数 → `[]` → argv 只含程序路径
- [ ] AC-017 **模块内不存在 `PySide6` / `Qt` 字样**（`grep -c "PySide6\|Qt" ` = 0）
- [ ] R-019 **不存在 `shell=True` / `os.system` / `subprocess.run(`**
- [ ] DM-03 macOS `.app` → `["open","-a",path,"--args",...]`
- [ ] DM-04 ⭐ `'--path=C:\\foo'` → `["--path=C:\\foo"]`（反斜杠未被吞）

**风险**：RK-04 相关的 `normalize_targets` 容错（配置可能被手工改坏 → 必须不抛异常）

---

### [ ] T-02 `core/config.py` 版本迁移 v11 → v12

**依赖**：T-01（`program_launcher` 存在，但本任务本身不 import 它）
**依据**：LLD COMP-03

**改动点**：
- [ ] `DEFAULT_CONFIG["version"]`：`11` → `12`（`config.py:228`）
- [ ] `DEFAULT_CONFIG["settings"]` 末尾新增 `"launch_targets": []`（**必须是 `[]`，不能是 `{}`** — RK-04）
- [ ] `_migrate()` 内、`if version < 11:` 块之后、`cfg.setdefault("settings", {})`（`:733`）之前，追加 `if version < 12:` 步，含 `isinstance(..., list)` 防御

**验收标准**：
- [ ] AC-006 构造 `{"version": 11, "settings": {"dpi": 1234}, ...}` → 迁移后 `version == 12`、`launch_targets == []`、**`dpi` 仍为 `1234`**
- [ ] AC-016 既有 profile / mappings 字段值零变化
- [ ] 迁移步位置正确（在 `return cfg` 之前）

**风险**：迁移步插错位置（放在 `return cfg` 之后 → 静默不生效）

---

## 阶段 B：执行链路（线程安全核心，最高风险区）

### [ ] T-03 `core/key_simulator.py` 四平台接线

**依赖**：T-01
**依据**：LLD COMP-02 ｜ **风险等级：最高（RK-01）**

**改动点**：
- [ ] 模块级新增 `_launch_action_handler` / `set_launch_action_handler()` / `request_launch_action()`（插入 `request_screenshot_action` 之后，约 `:78`）
- [ ] `win32` 的 `execute_action`（`:690-691` 处）加 `if request_launch_action(action_id): return`
- [ ] `darwin` 的 `execute_action`（`:1360` 区）加同样分支
- [ ] `linux` 的 `execute_action`（`:1832-1833` 处）加同样分支
- [ ] `else` stub 分支（`:1851`）**不改**（AC-010）

**验收标准**：
- [ ] AC-020 **`grep -c "request_launch_action" core/key_simulator.py` == 4**（1 定义 + 3 调用）
- [ ] `request_launch_action` 内部 `try/except Exception` 全捕获，**异常不穿透到 hook 线程**
- [ ] 三分支的插入位置都在 `request_screenshot_action` 之后（保持"越便宜越靠前"）
- [ ] AC-016 既有 `custom:` / 截图 / 鼠标按键分支顺序与语义未变

**风险**：RK-01 —— 漏改某平台 → 该平台按键完全无响应

---

### [ ] T-04 新建 `ui/program_launch.py`

**依赖**：T-01
**依据**：LLD COMP-04 ｜ **风险等级：高（RK-03）**

**交付**：
- [ ] `ProgramLaunchController(QObject)`，私有信号 `_requestAction = Signal(str)`
- [ ] `__init__(status_callback, target_provider, parent)`
- [ ] `request_action(action_id)` —— 仅 `emit`，**不含任何 I/O**
- [ ] `_handle_request(action_id)`（`@Slot(str)`）—— 解析 id → 取目标 → 缺失则状态提示 → `launch_target()` → 结果状态提示
- [ ] `_emit_status(message)` —— 调 `status_callback`

**验收标准**：
- [ ] AC-002 / R-020 **`connect(..., Qt.ConnectionType.QueuedConnection)` 显式存在**（RK-03；源码级 grep 可验）
- [ ] `request_action` 函数体内**不出现** `subprocess` / `Popen` / `open(` / `time.sleep`
- [ ] 目标缺失时给出 `"Launch target is missing; reassign this button"` 且不崩溃（AC-008）
- [ ] 控制器**只有一个**，无 `if sys.platform` 分叉（与截图控制器不同）

**风险**：RK-03 —— 漏写 `QueuedConnection` → `Popen` 在 hook 线程执行 → 鼠标卡顿

---

### [ ] T-09 `main_qml.py` 控制器接线

**依赖**：T-04、T-05
**依据**：LLD COMP-09

**改动点**：
- [ ] 在截图接线块（`:1178-1215`）之后、`# ── QML Engine ──`（`:1217`）之前插入接线代码
- [ ] `ProgramLaunchController(status_callback=backend.statusMessage.emit, target_provider=backend.findLaunchTargetForLaunch, parent=app)`
- [ ] **保存强引用** `app._mouser_program_launcher = ...`（RK-06）
- [ ] `set_launch_action_handler(program_launcher_controller.request_action)`

**验收标准**：
- [ ] `app._mouser_program_launcher` 引用存在（对照 `app._mouser_screenshot_controller` 写法）
- [ ] **无 `if sys.platform` 分叉**
- [ ] 插入位置在 QML engine 加载之前（保证 QML 可用前 handler 已就绪）

**风险**：RK-06 —— 不存强引用 → 随机时点功能失效

---

## 阶段 C：后端桥接

### [ ] T-05 `ui/backend.py` 标签、列表、CRUD

**依赖**：T-01、T-02
**依据**：LLD COMP-05 ｜ **风险等级：中（RK-07）**

**改动点**：
- [ ] import `program_launcher` 相关符号
- [ ] `_action_label(action_id, launch_targets=())` 增加 `launch:` 分支（**可选参数，保证既有调用点零影响**）
- [ ] 新增信号 `launchTargetsChanged`，并在 `__init__` 连线到 `_invalidate_launch_targets`
- [ ] `_invalidate_launch_targets()` → `_invalidate_device_dependent_caches()` + `deviceLayoutChanged.emit()`（RK-07）
- [ ] helper：`_launch_targets()` / `_find_launch_target(id)` / `findLaunchTargetForLaunch(id)`（公开）
- [ ] `_compute_action_categories()`：`:538-540` 之后追加 `Launch` 分类（目标项 + `__launch__`）
- [ ] `_compute_all_actions()`：`:569` 之前插入目标项，`:570` 之后追加 `__launch__`
- [ ] slots：`browseLaunchTargetPath` / `browseLaunchDirectory` / `suggestLaunchTargetName` / `launchTargetName` / `validateLaunchArgs` / `validateLaunchTarget` / `addLaunchTarget` / `updateLaunchTarget` / `removeLaunchTarget`
- [ ] 私有：`_save_launch_target` / `_unbind_launch_action`
- [ ] `actionLabelFor`（`:1995`）改为传 `self._launch_targets()`

**验收标准**：
- [ ] AC-001 绑定 `launch:<id>` 后 `profiles.<p>.mappings.<btn>` 值正确且已落盘
- [ ] AC-005 `removeLaunchTarget` 把所有 profile 中引用该目标的映射置为 `"none"`，并提示解除数量
- [ ] AC-009 无目标时 `allActions` 只多出 `__launch__` 一项，其余动作列表与改动前**逐项一致**
- [ ] AC-007 `launchTargetName("launch:<id>")` 返回目标名；目标不存在返回 `""`
- [ ] RK-07 新增目标后 `deviceLayoutChanged` 已发射（QML 列表能刷新）
- [ ] `_action_label` 旧签名调用行为不变（AC-016）

**风险**：RK-07 —— 忘了发 `deviceLayoutChanged` → 新目标不出现

---

## 阶段 D：UI 层

### [ ] T-08 `ui/locale_manager.py` 国际化

**依赖**：无（可与 T-01 ~ T-05 并行）
**依据**：LLD COMP-08

**改动点**：
- [ ] `_CATEGORY_TR` 两套表各加 `"Launch"`
- [ ] `_ACTION_TR` 两套表各加 `"Add Program…"`
- [ ] strings 表（英文 / `zh_CN` / `zh_TW`）新增 `launch_target.*` 共 13 个键（清单见 LLD §8.3）

**验收标准**：
- [ ] AC-019 三种语言均有条目，无遗漏
- [ ] **所有新增的中文一律以 `\uXXXX` 转义书写**（沿用既有风格）
- [ ] AC-019 用户自定义目标名不进入翻译表（靠 `trAction` 原样返回透传）

---

### [ ] T-06 新建 `ui/qml/LaunchTargetDialog.qml`

**依赖**：T-05、T-08
**依据**：LLD COMP-06 ｜ **风险等级：中（规范约束多）**

**交付**：
- [ ] `open()` / `openNew()` / `openEdit(id)` / `close()`
- [ ] 已安装应用搜索列表（`model: backend.knownApps`，含搜索过滤）
- [ ] 「浏览…」→ `backend.browseLaunchTargetPath()` → 回填路径 + `suggestLaunchTargetName` 回填名称
- [ ] 名称 / 参数 / 工作目录三个输入 + 工作目录浏览
- [ ] 参数实时校验（`backend.validateLaunchArgs`）→ 内联错误提示
- [ ] 保存 / 删除 / 取消按钮
- [ ] 已有目标列表（可编辑 / 删除）
- [ ] `signal saved(string)` / `signal cancelled()`

**验收标准**：
- [ ] AC-018 **只 import `QtQuick` / `QtQuick.Controls.Material` / `"Theme.js"`**（多一个即触发 spec 守卫失败）
- [ ] 模态范式对齐 `KeyCaptureDialog`：`anchors.fill: parent` + `color: "#80000000"` + `z: 100`
- [ ] 全部颜色取 `theme.*`，字体取 `uiState.fontFamily`
- [ ] **文件内不存在 CJK 字符**（文案全走 `s["launch_target.*"]`）
- [ ] AC-011 未闭合引号时保存按钮不可用 / 给出内联错误，且**不写入配置**

**风险**：引入新 QML import → `test_spec_coverage.py` 失败

---

### [ ] T-07 `ui/qml/MousePage.qml` 接线

**依赖**：T-06
**依据**：LLD COMP-07 ｜ **风险等级：高（RK-02）**

**改动点**：
- [ ] 新增 helper `sentinelIndex(sentinelId)` / `launchLabel(actionId)`（插在 `isCustomAction` 之后，`:475` 后）
- [ ] **`actionIndexForId` 改造**（`:459-466`）：`actions.length - 1` → `sentinelIndex("__custom__")`，并新增 `launch:` 回退到 `sentinelIndex("__launch__")`
- [ ] 10 处 `onPicked` / `onActivated` 各加 3 行 `__launch__` 拦截（行号：**1346 / 1380 / 1418 / 1518 / 1553 / 1588 / 1623 / 1702 / 1772 / 1850**）
- [ ] `:2905` 的 `KeyCaptureDialog` 之后实例化 `LaunchTargetDialog { id: launchTargetDialog }`

**验收标准**：
- [ ] RK-02 **`grep -c '"__launch__"' ui/qml/MousePage.qml` >= 10**
- [ ] **`custom:` 快捷方式绑定仍正确高亮**（`actionIndexForId` 改造后不能指向 `__launch__`）— 这是本次最有价值的回归点
- [ ] `launch:<id>` 目标项在 10 个站点均可正常选择与绑定（无需改 `onPicked` 的 else 路径）
- [ ] ComboBox 站点的 `displayText` 未改动且显示正确（目标名 / 翻译后的哨兵标签）

**风险**：
- RK-02 漏改某处 → 从该处无法新增目标
- **`actionIndexForId` 改造引入 `custom:` 高亮回归** → 必须显式验证

---

## 阶段 E：测试与验证

### [ ] T-10 新增测试

**依赖**：T-01 ~ T-07
**依据**：LLD COMP-10

**交付**：
- [ ] `tests/test_program_launcher.py`（7 个测试类，见 LLD §10.1）
- [ ] `tests/test_launch_target_dialog_qml.py`（源码级守卫，见 LLD §10.2）
- [ ] `tests/test_launch_wiring.py`（源码级守卫：RK-01 / RK-02 / RK-03 / RK-04，见 LLD §10.3）

**验收标准**：
- [ ] 三个测试文件**均不依赖 PySide6**，可在本机直接运行
- [ ] 全部通过：`python -m unittest tests.test_program_launcher tests.test_launch_target_dialog_qml tests.test_launch_wiring`

---

### [ ] T-11 Tester 阶段验证（静态 + 人工清单）

**依赖**：T-10
**说明**：本机无 PySide6 / pytest，且用户选择不跑自动测试 → 本阶段降级为静态验证 + 输出「需用户本机手动验证」清单

**执行内容**：
- [ ] `python -m compileall core ui main_qml.py`（全量语法检查）
- [ ] 纯逻辑模块导入冒烟：`python -c "import core.program_launcher, core.config"`
- [ ] 运行 T-10 的三个测试文件
- [ ] 运行可脱离 PySide6 的既有回归测试：`test_config` / `test_key_simulator` / `test_button_gestures` / `test_spec_coverage` / `test_key_registry`
- [ ] 源码级 grep 核对：`request_launch_action` ×4、`"__launch__"` ×≥10、`QueuedConnection` 存在、`shell=True` 不存在
- [ ] 产出 `docs/tester/qa-report.md` + **需用户本机手动验证清单**

**用户手动验证清单（T-11 产出，需在你本机执行）**：
1. 启动 Mouser → 鼠标页 → 任选按钮 → 动作选择器出现「启动程序」分类
2. 点「添加启动程序…」→ 从已安装应用选一个（或浏览）→ 填参数与工作目录 → 保存
3. 目标出现在选择器中 → 绑定到侧键 → 按侧键 → **程序启动，且鼠标不卡**
4. 重启 Mouser → 目标与绑定仍在
5. 参数填 `"unclosed` → 保存被拒且有提示
6. 路径改成一个不存在的文件 → 保存被拒且有提示
7. 删除该目标 → 原绑定按钮回到「无操作」，且有解除提示
8. 切到繁体中文 → 分类与对话框文案为繁体

---

### [ ] T-12 端到端静态校验

**依赖**：T-07、T-09
**执行内容**：
- [ ] 全量 `grep` 核对清单一次通过
- [ ] `python -m compileall` 零错误
- [ ] 三份 `.spec` 与 `tests/test_spec_coverage.py` **确认零改动**（DM-08）
- [ ] 交付摘要（改了哪些文件 / 为什么 / 影响范围）

---

## 不做清单（明确排除，防止范围蔓延）

| 项 | 理由 |
|---|---|
| 打开文档 / 文件夹 | 用户确认 OUT |
| 打开 URL | 用户确认 OUT（与既有 Browser 类动作重叠） |
| 管理员权限提权运行 | 用户确认 OUT（需 `ShellExecute runas`，脱离 `shell=False` 安全模型） |
| 进程去重 / 窗口激活 | 用户确认 OUT（R-013） |
| 环境变量与 `~` 展开 | PRD §1.3 OUT |
| `.lnk` / `.bat` / `.cmd` 支持 | PRD §1.3 OUT |
| 改动三份 PyInstaller spec | 不必要（DM-08） |
| 重构 10 处 picker 为可复用组件 | 超出需求；改为每处 3 行机械改动（RK-02 用 grep 守卫兜住） |
| 修改 `core/engine.py` | 不必要（`launch:` 走 `execute_action` 兜底） |

---

## 修复循环纪律

- 自审 → 静态检查 → 测试 → 端到端，**最多 3 轮修复**
- 超过 3 轮仍失败 → **停止并输出「待人工确认项」**，不擅自扩大改动范围
- 任何超出本清单的改动 → **先停下来问用户**
