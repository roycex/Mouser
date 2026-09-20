# Preprocess 人工审核清单

> 项目：Mouser ｜ 需求：按键启动程序 ｜ 时间：2026-09-19
> 用途：设计评审门禁材料。**RC / AMB / DUP / A 四类编号项均需用户过目确认。**
> 配套：`docs/preprocess/code-overview.md`、`docs/design/HLD.md`、`docs/design/LLD.md`

---

## RC —— 需求冲突 / 与现有实现的不一致

| 编号 | 冲突点 | 事实 | 本设计的处理 | 需用户裁决 |
|---|---|---|---|---|
| RC-01 | 动作 id 前缀风格 | 现有参数化动作前缀是 `custom:`，其载荷是**组合键语法**；把启动目标塞进 `custom:` 会被 `custom_action_label`（`key_simulator.py:18-33`）按组合键解析并美化，语义污染 | 新增独立前缀 `launch:` | 是否接受新增前缀（本设计已定为 `launch:`） |
| RC-02 | 目标注册表层级 vs 现有 profile 语义 | 现有 `actions_ring_slots` 有"全局 / per-app"双模式（`settings.actions_ring_use_global`）；本需求选了纯全局 | 走 `settings.launch_targets`（全局），不做双模式 | 是否接受（若要多模式需加开关，工作量 +约 40 行） |
| RC-03 | 失效动作的下标回退机制 | `actionIndexForId`（`MousePage.qml:459-466`）用 `actions.length - 1` 假设 `__custom__` 恒为 `allActions` 末项 | **必须改为按 id 查找**（`sentinelIndex("__custom__")`），否则新增 `__launch__` 后既有 `custom:` 绑定会错误高亮成「添加启动程序…」 | 这是**必需的正确性修复**，非可选优化 —— 确认接受该改动 |
| RC-04 | `_action_label` 签名 | 现有 `_action_label(action_id)`（`backend.py:80`）是模块级函数，**无法访问配置**，而目标名称存在配置里 | 增加**可选**参数 `launch_targets=()`，既有调用点行为完全不变 | 确认接受（AC-016 兼容性） |
| RC-05 | R-018「三平台行为一致」与平台现实冲突 | `app_catalog` 在 macOS 返回 `.app` **目录**（`app_catalog.py:519`），Windows/Linux 返回可执行**文件** → 代码路径必然不同 | 解读为"用户可感知结果一致"，平台差异在 `build_launch_argv` 内部分叉 | **LLD Q-01，需明确裁决** |
| RC-06 | 需求 S-008「UI 显示失效标识」与现有 UI 机制冲突 | 现有 picker 靠 `allActions` 里的静态条目渲染，没有"失效条目"的概念 | 改为"删除目标时主动解除绑定 + 状态提示"（AC-005），残留 id 靠 `actionIndexForId` 回退降级 | **LLD Q-04，需明确裁决** |

---

## AMB —— 含糊需求（本设计已给默认，逐条请确认）

| 编号 | 含糊点 | 本设计取值 | 依据 |
|---|---|---|---|
| AMB-01 | 启动参数的分词规则 | 自定义 4 条规则：空白分隔 / `"` `'` 包裹 / **反斜杠始终字面量**；未闭合引号报错 | DM-04（LLD Q-02）。**不用 `shlex`**，因为 `posix=True` 会把 `C:\foo` 吞成 `C:foo` |
| AMB-02 | 工作目录留空时的默认值 | **程序自身所在目录**；macOS `.app` 取包的父目录 | D-05（LLD Q-05）。备选：用户主目录 |
| AMB-03 | 目标名称默认取值 | ① `app_catalog.resolve_app_spec(path)` 的 `label` → ② basename 去扩展名 → ③ macOS 去 `.app` | D-06 |
| AMB-04 | 同一目标绑定多个按钮时的行为 | 各自独立触发，每次启动一个新实例，**不去重** | R-013 / AC-014 / AC-015 |
| AMB-05 | 目标名称的长度与字符限制 | 去空白 + 剥离控制字符 + 截断 64 字符 | `MAX_TARGET_NAME_LEN`（防 RK-08） |
| AMB-06 | 参数个数上限 | 64 个 token，超出报错 | `MAX_ARG_TOKENS`（防手改配置塞超长参数） |
| AMB-07 | 状态提示是否需要中文化 | **不做**，保持英文（与既有 `"Saved"` / `"Profile created"` 一致）；只翻译分类、哨兵标签、对话框静态文案 | LLD Q-03。`_ACTION_TR` 按精确整串查找，而错误消息是"前缀 + 动态内容"拼接串，**表驱动翻译天然不适用** |
| AMB-08 | 对话框是否需要"测试启动"按钮 | **不做**（超出需求范围） | PRD §1.3 |
| AMB-09 | 是否需要环境变量 / `~` 展开 | **不做** | PRD §1.3 |
| AMB-10 | Windows 上 `.lnk` / `.bat` 是否支持 | **不支持**，仅可执行文件（`.bat` 需 `cmd /c`，会破坏 `shell=False` 模型） | PRD §1.3 |

