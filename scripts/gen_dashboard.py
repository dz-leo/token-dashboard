# -*- coding: utf-8 -*-
"""Token 消耗看板构建脚本

扫描 ~/.workbuddy/projects/<工作空间>/<会话>.jsonl，抽取请求级真实 usage，
生成单文件自包含看板（离线可看、零外部依赖）。

仅依赖 Python 标准库（3.8+）。跨平台：Windows / macOS / Linux。

用法：
    python gen_dashboard.py                     # 输出 ./token-dashboard.html
    python gen_dashboard.py --out 看板.html      # 自定义输出路径
    python gen_dashboard.py --projects <目录>    # 自定义会话日志目录
    python gen_dashboard.py --prices <文件>      # 自定义价格表
"""
import argparse
import calendar
import datetime
import glob
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")   # Windows GBK 控制台防乱码
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

_ap = argparse.ArgumentParser(description="Token 消耗看板生成器")
_ap.add_argument("--projects", default=os.path.join(os.path.expanduser("~"), ".workbuddy", "projects"),
                 help="会话日志目录（默认 ~/.workbuddy/projects）")
_ap.add_argument("--out", default="token-dashboard.html", help="输出 HTML 路径")
_ap.add_argument("--prices", default=os.path.join(ROOT, "prices.json"), help="价格表 JSON 路径")
_ap.add_argument("--template", default=os.path.join(HERE, "template.html"), help="页面模板路径")
_args = _ap.parse_args()

PROJECTS, OUT, PRICES_PATH, TEMPLATE_PATH = _args.projects, _args.out, _args.prices, _args.template

# 内置兜底价格表：prices.json 缺失时仍能出图，但金额不可信（页面会明确标注）
BUILTIN_PRICES = {
    "version": "builtin", "currency": "CNY", "unit": "元 / 百万 token",
    "fallback": {"in": 4, "out": 12, "cacheRead": 1, "verified": False, "note": "内置兜底值"},
    "models": [],
}


def parse_local_date(v):
    """解析价格表的生效时间，返回**毫秒**时间戳。

    必须按本地时区解释：厂商公告写的是「北京时间 9月10日12:00 起」，
    若按 UTC 解析会整体偏移 8 小时，历史价在新价生效当天会算错。
    """
    if not v:
        return 0
    s = str(v).strip()
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return int(datetime.datetime.strptime(s, fmt).timestamp() * 1000)
        except Exception:
            pass
    return 0


def load_prices(path):
    """读取价格表；失败时回退到内置表并给出警告（不中断生成）。"""
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        if not isinstance(raw, dict) or not isinstance(raw.get("models"), list):
            raise ValueError("结构不合法")
        for m in raw["models"]:
            m["fromMs"] = parse_local_date(m.get("from"))
        raw.setdefault("fallback", BUILTIN_PRICES["fallback"])
        return raw, True
    except Exception as e:
        print("[warn] 价格表读取失败(%s)：%s，改用内置兜底值，金额仅供参考" % (path, e), file=sys.stderr)
        return dict(BUILTIN_PRICES), False


def parse_ts(v):
    """时间戳归一化为「秒」。支持毫秒/秒整数、ISO 字符串、数字字符串。"""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if v > 1e12:
            return v / 1000.0
        if v > 1e9:
            return float(v)
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
            try:
                return calendar.timegm(datetime.datetime.strptime(s, fmt).timetuple())
            except Exception:
                pass
        try:
            return float(s) / 1000.0
        except Exception:
            return None
    return None


def _first(*vals):
    """取第一个非 None 的值（0 也算有效值）。"""
    for v in vals:
        if v is not None:
            return v
    return None


def pick_usage(ru, u):
    """抽取一条请求的用量。返回 (总token, 总输入, 输出, 缓存读, 缓存写, 并列口径标志) 或 None。

    缓存字段存在三套流派，全部兼容：
      DeepSeek  → prompt_cache_hit_tokens / prompt_cache_miss_tokens / prompt_cache_write_tokens
      OpenAI    → prompt_tokens_details.cached_tokens（嵌套）
      Anthropic → cache_read_input_tokens / cache_creation_input_tokens
    Anthropic 的 input_tokens 与缓存读写是**并列**关系（不含缓存），
    另外两家则把缓存命中**包含**在 prompt_tokens 里 —— 因此总输入必须自适应判断，
    不能无脑套 min() 截断，否则 Anthropic 口径下缓存命中会被整段吞掉。
    """
    ptd = ru.get("prompt_tokens_details") or {}
    if not isinstance(ptd, dict):
        ptd = {}

    cache_read = _first(ru.get("prompt_cache_hit_tokens"),      # DeepSeek
                        ru.get("cached_tokens"),                 # OpenAI 顶层变体
                        ptd.get("cached_tokens"),                # OpenAI 嵌套
                        ru.get("cache_read_input_tokens"))       # Anthropic
    cache_write = _first(ptd.get("cached_creation_tokens"),
                         ptd.get("cache_write_tokens"),
                         ru.get("prompt_cache_write_tokens"),    # DeepSeek
                         ru.get("cache_creation_input_tokens"))  # Anthropic

    total = _first(ru.get("total_tokens"), u.get("totalTokens"))
    if not total:
        return None

    base_in = ru.get("prompt_tokens") or u.get("inputTokens") or 0
    cch, cwr = int(cache_read or 0), int(cache_write or 0)
    # 自适应：base_in 已含缓存读+写 → 直接用；否则说明是并列口径 → 相加
    parallel = base_in < cch + cwr
    total_in = base_in + cch + cwr if parallel else base_in

    return (int(total), int(total_in),
            int(ru.get("completion_tokens") or u.get("outputTokens") or 0),
            cch, cwr, parallel)


