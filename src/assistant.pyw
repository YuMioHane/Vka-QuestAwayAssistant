# -*- coding: utf-8 -*-
"""QuestAway 助手（分发包）

首次使用：点「选游戏路径」指向 Steam 库里的 QuestAway.exe，
然后「一键启动游戏」——它会给游戏带上调试端口，助手才连得上。

红线：身上装备（data-where=equip）与上锁物品（i.selo-trancada）永不触碰。
只点游戏自己的按钮、只拖游戏自己的格子，不改存档、不改协议、不伪造结算。
"""

import os
import sys
import time

# ---------- 最先落盘的启动标记：证明 Python 已经起来了 ----------
BASE = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
ERR_LOG = os.path.join(BASE, "helper_error.log")
_FALLBACK_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or BASE, "QuestAwayHelper")
_FALLBACK_LOG = os.path.join(_FALLBACK_DIR, "helper_error.log")


def log_error(text):
    """日志优先写程序目录；目录不可写时退到 %LOCALAPPDATA%。"""
    line = time.strftime("[%Y-%m-%d %H:%M:%S] ") + str(text).rstrip() + "\n"
    for p in (ERR_LOG, _FALLBACK_LOG):
        try:
            d = os.path.dirname(p)
            if d and not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                f.write(line)
            return True
        except Exception:
            continue
    return False


log_error("=== 启动 === pid=%s frozen=%s meipass=%s" % (
    os.getpid(), getattr(sys, "frozen", False), getattr(sys, "_MEIPASS", "-")))
log_error("exe=%s cwd=%s argv=%s" % (sys.executable, os.getcwd(), sys.argv))
try:
    import json
    import queue
    import subprocess
    import threading
    import traceback
    import webbrowser

    log_error("标准库导入完成，准备导入 tkinter")
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    log_error("tkinter 就绪")
    import cdp

    log_error("cdp 模块就绪")
except Exception:
    log_error("导入阶段失败\n" + traceback.format_exc())
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None, "依赖加载失败，把同目录的 helper_error.log 发给作者。",
            "QuestAway 助手", 0x10)
    except Exception:
        pass
    sys.exit(1)


class _Null:
    """窗口程序里 sys.stdout/stderr 是 None，库一写就炸，兜住。"""
    def write(self, *a):
        return 0

    def flush(self):
        pass


if sys.stdout is None:
    sys.stdout = _Null()
if sys.stderr is None:
    sys.stderr = _Null()


DATA_DIR = os.path.dirname(_FALLBACK_LOG)   # 配置仍放可写目录
CFG_PATH = os.path.join(DATA_DIR, "helper_config.json")
PORT = "9222"

RARITY = [("common", "普通"), ("uncommon", "精良"), ("rare", "稀有"),
          ("heroic", "英雄"), ("epic", "史诗"), ("mythic", "神话"),
          ("eternal", "永恒")]
CUBE_NEED = 8

AUTHOR_URL = "https://space.bilibili.com/8044987"

DEFAULT_CFG = {
    "game_exe": "",
    "map_a": "6:5", "map_b": "6:6", "map_stay": 60,
    "chest": 6, "craft": 120, "store": 60,
    "craft_rar": ["common"], "store_rar": ["common", "uncommon"],
    "notice_skip": False,
}

GUESS = [
    pat.format(d=d)
    for d in "CDEFGH"
    for pat in (r"{d}:\Steam\steamapps\common\QuestAway\QuestAway.exe",
                r"{d}:\SteamLibrary\steamapps\common\QuestAway\QuestAway.exe")
]


def load_cfg():
    cfg = dict(DEFAULT_CFG)
    # 兼容旧版：配置原来放在 exe 同目录
    legacy = os.path.join(BASE, "helper_config.json")
    for p in (CFG_PATH, legacy):
        try:
            with open(p, encoding="utf-8") as f:
                cfg.update(json.load(f))
            break
        except Exception:
            continue
    return cfg


def save_cfg(cfg):
    try:
        with open(CFG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def open_url(url):
    """打开外部链接：三种方式依次兜，绝不把异常抛到 Tk 回调里。"""
    try:
        if webbrowser.open(url):
            return True
    except Exception as e:
        log_error(f"webbrowser 打开失败：{e}")
    try:
        os.startfile(url)  # noqa: S606  Windows 专用
        return True
    except Exception as e:
        log_error(f"startfile 打开失败：{e}")
    try:
        messagebox.showwarning("打不开浏览器", f"请手动访问：\n{url}")
    except Exception:
        pass
    return False


def guess_game_exe():
    for pat in GUESS:
        p = pat
        if os.path.exists(p):
            return p
    return ""


def game_running():
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq QuestAway.exe"],
                             capture_output=True, timeout=8,
                             creationflags=0x08000000).stdout.decode("gbk", "ignore")
        return "QuestAway.exe" in out
    except Exception:
        return False


def launch_game(exe):
    """启动游戏；把 Windows 常见错误翻译成人话，绝不裸抛。"""
    env = dict(os.environ)
    env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"--remote-debugging-port={PORT}"
    try:
        subprocess.Popen([exe], cwd=os.path.dirname(exe), env=env,
                         creationflags=0x00000008)  # DETACHED_PROCESS
        return None
    except FileNotFoundError:
        return "找不到游戏文件，路径可能选错了，重新选一次 QuestAway.exe。"
    except PermissionError:
        return ("系统拒绝了启动（错误 5）。通常是杀毒软件拦截，"
                "把这个程序加入白名单后再试。")
    except OSError as e:
        code = getattr(e, "winerror", None)
        if code == 740:
            return ("游戏要求管理员权限（错误 740）。\n"
                    "请关掉助手，右键「以管理员身份运行」后再点一键启动。")
        if code == 193:
            return "选到的不是有效的 Windows 程序，路径选错了。"
        return f"启动失败：{e}"
    except Exception as e:
        return f"启动失败：{e}"


def close_windows(c, limit=5):
    for _ in range(limit):
        n = c.eval("(()=>{const xs=[...document.querySelectorAll('#winlayer .window .x')];"
                   "xs.forEach(b=>b.dispatchEvent(new MouseEvent('click',{bubbles:true})));"
                   "return xs.length;})()")
        if not n:
            break
        time.sleep(0.25)