---

## DUP —— 功能重复检查（"不要重复造轮子"核对）

| 编号 | 可能重复的对象 | 核对结论 | 处置 |
|---|---|---|---|
| DUP-01 | 与现有 `custom:` 动作 | **不重复**。`custom:` = 模拟键盘组合；`launch:` = 启动进程。机制上借鉴（id 自带数据 + 前缀分发），但载荷与执行完全不同 | 复用机制，不复用前缀 |
| DUP-02 | 与截图动作 | **不重复**。截图的 `SCREENSHOT_ACTIONS` 是 4 个固定 id；`launch:` 是无限目标。但**线程模型完全复用**（handler 注册 + 排队信号跳 GUI 线程） | **照抄 off-thread 范式**（`ui/windows_screenshot.py:169-258`） |
| DUP-03 | 与 `core/app_catalog.py` 的应用发现能力 | **本设计不重复造**。直接复用 `get_app_catalog()` / `resolve_app_spec()` / `get_app_label()` | ✅ 已复用 |
| DUP-04 | 与 `backend.browseForAppProfile()` 的文件选择 | **不重复造**。`browseLaunchTargetPath`（LLD §5.6）照抄其 `QFileDialog` 三平台分支写法（`backend.py:1920-1954`） | ✅ 已复用 |
| DUP-05 | 与 `backend.knownApps` 应用清单 | **不重复造**。对话框直接 `model: backend.knownApps`（`backend.py:1117-1128` 已含 `id/label/aliases/path/iconSource`） | ✅ 已复用 |
| DUP-06 | 与 `get_icon_for_exe` / `image://systemicons` 图标能力 | **不重复造**。对话框可直接用 `knownApps` 里的 `iconSource` | ✅ 已复用 |
| DUP-07 | 与 `Keyboard` 类 `_open_url` （`backend.py:197`） | **不重复**。那是 URL 打开，属 OUT 范围 | 无 |
| DUP-08 | 与 `Engine._dispatch_action` 内部动作机制 | **不重复**。明确走 `execute_action` 兜底路径，**不碰 `engine.py`**（HLD §7 备选 C 已论证为何不这么走） | 无 |
| DUP-09 | 与 `_atomic_write_json` 原子写 | **不重复造**。目标持久化统一走 `save_config()` | ✅ 已复用 |
| DUP-10 | 与 `_normalize_directory_path`（`backend.py:217`） | 目录路径规整已有实现；本设计在工作目录输入上只做"存在性 + 绝对路径"校验，未重复实现规整逻辑 | 无重复 |
| DUP-11 | 三平台截图控制器（`ui/windows_screenshot.py` 等三份） | **刻意不重复**。启动逻辑跨平台统一（平台差异已由 `build_launch_argv` 内部消化），只写**一份** `ui/program_launch.py` | ✅ 未制造三份 |

**结论：共识别 11 项潜在重复，其中 6 项判定为"已复用既有能力"，1 项判定为"刻意不复用（保持单份）"，其余 4 项无重复。无造轮子行为。**

---

## A —— 关键假设（逐条标注假设依据）

