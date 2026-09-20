# Preprocess 决策日志

> 项目：Mouser ｜ 需求：按键启动程序 ｜ 时间：2026-09-19
> `incomplete: false`

## 1. 执行环境决策

| 决策 | 内容 | 理由 |
|---|---|---|
| 产出方式 | **在主流程直接完成 Preprocess，不派发子 Agent** | 首次尝试子 Agent（`general-purpose`）时因 `copilot.tencent.com` DNS 解析失败（`getaddrinfo ENOTFOUND`）中断；改为主流程执行以避免重复受网络影响 |
| 工具替代 | 列目录用 `Glob`、搜内容用 `Grep`、读文件用 `Read`、执行 Python 用绝对路径 `C:/Users/royce/.workbuddy/binaries/python/versions/3.13.12/python.exe` | 本机沙箱 Bash **无 coreutils**（`ls`/`find`/`grep`/`mkdir`/`wc` 均 `command not found`） |
| 原型提取 | **跳过**（不产出 `prototype-extraction.md`） | 本项目为 PySide6/QML 桌面应用，**无 HTML 原型** |
| 基线 | `baseline.enabled=false` | 独立完整项目，非补丁项目 |

## 2. 项目状态判定

| 项 | 判定 | 依据 |
|---|---|---|
| 项目状态 | **迭代开发**（已有脚手架与大量存量代码） | 存在 `requirements.txt`、`main_qml.py` 入口、完整 `core/`（29 个 .py）+ `ui/`（9 个 .py + 10 个 .qml）+ `tests/`（42 个 .py） |
| 开发策略 | **最小增量改动**：不重构无关代码、不换技术栈、不重建脚手架 | 专家工作流"迭代最小改动"原则 |

## 3. 关键技术决策（Preprocess 阶段）

| 编号 | 决策 | 依据（有据 / 无据） |
|---|---|---|
| P-01 | 记录 `key_simulator.py` 的**四平台独立分支**结构（win32 / darwin / linux / else，各持一份 `ACTIONS` 与 `execute_action`），并标注任何平台相关改动必须四处同步 | **有据**：逐行读取确认（分支起始行 155 / 710 / 1387 / 1844） |
| P-02 | 判定 off-thread 执行范式（截图 `set_screenshot_action_handler` + 排队信号）为本次**核心复用点**，完整记录三步链路 | **有据**：`key_simulator.py:53/60/66`、`main_qml.py:1178-1215`、`windows_screenshot.py:169-258` |
| P-03 | 判定 `core/app_catalog.py` 为**可直接复用**的已安装应用发现能力，不重复造 | **有据**：`get_app_catalog():865` / `resolve_app_spec():996`；`backend.knownApps:1117-1128` 已消费 |
| P-04 | 判定 `backend.browseForAppProfile()`（`:1920-1954`）为文件选择对话框的**照抄模板** | **有据**：含三平台 `QFileDialog` 分支 |
| P-05 | **发现 macOS 的 `app_catalog` 返回 `.app` 包目录而非可执行文件** → 三平台启动方式必须分叉 | **有据**：`app_catalog.py:519` `path=app_path`；`_iter_mac_app_bundles():462-479` 枚举的是 `.app` 目录 |
| P-06 | 判定 `_validate_types()` 会静默重置类型不符的配置值 → 新配置键的默认值类型必须正确 | **有据**：`config.py:813-834` 显式 `cfg[key] = default_val` |
| P-07 | 判定版本号升级安全（测试对照常量而非硬编码 11） | **有据**：grep 确认 10 处断言全为 `DEFAULT_CONFIG["version"]` |
| P-08 | 判定新增 QML 文件**无需改三份 spec**（前提：不引入新 QML import） | **有据**：`test_spec_coverage.py:222` 断言 `datas` 含 `"ui/qml"` 整目录 |
| P-09 | 列出 `__custom__` 哨兵在 `MousePage.qml` 的**全部 10 个 picker 站点行号** | **有据**：grep `"__custom__"` 全量命中并逐处核对按钮 key |
| P-10 | **发现既有隐患**：`actionIndexForId` 用 `actions.length - 1` 假设 `__custom__` 恒为末项，新增哨兵后会破坏既有 `custom:` 高亮 | **有据**：`MousePage.qml:459-466` + LLD §7.2 |
| P-11 | 判定 `lm.trAction()` 对未登记字符串原样返回 → 目标名称可安全充当动作 label | **有据**：`locale_manager.py:1106-1108` |
| P-12 | 判定 `Engine._dispatch_action` **无需改动** | **有据**：`engine.py:1068-1069` 未命中 if/elif 即 `execute_action()` 兜底 |

## 4. 未决事项（移交 Design / 评审）

| 编号 | 事项 | 移交至 |
|---|---|---|
| O-01 | R-018「三平台行为一致」的解读（用户可感知一致 vs 代码路径一致） | LLD **Q-01** |
| O-02 | 参数分词规则（自定义 vs `shlex`） | LLD **Q-02**（已定：自定义） |
| O-03 | 状态提示是否中文化 | LLD **Q-03**（已定：不中文化） |
| O-04 | R-016「失效标识」的实现方式 | LLD **Q-04**（已定：删目标时解除绑定） |
| O-05 | 工作目录留空默认值 | LLD **Q-05**（已定：程序所在目录） |
| O-06 | 是否增设独立的目标管理入口页 | LLD **Q-06**（已定：不增设） |

## 5. 过程风险记录

| 风险 | 处置 |
|---|---|
| 子 Agent 派发因网络中断 | 改主流程执行（见 §1） |
| 增量写入碎片的步数风险 | 采用"先生成完整章节文本、再一次性 Write 落盘"策略，未发生碎片化写入 |
| 本机无 PySide6 / pytest | 已如实记录；验证方案降级为静态验证 + 纯逻辑单测 + 源码级 grep 守卫（`docs/design/tasks.md` T-11） |

## 6. 产出清单

| 文件 | 状态 |
|---|---|
| `docs/requirements.md` | ✅ 前一阶段已产出（R-001 ~ R-023） |
| `docs/preprocess/code-overview.md` | ✅ 本次产出（A ~ I 共 9 节 + 行号速查附录） |
| `docs/preprocess/review-checklist.md` | ✅ 本次产出（RC×6 / AMB×10 / DUP×11 / A×12） |
| `docs/preprocess/decision-preprocess.md` | ✅ 本文件 |
| `docs/sa/prd.md` | ✅ 本次产出（F-001 ~ F-014、AC-001 ~ AC-020、追溯矩阵） |
| `docs/design/HLD.md` | ✅ 本次产出（DM-01 ~ DM-08、IF-01 ~ IF-09、RK-01 ~ RK-11、备选 A ~ D） |
| `docs/design/LLD.md` | ✅ 本次产出（COMP-01 ~ COMP-10、数据契约、Q-01 ~ Q-06） |
| `docs/design/tasks.md` | ✅ 本次产出（T-01 ~ T-12 + 不做清单） |
