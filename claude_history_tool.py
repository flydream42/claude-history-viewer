# -*- coding: utf-8 -*-
"""Claude 对话历史浏览与导出工具 (单文件版, 便于 PyInstaller 打包)。"""
import sys as _sys

# ===== scanner.py =====
"""
Claude Desktop (Gateway/3P 模式) 对话历史 扫描与解析核心模块。

职责:
  1. 定位 Claude-3p 的 local-agent-mode-sessions 目录 (自动，无需用户指定)
  2. 读取每个 local_<uuid>.json 元数据
  3. 用 os.walk 把每个会话工作目录下的所有 transcript(jsonl) 合并去重，
     还原被"压缩接续"切成多段的完整对话时间线
  4. 解析出 标题/时间/首条/末条/全部消息(含 thinking / tool_use)

设计要点(均经真实数据验证):
  - audit.jsonl 才是"从会话第一天起、逐条追加、永不删改"的完整原始记录。
    分段 transcript(.claude/projects 下那些 jsonl)是压缩接续后重新生成的工作副本，
    会缺失被压缩掉的最早消息 -> 因此优先、且仅使用 audit.jsonl 作为对话来源，
    只有极少数没有 audit.jsonl 的会话才回退到分段 transcript。
    (实测 145 个会话全部有 audit.jsonl，且用户轮次是分段版的严格超集)
  - Python glob('**') 不进入 .claude 这类点目录 -> 回退扫描分段时必须用 os.walk
  - audit.jsonl 内同一条 uuid 可能出现多次 -> 按 message uuid 去重
  - 子 agent 分支: audit 里以 parent_tool_use_id 非空标记; 分段回退里以 agent-*.jsonl 文件名标记
"""

import os
import re
import json
import glob


# ---------------------------------------------------------------------------
# 目录定位
# ---------------------------------------------------------------------------

def default_sessions_root():
    """返回 Claude-3p 的 local-agent-mode-sessions 目录(若能找到)，否则 None。

    Windows: %LOCALAPPDATA%\\Claude-3p\\local-agent-mode-sessions
    旧版本可能在 %APPDATA%(Roaming) 下。
    macOS / Linux 一并兜底。
    """
    candidates = []

    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(os.path.join(local, "Claude-3p", "local-agent-mode-sessions"))
    roaming = os.environ.get("APPDATA")
    if roaming:
        candidates.append(os.path.join(roaming, "Claude-3p", "local-agent-mode-sessions"))

    home = os.path.expanduser("~")
    candidates.append(os.path.join(home, "Library", "Application Support",
                                   "Claude-3p", "local-agent-mode-sessions"))
    candidates.append(os.path.join(home, ".config", "Claude-3p",
                                   "local-agent-mode-sessions"))

    for c in candidates:
        if os.path.isdir(c):
            return c
    return None


def looks_like_sessions_root(path):
    """判断一个目录是否像 local-agent-mode-sessions(含 local_*.json)。

    支持用户手动指定该目录，或其上层/下层若干情况。
    返回真正含有 local_*.json 的目录，找不到返回 None。
    """
    if not path or not os.path.isdir(path):
        return None
    # 直接命中
    if glob.glob(os.path.join(path, "**", "local_*.json"), recursive=True):
        return path
    return None


# ---------------------------------------------------------------------------
# 元数据
# ---------------------------------------------------------------------------

def load_metadata(root):
    """扫描 root 下所有 local_<uuid>.json，返回 list[dict]，每个含解析好的字段。

    只认作为"文件"的 local_*.json (会话工作目录本身也叫 local_<uuid>，需排除目录)。
    """
    metas = []
    for path in glob.glob(os.path.join(root, "**", "local_*.json"), recursive=True):
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            continue
        if not isinstance(d, dict) or not d.get("sessionId"):
            continue
        metas.append({
            "sessionId": d.get("sessionId"),
            "cliSessionId": d.get("cliSessionId"),
            "title": d.get("title") or "(未命名对话)",
            "createdAt": d.get("createdAt"),
            "lastActivityAt": d.get("lastActivityAt"),
            "initialMessage": d.get("initialMessage") or "",
            "model": d.get("model") or "",
            "isStarred": bool(d.get("isStarred")),
            "isArchived": bool(d.get("isArchived")),
            "cwd": d.get("cwd") or "",
            "_metaPath": path,
        })
    return metas


def _workdir_for(meta, root):
    """根据元数据推断该会话的工作目录绝对路径。

    新格式: 工作目录名 = sessionId 去掉 'local_' 前缀后的前 8 位短 hex
    老格式: 工作目录名 = 完整 sessionId (local_<uuid>)
    以 cwd 中 00000000\\<workdir> 的那一段为准，两种都覆盖。
    """
    meta_dir = os.path.dirname(meta["_metaPath"])  # 通常就是 ...\00000000

    # 优先从 cwd 解析工作目录名
    cwd = meta.get("cwd") or ""
    parts = re.split(r"[\\/]", cwd)
    workname = None
    for i, p in enumerate(parts):
        if p == "00000000" and i + 1 < len(parts):
            workname = parts[i + 1]
            break

    candidates = []
    if workname:
        candidates.append(os.path.join(meta_dir, workname))
    sid = meta["sessionId"]
    candidates.append(os.path.join(meta_dir, sid))                    # 老格式 local_<uuid>
    candidates.append(os.path.join(meta_dir, sid.replace("local_", "")[:8]))  # 新格式短hex

    for c in candidates:
        if os.path.isdir(c):
            return c
    return None


# ---------------------------------------------------------------------------
# transcript 合并
# ---------------------------------------------------------------------------

def _audit_file(workdir):
    """返回该会话 audit.jsonl 的绝对路径(存在则返回，否则 None)。

    audit.jsonl 一般就在工作目录顶层；为稳妥也向下找一层。
    """
    if not workdir:
        return None
    top = os.path.join(workdir, "audit.jsonl")
    if os.path.isfile(top):
        return top
    for r, _dirs, files in os.walk(workdir):
        if "audit.jsonl" in files:
            return os.path.join(r, "audit.jsonl")
    return None


def _iter_transcript_files(workdir):
    """回退方案: 遍历工作目录下所有分段 transcript(.jsonl)，排除 audit.jsonl。

    仅在没有 audit.jsonl 时使用。返回 list[(path, is_agent)]。
    """
    out = []
    if not workdir:
        return out
    for r, _dirs, files in os.walk(workdir):
        for fn in files:
            if not fn.endswith(".jsonl"):
                continue
            if fn == "audit.jsonl":
                continue
            out.append((os.path.join(r, fn), fn.startswith("agent-")))
    return out


