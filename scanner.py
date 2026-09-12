# -*- coding: utf-8 -*-
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


if __name__ == "__main__":
    import sys
    root = sys.argv[1] if len(sys.argv) > 1 else default_sessions_root()
    if not root:
        print("未找到会话目录，请把目录作为参数传入。")
        sys.exit(1)
    print("扫描目录:", root)
    s = scan_all(root)
    print("会话数:", len(s))
    for x in s[:10]:
        print(f"  [{'★' if x['isStarred'] else ' '}] {x['title'][:24]:24}  "
              f"轮次{x['userTurns']:>4}  段{x['transcriptCount']}  "
              f"首:{(x['firstUserText'] or '')[:20]}")
