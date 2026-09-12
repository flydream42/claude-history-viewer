# -*- coding: utf-8 -*-
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