def _extract_blocks(msg_obj):
    """把一条 user/assistant 记录解析成有序的块列表。

    每块: {"kind": "text"|"thinking"|"tool_use"|"tool_result", ...}
    """
    m = msg_obj.get("message", {}) or {}
    content = m.get("content")
    blocks = []
    if isinstance(content, str):
        if content.strip():
            blocks.append({"kind": "text", "text": content})
        return blocks
    for b in (content or []):
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        if t == "text":
            blocks.append({"kind": "text", "text": b.get("text", "")})
        elif t == "thinking":
            blocks.append({"kind": "thinking", "text": b.get("thinking", "")})
        elif t == "tool_use":
            blocks.append({
                "kind": "tool_use",
                "name": b.get("name", ""),
                "input": b.get("input", {}),
            })
        elif t == "tool_result":
            c = b.get("content", "")
            if isinstance(c, list):
                c = "\n".join(
                    x.get("text", "") for x in c
                    if isinstance(x, dict) and x.get("type") == "text"
                )
            blocks.append({"kind": "tool_result", "text": c if isinstance(c, str) else ""})
    return blocks


_CONTINUE_PREFIX = "This session is being continued"


def _is_synthetic_user(blocks):
    """判断一条 user 记录是否是系统合成的(压缩摘要续接 / 纯 system-reminder)，
    这类不算真正的用户发言，预览首末条时应跳过。"""
    text = "\n".join(b["text"] for b in blocks if b["kind"] == "text").strip()
    if not text:
        return True
    if text.startswith(_CONTINUE_PREFIX):
        return True
    # 纯粹的 system-reminder 包裹、无真实内容
    if text.startswith("<") and "system-reminder" in text[:40] and len(text) < 400:
        return True
    return False


def build_conversation(meta, root, include_agent=False):
    """把一个会话的所有 transcript 合并去重，返回完整对话对象。

    返回 dict:
      title, createdAt, lastActivityAt, model, isStarred, isArchived,
      messages: [ {role, timestamp, blocks, isAgent, isSynthetic} ...] 时间升序、uuid去重
      firstUserText / firstUserTime / lastText / lastTime / userTurns / transcriptCount
    """
    workdir = _workdir_for(meta, root)

    # 优先用 audit.jsonl(完整原始记录)；没有才回退到分段 transcript。
    audit = _audit_file(workdir)
    if audit:
        sources = [(audit, "audit")]
        transcript_count = 1
    else:
        sources = [(p, "agent" if is_agent else "seg")
                   for p, is_agent in _iter_transcript_files(workdir)]
        transcript_count = len(sources)

    seen = set()
    merged = []
    for path, kind in sources:
        try:
            fh = open(path, encoding="utf-8")
        except Exception:
            continue
        with fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if o.get("type") not in ("user", "assistant"):
                    continue
                uuid = o.get("uuid")
                if uuid is not None:
                    if uuid in seen:
                        continue
                    seen.add(uuid)
                blocks = _extract_blocks(o)
                if not blocks:
                    continue
                # 子 agent 分支判定: audit 里看 parent_tool_use_id，分段里看文件名。
                if kind == "audit":
                    is_agent = bool(o.get("parent_tool_use_id"))
                else:
                    is_agent = (kind == "agent")
                role = o.get("type")
                merged.append({
                    "role": role,
                    "timestamp": o.get("timestamp") or "",
                    "blocks": blocks,
                    "isAgent": is_agent,
                    "isSynthetic": role == "user" and _is_synthetic_user(blocks),
                })

    merged.sort(key=lambda x: x["timestamp"])
    if not include_agent:
        main = [x for x in merged if not x["isAgent"]]
    else:
        main = merged

    # 首末条: 与预览口径一致 —— 都取"磁盘现存、有可见文本"的消息。
    # 预览按时间顺序渲染并跳过空消息/合成消息，因此首条应是"第一条有可见文本
    # 且非合成"的消息(可能是 user，也可能是 assistant——当更早的用户提问已被
    # 压缩删除、该会话现存最早记录恰为 Claude 回复时)。这样列表摘要与预览开头一致。
    def visible_text(msg):
        return "\n".join(b["text"] for b in msg["blocks"]
                         if b["kind"] == "text" and b["text"].strip()).strip()

    def is_displayable(m):
        return (not m.get("isSynthetic")) and bool(visible_text(m))

    # 真实用户轮次(用于计数)
    real_users = [m for m in main if m["role"] == "user" and is_displayable(m)]

    # 首条: 第一条可显示的消息(任意角色)
    first_visible = next((m for m in main if is_displayable(m)), None)

    # 末条: 最后一条可显示的消息(任意角色)
    last_visible = None
    for m in reversed(main):
        if is_displayable(m):
            last_visible = m
            break

    return {
        "sessionId": meta["sessionId"],
        "title": meta["title"],
        "createdAt": meta.get("createdAt"),
        "lastActivityAt": meta.get("lastActivityAt"),
        "model": meta.get("model"),
        "isStarred": meta.get("isStarred"),
        "isArchived": meta.get("isArchived"),
        "messages": main,
        "transcriptCount": transcript_count,
        "userTurns": len(real_users),
        "firstText": visible_text(first_visible) if first_visible else meta.get("initialMessage", ""),
        "firstRole": (first_visible["role"] if first_visible else None),
        "firstTime": (first_visible["timestamp"] if first_visible else None),
        # 兼容旧字段名
        "firstUserText": visible_text(first_visible) if first_visible else meta.get("initialMessage", ""),
        "firstUserTime": (first_visible["timestamp"] if first_visible else None),
        "lastText": visible_text(last_visible) if last_visible else "",
        "lastRole": (last_visible["role"] if last_visible else None),
        "lastTime": (last_visible["timestamp"] if last_visible else None),
    }


def scan_all(root, include_agent=False):
    """扫描整个 root，返回所有会话的摘要(不含完整 messages，用于列表页)。

    列表按 lastActivityAt 倒序(最近活动在前)。
    """
    metas = load_metadata(root)
    summaries = []
    for m in metas:
        conv = build_conversation(m, root, include_agent=include_agent)
        summaries.append({
            "sessionId": conv["sessionId"],
            "title": conv["title"],
            "createdAt": conv["createdAt"],
            "lastActivityAt": conv["lastActivityAt"],
            "model": conv["model"],
            "isStarred": conv["isStarred"],
            "isArchived": conv["isArchived"],
            "transcriptCount": conv["transcriptCount"],
            "userTurns": conv["userTurns"],
            "messageCount": len(conv["messages"]),
            "firstText": conv["firstText"],
            "firstRole": conv["firstRole"],
            "firstTime": conv["firstTime"],
            "firstUserText": conv["firstUserText"],
            "firstUserTime": conv["firstUserTime"],
            "lastText": conv["lastText"],
            "lastRole": conv["lastRole"],
            "lastTime": conv["lastTime"],
        })
    summaries.sort(key=lambda s: (s.get("lastActivityAt") or 0), reverse=True)
    return summaries



