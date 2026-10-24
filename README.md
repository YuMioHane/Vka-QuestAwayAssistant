# Vka-QuestAwayAssistant

QuestAway 的外部挂机助手。**完全免费、开源**，不修改游戏文件、不改存档、不改网络协议。

> 如果有人向你收费，请立刻申请退款并举报——作者从未、也不会收任何费用。

作者 B 站主页：<https://space.bilibili.com/8044987>

---

## 功能

| # | 模块 | 做什么 |
|---|---|---|
| 1 | 自动换关 | 两张图来回切，每张停留 N 秒；不开地图，直接派发 |
| 2 | 自动收箱 | HUD 上出现宝箱就点掉（普通 / 白银 / 首领） |
| 3 | 自动转化 | 材料 / 装备 / 两者；右键逐格放入，凑满 8 格点转化 |
| 4 | 自动存仓 | 右键直接存入仓库，可勾选是否连材料一起存 |
| 5 | 自动分解 | 工作台「分解」，装备可按稀有度筛选，默认只分解背包内 |

规则细节：

- **存仓与分解的稀有度互斥**：同一品阶只能选一边，冲突时自动取消并提示。
- 勾了「转化」或「分解」，点开始会**连弹两次确认**，第二次必须点「我真的确认了」。
- 每个操作跑完**自动关闭它自己打开的窗口**，你原本开着的窗口不动。

## 硬性红线（代码里写死）

1. **身上正在穿的装备（`data-where=equip`）永不移动、永不转化、永不分解。**
2. **上锁的物品（`.selo-trancada`）永不触碰。**

扫描阶段过滤一遍，操作前再用 `elementFromPoint` 校验一遍，两道闸都过不去才动手。

## 原理

游戏是 Tauri + WebView2，通过自己的调试端口连接页面：

- 用 `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9222` 启动游戏；
- CDP 连上页面后，**只做两件事**：派发游戏自己的 `data-action` 点击、对物品元素派发右键事件；
- 不注入游戏逻辑、不调用内部函数、不伪造结算数据。

物品移动方式：

| 操作 | 方式 |
|---|---|
| 存仓 / 取回 | 右键（游戏自带：右键背包物品=存入，右键仓库物品=取回） |
| 转化填格 | 对物品元素逐个派发右键，放进立方体 |
| 分解填台 | 同上 |
| 全程 | **不使用拖拽，也不使用「自动填入」** |

## 运行要求

- Windows 10 / 11，64 位（Win7/8 无法运行 Python 3.12 运行时）
- Steam 版 QuestAway
- 不需要安装 Python（发行版已内置）

## 使用方法

1. 彻底退出游戏（含托盘）；
2. 运行 `QuestAwayHelper.exe`（首次可能被 SmartScreen 拦，点「更多信息 → 仍要运行」）；
3. 首次点「选游戏路径」指向 `QuestAway.exe`（会自动扫 C–H 盘常见 Steam 路径）；
4. 点「一键启动游戏」→ 助手会给游戏带上调试端口并连接；
5. 勾选模块、设参数，点「开始挂机」。

详细说明见 [`docs/使用说明.md`](docs/使用说明.md)。

## 从源码运行 / 自行构建

```bat
python -m venv .venv
.venv\Scripts\pip install websocket-client pyinstaller
.venv\Scripts\python src\assistant.pyw
```

构建绿色版（exe + _internal）：

```bat
scripts\build.bat
```

产物在 `release\QuestAwayHelper\`，打包 zip 后分发。

## 文件结构

```
src/assistant.pyw        GUI 与五个模块的调度
src/cdp.py               CDP 连接、DOM 扫描、动作派发、面板状态解析
tools/启动-自检.bat       带环境自检的启动器（检查是否完整解压 / 64 位 / UCRT）
scripts/build.bat       PyInstaller 打包脚本
docs/使用说明.md         面向玩家的完整教程
```

## 免责

- 仅限在**你自己的账号**上使用。是否允许外部工具，请自行对照游戏用户协议与 Steam 条款。
- 「转化」「分解」会真实消耗物品且不可逆，使用前请用 `ALT + 左键` 锁好重要物品。
- 本程序按「现状」提供，作者不对任何物品损失、封号或其它后果负责。

## License

[MIT](LICENSE)
