# -*- coding: utf-8 -*-
"""QuestAway CDP 桥：从外部向游戏页面发指令（调用它自己的 JS 函数）

前提：游戏用 launch_debug.bat 启动（带 --remote-debugging-port=9222）。

命令：
    python cdp.py targets                 列出可调试页面
    python cdp.py eval "1+1"              执行任意 JS 并按值返回
    python cdp.py call "app.ui.openBag()" 调用页面里的函数（就是"发指令"）
    python cdp.py probe                   探测页面里有哪些游戏对象/函数，写 probe.json
"""

import json
import os
import platform
import socket
import subprocess
import sys
import time
import urllib.request

try:
    import websocket  # websocket-client
except ImportError:
    raise ImportError("缺依赖 websocket-client，请 pip install websocket-client")

PORT = int(os.environ.get("CDP_PORT", "9222"))
BASE = os.path.dirname(os.path.abspath(__file__))

# 本机开了系统代理（clash 之类）时 urllib 会把 127.0.0.1 也塞给代理，返回 502。全部绕开。
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class CdpError(RuntimeError):
    """连不上游戏 / 没有页面。GUI 里必须抛这个，绝不能 sys.exit——
    tkinter 会把回调里的 SystemExit 原样抛出，直接结束 mainloop（表现就是闪退）。"""


_NO_WIN = 0x08000000  # CREATE_NO_WINDOW：别在用户面前闪黑框


def _port_listening(port=None):
    """端口上到底有没有人在听。比直接 HTTP 更快，也不受代理影响。"""
    port = port or PORT
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.8)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def port_owner(port=None):
    """谁在监听这个端口，返回 'xxx.exe (PID 1234)'；查不到返回空串。"""
    port = port or PORT
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True,
                             timeout=8, creationflags=_NO_WIN).stdout.decode("gbk", "ignore")
    except Exception:
        return ""
    for line in out.splitlines():
        p = line.split()
        if len(p) >= 5 and p[1].endswith(":%d" % port) and p[3].upper() == "LISTENING":
            pid = p[4]
            try:
                t = subprocess.run(["tasklist", "/FI", "PID eq %s" % pid], capture_output=True,
                                   timeout=8, creationflags=_NO_WIN).stdout.decode("gbk", "ignore")
                for l2 in t.splitlines():
                    if l2.strip().startswith("QuestAway") or ".exe" in l2:
                        name = l2.split()[0]
                        if name.lower() != "映像名称" and name.lower() != "image":
                            return f"{name} (PID {pid})"
            except Exception:
                pass
            return f"PID {pid}"
    return ""


def _proc_running(name):
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq %s" % name], capture_output=True,
                             timeout=8, creationflags=_NO_WIN).stdout.decode("gbk", "ignore")
        return name.lower() in out.lower()
    except Exception:
        return False


def _proc_count(name):
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq %s" % name], capture_output=True,
                             timeout=8, creationflags=_NO_WIN).stdout.decode("gbk", "ignore")
        return sum(1 for l in out.splitlines() if name.lower() in l.lower())
    except Exception:
        return 0


def webview2_version():
    """WebView2 Runtime 版本。Win11 自带，Win10 要靠 Edge 带装或单独装。"""
    try:
        import winreg
    except Exception:
        return "读不到（非 Windows）"
    paths = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\EdgeUpdate\Clients"),
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\EdgeUpdate\Clients"),
    ]
    for root, path in paths:
        try:
            k = winreg.OpenKey(root, path)
        except OSError:
            continue
        try:
            n = winreg.QueryInfoKey(k)[0]
        except Exception:
            continue
        for i in range(n):
            try:
                sub = winreg.OpenKey(k, winreg.EnumKey(k, i))
                name = str(winreg.QueryValueEx(sub, "name")[0])
                if "WebView2" in name:
                    return "%s %s" % (name, winreg.QueryValueEx(sub, "pv")[0])
            except Exception:
                continue
    return "没装（Win10 常见，去微软官网下 Evergreen 运行时）"


def _why_no_port(err):
    """把「连不上」翻译成能直接照着做的结论。"""
    if _port_listening():
        who = port_owner() or "未知程序"
        return ("127.0.0.1:%d 有程序在监听，但不是游戏的调试端口：%s\n"
                "这个端口被别的软件占了，游戏就开不出调试端口。\n"
                "把占用它的程序关掉，再重新「一键启动游戏」。\n"
                "（原始错误：%s）" % (PORT, who, err))
    return ("127.0.0.1:%d 上没有任何程序在监听 —— 游戏的调试端口没开。\n"
            "按顺序自查：\n"
            "1. 游戏必须用助手的「一键启动游戏」拉起；直接开 Steam、双击桌面图标都不会带调试端口\n"
            "2. 启动前要完全退出游戏（任务管理器里不能还有 QuestAway.exe）\n"
            "3. 冷启动可能要十几秒到一分钟，多等一会儿再点「连接」\n"
            "（原始错误：%s）" % (PORT, err))


def targets(timeout=5):
    try:
        with _OPENER.open(f"http://127.0.0.1:{PORT}/json", timeout=timeout) as r:
            return json.load(r)
    except Exception as e:
        raise CdpError(_why_no_port(e))