# ===== exporter.py =====
"""
把 build_conversation() 产出的对话对象导出为 Markdown 或 HTML。

开关:
  show_thinking : 是否包含 Claude 思考过程 (默认 False)
  show_tools    : 是否包含工具调用/结果 (默认 False)

两个导出都尽量自包含、可离线阅读。HTML 内嵌样式，中文友好。
"""

import os
import re
import html
import getpass
import datetime


# ---------------------------------------------------------------------------
# 用户名(隐私安全): 运行时取当前系统登录名，谁跑就显示谁；取不到用中性默认。
# 可用环境变量 CLAUDE_HISTORY_USERNAME 覆盖。
# ---------------------------------------------------------------------------

def current_user_label(lang="zh"):
    name = os.environ.get("CLAUDE_HISTORY_USERNAME")
    if name:
        return name
    try:
        u = getpass.getuser()
        if u:
            return u
    except Exception:
        pass
    return "我" if lang == "zh" else "Me"


# ---------------------------------------------------------------------------
# 双语标签表 (zh 为主，en 并存)
# ---------------------------------------------------------------------------

I18N = {
    "zh": {
        "created": "创建时间",
        "last_active": "最后活动",
        "model": "模型",
        "turns": "提问轮次",
        "subtask": "子任务",
        "thinking": "💭 思考过程",
        "tool_call": "🔧 工具调用",
        "tool_result": "📥 工具结果",
        "truncated": "…(已截断)",
        "html_lang": "zh-CN",
    },
    "en": {
        "created": "Created",
        "last_active": "Last active",
        "model": "Model",
        "turns": "User turns",
        "subtask": "subtask",
        "thinking": "💭 Thinking",
        "tool_call": "🔧 Tool call",
        "tool_result": "📥 Tool result",
        "truncated": "…(truncated)",
        "html_lang": "en",
    },
}


def _L(lang):
    return I18N.get(lang, I18N["zh"])


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def fmt_ts(ts):
    """ISO 时间戳 或 毫秒时间戳 -> 'YYYY-MM-DD HH:MM' (本地可读)。"""
    if ts is None or ts == "":
        return ""
    if isinstance(ts, (int, float)):
        try:
            return datetime.datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return str(ts)
    # ISO 字符串
    s = str(ts).replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(s)
        # 转本地时间
        if dt.tzinfo:
            dt = dt.astimezone()
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts)[:16].replace("T", " ")


def safe_filename(name, maxlen=80):
    """把标题清洗成安全文件名。"""
    name = name or "对话"
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name).strip()
    name = re.sub(r"\s+", " ", name)
    if len(name) > maxlen:
        name = name[:maxlen]
    return name or "对话"


def _role_label(role, lang="zh"):
    return current_user_label(lang) if role == "user" else "Claude"


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

def to_markdown(conv, show_thinking=False, show_tools=False, lang="zh"):
    L = _L(lang)
    lines = []
    lines.append(f"# {conv['title']}\n")
    meta = []
    if conv.get("createdAt"):
        meta.append(f"{L['created']}: {fmt_ts(conv['createdAt'])}")
    if conv.get("lastActivityAt"):
        meta.append(f"{L['last_active']}: {fmt_ts(conv['lastActivityAt'])}")
    if conv.get("model"):
        meta.append(f"{L['model']}: {conv['model']}")
    meta.append(f"{L['turns']}: {conv.get('userTurns', 0)}")
    lines.append("> " + " ｜ ".join(meta) + "\n")
    lines.append("\n---\n")

    for m in conv["messages"]:
        if m.get("isSynthetic"):
            continue
        role = _role_label(m["role"], lang)
        ts = fmt_ts(m.get("timestamp"))
        header = f"\n## {role}"
        if ts:
            header += f"  ·  {ts}"
        if m.get("isAgent"):
            header += f"  · [{L['subtask']}]"
        emitted = False
        body = []
        for b in m["blocks"]:
            k = b["kind"]
            if k == "text":
                if b["text"].strip():
                    body.append(b["text"].rstrip())
                    emitted = True
            elif k == "thinking" and show_thinking:
                if b["text"].strip():
                    quoted = "\n".join("> " + ln for ln in b["text"].rstrip().splitlines())
                    body.append(f"**{L['thinking']}**\n\n{quoted}")
                    emitted = True
            elif k == "tool_use" and show_tools:
                import json as _json
                inp = _json.dumps(b.get("input", {}), ensure_ascii=False, indent=2)
                if len(inp) > 1500:
                    inp = inp[:1500] + "\n" + L["truncated"]
                body.append(f"**{L['tool_call']}: {b.get('name','')}**\n\n```json\n{inp}\n```")
                emitted = True
            elif k == "tool_result" and show_tools:
                t = b.get("text", "")
                if len(t) > 1500:
                    t = t[:1500] + "\n" + L["truncated"]
                if t.strip():
                    body.append(f"**{L['tool_result']}**\n\n```\n{t}\n```")
                    emitted = True
        if emitted:
            lines.append(header)
            lines.append("\n" + "\n\n".join(body) + "\n")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