| 编号 | 假设 | `[假设依据]` | 若假设不成立的后果 |
|---|---|---|---|
| A-01 | `execute_action` 运行在鼠标 Hook 回调线程上，任何阻塞都会卡住鼠标 | **有**（`docs/preprocess/code-overview.md` §A.5；截图功能专门为此设计 off-thread 模式；`ui/windows_screenshot.py` 头部 docstring 明说 "The mouse hook can invoke actions from a non-Qt thread"） | 若实际不在 hook 线程，则 off-thread 设计过度但无害 |
| A-02 | `Signal.emit()` 在 `QueuedConnection` 下的开销足够小（O(1)），不会造成可感知延迟 | **有**（截图功能已用同一模式上线运行；R-020 要求"与现有动作同一量级"） | 若开销大，需改为原生线程 |
| A-03 | macOS 上从 `app_catalog` 选出的程序，`path` 恒为 `.app` 包目录 | **有**（`app_catalog.py:519` `path=app_path`，`app_path` 来自 `_iter_mac_app_bundles()` 的 `.app` 目录枚举） | 若某条目 path 实为内部可执行文件，`is_macos_bundle` 返回 False → 走直接 `Popen`，仍能工作（更稳） |
| A-04 | `lm.trAction()` 对未登记字符串原样返回 | **有**（`locale_manager.py:1106-1108` `.get(english_label, english_label)`） | 若行为变化，目标名称会被错误翻译（需改为不经 `trAction`） |
| A-05 | `_validate_types` 会把类型不符的值重置为默认 | **有**（`config.py:813-834`，显式 `cfg[key] = default_val` 并打印告警） | 若无此行为，`launch_targets` 默认值类型写错也不会出事（但设计已按最严处理） |
| A-06 | 测试断言对照 `DEFAULT_CONFIG["version"]` 而非硬编码 11 | **有**（`test_config.py:47/102/176/209/273/330/346`、`test_smart_shift.py:945/1007/1047` 全部为 `assertEqual(migrated["version"], DEFAULT_CONFIG["version"])`） | 若某处硬编码，版本升级会破坏该测试（已逐条 grep 确认无硬编码） |
| A-07 | 新增 QML 文件若只用已映射 import，则三份 spec 无需改动 | **有**（`test_spec_coverage.py:222` 断言 `datas` 含 `"ui/qml"` 整目录；`QmlCoverageTests` 只校验 import 映射与白名单） | 若 spec 改为逐文件列举，则需同步三份 spec |
| A-08 | `launch:<id>` 作为普通动作 id 可直接被 10 个 picker 站点选择，无需改 `onPicked` | **有**（LLD §7.5 逐项核对 `actionLabel` / `isCurrent` / `displayText` / `actionIndexForId` 四个表达式） | 若某个站点有额外过滤（如 `visible:` 条件），该处可能不显示目标项 —— **需在 T-07 编码时逐处实读确认** |
| A-09 | 用户接受"状态提示保持英文" | **无** ⚠️ | 见 AMB-07 / LLD Q-03。若不接受，需把错误改为"错误码 + 参数"结构，三处改动 +约 60 行 |
| A-10 | 本机无 PySide6 / pytest，UI 与打包测试无法自动运行 | **有**（已实测：`C:/Users/royce/.workbuddy/binaries/python/versions/3.13.12/python.exe` 无 PySide6；项目无 `.venv`；用户明确选择"不跑自动测试"） | 无（已按此设计降级验证方案） |
| A-11 | `subprocess.Popen` 不加 `start_new_session`（POSIX）/ 不加 creationflags（Windows）也能让子进程存活于 Mouser 之后 | **有**（POSIX 下父进程退出不发送 SIGHUP；Windows 下无 job object 绑定） | 若实测发现子进程随 Mouser 退出而终止，需补 `creationflags=CREATE_NEW_PROCESS_GROUP`（一行） |
| A-12 | 10 处 picker 站点覆盖了用户实际会用到的全部绑定入口 | **有**（grep `"__custom__"` 全量命中 10 处，与 `docs/preprocess/code-overview.md` §D.2 表格一致） | 若存在未纳入的绑定入口（如 Settings 页也有动作选择），该处无法新增目标 |

---

## 审核结论区（待用户填写）

| 类别 | 需用户裁决项 | 用户结论 |
|---|---|---|
| RC | RC-01 ~ RC-06（尤其 **RC-05 / RC-06**） | |
| AMB | AMB-01 ~ AMB-10（尤其 **AMB-01 / AMB-02 / AMB-07**） | |
| DUP | 11 项核对结论是否认可 | |
| A | 假设 A-09（状态提示英文）是否接受 | |
| Q | LLD 的 **Q-01 ~ Q-06** | |
