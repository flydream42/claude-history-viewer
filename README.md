# Claude History Viewer

> Claude Desktop（Gateway / 自接 API 模式）本地对话历史的浏览与导出工具。
> A local browser & exporter for Claude Desktop conversation history (Gateway / bring-your-own-API mode).

**中文说明在上，English below.**

纯 Python 标准库实现，无第三方依赖。只在本机运行、只读你的对话文件、绝不联网上传。
Pure Python standard library, no third-party dependencies. Runs locally, reads your data read-only, never uploads anything.

> **状态 / Status**
>
> 🪟 仅支持 **Windows**（其它平台未测试）。目前仅在作者本人电脑上测试通过，虚拟机环境的兼容性测试正在进行中，届时会更新本说明。欢迎试用并反馈问题。
>
> 🪟 **Windows only** (other platforms untested). So far verified only on the author's own machine; compatibility testing in a clean virtual machine is in progress and this README will be updated accordingly. Try it out and please report issues.

---

## 中文说明

### 这个工具解决什么问题

在 Claude Desktop 的 **Gateway / 自接 API 模式**下，所有对话都存在本机。但有两个痛点：

1. **侧边栏不显示历史会话**（已知 bug [#83164](https://github.com/anthropics/claude-code/issues)）——会话数据明明在磁盘上，界面却列不出来。
2. **上下文压缩会"吃掉"早期内容**——一旦对话被自动压缩接续，界面里就再也翻不到最早的那些消息了。

本工具直接扫描本机会话目录，把**全部**对话列出来，并能一键导出成 Markdown 或 HTML 网页归档。

### 为什么它能拿到"完整"历史

关键在于读对了文件。每个会话目录里有一个 **`audit.jsonl`**——这是从会话第一天起、逐条追加、带 HMAC 链式校验、**永不删改的原始账本**。

压缩接续后系统会重新生成一批"工作副本"（`.claude/projects/` 下的分段 jsonl），那些副本**天生就缺被压缩掉的最早消息**。很多同类尝试读的是这些副本，所以还是丢早期内容。本工具优先读 `audit.jsonl`，因此连最早的第一条消息也能完整还原——**原始记录一条不丢**。

（实测：某条从 7 月初开始的长对话，读分段副本只能恢复到 7 月下旬，读 `audit.jsonl` 能完整恢复到真正的首条。）

### 快速开始

**方式一：下载 exe，双击即用（推荐，无需装 Python）**

到本仓库的 [Releases](../../releases) 页面下载 `ClaudeHistoryViewer.exe`，双击运行即可。它会自动定位你的对话目录、起一个只在本机的小服务、打开浏览器。用完关掉黑色命令行窗口即停止。

**方式二：用源码跑（需要 Python 3）**

双击 `run.bat`，或在命令行：

```bash
python claude_history_tool.py
```

没有 Python 的话，去 <https://www.python.org/downloads/> 安装 Python 3，安装时务必勾选 **“Add Python to PATH”**。

### 界面怎么用

- **左栏**：全部对话列表。显示标题、创建时间、提问轮次。顶部可搜索（标题＋首末条内容）、按最近活动 / 创建时间 / 标题 / 轮次排序、只看星标或未归档。
- **右栏**：点任意对话看全文。两个开关：**显示思考过程**、**显示工具调用**（默认都关）。
- **语言**：左上角 `EN / 中` 按钮一键切换界面中英文。
- **导出**：右上「导出此对话」导出当前这条；左上「批量导出」导出当前筛选出的全部。格式可选 Markdown / HTML，导出语言可选中 / 英，思考过程与工具调用是否包含由弹窗勾选。导出文件默认放在你用户主目录下的 `Claude对话导出` 文件夹。

### 找不到目录时

正常会自动定位。如果左上提示"未自动找到目录"，点那行字，把会话目录完整路径粘进去即可，通常是：

```
%LOCALAPPDATA%\Claude-3p\local-agent-mode-sessions
```

### 隐私声明

- **只读**你的对话文件，从不修改。
- **绝不联网**、绝不把任何内容上传到任何地方。全部处理在本机完成。
- 本地服务只监听 `127.0.0.1`（本机回环），同一网络的其它设备访问不到。
- 界面里显示的用户名取自你当前的系统登录名（可用环境变量 `CLAUDE_HISTORY_USERNAME` 覆盖），源码里不写死任何人的名字。
- ⚠️ 如果你 fork 本仓库，请务必**不要**把你自己的对话数据、`audit.jsonl`、或导出结果提交上去。仓库自带的 `.gitignore` 已经帮你挡住了这些文件。

### 自行打包 exe

不想用 Releases 里的、想自己打，双击 `build_exe.bat`（需要 Python）。它会重新合并单文件、装 PyInstaller、打出 `dist\ClaudeHistoryViewer.exe`。

### 项目结构

| 文件 | 作用 |
|------|------|
| `scanner.py` | 扫描定位会话目录、解析 `audit.jsonl`、还原完整时间线 |
| `exporter.py` | 导出 Markdown / HTML（中英双语） |
| `app.py` | 本地 HTTP 服务 + 内嵌单页前端 |
| `build_single.py` | 把上面三个模块合并成单文件 `claude_history_tool.py` |
| `claude_history_tool.py` | 合并后的单文件版（供打包 / 直接运行） |
| `run.bat` / `build_exe.bat` | 一键运行 / 一键打包（Windows） |
| `.github/workflows/release.yml` | 打 tag 自动云端打包 exe 并发 Release |

改了 `scanner/exporter/app` 任一个后，重跑 `python build_single.py` 重新生成单文件。

---

## English

### What it solves

In Claude Desktop's **Gateway / bring-your-own-API mode**, all conversations are stored locally, but two things hurt:

1. **The sidebar doesn't list past conversations** (known bug #83164) — the data is on disk, but the UI won't show it.
2. **Context compaction "eats" early content** — once a conversation is auto-compacted, you can no longer scroll back to the earliest messages in the UI.

This tool scans your local session directory, lists **every** conversation, and exports any of them to Markdown or an HTML page for archiving.

### Why it recovers the *complete* history

It comes down to reading the right file. Each session folder contains an **`audit.jsonl`** — an append-only, HMAC-chained, **tamper-proof original ledger** written from day one of the session.

After compaction, the app regenerates "working copies" (the segmented jsonl files under `.claude/projects/`) that **inherently lack the compacted-away earliest messages**. Many naive attempts read those copies and still lose early content. This tool reads `audit.jsonl` first, so even the very first message is fully recovered — **no original record is ever lost**.

### Quick start

**Option A — download the exe (recommended, no Python needed)**

Grab `ClaudeHistoryViewer.exe` from the [Releases](../../releases) page and double-click it. It auto-locates your session folder, starts a local-only server, and opens your browser. Close the console window to stop.

**Option B — run from source (needs Python 3)**

Double-click `run.bat`, or:

```bash
python claude_history_tool.py
```

No Python? Install Python 3 from <https://www.python.org/downloads/> and check **“Add Python to PATH”** during setup.

### Using the UI

- **Left pane**: all conversations, with search, sort (recent / created / title / turns), and star / archive filters.
- **Right pane**: click any conversation to read it. Two toggles: **Show thinking** and **Show tool calls** (both off by default).
- **Language**: the top-left `EN / 中` button switches the UI between English and Chinese.
- **Export**: "Export this" for the current one, "Export all" for the current filtered set. Choose Markdown / HTML, export language (Chinese / English), and whether to include thinking / tool calls. Files land in a `Claude对话导出` folder in your home directory by default.

### Privacy

- **Read-only** access to your conversation files; never modifies them.
- **No network**, ever — nothing is uploaded anywhere. All processing is local.
- The local server binds to `127.0.0.1` only; other devices on your network cannot reach it.
- The displayed username is taken from your current OS login (override with the `CLAUDE_HISTORY_USERNAME` env var). No personal name is hardcoded anywhere in the source.
- ⚠️ If you fork this repo, **do not** commit your own conversation data, `audit.jsonl`, or exports. The bundled `.gitignore` already blocks them.

### Building the exe yourself

Double-click `build_exe.bat` (needs Python). It re-merges the single file, installs PyInstaller, and produces `dist\ClaudeHistoryViewer.exe`. Or let GitHub Actions do it: push a tag like `v1.0.0` and the workflow builds the Windows exe and attaches it to a Release automatically.

### Project layout

| File | Purpose |
|------|---------|
| `scanner.py` | Locate the session dir, parse `audit.jsonl`, rebuild the full timeline |
| `exporter.py` | Export to Markdown / HTML (bilingual) |
| `app.py` | Local HTTP server + embedded single-page frontend |
| `build_single.py` | Merge the three modules into one file, `claude_history_tool.py` |
| `claude_history_tool.py` | The merged single-file build (for packaging / direct run) |
| `run.bat` / `build_exe.bat` | One-click run / build (Windows) |
| `.github/workflows/release.yml` | Auto-build the exe and publish a Release on tag push |

After editing any of `scanner/exporter/app`, re-run `python build_single.py` to regenerate the single file.

---

## License

[MIT](LICENSE) © 2026 flydream42