def session_title(o):
    """首条非内部标签的用户消息前 42 字作为会话标题；'<' 开头的是系统注入内容，跳过。"""
    if o.get("role") != "user":
        return None
    c = o.get("content")
    if isinstance(c, str):
        t = " ".join(c.split())
        return t[:42] if t and not t.startswith("<") else None
    if not isinstance(c, list):
        return None
    for seg in c:
        if not isinstance(seg, dict):
            continue
        if seg.get("type") in ("input_text", "text"):
            t = " ".join((seg.get("text") or "").split())
            if not t:
                continue
            return None if t.startswith("<") else t[:42]
    return None


def short_ws(name):
    """工作空间目录名是路径 slug（如 c-Users-foo-WorkBuddy-2026-08-01-10-00-00），
    取 -WorkBuddy- 之后的部分；非 WorkBuddy 目录原样返回。"""
    i = name.rfind("-WorkBuddy-")
    return name[i + 11:] if i >= 0 and name[i + 11:] else name


prices, prices_ok = load_prices(PRICES_PATH)
now = datetime.datetime.now()
gen_ms = int(now.timestamp() * 1000)

ws_names, ws_idx, models, model_idx, sessions = {}, {}, [], {}, {}


def scan():
    """遍历日志目录，聚合成 {sid: {w, t, r}}。"""
    for fp in sorted(glob.glob(os.path.join(PROJECTS, "**", "*.jsonl"), recursive=True)):
        parts = os.path.relpath(fp, PROJECTS).split(os.sep)
        if len(parts) < 2:
            continue
        folder = parts[0]
        # 二级文件 = 会话文件；更深（如 subagents/agent-*.jsonl）归属其父会话
        sid = os.path.splitext(parts[1])[0] if len(parts) == 2 else parts[1]
        if folder not in ws_idx:
            ws_names[folder] = short_ws(folder)
            ws_idx[folder] = len(ws_idx)

        recs, title, sid_final = [], None, sid
        try:
            fh = open(fp, encoding="utf-8", errors="ignore")
        except Exception:
            continue
        with fh:
            for line in fh:
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if not isinstance(o, dict):
                    continue
                if len(parts) == 2 and o.get("sessionId"):
                    sid_final = o["sessionId"]
                if title is None:
                    title = session_title(o)

                pd = o.get("providerData")
                if not isinstance(pd, dict):
                    continue
                got = pick_usage(pd.get("rawUsage") or {}, pd.get("usage") or {})
                if not got:
                    continue
                total, tin, tout, cch, cwr, _ = got
                ts = parse_ts(o.get("timestamp"))
                if not ts:
                    continue
                name = pd.get("model") or pd.get("requestModelId") or pd.get("requestModelName") or "unknown"
                if name not in model_idx:
                    model_idx[name] = len(models)
                    models.append(name)
                aborted = 1 if pd.get("isPartialAborted") else 0
                recs.append([int(ts // 60), model_idx[name], total, tin, tout, cch, cwr, aborted])

        if not recs:
            continue
        recs.sort(key=lambda x: x[0])
        # setdefault 只在首次建键时落标题，而 glob 顺序不保证 —— 后续读到更好的标题要能覆盖
        d = sessions.setdefault(sid_final, {"w": ws_idx[folder], "id": sid_final, "t": None, "r": []})
        if not d["t"] and title:
            d["t"] = title
        d["r"].extend(recs)


scan()

sess_list = []
for sid, d in sessions.items():
    if not d["r"]:
        continue
    d["r"].sort(key=lambda x: x[0])
    sess_list.append({"w": d["w"], "id": sid[:8], "t": d["t"] or "(无标题会话)", "r": d["r"]})
sess_list.sort(key=lambda s: s["r"][0][0])

DATA = {
    "genMs": gen_ms,
    "gen": now.strftime("%Y-%m-%d %H:%M"),
    "ws": list(ws_names.values()),
    "models": models,
    "sess": sess_list,
    "price": prices,
    "priceOk": prices_ok,
    "proj": PROJECTS,
}

try:
    with open(TEMPLATE_PATH, encoding="utf-8") as fh:
        TEMPLATE = fh.read()
except Exception as e:
    sys.exit("模板读取失败 %s：%s" % (TEMPLATE_PATH, e))

js = json.dumps(DATA, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
html = TEMPLATE.replace("__DATA__", js)

out_dir = os.path.dirname(os.path.abspath(OUT))
if out_dir and not os.path.isdir(out_dir):
    os.makedirs(out_dir, exist_ok=True)
try:
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(html)
except Exception as e:
    sys.exit("写入失败 %s：%s" % (OUT, e))

print("written: %s (%.1f MB)" % (OUT, os.path.getsize(OUT) / 1e6))
print("sessions: %d | models: %d | workspaces: %d | price: %s"
      % (len(sess_list), len(models), len(ws_names), prices.get("version")))