_HTML_HEAD = """<!DOCTYPE html>
<html lang="{html_lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ color-scheme: light; }}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; padding: 0;
  font-family: -apple-system, "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif;
  background: #f5f5f4; color: #1c1917; line-height: 1.7;
}}
.wrap {{ max-width: 820px; margin: 0 auto; padding: 32px 20px 80px; }}
header.doc {{ border-bottom: 2px solid #e7e5e4; padding-bottom: 20px; margin-bottom: 28px; }}
header.doc h1 {{ font-size: 26px; margin: 0 0 10px; }}
.meta {{ color: #78716c; font-size: 13px; }}
.meta span {{ margin-right: 14px; white-space: nowrap; }}
.msg {{ margin: 22px 0; padding: 16px 18px; border-radius: 12px; }}
.msg.user {{ background: #eef2ff; border: 1px solid #e0e7ff; }}
.msg.assistant {{ background: #ffffff; border: 1px solid #e7e5e4; }}
.msg .role {{ font-weight: 600; font-size: 13px; margin-bottom: 8px; display: flex; gap: 10px; align-items: baseline; }}
.msg.user .role {{ color: #4f46e5; }}
.msg.assistant .role {{ color: #0f766e; }}
.msg .time {{ color: #a8a29e; font-weight: 400; font-size: 12px; }}
.tag {{ font-size: 11px; background:#f5f5f4; color:#78716c; border:1px solid #e7e5e4; border-radius:6px; padding:1px 6px; }}
.text {{ white-space: pre-wrap; word-wrap: break-word; }}
.thinking {{
  background: #fafaf9; border-left: 3px solid #d6d3d1; color: #57534e;
  padding: 10px 14px; margin: 10px 0; border-radius: 6px; font-size: 14px;
  white-space: pre-wrap; word-wrap: break-word;
}}
.thinking .lbl {{ font-weight:600; color:#78716c; display:block; margin-bottom:4px; font-size:12px; }}
.tool {{
  background: #1c1917; color: #d6d3d1; padding: 10px 14px; margin: 10px 0;
  border-radius: 6px; font-size: 12.5px; overflow-x: auto;
}}
.tool .lbl {{ color:#a8a29e; font-weight:600; display:block; margin-bottom:4px; }}
.tool pre {{ margin: 0; white-space: pre-wrap; word-wrap: break-word; }}
code {{ background:#f5f5f4; padding:1px 5px; border-radius:4px; font-size:0.9em; }}
pre code {{ background:none; padding:0; }}
hr {{ border:none; border-top:1px solid #e7e5e4; margin:24px 0; }}
</style>
</head>
<body><div class="wrap">
"""

_HTML_TAIL = "\n</div></body></html>\n"


def _esc(t):
    return html.escape(t, quote=False)


def to_html(conv, show_thinking=False, show_tools=False, lang="zh"):
    import json as _json
    L = _L(lang)
    parts = [_HTML_HEAD.format(title=_esc(conv["title"]), html_lang=L["html_lang"])]

    meta_spans = []
    if conv.get("createdAt"):
        meta_spans.append(f"<span>{L['created']} {fmt_ts(conv['createdAt'])}</span>")
    if conv.get("lastActivityAt"):
        meta_spans.append(f"<span>{L['last_active']} {fmt_ts(conv['lastActivityAt'])}</span>")
    if conv.get("model"):
        meta_spans.append(f"<span>{L['model']} {_esc(str(conv['model']))}</span>")
    meta_spans.append(f"<span>{L['turns']} {conv.get('userTurns',0)}</span>")

    parts.append(f'<header class="doc"><h1>{_esc(conv["title"])}</h1>'
                 f'<div class="meta">{"".join(meta_spans)}</div></header>')

    for m in conv["messages"]:
        if m.get("isSynthetic"):
            continue
        pieces = []
        for b in m["blocks"]:
            k = b["kind"]
            if k == "text" and b["text"].strip():
                pieces.append(f'<div class="text">{_esc(b["text"])}</div>')
            elif k == "thinking" and show_thinking and b["text"].strip():
                pieces.append(f'<div class="thinking"><span class="lbl">{L["thinking"]}</span>{_esc(b["text"])}</div>')
            elif k == "tool_use" and show_tools:
                inp = _json.dumps(b.get("input", {}), ensure_ascii=False, indent=2)
                if len(inp) > 2000:
                    inp = inp[:2000] + "\n" + L["truncated"]
                pieces.append(f'<div class="tool"><span class="lbl">{L["tool_call"]}: {_esc(b.get("name",""))}</span>'
                              f'<pre>{_esc(inp)}</pre></div>')
            elif k == "tool_result" and show_tools:
                t = b.get("text", "")
                if len(t) > 2000:
                    t = t[:2000] + "\n" + L["truncated"]
                if t.strip():
                    pieces.append(f'<div class="tool"><span class="lbl">{L["tool_result"]}</span>'
                                  f'<pre>{_esc(t)}</pre></div>')
        if not pieces:
            continue
        role_cls = "user" if m["role"] == "user" else "assistant"
        ts = fmt_ts(m.get("timestamp"))
        tag = f'<span class="tag">{L["subtask"]}</span>' if m.get("isAgent") else ""
        parts.append(
            f'<div class="msg {role_cls}"><div class="role">{_role_label(m["role"], lang)}'
            f'<span class="time">{ts}</span>{tag}</div>{"".join(pieces)}</div>'
        )

    parts.append(_HTML_TAIL)
    return "".join(parts)


def export_conversation(conv, out_dir, fmt="md", show_thinking=False, show_tools=False, lang="zh"):
    """导出单个对话到文件，返回文件路径。"""
    os.makedirs(out_dir, exist_ok=True)
    base = safe_filename(conv["title"])
    # 加日期前缀，避免同名覆盖
    date_prefix = ""
    if conv.get("createdAt"):
        date_prefix = fmt_ts(conv["createdAt"])[:10] + "_"
    if fmt == "html":
        content = to_html(conv, show_thinking, show_tools, lang)
        path = os.path.join(out_dir, f"{date_prefix}{base}.html")
    else:
        content = to_markdown(conv, show_thinking, show_tools, lang)
        path = os.path.join(out_dir, f"{date_prefix}{base}.md")
    # 若重名，追加短id
    if os.path.exists(path):
        sid = (conv.get("sessionId") or "")[-6:]
        root, ext = os.path.splitext(path)
        path = f"{root}_{sid}{ext}"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path

# 让 app 段里的 scanner./exporter. 调用解析到本文件顶层函数
scanner = _sys.modules[__name__]
exporter = _sys.modules[__name__]

# ===== app.py =====
"""
Claude 对话历史浏览与导出工具 —— 本地服务主程序。

启动后:
  1. 自动定位 Claude-3p 会话目录 (找不到时可在界面里手动填)
  2. 起一个本地 HTTP 服务 (仅监听 127.0.0.1)
  3. 自动打开浏览器
  4. 左侧列出全部对话(名称/创建时间/首条/末条/星标)，可搜索排序
     右侧预览完整对话，思考过程 / 工具调用 两个开关
     支持导出单个 或 批量导出 为 Markdown / HTML

纯标准库实现，无第三方依赖，便于 PyInstaller 打包成单文件 exe。
"""

import os
import re
import sys
import json
import time
import socket
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs



# 全局：当前会话根目录 & 摘要缓存
STATE = {
    "root": None,
    "summaries": None,
    "include_agent": False,
}