def diagnose(game_exe=""):
    """连不上时把现场信息一次性摊开，用户复制发给作者就能定位。"""
    out = ["—— 诊断 ——"]
    try:
        out.append("时间：%s" % time.strftime("%Y-%m-%d %H:%M:%S"))
        out.append("系统：%s" % platform.platform())
    except Exception:
        pass
    out.append("游戏 exe：%s" % (game_exe or "未设置"))
    out.append("WebView2 Runtime：%s" % webview2_version())

    living = _port_listening()
    out.append("端口 %d 有程序监听：%s" % (PORT, "是" if living else "否"))
    if living:
        out.append("监听者：%s" % (port_owner() or "查不到（试试以管理员运行）"))
        try:
            ts = targets(timeout=3)
            out.append("调试页面 %d 个：" % len(ts))
            for t in ts:
                out.append("  · [%s] %s %s" % (t.get("type"), t.get("url"), t.get("title") or ""))
        except Exception as e:
            out.append("读 /json 失败：%s" % e)
    else:
        out.append("QuestAway.exe 在运行：%s" % ("是" if _proc_running("QuestAway.exe") else "否"))
        n = _proc_count("msedgewebview2.exe")
        out.append("msedgewebview2.exe 进程数：%d" % n)
        out.append("→ 端口没开：游戏启动时没带上调试参数，或者还没启动完")
        if n:
            out.append("  机器上已经有一批 WebView2 进程。WebView2 是按「用户数据目录」"
                       "单例的，旧的进程组还活着时，新启动的游戏会直接复用它，\n"
                       "  此时调试端口参数会被忽略 —— 这是「明明用助手启动的却连不上」的常见原因。\n"
                       "  最省事的解法：重启一次电脑，再打开助手「一键启动游戏」。")
    out.append("—— 诊断结束 ——")
    return "\n".join(out)


def _rank(t):
    u = t.get("url", "")
    if "tauri.localhost" in u and u.rstrip("/").endswith("localhost"):
        return 0
    if "tauri.localhost" in u:
        return 1
    return 2


# 判定「这个页面是不是游戏主界面」——只读 DOM，不点任何东西
IS_GAME_JS = r"""
(() => {
  const q = s => document.querySelectorAll(s).length;
  return {
    winlayer: !!document.querySelector('#winlayer'),
    dock: !!document.querySelector('#dock'),
    actions: q('[data-action]'),
    slots: q('.slot'),
    href: location.href,
    title: document.title || ''
  };
})()
"""


def is_game_page(info):
    """游戏主界面有 #winlayer（窗口层）；log.html 只有 5 个零散按钮、0 个格子。"""
    if not info:
        return False
    return bool(info.get("winlayer")) or (info.get("slots") or 0) >= 20


def pick_game(max_try=8, render_wait=0.0):
    """挑「真正的游戏主界面」，返回 (CDP, info, target)。

    9222 上一般有两个 page：主界面 `http://tauri.localhost/` 和
    日志页 `http://tauri.localhost/log.html`。两个 WebSocket 都能连上，
    但只有主界面有 #winlayer / .slot。以前只按 URL 排序就选第一个，
    主界面还没加载完时会连到日志页 —— 表现正是「显示已连接，但所有
    功能都没反应」（scan 全是空，而空结果不报错，于是一直错下去）。

    render_wait > 0 时，主页面 DOM 还没长出来（格子数 0）会再等几轮，
    因为游戏是单页应用，格子是 JS 生成的，刚起来那一两秒必然是 0。
    不等的话，冷启动慢的机器会被误判成「没找到游戏主界面」。
    """
    ts = [t for t in targets() if t.get("type") == "page"]
    if not ts:
        raise CdpError("没有找到游戏页面，游戏主窗口可能还没起来。")
    ts.sort(key=_rank)

    seen = []
    for t in ts[:max_try]:
        url = t.get("url", "?")
        try:
            c = CDP(t["webSocketDebuggerUrl"])
        except Exception as e:
            seen.append(f"{url}：连不上（{e}）")
            continue
        try:
            info = c.eval(IS_GAME_JS) or {}
        except Exception as e:
            c.close()
            seen.append(f"{url}：读不到页面（{e}）")
            continue
        if is_game_page(info):
            return c, info, t
        if render_wait > 0 and _rank(t) == 0:
            for _ in range(2):
                time.sleep(render_wait)
                try:
                    info = c.eval(IS_GAME_JS) or {}
                except Exception:
                    break
                if is_game_page(info):
                    return c, info, t
        c.close()
        seen.append(f'{url}：不是游戏界面（格子 {info.get("slots", 0)}、'
                    f'动作 {info.get("actions", 0)}、窗口层 {info.get("winlayer")}）')

    raise CdpError(
        "端口连上了，但没找到游戏主界面。\n"
        + ("\n".join("· " + s for s in seen) if seen else "· 没有可用的页面")
        + "\n\n游戏可能还在加载，或只连到了日志页。等游戏主界面出来后点「连接」再试。")


def pick():
    """返回游戏主页面的 target（内部会验证页面真的是游戏主界面）。"""
    c, _info, t = pick_game()
    c.close()
    return t