def right_click_item(c, it, want=("inv", "stash")):
    """红线闸门 + 右键。

    - 合成面板**关着**时：右键背包物品=存入仓库，右键仓库物品=取回背包。
    - 合成面板**开着**时：右键背包物品=放入立方体（游戏行为，正好用来"先放一件"限定稀有度）。
    调用方通过 want 声明这次允许的来源位置；装备中/上锁的一律拒绝。
    """
    if it.get("where") not in want:
        return False
    g = c.eval(f"({cdp.SLOT_AT_JS})([{it['x']}, {it['y']}])")
    if not g or not g.get("ok") or g.get("where") not in want:
        return False
    cdp.right_click(c, it)
    return True


class Engine:
    def __init__(self, log):
        self.log = log
        self.stop = threading.Event()
        self.c = None
        self.stat = {"switches": 0, "chests": 0, "crafts": 0, "stored": 0}

    def ui_flags(self):
        s = self.scan()
        return {"bag": s["hasBag"], "bench": s["hasBench"], "stash": s["hasStash"]}

    def restore_ui(self, before):
        """收尾：只关闭「本次操作自己打开的窗口」，用户原本开着的保持原样。"""
        c = self.c
        if not c or not before:
            return
        try:
            now = self.scan()
        except Exception:
            return
        try:
            if now["hasBench"] and not before.get("bench"):
                cdp.close_window(c, "workbench")
                time.sleep(0.5)
            if now["hasStash"] and not before.get("stash"):
                cdp.close_window(c, "stash")
                time.sleep(0.4)
            if now["hasBag"] and not before.get("bag"):
                cdp.close_window(c, "inventory")
                time.sleep(0.4)
        except Exception as e:
            self.log(f"收尾关窗失败：{e}")

    def connect(self):
        if self.c:
            return self.c
        t = cdp.pick()
        self.c = cdp.CDP(t["webSocketDebuggerUrl"])
        self.log(f"已连接：{t.get('title')}")
        return self.c

    def alive(self):
        try:
            self.connect().eval("1")
            return True
        except Exception:
            self.c = None
            return False

    def scan(self):
        return self.connect().eval(cdp.UI_SCAN_JS)

    def ensure_ui(self, bag=True, bench=False, stash=False):
        c = self.connect()
        s = self.scan()
        if bag and not s["hasBag"]:
            cdp.bag(c, True)
            time.sleep(0.7)
            s = self.scan()
        if bench and not s["hasBench"]:
            cdp.act(c, "panel", "workbench")
            time.sleep(0.9)
            s = self.scan()
        if stash and not s["hasStash"]:
            cdp.act(c, "panel", "stash")
            time.sleep(0.9)
            s = self.scan()
        return s

    # ---------- 1 换图 ----------
    def switch_stage(self, target):
        c = self.connect()
        cdp.act(c, "mapstage", target)
        time.sleep(0.35)
        self.stat["switches"] += 1
        self.log(f"换图 → {target}")
        return True

    # ---------- 2 收箱 ----------
    def open_chests(self):
        c = self.connect()
        cs = c.eval(cdp.CHESTS_JS) or []
        pending = [x for x in cs if x["visible"]]
        if not pending:
            return 0
        opened, failed = [], []
        for x in pending:
            name = cdp.KIND_ZH.get(x["kind"], x["kind"] or "空槽")
            cdp.act(c, "grabchest", x["kind"])
            time.sleep(0.9)
            left = [y for y in (c.eval(cdp.CHESTS_JS) or [])
                    if y["visible"] and y["kind"] == x["kind"]]
            (failed if left else opened).append(name)
            if not left:
                self.stat["chests"] += 1
        if opened:
            self.log("收箱：" + "、".join(opened))
        if failed:
            self.log("没开掉：" + "、".join(failed))
        return len(opened)

    # ---------- 3 转化（右键做种 + 自动填入，全流程不拖拽） ----------
    def take_materials(self, stack, need):
        """把仓库里某材料右键取回背包，直到背包里该材料格数 >= need。"""
        c = self.connect()
        s = self.scan()
        if s["hasBench"]:
            cdp.close_window(c, "workbench")
            time.sleep(0.7)
            if self.scan()["hasBench"]:
                self.log("取材料中止：工作台关不掉（右键会放进立方体）")
                return 0
        s = self.ensure_ui(bag=True, stash=True)
        for _ in range(need + 6):
            s = self.scan()
            in_bag = len([m for m in s["bagMats"] if m["stack"] == stack])
            if in_bag >= need:
                return in_bag
            cand = next((m for m in s["stashMats"] if m["stack"] == stack), None)
            if not cand:
                break
            g = c.eval(f"({cdp.MAT_AT_JS})([{cand['x']}, {cand['y']}])")
            if not g or not g.get("ok"):
                break
            cdp.right_click(c, cand)
            time.sleep(0.3)
        return len([m for m in self.scan()["bagMats"] if m["stack"] == stack])

    def _fill_by_right_click(self, kind, key, need=CUBE_NEED):
        """用元素级右键把候选逐个放进立方体，直到面板显示 need 格。

        kind='mat' 按材料 stack，kind='item' 按稀有度；不用自动填入，也不用拖拽，
        更不依赖坐标（背包滚动、窗口遮挡都不影响）。
        """
        c = self.connect()
        stuck = 0
        for _ in range(need + 14):
            st = cdp.panel_state(c) or {}
            if st.get("ready") or st.get("filled", 0) >= need:
                break
            r = cdp.rc_element(c, kind, key)
            if not r.get("ok"):
                cdp.scroll_bag(c)
                time.sleep(0.45)
                stuck += 1
                if stuck > 10:
                    break
                continue
            stuck = 0
            time.sleep(0.5)
        return (cdp.panel_state(c) or {}).get("filled", 0)

    def _do_transmute(self, label):
        """点 ✦ 转化 并等揭晓动画走完再判定成败。"""
        c = self.connect()
        before = cdp.panel_state(c) or {}
        r = cdp.click_action_button(c)
        if not r.get("ok"):
            self.log(f"转化没点成：{label}，{r}")
            return False
        # 揭晓动画期间面板显示「⏳揭晓中……」，最多等 8 秒
        for _ in range(16):
            time.sleep(0.5)
            st = cdp.panel_state(c) or {}
            if st.get("filled", 0) == 0 and not st.get("ready"):
                self.stat["crafts"] += 1
                self.log(f"转化完成：{label}（消耗 {before.get('filled')} 格）")
                return True
        st = cdp.panel_state(c) or {}
        self.log(f"转化状态未确认：{label}，当前 {st.get('text', '')[:30]}")
        return True

    def craft_equipment(self, rarities=None, need=CUBE_NEED):
        """装备 8 合 1：右键逐个放入同稀有度的装备。"""
        c = self.connect()
        before_ui = self.ui_flags()
        rarities = rarities or ["common", "uncommon", "rare", "heroic", "mythic"]
        s = self.scan()
        if s["hasBench"]:
            cdp.close_window(c, "workbench")
            time.sleep(0.7)
            if self.scan()["hasBench"]:
                self.log("转化中止：工作台关不掉")
                self.restore_ui(before_ui)
                return False
        self.take(rarities, limit=30)
        self.ensure_ui(bag=True, bench=True)
        cdp.ensure_station(c, "转化")
        time.sleep(1.2)
        if (cdp.panel_state(c) or {}).get("filled"):
            cdp.act(c, "cubeclear")
            time.sleep(0.8)

        for rar in rarities:
            name = dict(RARITY).get(rar, rar)
            filled = self._fill_by_right_click("item", rar, need)
            if filled >= need or (cdp.panel_state(c) or {}).get("ready"):
                ok = self._do_transmute(f"装备·{name}")
                self.restore_ui(before_ui)
                return ok
            self.log(f"装备·{name}：右键放入 {filled}/{need}")
            cdp.act(c, "cubeclear")
            time.sleep(0.7)
        self.restore_ui(before_ui)
        return False

    def craft_material(self, stack=None, need=CUBE_NEED):
        """材料 8 合 1：右键逐个放入同种材料。"""
        c = self.connect()
        before_ui = self.ui_flags()
        s = self.scan()
        if s["hasBench"]:
            cdp.close_window(c, "workbench")
            time.sleep(0.7)
            if self.scan()["hasBench"]:
                self.log("转化中止：工作台关不掉")
                self.restore_ui(before_ui)
                return False
        s = self.ensure_ui(bag=True, stash=True)
        if s["freeBag"] < need:
            self.log(f"背包只剩 {s['freeBag']} 空格，先存装备腾格")
            self.store(["common", "uncommon", "rare", "heroic", "mythic", "epic"], limit=40)
            s = self.scan()

        if not stack:
            pool = {}
            for m in s["stashMats"] + s["bagMats"]:
                pool[m["stack"]] = pool.get(m["stack"], 0) + 1
            if not pool:
                self.log("转化：没有材料")
                return False
            stack = max(pool, key=lambda k: pool[k])

        have = self.take_materials(stack, need)
        title = next((m["title"] for m in self.scan()["bagMats"] if m["stack"] == stack), stack)
        if have < need:
            self.log(f"材料·{title}：背包只有 {have} 格，凑不满 {need}")
            self.restore_ui(before_ui)
            return False

        self.ensure_ui(bag=True, bench=True)
        cdp.ensure_station(c, "转化")
        time.sleep(1.2)
        if (cdp.panel_state(c) or {}).get("filled"):
            cdp.act(c, "cubeclear")
            time.sleep(0.8)

        filled = self._fill_by_right_click("mat", stack, need)
        if filled >= need or (cdp.panel_state(c) or {}).get("ready"):
            ok = self._do_transmute(f"材料·{title}")
            self.restore_ui(before_ui)
            return ok
        self.log(f"材料·{title}：右键放入 {filled}/{need}")
        cdp.act(c, "cubeclear")
        time.sleep(0.7)
        self.restore_ui(before_ui)
        return False

    # ---------- 5 分解 ----------
    def dismantle(self, rarities=None, kind="item", limit=8, bag_only=False):
        before_ui = None
        """分解：工位切到「分解」，右键放物品/材料，再点 ♻ 分解。

        和转化一样：仓库候选先取回背包，放不满不点按钮。
        """
        c = self.connect()
        before_ui = self.ui_flags()
        rarities = rarities or []
        if kind == "item" and not rarities:
            self.log("分解跳过：没勾稀有度")
            return False
        s = self.scan()
        if s["hasBench"]:
            cdp.close_window(c, "workbench")
            time.sleep(0.7)
            if self.scan()["hasBench"]:
                self.log("分解中止：工作台关不掉")
                return False
        if bag_only:
            # 严格模式：只动背包，绝不取仓库、绝不开仓库窗口
            self.ensure_ui(bag=True)
            n = len([i for i in self.scan()["bagItems"] if i["where"] == "inv"
                     and i["rar"] in rarities]) if kind == "item" else len(self.scan()["bagMats"])
            if not n:
                self.log("只分解背包：背包里没有符合条件的物品，跳过")
                self.restore_ui(before_ui)
                return False
        elif kind == "item":
            self.take(rarities, limit=30)
        else:
            s = self.ensure_ui(bag=True, stash=True)
            pool = {}
            for m in s["stashMats"] + s["bagMats"]:
                pool[m["stack"]] = pool.get(m["stack"], 0) + 1
            if not pool:
                self.log("分解：没有材料")
                self.restore_ui(before_ui)
                return False
            self.take_materials(max(pool, key=lambda k: pool[k]), limit)

        self.ensure_ui(bag=True, bench=True)
        cdp.ensure_station(c, "分解")
        time.sleep(1.3)
        if (cdp.panel_state(c) or {}).get("filled"):
            cdp.act(c, "cubeclear")
            time.sleep(0.7)

        placed, idle = 0, 0
        for _ in range(limit + 12):
            st = cdp.panel_state(c) or {}
            # 分解台放 1 件就能点，所以不按 ready 提前停，尽量凑一批再点
            if st.get("filled", 0) >= limit or idle >= 4:
                break
            if kind == "item":
                key = next((r for r in rarities
                            if cdp.rc_element(c, "item", r).get("ok")), None)
                r = {"ok": key is not None}
            else:
                m = next((x for x in self.scan()["bagMats"]), None)
                r = cdp.rc_element(c, "mat", m["stack"]) if m else {"ok": False}
            if not r.get("ok"):
                cdp.scroll_bag(c)
                time.sleep(0.4)
                idle += 1
                continue
            idle = 0
            placed += 1
            time.sleep(0.5)

        st = cdp.panel_state(c) or {}
        self.log(f"分解台已放 {st.get('filled', placed)} 格（可点：{st.get('ready')}）")
        if not st.get("ready"):
            self.log("分解：分解台没就绪，没点按钮")
            cdp.act(c, "cubeclear")
            time.sleep(0.6)
            self.restore_ui(before_ui)
            return False
        r = cdp.click_action_button(c)
        time.sleep(1.8)
        if r.get("ok"):
            self.log("分解已点，等结果")
            cdp.act(c, "cubeclear")
            time.sleep(0.6)
            self.restore_ui(before_ui)
            return True
        self.log(f"分解没点成：{r}")
        self.restore_ui(before_ui)
        return False

    def craft(self, mode="equipment"):
        if mode == "material":
            return self.craft_material()
        if mode == "both":
            return self.craft_equipment() or self.craft_material()
        return self.craft_equipment()

    # ---------- 4b 取回（仓库 → 背包，右键） ----------
    def take(self, rarities=None, limit=60):
        """右键仓库物品取回背包，直到背包装满或仓库没有符合条件的。

        搬运前必须先关工作台：合成面板开着会抢右键，物品容易被丢进立方体。
        """
        c = self.connect()
        s = self.scan()
        if s["hasBench"]:
            cdp.act(c, "close workbench")
            time.sleep(0.6)
        s = self.ensure_ui(bag=True, stash=True)
        if not s["hasStash"]:
            self.log("取回失败：仓库没打开")
            return 0
        moved, seen = 0, set()
        for _ in range(limit + 8):
            s = self.scan()
            if s["freeBag"] <= 0:
                self.log("取回停止：背包满了")
                break
            cand = next((it for it in s["stashItems"]
                         if (not rarities or it["rar"] in rarities)
                         and it["id"] not in seen), None)
            if not cand:
                break
            seen.add(cand["id"])
            if right_click_item(c, cand, want=("stash",)):
                moved += 1
            time.sleep(0.32)
        if moved:
            self.log(f"取回：右键取回 {moved} 件")
        return moved

    # ---------- 4 存仓 ----------
    def store_materials(self, limit=60):
        """把背包里的材料右键存进仓库（右键=直接存仓）。"""
        c = self.connect()
        moved = 0
        for _ in range(limit):
            s = self.scan()
            if not s["bagMats"]:
                break
            r = cdp.rc_element(c, "mat", s["bagMats"][0]["stack"])
            if not r.get("ok"):
                cdp.scroll_bag(c)
                time.sleep(0.4)
                continue
            moved += 1
            time.sleep(0.28)
        return moved

    def store(self, rarities, limit=60, include_mats=True):
        before_ui = self.ui_flags()
        """对背包物品右键直接存入仓库。

        不用拖拽：拖拽有落点风险，合成面板开着时可能把物品丢进立方体。
        右键是游戏自带的「直接存入」，不依赖任何落点。
        """
        c = self.connect()
        s = self.scan()
        if s["hasBench"]:
            cdp.act(c, "close workbench")
            time.sleep(0.6)
        s = self.ensure_ui(bag=True, stash=True)
        if not s["hasStash"]:
            self.log("存仓失败：仓库没打开")
            return 0

        moved, blocked, seen = 0, 0, set()
        for _ in range(limit + 8):
            s = self.scan()
            cand = next((it for it in s["bagItems"]
                         if it["where"] == "inv" and it["rar"] in rarities
                         and it["id"] not in seen), None)
            if not cand:
                break
            seen.add(cand["id"])
            if right_click_item(c, cand):
                moved += 1
            else:
                blocked += 1
            time.sleep(0.32)

        if include_mats:
            mats = self.store_materials(limit=limit)
            if mats:
                moved += mats
                self.log(f"存仓：材料 {mats} 格也进仓库了")
        self.restore_ui(before_ui)
        if moved:
            self.stat["stored"] += moved
            self.log(f"存仓：右键存入 {moved} 件")
        elif blocked:
            self.log(f"存仓：{blocked} 件被红线拦下（装备中/上锁/不是背包里的）")
        return moved


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        # 任何界面回调里的异常都记日志 + 弹窗，绝不让它把进程带走
        self.report_callback_exception = self._on_error
        self.title("QuestAway 助手")
        self.geometry("490x820+820+10")
        self.attributes("-topmost", True)
        self.cfg = load_cfg()
        self.q = queue.Queue()
        self.engine = Engine(self.q.put)
        self.worker = None
        self.snapshot = {}
        self._warned = False
        self._syncing = False
        self._build()
        self._refresh_cfg()
        for k in self.store_vars:
            self.store_vars[k].trace_add("write", lambda *_a, k=k: self._on_rar_toggle("store", k))
        for k in self.dis_vars:
            self.dis_vars[k].trace_add("write", lambda *_a, k=k: self._on_rar_toggle("dis", k))
        self.after(200, self.drain)
        self.after(300, self.poll_cfg)
        self.after(400, self.show_notice)

    # ---------- 启动声明弹窗 ----------
    def _on_error(self, exc, val, tb):
        text = "".join(traceback.format_exception(exc, val, tb))
        log_error("界面回调异常\n" + text)
        try:
            messagebox.showerror("出错了（已记录）", f"{val}\n\n日志：\n{ERR_LOG}")
        except Exception:
            pass

    def show_notice(self):
        if self.cfg.get("notice_skip"):
            return
        win = tk.Toplevel(self)
        win.title("关于本软件")
        win.transient(self)
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.configure(bg="#ffffff")
        body = ttk.Frame(win, padding=16)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="QuestAway 助手", font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w")
        ttk.Label(body, text="完全免费 · 开源（代码待上传 GitHub）",
                  font=("Microsoft YaHei UI", 11, "bold"), foreground="#2f9e44").pack(anchor="w", pady=(6, 10))
        ttk.Label(body, justify="left", wraplength=400,
                  text="如果有人向你收费（激活码、会员、代挂、付费下载等），\n"
                       "请立刻申请退款，并向平台举报。作者从未、也不会收任何费用。"
                  ).pack(anchor="w")
        ttk.Label(body, justify="left", wraplength=400, foreground="#8b93a1",
                  text="软件只操作游戏里本来就有的按钮与格子，不改存档、不改协议。\n"
                       "「自动转化」「自动存仓」为试验功能，会真实处理物品，后果自负；\n"
                       "身上装备与上锁物品程序硬拦，永不触碰。"
                  ).pack(anchor="w", pady=(10, 0))

        link = ttk.Label(body, text="作者 B 站主页 ↗", foreground="#1c7ed6", cursor="hand2")
        link.pack(anchor="w", pady=(10, 0))
        link.bind("<Button-1>", lambda e: open_url(AUTHOR_URL))
        ttk.Label(body, text=AUTHOR_URL, foreground="#8b93a1").pack(anchor="w")

        skip = tk.BooleanVar(value=False)
        ttk.Checkbutton(body, text="以后不再显示", variable=skip).pack(anchor="w", pady=(12, 8))

        def close():
            if skip.get():
                self.cfg["notice_skip"] = True
                save_cfg(self.cfg)
            win.destroy()

        row = ttk.Frame(body)
        row.pack(fill="x")
        ttk.Button(row, text="打开作者主页",
                   command=lambda: open_url(AUTHOR_URL)).pack(side="left")
        ttk.Button(row, text="我知道了", command=close).pack(side="right")

        win.protocol("WM_DELETE_WINDOW", close)

        win.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - win.winfo_width()) // 2
        y = self.winfo_rooty() + 80
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        win.grab_set()

    # ---------- UI ----------
    def _build(self):
        pad = {"padx": 10, "pady": (8, 0)}

        head = ttk.Frame(self)
        head.pack(fill="x", **pad)
        ttk.Label(head, text="QuestAway 助手", font=("Microsoft YaHei UI", 13, "bold")).pack(side="left")
        self.lbl = ttk.Label(head, text="未连接", foreground="#8b93a1")
        self.lbl.pack(side="right")

        g0 = ttk.LabelFrame(self, text=" 0 · 游戏 ", padding=8)
        g0.pack(fill="x", **pad)
        self.lbl_path = ttk.Label(g0, text="", foreground="#495057", wraplength=430, justify="left")
        self.lbl_path.grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Button(g0, text="选游戏路径", command=self.pick_exe).grid(row=1, column=0, pady=(6, 0), sticky="w")
        ttk.Button(g0, text="一键启动游戏", command=self.start_game).grid(row=1, column=1, padx=6, pady=(6, 0))
        ttk.Button(g0, text="连接", command=self.probe).grid(row=1, column=2, pady=(6, 0))
        ttk.Label(g0, text="先完全关闭游戏，再用这里启动", foreground="#c92a2a").grid(
            row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))

        g1 = ttk.LabelFrame(self, text=" 1 · 换图循环（不开地图，直接切） ", padding=8)
        g1.pack(fill="x", **pad)
        self.map_on = tk.BooleanVar()
        ttk.Checkbutton(g1, text="启用", variable=self.map_on).grid(row=0, column=0, sticky="w")
        ttk.Label(g1, text="图A").grid(row=0, column=1, padx=(10, 2))
        self.map_a = tk.StringVar()
        ttk.Entry(g1, textvariable=self.map_a, width=7).grid(row=0, column=2)
        ttk.Label(g1, text="图B").grid(row=0, column=3, padx=(10, 2))
        self.map_b = tk.StringVar()
        ttk.Entry(g1, textvariable=self.map_b, width=7).grid(row=0, column=4)
        ttk.Label(g1, text="停留(秒)").grid(row=0, column=5, padx=(10, 2))
        self.map_sec = tk.StringVar()
        ttk.Spinbox(g1, from_=5, to=3600, width=5, textvariable=self.map_sec).grid(row=0, column=6)

        g2 = ttk.LabelFrame(self, text=" 2 · 自动收箱（普通/白银/首领，看见就收） ", padding=8)
        g2.pack(fill="x", **pad)
        self.chest_on = tk.BooleanVar()
        ttk.Checkbutton(g2, text="启用", variable=self.chest_on).grid(row=0, column=0, sticky="w")
        ttk.Label(g2, text="检查间隔(秒)").grid(row=0, column=1, padx=(10, 2))
        self.chest_sec = tk.StringVar()
        ttk.Spinbox(g2, from_=2, to=600, width=5, textvariable=self.chest_sec).grid(row=0, column=2)

        g3 = ttk.LabelFrame(self, text=" 3 · 自动转化（工作台自动填入 → 转化） ", padding=8)
        g3.pack(fill="x", **pad)
        self.craft_on = tk.BooleanVar()
        ttk.Checkbutton(g3, text="启用", variable=self.craft_on).grid(row=0, column=0, sticky="w")
        ttk.Label(g3, text="间隔(秒)").grid(row=0, column=1, padx=(10, 2))
        self.craft_sec = tk.StringVar()
        ttk.Spinbox(g3, from_=20, to=7200, width=5, textvariable=self.craft_sec).grid(row=0, column=2)
        self.craft_vars = {}
        ttk.Label(g3, text="转化对象").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.craft_mode = tk.StringVar(value="材料")
        ttk.Combobox(g3, values=["材料", "装备", "材料+装备"], width=10, state="readonly",
                     textvariable=self.craft_mode).grid(row=1, column=1, sticky="w", pady=(6, 0))
        ttk.Label(g3, text="右键逐个放入 8 格 → 点转化（不用自动填入、不拖拽）",
                  foreground="#495057").grid(row=2, column=0, columnspan=4, sticky="w", pady=(2, 0))
        ttk.Label(g3, text="⚠ 试验功能：转化会消耗物品、结果不可逆，出问题后果自负",
                  foreground="#c92a2a").grid(row=3, column=0, columnspan=4, sticky="w", pady=(4, 0))
        ttk.Label(g3, text="装备中 / 上锁的物品永不触碰（程序硬拦）",
                  foreground="#8b93a1").grid(row=4, column=0, columnspan=4, sticky="w")

        g4 = ttk.LabelFrame(self, text=" 4 · 自动存仓（背包 → 仓库） ", padding=8)
        g4.pack(fill="x", **pad)
        self.store_on = tk.BooleanVar()
        ttk.Checkbutton(g4, text="启用", variable=self.store_on).grid(row=0, column=0, sticky="w")
        ttk.Label(g4, text="间隔(秒)").grid(row=0, column=1, padx=(10, 2))
        self.store_sec = tk.StringVar()
        ttk.Spinbox(g4, from_=20, to=7200, width=5, textvariable=self.store_sec).grid(row=0, column=2)
        pick2 = ttk.Frame(g4)
        pick2.grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))
        self.store_vars = {}
        for i, (k, z) in enumerate(RARITY[:6]):
            v = tk.BooleanVar()
            self.store_vars[k] = v
            ttk.Checkbutton(pick2, text=z, variable=v).grid(row=0, column=i, padx=(0, 6))
        self.store_mats = tk.BooleanVar(value=True)
        ttk.Checkbutton(pick2, text="材料", variable=self.store_mats).grid(row=0, column=6, padx=(10, 0))
        ttk.Label(g4, text="⚠ 试验功能：会自动移动背包物品，出问题后果自负",
                  foreground="#c92a2a").grid(row=2, column=0, columnspan=4, sticky="w", pady=(4, 0))
        ttk.Label(g4, text="装备中 / 上锁的物品永不触碰（程序硬拦）",
                  foreground="#8b93a1").grid(row=3, column=0, columnspan=4, sticky="w")

        g5 = ttk.LabelFrame(self, text=" 5 · 自动分解（工作台 ♻ 分解） ", padding=8)
        g5.pack(fill="x", **pad)
        self.dis_on = tk.BooleanVar()
        ttk.Checkbutton(g5, text="启用", variable=self.dis_on).grid(row=0, column=0, sticky="w")
        ttk.Label(g5, text="间隔(秒)").grid(row=0, column=1, padx=(10, 2))
        self.dis_sec = tk.StringVar(value="180")
        ttk.Spinbox(g5, from_=20, to=7200, width=5, textvariable=self.dis_sec).grid(row=0, column=2)
        ttk.Label(g5, text="对象").grid(row=0, column=3, padx=(10, 2))
        self.dis_kind = tk.StringVar(value="装备")
        ttk.Combobox(g5, values=["装备", "材料"], width=6, state="readonly",
                     textvariable=self.dis_kind).grid(row=0, column=4)
        pick3 = ttk.Frame(g5)
        pick3.grid(row=1, column=0, columnspan=5, sticky="w", pady=(6, 0))
        self.dis_vars = {}
        for i, (k, z) in enumerate(RARITY[:6]):
            v = tk.BooleanVar(value=(k in ("common", "uncommon")))
            self.dis_vars[k] = v
            ttk.Checkbutton(pick3, text=z, variable=v).grid(row=0, column=i, padx=(0, 6))
        self.dis_bagonly = tk.BooleanVar(value=True)
        ttk.Checkbutton(pick3, text="只分解背包内", variable=self.dis_bagonly).grid(
            row=0, column=6, padx=(10, 0))
        ttk.Label(g5, text="稀有度只对「对象=装备」生效；与存仓互斥——同一品阶只能选一边，"
                           "勾「只分解背包内」时绝不碰仓库和装备区",
                  foreground="#8b93a1", wraplength=430, justify="left").grid(
            row=2, column=0, columnspan=5, sticky="w")
        ttk.Label(g5, text="⚠ 试验功能：分解不可逆，后果自负", foreground="#c92a2a").grid(
            row=3, column=0, columnspan=5, sticky="w", pady=(2, 0))

        bar = ttk.Frame(self)
        bar.pack(fill="x", **pad)
        self.btn = ttk.Button(bar, text="开始挂机", command=self.toggle)
        self.btn.pack(side="left")
        ttk.Button(bar, text="收箱一次",
                   command=lambda: self.run_async(self.engine.open_chests)).pack(side="left", padx=6)
        ttk.Button(bar, text="转化一次",
                   command=lambda: self.run_async(self.engine.craft,
                                                  self.cfg.get("craft_mode", "material"))).pack(side="left")
        ttk.Button(bar, text="存仓一次", command=lambda: self.run_async(
            self.engine.store, self.picked_cfg("store_rar"))).pack(side="left", padx=6)
        ttk.Button(bar, text="取回一次",
                   command=lambda: self.run_async(self.engine.take, None)).pack(side="left")
        ttk.Button(bar, text="分解一次", command=lambda: self.run_async(
            self.engine.dismantle, list(self.cfg.get("dis_rar") or []),
            "mat" if self.cfg.get("dis_kind") == "材料" else "item",
            8, self.dis_bagonly.get())).pack(side="left", padx=6)

        # 底部：免费开源声明 + 作者主页（必须先于可扩展的日志框打包，否则会被挤没）
        bottom = ttk.Frame(self)
        bottom.pack(side="bottom", fill="x", padx=10, pady=(0, 8))
        ttk.Label(bottom, text="本软件完全免费、开源（代码待上传 GitHub）。若遇到收费，请立刻申请退款。",
                  foreground="#c92a2a", wraplength=450, justify="left").pack(side="top", anchor="w")
        linkrow = ttk.Frame(bottom)
        linkrow.pack(side="top", fill="x", pady=(4, 0))
        link = ttk.Label(linkrow, text="作者 B 站主页 ↗", foreground="#1c7ed6", cursor="hand2")
        link.pack(side="left")
        link.bind("<Button-1>", lambda e: open_url(AUTHOR_URL))
        ttk.Label(linkrow, text=f"   {AUTHOR_URL}", foreground="#8b93a1").pack(side="left")

        self.log_box = tk.Text(self, height=10, wrap="none", font=("Consolas", 9),
                               background="#fbfcfe", borderwidth=0)
        sb = ttk.Scrollbar(self, command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=sb.set, state="disabled")
        sb.pack(side="right", fill="y", pady=(8, 4))
        self.log_box.pack(fill="both", expand=True, padx=(10, 0), pady=(8, 4))

    # ---------- 配置 ----------
    def _refresh_cfg(self):
        c = self.cfg
        self.map_a.set(c["map_a"])
        self.map_b.set(c["map_b"])
        self.map_sec.set(str(c["map_stay"]))
        self.chest_sec.set(str(c["chest"]))
        self.craft_sec.set(str(c["craft"]))
        self.store_sec.set(str(c["store"]))
        for k, v in self.store_vars.items():
            v.set(k in c["store_rar"])
        rev = {"material": "材料", "equipment": "装备", "both": "材料+装备"}
        self.craft_mode.set(rev.get(c.get("craft_mode", "material"), "材料"))
        self.store_mats.set(c.get("store_mats", True))
        self.dis_sec.set(str(c.get("dis_sec", 180)))
        self.dis_kind.set(c.get("dis_kind", "装备"))
        for k, v in self.dis_vars.items():
            v.set(k in c.get("dis_rar", ["common", "uncommon"]))
        self.dis_bagonly.set(c.get("dis_bagonly", True))
        # 载入后去重：同一品阶只能选一边，存仓优先（保留 > 销毁）
        self._syncing = True
        dup = []
        for k in self.store_vars:
            if self.store_vars[k].get() and self.dis_vars[k].get():
                self.dis_vars[k].set(False)
                dup.append(dict(RARITY).get(k, k))
        self._syncing = False
        if dup:
            self.q.put("配置修正：存仓已占用 " + "、".join(dup) + "，分解里的同名品阶已取消")
        self._show_path()

    def _show_path(self):
        p = self.cfg.get("game_exe") or guess_game_exe()
        if p:
            self.lbl_path.config(text=f"游戏：{p}")
        else:
            self.lbl_path.config(text="游戏：未设置（点「选游戏路径」）")

    def _collect(self):
        self.cfg.update({
            "map_a": self.map_a.get().strip(), "map_b": self.map_b.get().strip(),
            "map_stay": self.map_sec.get(), "chest": self.chest_sec.get(),
            "craft": self.craft_sec.get(), "store": self.store_sec.get(),
            "store_rar": [k for k, v in self.store_vars.items() if v.get()],
            "craft_mode": {"材料": "material", "装备": "equipment",
                           "材料+装备": "both"}.get(self.craft_mode.get(), "material"),
            "store_mats": self.store_mats.get(),
            "dis_on": self.dis_on.get(), "dis_sec": self.dis_sec.get(),
            "dis_kind": self.dis_kind.get(),
            "dis_rar": [k for k, v in self.dis_vars.items() if v.get()],
            "dis_bagonly": self.dis_bagonly.get(),
            "map_on": self.map_on.get(), "chest_on": self.chest_on.get(),
            "craft_on": self.craft_on.get(), "store_on": self.store_on.get(),
        })
        save_cfg(self.cfg)
        return dict(self.cfg)

    def poll_cfg(self):
        self.snapshot = self._collect()
        self.after(1000, self.poll_cfg)

    def picked_cfg(self, key):
        return list(self.cfg.get(key) or [])

    def pick_exe(self):
        p = filedialog.askopenfilename(title="选择 QuestAway.exe", filetypes=[("QuestAway", "QuestAway.exe"), ("exe", "*.exe")])
        if p:
            self.cfg["game_exe"] = p
            save_cfg(self.cfg)
            self._show_path()

    # ---------- 动作 ----------
    def start_game(self):
        try:
            exe = self.cfg.get("game_exe") or guess_game_exe()
            if not exe or not os.path.exists(exe):
                messagebox.showwarning("缺游戏路径", "先点「选游戏路径」选到 QuestAway.exe")
                return
            self.cfg["game_exe"] = exe
            save_cfg(self.cfg)
            if game_running():
                messagebox.showinfo("先关游戏",
                                    "检测到 QuestAway 正在运行。\n"
                                    "请先完全退出游戏，再用这里启动，否则没有调试端口。")
                return
            err = launch_game(exe)
            if err:
                log_error("launch_game: " + err)
                messagebox.showerror("启动失败", err)
                return
            self.q.put("已启动游戏，等它出现窗口…")
            self.after(6000, self.probe)
        except Exception:
            log_error("start_game\n" + traceback.format_exc())
            messagebox.showerror("启动出错", f"详情已写入：\n{ERR_LOG}")

    def probe(self):
        try:
            self.engine.c = None
            self.engine.connect()
            self.lbl.config(text="已连接", foreground="#2f9e44")
        except Exception as e:
            self.lbl.config(text="未连上", foreground="#e03131")
            self.q.put(f"连接失败：{e}")

    def drain(self):
        try:
            while True:
                line = self.q.get_nowait()
                self.log_box.config(state="normal")
                self.log_box.insert("end", f"{time.strftime('%H:%M:%S')}  {line}\n")
                self.log_box.see("end")
                self.log_box.config(state="disabled")
        except queue.Empty:
            pass
        self.after(250, self.drain)

    def run_async(self, fn, *a):
        self._collect()
        threading.Thread(target=self._safe, args=(fn, *a), daemon=True).start()

    def _safe(self, fn, *a):
        try:
            fn(*a)
        except Exception as e:
            self.q.put(f"出错：{e}")
            self.engine.c = None

    def _rar_zh(self, key):
        return dict(RARITY).get(key, key)

    def _on_rar_toggle(self, which, key):
        """存仓与分解的稀有度互斥：同一个品阶只能选一边。"""
        if self._syncing:
            return
        sv, dv = self.store_vars.get(key), self.dis_vars.get(key)
        if not sv or not dv:
            return
        name = self._rar_zh(key)
        if which == "store" and sv.get() and dv.get():
            self._syncing = True
            dv.set(False)
            self._syncing = False
            self._hint(f"「{name}」已在存仓里 → 分解自动取消\n"
                       f"既然选择存{name}，那么就无法分解{name}")
        elif which == "dis" and dv.get() and sv.get():
            self._syncing = True
            sv.set(False)
            self._syncing = False
            self._hint(f"「{name}」已在分解里 → 存仓自动取消\n"
                       f"既然选择分解{name}，那么就无法存仓{name}")
        if not self._syncing:
            self._collect()

    def _hint(self, text, ms=2600):
        """不挡操作的轻提示框，自动消失。"""
        try:
            win = tk.Toplevel(self)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            win.configure(bg="#fff4e6")
            f = tk.Frame(win, bg="#fff4e6", highlightbackground="#e8590c",
                         highlightthickness=1)
            f.pack(fill="both", expand=True)
            tk.Label(f, text=text, bg="#fff4e6", fg="#a33b0a",
                     justify="left", padx=12, pady=8,
                     font=("Microsoft YaHei UI", 9)).pack()
            win.update_idletasks()
            x = self.winfo_rootx() + self.winfo_width() - win.winfo_width() - 24
            y = self.winfo_rooty() + self.winfo_height() - 90
            win.geometry(f"+{max(0, x)}+{max(0, y)}")
            win.after(ms, win.destroy)
        except Exception:
            pass

    def _abort_start(self):
        self.craft_on.set(False)
        self.dis_on.set(False)
        self._collect()
        self.btn.config(text="开始挂机")
        self.lbl.config(text="已取消", foreground="#e03131")
        self.q.put("已取消开始：你没点最终确认")

    def _ask(self, title, body, ok_text="确定", danger=False):
        """自绘模态确认框，返回是否点了 ok_text 那个按钮。"""
        win = tk.Toplevel(self)
        win.title(title)
        win.configure(bg="#ffffff")
        win.transient(self)
        win.attributes("-topmost", True)
        win.resizable(False, False)
        frame = ttk.Frame(win, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=title, font=("Microsoft YaHei UI", 13, "bold"),
                  foreground=("#c92a2a" if danger else "#1c1c1c")).pack(anchor="w")
        ttk.Label(frame, text=body, justify="left", wraplength=420).pack(anchor="w", pady=(10, 0))
        res = {"ok": False}
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(16, 0))

        def yes():
            res["ok"] = True
            win.destroy()

        def no():
            win.destroy()

        ttk.Button(row, text="取消", command=no).pack(side="left")
        b = ttk.Button(row, text=ok_text, command=yes)
        b.pack(side="right")
        if danger:
            try:
                b.configure(style="Danger.TButton")
            except Exception:
                pass
        win.protocol("WM_DELETE_WINDOW", no)
        win.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - win.winfo_width()) // 2
        y = self.winfo_rooty() + 120
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        win.grab_set()
        self.wait_window(win)
        return res["ok"]

    def toggle(self):
        if self.worker and self.worker.is_alive():
            self.engine.stop.set()
            self.btn.config(text="开始挂机")
            self.lbl.config(text="已停止")
            return
        # 勾了「转化」或「分解」→ 两次弹窗，第二次必须点「我真的确认了」
        if self.craft_on.get() or self.dis_on.get():
            if not self._ask(
                "⚠ 物品安全提示",
                "你勾选了「自动转化」和/或「自动分解」。\n\n"
                "请自行使用  ALT + 左键  锁住自己重要的物品，\n"
                "不然可能会出现意料之外的 bug 导致物品被分解。\n\n"
                "（程序会硬拦装备栏与带锁物品，但无法保证 100% 无误。）",
                ok_text="我已了解，继续"):
                self._abort_start()
                return
            if not self._ask(
                "⚠ 最后确认",
                "转化 / 分解会真实消耗物品，且不可逆。\n\n"
                "确认现在开始挂机？",
                ok_text="我真的确认了", danger=True):
                self._abort_start()
                return
        elif self.store_on.get() and not self._warned:
            ok = messagebox.askyesno(
                "试验功能警告",
                "你勾选了「自动存仓」。\n\n"
                "这个功能属于试验功能，会真的移动你的物品，\n"
                "一旦判断失误或游戏改版，物品可能被误处理，后果自负。\n\n"
                "确定继续？")
            if not ok:
                self._abort_start()
                return
            self._warned = True
        snap = self._collect()
        self.engine.stop.clear()
        self.worker = threading.Thread(target=self.loop, args=(snap,), daemon=True)
        self.worker.start()
        self.btn.config(text="停止")
        self.lbl.config(text="运行中", foreground="#2f9e44")

    # ---------- 主循环 ----------
    def loop(self, snap):
        """后台线程只读 self.snapshot（主线程每秒刷新），不直接碰 Tk 变量。"""
        e = self.engine
        to_b = False
        next_switch = time.time() + max(5.0, float(snap["map_stay"] or 60))
        next_chest = next_craft = next_store = next_dis = 0.0
        self.q.put("启动：换图 %s⇄%s/%ss | 收箱 %ss | 转化 %ss | 存仓 %ss" % (
            snap["map_a"], snap["map_b"], snap["map_stay"],
            snap["chest"], snap["craft"], snap["store"]))

        while not e.stop.is_set():
            s = self.snapshot or snap
            now = time.time()
            stay = max(5.0, float(s["map_stay"] or 60))
            chest_every = max(2.0, float(s["chest"] or 6))
            craft_every = max(20.0, float(s["craft"] or 120))
            store_every = max(20.0, float(s["store"] or 60))

            if not e.alive():
                self.q.put("连不上游戏（端口关了吗？），5 秒后重试")
                if e.stop.wait(5):
                    break
                continue
            try:
                if s.get("map_on") and now >= next_switch:
                    e.switch_stage(s["map_b"] if to_b else s["map_a"])
                    to_b = not to_b
                    next_switch = time.time() + stay
                if s.get("chest_on") and now >= next_chest:
                    e.open_chests()
                    next_chest = time.time() + chest_every
                if s.get("craft_on") and now >= next_craft:
                    e.craft(s.get("craft_mode") or "material")
                    next_craft = time.time() + craft_every
                if s.get("store_on") and now >= next_store:
                    e.store(list(s.get("store_rar") or []), include_mats=s.get("store_mats", True))
                    next_store = time.time() + store_every
                if s.get("dis_on") and now >= next_dis:
                    e.dismantle(list(s.get("dis_rar") or []),
                                kind=("mat" if s.get("dis_kind") == "材料" else "item"),
                                bag_only=s.get("dis_bagonly", True))
                    next_dis = time.time() + max(20.0, float(s.get("dis_sec") or 180))
            except Exception as ex:
                self.q.put(f"出错：{ex}")
                e.c = None
            e.stop.wait(0.5)

        self.q.put("已停止")


if __name__ == "__main__":
    import faulthandler

    def _hook(exc, val, tb):
        log_error("未捕获异常\n" + "".join(traceback.format_exception(exc, val, tb)))

    def _thook(args):
        log_error("线程未捕获异常(%s)\n" % args.thread.name
                  + "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))

    sys.excepthook = _hook
    try:
        threading.excepthook = _thook
    except Exception:
        pass
    try:
        _fh = open(ERR_LOG, "a", encoding="utf-8")
        faulthandler.enable(file=_fh)
    except Exception:
        _fh = None
    try:
        App().mainloop()
    except SystemExit:
        # tkinter 会把回调里的 SystemExit 原样抛出，必须单独识别，否则日志会误报“正常退出”
        log_error("主循环被 SystemExit 结束：某个回调里还有 sys.exit()，这是 bug\n"
                  + traceback.format_exc())
        sys.exit(1)
    except Exception:
        detail = traceback.format_exc()
        log_error("启动失败\n" + detail)
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None, f"助手启动失败：\n\n{detail[-800:]}\n\n日志：{ERR_LOG}",
                "QuestAway 助手", 0x10)
        except Exception:
            pass
        sys.exit(1)
    finally:
        log_error("=== 正常退出 pid=%s ===" % os.getpid())