def get_summaries(force=False):
    if STATE["summaries"] is None or force:
        if not STATE["root"]:
            return []
        STATE["summaries"] = scanner.scan_all(STATE["root"],
                                              include_agent=STATE["include_agent"])
    return STATE["summaries"]


def default_export_dir():
    """导出默认落点：用户主目录下 Claude对话导出/。"""
    base = os.path.join(os.path.expanduser("~"), "Claude对话导出")
    return base


# ---------------------------------------------------------------------------
# 前端页面 (单文件内嵌)
# ---------------------------------------------------------------------------

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Claude 对话历史</title>
<style>
:root{color-scheme:light;}
*{box-sizing:border-box;}
body{margin:0;font-family:-apple-system,"Segoe UI","Microsoft YaHei","PingFang SC",sans-serif;
  background:#f5f5f4;color:#1c1917;height:100vh;overflow:hidden;}
.app{display:flex;height:100vh;}
/* 左栏 */
.side{width:380px;min-width:300px;background:#fff;border-right:1px solid #e7e5e4;
  display:flex;flex-direction:column;height:100vh;}
.side header{padding:14px 16px;border-bottom:1px solid #e7e5e4;}
.side header h1{font-size:15px;margin:0 0 10px;display:flex;align-items:center;gap:8px;}
.langbtn{margin-left:auto;font-size:11px;padding:3px 9px;border:1px solid #e7e5e4;border-radius:6px;
  background:#fafaf9;cursor:pointer;color:#57534e;font-weight:600;}
.langbtn:hover{background:#eef2ff;border-color:#4f46e5;color:#4f46e5;}
.rootbar{font-size:11px;color:#a8a29e;word-break:break-all;line-height:1.4;margin-bottom:8px;}
.search{width:100%;padding:8px 10px;border:1px solid #e7e5e4;border-radius:8px;font-size:13px;}
.toolbar{display:flex;gap:6px;margin-top:8px;flex-wrap:wrap;align-items:center;}
.toolbar select,.toolbar button{font-size:12px;padding:5px 8px;border:1px solid #e7e5e4;
  border-radius:7px;background:#fafaf9;cursor:pointer;}
.toolbar button:hover{background:#f5f5f4;}
.count{font-size:11px;color:#a8a29e;margin-left:auto;}
.list{overflow-y:auto;flex:1;}
.item{padding:12px 16px;border-bottom:1px solid #f5f5f4;cursor:pointer;}
.item:hover{background:#fafaf9;}
.item.active{background:#eef2ff;}
.item .t{font-size:13.5px;font-weight:600;margin-bottom:3px;display:flex;gap:6px;align-items:center;}
.item .t .star{color:#f59e0b;}
.item .sub{font-size:11px;color:#a8a29e;margin-bottom:4px;}
.item .snip{font-size:12px;color:#78716c;overflow:hidden;text-overflow:ellipsis;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;}
/* 右栏 */
.main{flex:1;display:flex;flex-direction:column;height:100vh;overflow:hidden;}
.main header{padding:14px 22px;border-bottom:1px solid #e7e5e4;background:#fff;
  display:flex;align-items:center;gap:14px;flex-wrap:wrap;}
.main header h2{font-size:16px;margin:0;flex:1;min-width:200px;}
.opt{font-size:12.5px;display:flex;align-items:center;gap:5px;color:#57534e;cursor:pointer;user-select:none;}
.expbtn{font-size:12.5px;padding:6px 12px;border:1px solid #4f46e5;background:#4f46e5;color:#fff;
  border-radius:8px;cursor:pointer;}
.expbtn:hover{background:#4338ca;}
.expbtn.ghost{background:#fff;color:#4f46e5;}
.expbtn.ghost:hover{background:#eef2ff;}
.view{flex:1;overflow-y:auto;padding:24px 28px 80px;}
.view .metaline{color:#78716c;font-size:12.5px;margin-bottom:20px;padding-bottom:14px;border-bottom:1px solid #e7e5e4;}
.view .metaline span{margin-right:14px;}
.msg{margin:18px 0;padding:14px 16px;border-radius:12px;}
.msg.user{background:#eef2ff;border:1px solid #e0e7ff;}
.msg.assistant{background:#fff;border:1px solid #e7e5e4;}
.msg .role{font-weight:600;font-size:12.5px;margin-bottom:7px;display:flex;gap:10px;align-items:baseline;}
.msg.user .role{color:#4f46e5;}.msg.assistant .role{color:#0f766e;}
.msg .time{color:#a8a29e;font-weight:400;font-size:11px;}
.tag{font-size:10px;background:#f5f5f4;color:#78716c;border:1px solid #e7e5e4;border-radius:6px;padding:1px 6px;}
.text{white-space:pre-wrap;word-wrap:break-word;font-size:14.5px;line-height:1.7;}
.thinking{background:#fafaf9;border-left:3px solid #d6d3d1;color:#57534e;padding:9px 13px;
  margin:9px 0;border-radius:6px;font-size:13.5px;white-space:pre-wrap;word-wrap:break-word;}
.thinking .lbl{font-weight:600;color:#78716c;display:block;margin-bottom:4px;font-size:11.5px;}
.tool{background:#1c1917;color:#d6d3d1;padding:9px 13px;margin:9px 0;border-radius:6px;
  font-size:12px;overflow-x:auto;}
.tool .lbl{color:#a8a29e;font-weight:600;display:block;margin-bottom:4px;}
.tool pre{margin:0;white-space:pre-wrap;word-wrap:break-word;}
.empty{color:#a8a29e;text-align:center;margin-top:80px;font-size:14px;}
.toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#1c1917;color:#fff;
  padding:10px 18px;border-radius:10px;font-size:13px;opacity:0;transition:opacity .3s;z-index:99;}
.toast.show{opacity:1;}
.modal{position:fixed;inset:0;background:rgba(0,0,0,.4);display:none;align-items:center;justify-content:center;z-index:50;}
.modal.show{display:flex;}
.modal .box{background:#fff;border-radius:14px;padding:24px;width:420px;max-width:90vw;}
.modal h3{margin:0 0 14px;font-size:16px;}
.modal .row{margin:10px 0;font-size:13.5px;display:flex;align-items:center;gap:8px;}
.modal .row label{display:flex;align-items:center;gap:6px;cursor:pointer;}
.modal .actions{margin-top:18px;display:flex;gap:10px;justify-content:flex-end;}
.spinner{display:inline-block;width:14px;height:14px;border:2px solid #e7e5e4;border-top-color:#4f46e5;
  border-radius:50%;animation:spin .7s linear infinite;vertical-align:-2px;}
@keyframes spin{to{transform:rotate(360deg);}}
</style>
</head>
<body>
<div class="app">
  <div class="side">
    <header>
      <h1><span id="appTitle">🗂️ Claude 对话历史</span>
        <button id="btnLang" class="langbtn" title="切换语言 / Switch language">EN</button></h1>
      <div class="rootbar" id="rootbar"></div>
      <input class="search" id="search">
      <div class="toolbar">
        <select id="sort">
          <option value="recent"></option>
          <option value="created"></option>
          <option value="title"></option>
          <option value="turns"></option>
        </select>
        <select id="filter">
          <option value="all"></option>
          <option value="star"></option>
          <option value="active"></option>
        </select>
        <button id="btnExportAll"></button>
        <span class="count" id="count"></span>
      </div>
    </header>
    <div class="list" id="list"></div>
  </div>
  <div class="main">
    <header>
      <h2 id="title"></h2>
      <label class="opt"><input type="checkbox" id="optThink"> <span id="lblThink"></span></label>
      <label class="opt"><input type="checkbox" id="optTool"> <span id="lblTool"></span></label>
      <button class="expbtn ghost" id="btnExportOne" disabled></button>
    </header>
    <div class="view" id="view"><div class="empty" id="viewEmpty"></div></div>
  </div>
</div>

<div class="modal" id="modal"><div class="box">
  <h3 id="mTitle"></h3>
  <div class="row"><span id="mFmtLabel"></span>
    <label><input type="radio" name="fmt" value="md" checked> Markdown</label>
    <label><input type="radio" name="fmt" value="html"> <span id="mHtmlLabel"></span></label>
  </div>
  <div class="row"><span id="mLangLabel"></span>
    <label><input type="radio" name="elang" value="zh" checked> 中文</label>
    <label><input type="radio" name="elang" value="en"> English</label>
  </div>
  <div class="row"><label><input type="checkbox" id="mThink"> <span id="lblMThink"></span></label></div>
  <div class="row"><label><input type="checkbox" id="mTool"> <span id="lblMTool"></span></label></div>
  <div class="row" id="mScope"></div>
  <div class="actions">
    <button class="expbtn ghost" id="mCancel"></button>
    <button class="expbtn" id="mGo"></button>
  </div>
</div></div>

<div class="toast" id="toast"></div>

<script>
let SUMS=[], CUR=null, FILTERED=[], USERNAME='', LANG='zh';

// ---- 双语字典 (zh 为主, en 并存) ----
const I18N={
  zh:{appTitle:'🗂️ Claude 对话历史',langBtn:'EN',
    locating:'正在定位目录…',rootPrefix:'目录：',rootMissing:'未自动找到目录，点此手动指定',
    search:'搜索标题 / 首条消息…',
    sortRecent:'最近活动',sortCreated:'创建时间',sortTitle:'标题',sortTurns:'轮次最多',
    filtAll:'全部',filtStar:'仅星标',filtActive:'未归档',
    exportAll:'批量导出',pickHint:'选择左侧的一个对话',
    optThink:'显示思考过程',optTool:'显示工具调用',exportOne:'导出此对话',
    viewEmpty:'← 左侧点击任意对话即可预览全文',
    loading:'加载中…',reading:'读取中…',noMatch:'没有匹配的对话',
    mTitle:'批量导出',mFmt:'格式：',mHtml:'HTML 网页',mLang:'导出语言：',
    mThink:'包含思考过程',mTool:'包含工具调用',cancel:'取消',go:'开始导出',
    metaCreated:'创建',metaLast:'最后活动',metaModel:'模型',metaTurnsPre:'提问',metaTurnsPost:'轮',
    subtask:'子任务',thinking:'💭 思考过程',toolCall:'🔧 工具调用',toolResult:'📥 工具结果',
    turnUnit:'轮',claudePrefix:'Claude：',
    exporting:'正在导出…',exported:(n,d)=>`已导出 ${n} 个到：${d}`,exportFail:'导出失败：',
    manualPrompt:'请输入 local-agent-mode-sessions 目录的完整路径：',rootInvalid:'目录无效或其中没有对话数据',
    scope:(n)=>`将导出当前筛选结果：<b>${n}</b> 个对话`},
  en:{appTitle:'🗂️ Claude History',langBtn:'中',
    locating:'Locating folder…',rootPrefix:'Folder: ',rootMissing:'Folder not found — click to set it manually',
    search:'Search title / first message…',
    sortRecent:'Recent activity',sortCreated:'Created',sortTitle:'Title',sortTurns:'Most turns',
    filtAll:'All',filtStar:'Starred',filtActive:'Not archived',
    exportAll:'Export all',pickHint:'Select a conversation on the left',
    optThink:'Show thinking',optTool:'Show tool calls',exportOne:'Export this',
    viewEmpty:'← Click any conversation on the left to preview',
    loading:'Loading…',reading:'Reading…',noMatch:'No matching conversations',
    mTitle:'Batch export',mFmt:'Format: ',mHtml:'HTML page',mLang:'Export language: ',
    mThink:'Include thinking',mTool:'Include tool calls',cancel:'Cancel',go:'Export',
    metaCreated:'Created',metaLast:'Last active',metaModel:'Model',metaTurnsPre:'',metaTurnsPost:' turns',
    subtask:'subtask',thinking:'💭 Thinking',toolCall:'🔧 Tool call',toolResult:'📥 Tool result',
    turnUnit:' turns',claudePrefix:'Claude: ',
    exporting:'Exporting…',exported:(n,d)=>`Exported ${n} to: ${d}`,exportFail:'Export failed: ',
    manualPrompt:'Enter the full path of the local-agent-mode-sessions folder:',rootInvalid:'Invalid folder or no conversation data inside',
    scope:(n)=>`Will export the current ${n} filtered conversation(s)`}
};
function T(){return I18N[LANG];}
let LAST_ROOT=null;
function applyLang(){
  const t=T();
  document.documentElement.lang = (LANG==='zh'?'zh-CN':'en');
  document.getElementById('appTitle').textContent=t.appTitle;
  document.getElementById('btnLang').textContent=t.langBtn;
  document.getElementById('search').placeholder=t.search;
  const so=document.getElementById('sort').options;
  so[0].textContent=t.sortRecent;so[1].textContent=t.sortCreated;so[2].textContent=t.sortTitle;so[3].textContent=t.sortTurns;
  const fo=document.getElementById('filter').options;
  fo[0].textContent=t.filtAll;fo[1].textContent=t.filtStar;fo[2].textContent=t.filtActive;
  document.getElementById('btnExportAll').textContent=t.exportAll;
  document.getElementById('lblThink').textContent=t.optThink;
  document.getElementById('lblTool').textContent=t.optTool;
  document.getElementById('btnExportOne').textContent=t.exportOne;
  document.getElementById('viewEmpty').textContent=t.viewEmpty;
  document.getElementById('mTitle').textContent=t.mTitle;
  document.getElementById('mFmtLabel').textContent=t.mFmt;
  document.getElementById('mHtmlLabel').textContent=t.mHtml;
  document.getElementById('mLangLabel').textContent=t.mLang;
  document.getElementById('lblMThink').textContent=t.mThink;
  document.getElementById('lblMTool').textContent=t.mTool;
  document.getElementById('mCancel').textContent=t.cancel;
  document.getElementById('mGo').textContent=t.go;
  // 目录栏
  const rb=document.getElementById('rootbar');
  if(LAST_ROOT) rb.textContent=t.rootPrefix+LAST_ROOT;
  else rb.textContent=t.rootMissing;
  // 未选中对话时标题占位
  if(!CUR) document.getElementById('title').textContent=t.pickHint;
  // 重渲染列表与当前对话
  if(SUMS.length) render();
  if(LASTCONV) renderConv(LASTCONV);
}
function toggleLang(){LANG=(LANG==='zh'?'en':'zh');applyLang();}

function toast(msg,ms=2200){const t=document.getElementById('toast');t.textContent=msg;
  t.classList.add('show');clearTimeout(t._t);t._t=setTimeout(()=>t.classList.remove('show'),ms);}

function fmtTime(v){ if(!v) return '';
  let d; if(typeof v==='number'){d=new Date(v);} else {d=new Date(v);}
  if(isNaN(d)) return ''; const p=n=>String(n).padStart(2,'0');
  return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;}

async function boot(){
  document.getElementById('btnLang').onclick=toggleLang;
  applyLang();
  const r=await fetch('/api/root').then(r=>r.json());
  USERNAME=r.user||'';
  LAST_ROOT=r.root||null;
  const rb=document.getElementById('rootbar');
  rb.textContent = r.root ? (T().rootPrefix+r.root) : T().rootMissing;
  if(!r.root){ rb.style.cursor='pointer'; rb.onclick=manualRoot; }
  await loadList();
}
async function manualRoot(){
  const p=prompt(T().manualPrompt);
  if(!p) return;
  const r=await fetch('/api/root',{method:'POST',body:JSON.stringify({root:p})}).then(r=>r.json());
  if(r.ok){LAST_ROOT=r.root; document.getElementById('rootbar').textContent=T().rootPrefix+r.root; loadList();}
  else toast(T().rootInvalid);
}
async function loadList(){
  document.getElementById('list').innerHTML='<div class="empty"><span class="spinner"></span> '+T().loading+'</div>';
  SUMS=await fetch('/api/list').then(r=>r.json());
  render();
}
function render(){
  const kw=document.getElementById('search').value.trim().toLowerCase();
  const sort=document.getElementById('sort').value;
  const filt=document.getElementById('filter').value;
  FILTERED=SUMS.filter(s=>{
    if(filt==='star'&&!s.isStarred) return false;
    if(filt==='active'&&s.isArchived) return false;
    if(kw){const hay=((s.title||'')+' '+(s.firstText||s.firstUserText||'')+' '+(s.lastText||'')).toLowerCase();
      if(!hay.includes(kw)) return false;}
    return true;
  });
  FILTERED.sort((a,b)=>{
    if(sort==='title') return (a.title||'').localeCompare(b.title||'','zh');
    if(sort==='created') return (b.createdAt||0)-(a.createdAt||0);
    if(sort==='turns') return (b.userTurns||0)-(a.userTurns||0);
    return (b.lastActivityAt||0)-(a.lastActivityAt||0);
  });
  const box=document.getElementById('list');
  const t=T();
  document.getElementById('count').textContent=FILTERED.length+' / '+SUMS.length;
  if(!FILTERED.length){box.innerHTML='<div class="empty">'+t.noMatch+'</div>';return;}
  box.innerHTML=FILTERED.map((s,i)=>{
    const star=s.isStarred?'<span class="star">★</span>':'';
    const who=(s.firstRole==='assistant')?t.claudePrefix:'';
    const snip=(s.firstText!==undefined?s.firstText:s.firstUserText)||'';
    return `<div class="item" data-id="${s.sessionId}">
      <div class="t">${star}${esc(s.title)}</div>
      <div class="sub">${fmtTime(s.createdAt)} · ${s.userTurns}${t.turnUnit}</div>
      <div class="snip">${who?('<b>'+who+'</b>'):''}${esc(snip.slice(0,120))}</div></div>`;
  }).join('');
  [...box.querySelectorAll('.item')].forEach(el=>el.onclick=()=>openConv(el.dataset.id,el));
}
function esc(t){const d=document.createElement('div');d.textContent=t||'';return d.innerHTML;}

async function openConv(id,el){
  [...document.querySelectorAll('.item')].forEach(x=>x.classList.remove('active'));
  if(el)el.classList.add('active');
  CUR=id;
  document.getElementById('btnExportOne').disabled=false;
  document.getElementById('view').innerHTML='<div class="empty"><span class="spinner"></span> '+T().reading+'</div>';
  const c=await fetch('/api/conv?id='+encodeURIComponent(id)).then(r=>r.json());
  document.getElementById('title').textContent=c.title;
  renderConv(c);
}
let LASTCONV=null;
function renderConv(c){
  LASTCONV=c;
  const t=T();
  const showT=document.getElementById('optThink').checked;
  const showU=document.getElementById('optTool').checked;
  let meta=`<div class="metaline">
    <span>${t.metaCreated} ${fmtTime(c.createdAt)}</span>
    <span>${t.metaLast} ${fmtTime(c.lastActivityAt)}</span>
    <span>${t.metaModel} ${esc(c.model||'')}</span>
    <span>${t.metaTurnsPre} ${c.userTurns}${t.metaTurnsPost}</span></div>`;
  let html=meta;
  for(const m of c.messages){
    if(m.isSynthetic) continue;
    let pieces='';
    for(const b of m.blocks){
      if(b.kind==='text'&&b.text.trim()) pieces+=`<div class="text">${esc(b.text)}</div>`;
      else if(b.kind==='thinking'&&showT&&b.text.trim())
        pieces+=`<div class="thinking"><span class="lbl">${t.thinking}</span>${esc(b.text)}</div>`;
      else if(b.kind==='tool_use'&&showU)
        pieces+=`<div class="tool"><span class="lbl">${t.toolCall}: ${esc(b.name||'')}</span><pre>${esc(JSON.stringify(b.input||{},null,2)).slice(0,4000)}</pre></div>`;
      else if(b.kind==='tool_result'&&showU&&(b.text||'').trim())
        pieces+=`<div class="tool"><span class="lbl">${t.toolResult}</span><pre>${esc((b.text||'').slice(0,4000))}</pre></div>`;
    }
    if(!pieces) continue;
    const cls=m.role==='user'?'user':'assistant';
    const role=m.role==='user'?USERNAME:'Claude';
    const tag=m.isAgent?`<span class="tag">${t.subtask}</span>`:'';
    html+=`<div class="msg ${cls}"><div class="role">${role}<span class="time">${fmtTime(m.timestamp)}</span>${tag}</div>${pieces}</div>`;
  }
  document.getElementById('view').innerHTML=html;
  document.getElementById('view').scrollTop=0;
}
document.getElementById('optThink').onchange=()=>LASTCONV&&renderConv(LASTCONV);
document.getElementById('optTool').onchange=()=>LASTCONV&&renderConv(LASTCONV);
document.getElementById('search').oninput=render;
document.getElementById('sort').onchange=render;
document.getElementById('filter').onchange=render;

// 批量导出弹窗
const modal=document.getElementById('modal');
let EXPORT_SINGLE=false;   // 弹窗当前是"导出此对话"还是"批量导出"
document.getElementById('btnExportAll').onclick=()=>{
  EXPORT_SINGLE=false;
  document.getElementById('mScope').innerHTML=T().scope(FILTERED.length);
  modal.classList.add('show');
};
document.getElementById('mCancel').onclick=()=>modal.classList.remove('show');
document.getElementById('mGo').onclick=async()=>{
  const fmt=document.querySelector('input[name=fmt]:checked').value;
  const elang=document.querySelector('input[name=elang]:checked').value;
  const ids=EXPORT_SINGLE?(CUR?[CUR]:[]):FILTERED.map(s=>s.sessionId);
  const body={ids,fmt,lang:elang,
    thinking:document.getElementById('mThink').checked,
    tools:document.getElementById('mTool').checked};
  modal.classList.remove('show');
  await doExport(body);
};
async function doExport(body){
  const t=T();
  toast(t.exporting,60000);
  const r=await fetch('/api/export',{method:'POST',body:JSON.stringify(body)}).then(r=>r.json());
  if(r.ok) toast(t.exported(r.count,r.dir),5000);
  else toast(t.exportFail+(r.error||''),4000);
}
// 单个导出也走同一个弹窗(带语言选择)，比 prompt 清晰
document.getElementById('btnExportOne').onclick=()=>{
  if(!CUR) return;
  EXPORT_SINGLE=true;
  document.getElementById('mScope').innerHTML=esc(LASTCONV?LASTCONV.title:'');
  modal.classList.add('show');
};
boot();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # 静音

    def _send(self, code, ctype, body):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, "application/json", json.dumps(obj, ensure_ascii=False))

    def _read_body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        if p == "/" or p == "/index.html":
            self._send(200, "text/html", INDEX_HTML)
        elif p == "/api/root":
            self._json({"root": STATE["root"], "user": exporter.current_user_label()})
        elif p == "/api/list":
            self._json(get_summaries())
        elif p == "/api/conv":
            qs = parse_qs(u.query)
            sid = (qs.get("id") or [""])[0]
            self._json(self._get_conv(sid))
        else:
            self._send(404, "text/plain", "not found")

    def do_POST(self):
        u = urlparse(self.path)
        p = u.path
        body = self._read_body()
        if p == "/api/root":
            root = scanner.looks_like_sessions_root(body.get("root", ""))
            if root:
                STATE["root"] = root
                STATE["summaries"] = None
                self._json({"ok": True, "root": root})
            else:
                self._json({"ok": False}, 400)
        elif p == "/api/export":
            self._json(self._do_export(body))
        else:
            self._send(404, "text/plain", "not found")

    # -- helpers --
    def _get_conv(self, sid):
        metas = scanner.load_metadata(STATE["root"]) if STATE["root"] else []
        m = next((x for x in metas if x["sessionId"] == sid), None)
        if not m:
            return {"error": "not found", "messages": []}
        return scanner.build_conversation(m, STATE["root"],
                                          include_agent=STATE["include_agent"])

    def _do_export(self, body):
        try:
            ids = body.get("ids", [])
            fmt = body.get("fmt", "md")
            thinking = bool(body.get("thinking"))
            tools = bool(body.get("tools"))
            lang = body.get("lang", "zh")
            if lang not in ("zh", "en"):
                lang = "zh"
            out_dir = default_export_dir()
            metas = scanner.load_metadata(STATE["root"]) if STATE["root"] else []
            mmap = {x["sessionId"]: x for x in metas}
            count = 0
            for sid in ids:
                m = mmap.get(sid)
                if not m:
                    continue
                conv = scanner.build_conversation(m, STATE["root"],
                                                  include_agent=STATE["include_agent"])
                exporter.export_conversation(conv, out_dir, fmt, thinking, tools, lang)
                count += 1
            return {"ok": True, "count": count, "dir": out_dir}
        except Exception as e:
            return {"ok": False, "error": str(e)}


def pick_port(start=8734):
    for port in range(start, start + 40):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start


def main():
    # 允许命令行指定目录，否则自动定位
    if len(sys.argv) > 1:
        STATE["root"] = scanner.looks_like_sessions_root(sys.argv[1]) or sys.argv[1]
    else:
        STATE["root"] = scanner.default_sessions_root()

    port = pick_port()
    url = f"http://127.0.0.1:{port}/"
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)

    banner = (
        "=" * 54 + "\n"
        "  Claude 对话历史浏览与导出工具\n" +
        "=" * 54 + "\n"
        "  目录: " + (STATE["root"] or "(未自动找到，可在网页里手动指定)") + "\n"
        "  地址: " + url + "\n"
        "  导出落点: " + default_export_dir() + "\n"
        "  关闭本窗口即可停止程序。\n" +
        "=" * 54
    )
    print(banner, flush=True)

    threading.Thread(target=lambda: (time.sleep(0.8), webbrowser.open(url)),
                     daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()