class CDP:
    def __init__(self, url):
        # Chromium 111+ 会用 403 拒绝带 Origin 头的 WebSocket；不发 Origin 即可，不加 --remote-allow-origins
        self.ws = websocket.create_connection(
            url, timeout=20, max_size=64 * 1024 * 1024, suppress_origin=True,
            http_no_proxy=["127.0.0.1", "localhost"], http_proxy_host=None)
        self.i = 0

    def call(self, method, **params):
        self.i += 1
        self.ws.send(json.dumps({"id": self.i, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.i:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result", {})

    def eval(self, expr, await_promise=False):
        r = self.call("Runtime.evaluate", expression=expr, returnByValue=True,
                      awaitPromise=await_promise, userGesture=True)
        res = r.get("result", {})
        if r.get("exceptionDetails"):
            raise RuntimeError(json.dumps(r["exceptionDetails"].get("exception", {}), ensure_ascii=False)[:800])
        return res.get("value")

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


PROBE_JS = r"""
(() => {
  const skip = new Set(['window','self','document','location','navigator','top','parent','frames',
    'localStorage','sessionStorage','indexedDB','caches','console','screen','history','customElements',
    'performance','crypto','speechSynthesis','visualViewport','opener','origin','name','closed','length',
    'innerWidth','innerHeight','outerWidth','outerHeight','devicePixelRatio','scrollX','scrollY',
    'isSecureContext','crossOriginIsolated','frameElement','event','clientInformation','external']);
  const globals = {};
  for (const k of Object.getOwnPropertyNames(window)) {
    if (skip.has(k) || k.startsWith('webkit') || k.startsWith('on')) continue;
    let v; try { v = window[k]; } catch (e) { continue; }
    if (v === null || v === undefined) continue;
    const t = typeof v;
    if (t === 'function') { globals[k] = 'function(' + (v.length || 0) + ')'; continue; }
    if (t !== 'object') continue;
    if (v === window || v.nodeType) continue;
    let keys = [];
    try { keys = Object.keys(v).slice(0, 40); } catch (e) {}
    globals[k] = {__keys: keys, __n: keys.length};
  }
  const looks = {};
  const want = /bag|invent|stash|panel|ui|game|state|save|tela|janela|abrir|open|modal/i;
  for (const [k, v] of Object.entries(globals)) {
    if (v && typeof v === 'object' && want.test(k)) looks[k] = v;
  }
  const domHints = {
    buttons: [...document.querySelectorAll('[class*=bag],[id*=bag],[class*=inv],[id*=inv]')]
      .slice(0, 20).map(e => ({ tag: e.tagName, id: e.id, cls: (e.className || '').toString().slice(0, 80) })),
    canvases: document.querySelectorAll('canvas').length,
    iframes: [...document.querySelectorAll('iframe')].map(f => f.src).slice(0, 5)
  };
  return { url: location.href, title: document.title, globals, looks, domHints };
})()
"""


LEARN_JS = r"""
(() => {
  if (window.__qaRec) return 'already installed';
  window.__qaLast = null;
  window.__qaLog = [];
  document.addEventListener('click', (e) => {
    const el = e.target && e.target.closest ? e.target.closest('[data-action]') : null;
    if (!el) return;
    const rec = {a: el.dataset.action, arg: el.dataset.arg || '',
                 tip: el.dataset.tip || '', txt: (el.textContent || '').trim().slice(0, 20)};
    window.__qaLast = rec;
    window.__qaLog.push(rec);
    if (window.__qaLog.length > 50) window.__qaLog.shift();
  }, true);
  window.__qaRec = 1;
  return 'installed';
})()
"""

ACT_JS = r"""
([action, arg, allowSynthetic]) => {
  const sel = arg ? `[data-action="${action}"][data-arg="${arg}"]` : `[data-action="${action}"]`;
  const all = [...document.querySelectorAll(sel)];
  const visible = all.find(e => {
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  });
  const fire = node => node.dispatchEvent(new MouseEvent('click', {
    bubbles: true, cancelable: true, composed: true, view: window, button: 0
  }));

  if (all.length) {
    fire(visible || all[0]);
    return {mode: 'real', count: all.length, visible: !!visible};
  }
  if (!allowSynthetic) return {mode: 'none', count: 0};

  // 元素不在页面上：挂到事件委托的根节点里再派发（不在 body 上，否则委托收不到）
  const host = document.querySelector('#app') || document.body;
  const fake = document.createElement('button');
  fake.dataset.action = action;
  if (arg) fake.dataset.arg = arg;
  fake.style.cssText = 'position:fixed;left:-9999px;top:-9999px;width:1px;height:1px;';
  host.appendChild(fake);
  fire(fake);
  setTimeout(() => fake.remove(), 0);
  return {mode: 'synthetic', count: 0};
}
"""

LIST_JS = r"""
(() => {
  const m = {};
  for (const e of document.querySelectorAll('[data-action]')) {
    const r = e.getBoundingClientRect();
    const k = e.dataset.action + (e.dataset.arg ? ' ' + e.dataset.arg : '');
    m[k] = (m[k] || 0) + (r.width > 0 && r.height > 0 ? 1 : 0);
  }
  return m;
})()
"""


def act(c, action, arg="", allow_synthetic=True):
    payload = json.dumps([action, arg, allow_synthetic])
    r = c.eval(f"({ACT_JS})({payload})")
    # 地图上的关卡按钮只在地图窗口开着时才存在，先开地图再试
    if r.get("mode") == "none" and action == "mapstage":
        act(c, "frontier", "", False)
        time.sleep(0.7)
        r = c.eval(f"({ACT_JS})({payload})")
    return r


VK = {
    "esc": 27, "enter": 13, "space": 32, "tab": 9, "backspace": 8,
    "left": 37, "up": 38, "right": 39, "down": 40,
    **{f"f{i}": 111 + i for i in range(1, 13)},
}


def press(c, key):
    """往页面里注入一次真实按键（走 CDP Input，等同物理键盘）"""
    k = key.lower()
    if len(k) == 1 and k.isalpha():
        vk, code = ord(k.upper()), f"Key{k.upper()}"
    elif len(k) == 1 and k.isdigit():
        vk, code = ord(k), f"Digit{k}"
    elif k in VK:
        vk, code = VK[k], k.capitalize()
    else:
        raise ValueError(f"不认识的键: {key}")

    for t in ("keyDown", "keyUp"):
        c.call("Input.dispatchKeyEvent", type=t, key=k, code=code,
               windowsVirtualKeyCode=vk, nativeVirtualKeyCode=vk)
        time.sleep(0.05)
    return {"key": k, "vk": vk}


def status(c):
    js = r"""
(() => {
  const vis = [];
  for (const e of document.querySelectorAll('[data-action]')) {
    const r = e.getBoundingClientRect();
    if (r.width > 0 && r.height > 0) vis.push(e.dataset.action + (e.dataset.arg ? ' ' + e.dataset.arg : ''));
  }
  return {
    focus: document.hasFocus(),
    inner: [innerWidth, innerHeight],
    wins: [...document.querySelectorAll('#winlayer .window')].map(w => w.className),
    bagOpen: !!document.querySelector('#dock'),
    visibleActions: [...new Set(vis)]
  };
})()
"""
    return c.eval(js)


def bag(c, open_it=True):
    """背包（物品栏）= togglehub 打开的中心窗口，里面含 #dock。"""
    s = status(c)
    if s["bagOpen"] == open_it:
        return {"changed": False, "bagOpen": s["bagOpen"]}
    r = act(c, "togglehub")
    time.sleep(0.8)
    return {"changed": True, "bagOpen": status(c)["bagOpen"], "how": r.get("mode")}


ITEMS_JS = r"""
(() => [...document.querySelectorAll('[data-item]')].map(e => {
  const m = (e.className || '').match(/r-([a-z]+)/);
  const r = e.getBoundingClientRect();
  return {
    id: e.dataset.item, where: e.dataset.where || '', slot: e.dataset.slot || '',
    rarity: m ? m[1] : '', vis: r.width > 0 && r.height > 0
  };
}))()
"""

CHESTS_JS = r"""
(() => [...document.querySelectorAll('[data-action="grabchest"]')].map(e => {
  const r = e.getBoundingClientRect();
  const badge = ((e.querySelector('.cfn') || {}).textContent || '').trim();
  return {
    kind: e.dataset.kind || '', el: e.id, badge,
    // 槽位可见 = 有这个箱子可收；data-tip 里的「已存 x/y」是模板文本，不可信
    visible: r.width > 0 && r.height > 0,
    title: e.dataset.tiptitle || ''
  };
}))()
"""

KIND_ZH = {"normal": "普通", "silver": "白银", "gold": "黄金",
           "stage": "首领", "boss": "首领", "colosso": "巨像"}


# 拖拽前再验一次源头：必须是背包/仓库里没上锁的物品，绝不是身上装备

UI_SCAN_JS = r"""
(() => {
  const ws = [...document.querySelectorAll('#winlayer .window')];
  // 用窗口关闭按钮的 data-arg 认窗口，跟游戏语言无关（inventory / stash / workbench）
  const argOf = w => { const b = w.querySelector('.x'); return b ? (b.dataset.arg || '') : ''; };
  const bag = ws.find(w => argOf(w) === 'inventory') || ws.find(w => w.querySelector('#dock'));
  const bench = ws.find(w => argOf(w) === 'workbench') || ws.find(w => w.querySelector('[data-drop=cube]'));
  const stash = ws.find(w => argOf(w) === 'stash')
      || ws.find(w => w !== bag && w !== bench && w.querySelectorAll('.slot').length >= 20);
  const ctr = e => { const r = e.getBoundingClientRect(); return {x: r.x + r.width / 2, y: r.y + r.height / 2}; };
  const rar = e => (e.className.match(/r-([a-z]+)/) || [])[1] || '';
  // 红线：身上装备（data-where=equip）与上锁物品（子节点 .selo-trancada）一律排除
  const locked = e => !!(e.querySelector('.selo-trancada') || e.classList.contains('selo-trancada'));
  const movable = e => e.dataset.where !== 'equip' && e.dataset.item && !locked(e);
  const bagItems = bag ? [...bag.querySelectorAll('.slot[data-item]')].filter(movable).map(e => ({
      id: e.dataset.item, where: e.dataset.where || '', rar: rar(e), ...ctr(e)
  })) : [];
  const stashItems = stash ? [...stash.querySelectorAll('.slot[data-item]')].filter(movable).map(e => ({
      id: e.dataset.item, where: 'stash', rar: rar(e), ...ctr(e)
  })) : [];
  const matOf = w => w ? [...w.querySelectorAll('.slot.mat')]
      .filter(e => e.getBoundingClientRect().width > 0 && !e.querySelector('.selo-trancada'))
      .map(e => ({stack: e.dataset.stack || '', title: e.dataset.tiptitle || '',
                  qty: +(e.dataset.tipval || 0), ...ctr(e)})) : [];
  const bagMats = matOf(bag);
  const stashMats = matOf(stash);
  const equipped = (bag ? [...bag.querySelectorAll('.slot[data-item]')] : []).filter(e => e.dataset.where === 'equip').length;
  const lockedCount = [...document.querySelectorAll('.slot')].filter(locked).length;
  const all = bench ? [...bench.querySelectorAll('.ccell')] : [];
  // .ccell.out 是产出格，不算输入位
  const cube = all.filter(e => !e.classList.contains('out')).map(e => ({
      filled: e.children.length > 0, ...ctr(e)
  }));
  const out = all.filter(e => e.classList.contains('out')).map(e => ({
      filled: e.children.length > 0, ...ctr(e)
  }));
  const free = stash ? [...stash.querySelectorAll('.slot')]
      .filter(s => !s.dataset.item && s.getBoundingClientRect().width > 0).map(ctr) : [];
  // 背包空格：排除空装备槽（带 data-slot）与材料/宝石/药水格（带 data-stack 或 .mat）
  const freeBag = bag ? [...bag.querySelectorAll('.slot')].filter(s =>
      !s.dataset.item && !s.dataset.slot && !s.dataset.stack
      && !s.classList.contains('mat')
      && s.dataset.where !== 'equip'
      && s.getBoundingClientRect().width > 0).length : 0;
  return {hasBag: !!bag, hasBench: !!bench, hasStash: !!stash,
          bagItems, stashItems, bagMats, stashMats, cube, out, free, freeBag,
          equipped, lockedCount,
          // 页面身份：连错页（比如 log.html）时这两个都是 0/false，调用方据此重连
          winlayer: !!document.querySelector('#winlayer'),
          slots: document.querySelectorAll('.slot').length,
          cubeFilled: cube.filter(c => c.filled).length,
          outFilled: out.filter(c => c.filled).length};
})()
"""

# 拖拽前再验一次源头：必须是背包/仓库里没上锁的物品，绝不是身上装备
SLOT_AT_JS = r"""
([x, y]) => {
  const el = document.elementFromPoint(x, y);
  const s = el && el.closest ? el.closest('.slot') : null;
  if (!s) return {ok: false, why: 'no-slot'};
  const locked = !!(s.querySelector('.selo-trancada') || s.classList.contains('selo-trancada'));
  return {ok: s.dataset.where !== 'equip' && !locked && !!s.dataset.item,
          where: s.dataset.where || '', id: s.dataset.item || '',
          locked, why: s.dataset.where === 'equip' ? 'equipped' : (locked ? 'locked' : '')};
}
"""

# 工作台面板状态：输入格填了几格、动作按钮（✦ 转化 / ⚒ 锻造）能不能点
# 材料格校验（材料没有 data-item，不能用 SLOT_AT_JS）
MAT_AT_JS = r"""
([x, y]) => {
  const el = document.elementFromPoint(x, y);
  const s = el && el.closest ? el.closest('.slot.mat') : null;
  if (!s) return {ok: false, why: 'no-mat'};
  return {ok: !s.querySelector('.selo-trancada'),
          stack: s.dataset.stack || '', title: s.dataset.tiptitle || '',
          locked: !!s.querySelector('.selo-trancada')};
}
"""


PANEL_JS = r"""
(() => {
  const b = [...document.querySelectorAll('#winlayer .window')]
      .find(w => w.querySelector('.x') && w.querySelector('.x').dataset.arg === 'workbench');
  if (!b) return null;
  const text = b.textContent.replace(/\s+/g, ' ').trim();
  const btn = [...b.querySelectorAll('button')].find(x => /^[✦⚒♻]/.test(x.textContent.trim()));
  const frac = text.match(/(\d+)\s*\/\s*(\d+)/);     // 3/8 这种未满状态
  const recipe = text.match(/(\d+)\s*×/);              // 满了会变成 8× 浑浊精华 → 1× 明亮精华
  const inputs = [...b.querySelectorAll('.ccell')].filter(x => !x.classList.contains('out'));
  return {
    filled: frac ? +frac[1] : (recipe ? +recipe[1]
            : inputs.filter(x => x.children.length > 0).length),
    need: frac ? +frac[2] : 8,
    ready: !!(btn && !btn.disabled),
    text: text.slice(0, 60),
    btn: btn ? btn.textContent.trim() : null,
    disabled: btn ? btn.disabled : null
  };
})()
"""


CLICK_ACTION_BTN_JS = r"""
(() => {
  const b = [...document.querySelectorAll('#winlayer .window')]
      .find(w => w.querySelector('.x') && w.querySelector('.x').dataset.arg === 'workbench');
  if (!b) return {ok: false, why: 'no-bench'};
  const dfd = [...b.querySelectorAll('button')];
  const btn = dfd.find(x => /^[✦⚒♻]/.test(x.textContent.trim()));
  if (!btn) return {ok: false, why: 'no-button'};
  if (btn.disabled) return {ok: false, why: 'disabled'};
  btn.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, composed: true}));
  return {ok: true, label: btn.textContent.trim()};
})()
"""


# 切工作台工位：转化 / 锻造 / 镶嵌 / 卷轴 / 附魔 / 强化 / 唤醒
STATION_JS = r"""
([name]) => {
  const b = [...document.querySelectorAll('#winlayer .window')]
      .find(w => w.querySelector('.x') && w.querySelector('.x').dataset.arg === 'workbench');
  if (!b) return {ok: false, why: 'no-bench'};
  const dd = [...b.querySelectorAll('.lvddbtn')][0];
  if (!dd) return {ok: false, why: 'no-dropdown'};
  if (dd.textContent.indexOf(name) >= 0) return {ok: true, already: true};
  dd.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  const opt = [...document.querySelectorAll('.lvddopt')]
      .find(o => o.textContent.replace(/\s+/g, '').indexOf(name) >= 0);
  if (!opt) {
    document.body.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    return {ok: false, why: 'no-option'};
  }
  opt.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  return {ok: true, switched: true};
}
"""


# 关指定窗口（用窗口自己的 ✕，比 data-action 名更可靠）
CLOSE_WIN_JS = r"""
([arg]) => {
  const w = [...document.querySelectorAll('#winlayer .window')].find(x => {
    const b = x.querySelector('.x');
    return b && (b.dataset.arg || '') === arg;
  });
  if (!w) return false;
  w.querySelector('.x').dispatchEvent(new MouseEvent('click', {bubbles: true}));
  return true;
}
"""


def close_window(c, arg):
    return c.eval(f"({CLOSE_WIN_JS})([{arg!r}])")


def ensure_station(c, name):
    return c.eval(f"({STATION_JS})([{name!r}])")


def panel_state(c):
    return c.eval(PANEL_JS)


def click_action_button(c):
    return c.eval(CLICK_ACTION_BTN_JS)


# 元素级右键：不依赖坐标、不受窗口遮挡与滚动影响
RC_EL_JS = r"""
([kind, key]) => {
  const bag = [...document.querySelectorAll('#winlayer .window')]
      .find(w => w.querySelector('.x') && w.querySelector('.x').dataset.arg === 'inventory');
  if (!bag) return {ok: false, why: 'no-bag'};
  let el = null;
  if (kind === 'mat') {
    el = [...bag.querySelectorAll('.slot.mat')].find(s => s.dataset.stack === key);
  } else {
    el = [...bag.querySelectorAll('.slot[data-item]')]
      .find(s => s.dataset.where === 'inv'
              && (s.className.match(/r-([a-z]+)/) || [])[1] === key);
  }
  if (!el) return {ok: false, why: 'not-found'};
  if (el.querySelector('.selo-trancada')) return {ok: false, why: 'locked'};
  const fire = t => el.dispatchEvent(new MouseEvent(t, {
    bubbles: true, cancelable: true, composed: true, button: 2, buttons: 2, view: window
  }));
  ['pointerdown', 'mousedown', 'mouseup', 'contextmenu'].forEach(fire);
  return {ok: true, item: el.dataset.item || '', stack: el.dataset.stack || ''};
}
"""

# 背包网格滚动（虚拟滚动，格子没渲染出来时用）
SCROLL_BAG_JS = r"""
(() => {
  const bag = [...document.querySelectorAll('#winlayer .window')]
      .find(w => w.querySelector('.x') && w.querySelector('.x').dataset.arg === 'inventory');
  const box = bag && (bag.querySelector('.invscroll') || bag);
  if (!box) return false;
  box.scrollTop = Math.min(box.scrollTop + 220, box.scrollHeight);
  return true;
})()
"""


def rc_element(c, kind, key):
    return c.eval(f"({RC_EL_JS})([{kind!r}, {key!r}])")


def scroll_bag(c):
    return c.eval(SCROLL_BAG_JS)


def scroll_at(c, p, delta=400):
    """在坐标处滚轮（用于背包虚拟滚动，让更多格子现身）。不是拖拽。"""
    c.call("Input.dispatchMouseEvent", type="mouseWheel",
           x=int(p["x"]), y=int(p["y"]), deltaX=0, deltaY=int(delta))


def bag_scroll_point(c):
    """背包网格中心点，供滚轮使用。"""
    return c.eval(r"""
    (() => {
      const bag = [...document.querySelectorAll('#winlayer .window')]
        .find(w => w.querySelector('.x') && w.querySelector('.x').dataset.arg === 'inventory');
      if (!bag) return null;
      const g = bag.querySelector('.invscroll') || bag.querySelector('#dock');
      const target = g || bag;
      const r = target.getBoundingClientRect();
      if (r.width < 20 || r.height < 20) return null;
      return {x: r.x + r.width / 2, y: r.y + Math.min(r.height / 2, 300)};
    })()
    """)


def right_click(c, p):
    """在坐标处点一次右键。游戏里对背包物品右键 = 直接存入仓库（无菜单、无拖拽落点风险）。"""
    c.call("Input.dispatchMouseEvent", type="mousePressed",
           x=int(p["x"]), y=int(p["y"]), button="right", buttons=2, clickCount=1)
    time.sleep(0.06)
    c.call("Input.dispatchMouseEvent", type="mouseReleased",
           x=int(p["x"]), y=int(p["y"]), button="right", buttons=0, clickCount=1)

SAVE = os.path.join(os.environ.get("APPDATA", ""), "com.artxgames.questaway", "save.json")

RARITY_ZH = {
    "common": ("普通", "#8b93a1"), "uncommon": ("精良", "#2f9e44"),
    "rare": ("稀有", "#1c7ed6"), "heroic": ("英雄", "#7048e8"),
    "epic": ("史诗", "#e8590c"), "mythic": ("神话", "#c2255c"),
    "legendary": ("传说", "#f08c00"), "eternal": ("永恒", "#e03131"),
}
SLOT_ZH = {
    "weapon": "武器", "offhand": "副手", "armor": "护甲", "helmet": "头盔",
    "gloves": "手套", "boots": "靴子", "legs": "护腿", "ring": "戒指",
    "ring1": "戒指1", "ring2": "戒指2", "ring3": "戒指3",
    "earrings": "耳环", "earrings2": "耳环2", "necklace": "项链",
    "amulet": "项链", "bracelet": "手镯", "belt": "腰带", "cloak": "披风",
}
WHERE_ZH = {"equip": "已装备", "inv": "背包", "stash": "仓库", "bench": "工位"}


def load_save_game():
    try:
        with open(SAVE, "r", encoding="utf-8") as f:
            outer = json.load(f)
        return json.loads(outer["game"])["game"]
    except Exception:
        return None


def load_save_items():
    """存档是权威数据源：DOM 里只有已装备的槽位有 data-item。"""
    g = load_save_game()
    if not g:
        return []
    rows = []

    def add(it, where):
        if not isinstance(it, dict) or not it.get("id"):
            return
        rows.append({
            "id": it["id"], "where": where,
            "slot": it.get("slot", ""), "rarity": it.get("rarity", ""),
            "ilvl": it.get("itemLevel", 0), "enh": it.get("enhancement", 0),
            "affixes": "、".join(f'{a.get("stat")}+{round(a.get("value", 0))}'
                                 for a in (it.get("affixes") or [])[:3]),
        })

    for src, where in (("inventory", "inv"), ("stash", "stash")):
        for it in g.get("sim", {}).get(src) or []:
            add(it, where)
    for h in (g.get("heroes") or []) + (g.get("bench") or []):
        for it in (h.get("equipment") or {}).values():
            add(it, "equip")
    return rows


def chests(c):
    return c.eval(CHESTS_JS) or []


def craft(c, mode):
    action = {"fill": "cubeautofill", "run": "transmutecube", "clear": "cubeclear"}.get(mode)
    if not action:
        raise ValueError("mode 只能是 fill / run / clear")
    return act(c, action)





def learn_watch(c, seconds=120):
    print(c.eval(LEARN_JS))
    print("现在到游戏里点你想自动化的那个按钮（例如背包）。Ctrl+C 结束。\n")
    last, t0 = None, time.time()
    try:
        while time.time() - t0 < seconds:
            cur = c.eval("window.__qaLast || null")
            if cur and cur != last:
                last = cur
                print(f">>> {cur['a']}   参数: {cur.get('arg') or '(无)'}   提示: {cur.get('tip') or ''}")
                print(f"    对应命令: act {cur['a']} {cur.get('arg') or ''}\n")
            time.sleep(0.4)
    except (KeyboardInterrupt, EOFError):
        pass


def shell():
    """交互控制台：输入 JS 回车即执行，:q 退出，:t 列页面，:p 探测并保存。"""
    t = pick()
    c = CDP(t["webSocketDebuggerUrl"])
    print(f"已连接: {t.get('title')} · {t.get('url')}")
    print("输入 JS 回车执行；:t 列页面  :p 探测  :q 退出\n")
    try:
        while True:
            try:
                line = input("cdp> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                continue
            if line in (":q", ":quit", "exit"):
                break
            if line == ":t":
                for x in targets():
                    print(f'  {x.get("type")}  {x.get("title","")[:30]}  {x.get("url","")[:60]}')
                continue
            if line == ":p":
                data = c.eval(PROBE_JS)
                out = os.path.join(BASE, "probe.json")
                with open(out, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=1)
                print("可疑对象:", ", ".join(data["looks"].keys()) or "(没有)")
                print("已写入", out)
                continue
            if line in (":w", ":watch"):
                learn_watch(c)
                continue
            try:
                val = c.eval(line, await_promise=True)
                print(json.dumps(val, ensure_ascii=False, indent=1))
            except Exception as e:
                print("×", str(e)[:400])
    finally:
        c.close()
        print("已断开")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    arg = sys.argv[2] if len(sys.argv) > 2 else ""

    if cmd == "shell":
        shell()
        return

    if cmd in ("act", "learn", "last", "actions", "key", "status", "bag", "items", "chest", "craft"):
        if cmd == "act":
            if len(sys.argv) < 3:
                sys.exit("用法: cdp.py act <action> [arg]   例如: cdp.py act mapstage 6:9")
            t = pick()
            c = CDP(t["webSocketDebuggerUrl"])
            try:
                a = sys.argv[2]
                b = sys.argv[3] if len(sys.argv) > 3 else ""
                r = act(c, a, b)
                if r["mode"] == "real":
                    print(f"[OK] 已触发 {a} {b}  (页面上找到 {r['count']} 个按钮)")
                elif r["mode"] == "synthetic":
                    print(f"[?] 页面上没有 {a} {b} 的按钮，已用合成事件试了一次")
                else:
                    print(f"[X] 页面上找不到 {a} {b}，先打开对应窗口再试")
            finally:
                c.close()
            return
        t = pick()
        c = CDP(t["webSocketDebuggerUrl"])
        try:
            if cmd == "learn":
                learn_watch(c, seconds=int(sys.argv[2]) if len(sys.argv) > 2 else 120)
            elif cmd == "actions":
                m = c.eval(LIST_JS) or {}
                print("当前页面上可用的动作（数字=可见按钮数）：")
                for k in sorted(m):
                    print(f"  {k:28s} {m[k]}")
            elif cmd == "status":
                s = status(c)
                print(f"页面尺寸: {s['inner'][0]}x{s['inner'][1]}   页面有焦点: {s['focus']}")
                print(f"开着的窗口: {s['wins'] or '(无)'}")
                print("当前可点的动作:", s["visibleActions"] or "(没有，HUD 收起了？)")
            elif cmd == "key":
                print("已发送按键:", press(c, sys.argv[2] if len(sys.argv) > 2 else "esc"))
            elif cmd == "bag":
                r = bag(c, open_it=(len(sys.argv) < 3 or sys.argv[2] != "close"))
                if not r["changed"]:
                    print(f"背包已经是{'开' if r['bagOpen'] else '关'}着的，没动")
                else:
                    print(f"背包现在{'开着' if r['bagOpen'] else '关着'}了")
            elif cmd == "items":
                rows = load_save_items()
                if not rows:
                    print("没读到物品：先把背包打开（cdp.py bag）")
                else:
                    order = {k: i for i, k in enumerate(RARITY_ZH)}
                    rows.sort(key=lambda r: (order.get(r["rarity"], 9), -r["ilvl"]))
                    print(f"{'位置':8s} {'稀有':6s} {'ilvl':>4s} {'部位':8s} 词条")
                    for r in rows:
                        rar = RARITY_ZH.get(r["rarity"], (r["rarity"], ""))[0]
                        print(f'{WHERE_ZH.get(r["where"], r["where"]):8s} {rar:6s} '
                              f'{r["ilvl"]:>4} {SLOT_ZH.get(r["slot"], r["slot"]):8s} {r["affixes"]}')
                    stat = {}
                    for r in rows:
                        stat[r["where"]] = stat.get(r["where"], 0) + 1
                    print("合计:", ", ".join(f"{WHERE_ZH.get(k, k)} {v}" for k, v in stat.items()))
            elif cmd == "chest":
                cs = chests(c)
                if not cs:
                    print("页面上没有宝箱槽")
                for x in cs:
                    name = KIND_ZH.get(x["kind"], x["kind"] or "（未解锁）")
                    print(f'  {name:8s} kind={x["kind"] or "-":7s} '
                          f'{"可收" if x["visible"] else "空/隐藏"}'
                          + (f'  徽章 {x["badge"]}' if x["badge"] else ""))
                if len(sys.argv) > 2 and sys.argv[2] == "open":
                    done = []
                    for x in [y for y in cs if y["visible"]]:
                        name = KIND_ZH.get(x["kind"], x["kind"] or "空槽")
                        cdp_act = act(c, "grabchest", x["kind"])
                        time.sleep(0.9)
                        left = [y for y in (chests(c) or []) if y["visible"] and y["kind"] == x["kind"]]
                        if left:
                            done.append(f"{name} 没开掉（{cdp_act.get('mode')}）")
                        else:
                            done.append(f"{name} 已开")
                    print("结果:", "；".join(done) if done else "当前没有可收的箱子")
            elif cmd == "craft":
                print("结果:", craft(c, sys.argv[2] if len(sys.argv) > 2 else "fill"))
            else:
                print(json.dumps(c.eval("window.__qaLast || window.__qaLog || null"),
                                 ensure_ascii=False, indent=1))
        finally:
            c.close()
        return

    if cmd == "targets":
        for t in targets():
            print(f'{t.get("type"):8s} {t.get("title","")[:40]:42s} {t.get("url","")[:70]}')
            print(f'         ws: {t.get("webSocketDebuggerUrl","")}')
        return

    t = pick()
    c = CDP(t["webSocketDebuggerUrl"])
    try:
        if cmd == "eval":
            print(json.dumps(c.eval(arg), ensure_ascii=False, indent=1))
        elif cmd == "call":
            print(json.dumps(c.eval(arg, await_promise=True), ensure_ascii=False, indent=1))
        elif cmd == "probe":
            data = c.eval(PROBE_JS)
            out = os.path.join(BASE, "probe.json")
            with open(out, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            print(f"页面: {data.get('title')} · {data.get('url')}")
            print(f"canvas={data['domHints']['canvases']} iframe={data['domHints']['iframes']}")
            print("可疑对象:", ", ".join(data["looks"].keys()) or "(没有)")
            print(f"全部全局对象已写入 {out}")
        else:
            print(__doc__)
    finally:
        c.close()


if __name__ == "__main__":
    main()
