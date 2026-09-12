# Claude History Viewer

> Claude Desktop（Gateway / 自接 API 模式）本地对话历史的浏览与导出工具。
> A local browser & exporter for Claude Desktop conversation history (Gateway / bring-your-own-API mode).

**中文说明在上，English below.**

> ⚠️ **适用范围：仅限 Gateway 模式（自己接入 API 的用户），不适用于官方订阅用户**
>
> 本工具是开发者本人为解决自己的痛点而做的——我在 Claude Desktop 里用的是 **Gateway 模式**，也就是**自己接入第三方 / 自建的 API**（配合 [CC Switch](https://github.com/farion1231/cc-switch) 这类工具来切换、管理各家 API 供应商），而**不是**用 Claude 官方订阅登录。这种模式下，所有对话以明文形式存在本机磁盘上，本工具正是直接读取这些本地文件。
>
> 如果你用的是 **Claude 官方订阅**（在客户端里登录 Anthropic 账号使用），你的对话**不以这种形式存储在本地**，本工具**读不到、也不适用**。请勿在官方订阅场景下期待它能导出你的对话。

> ⚠️ **Scope: Gateway mode only (bring-your-own-API users). NOT for official subscription users.**
>
> This tool was built by its author to scratch a personal itch. I use Claude Desktop in **Gateway mode** — connecting my **own / third-party API** (using tools like [CC Switch](https://github.com/farion1231/cc-switch) to switch and manage API providers for Claude Desktop), rather than signing in with an official Claude subscription. In this mode every conversation is stored as plaintext on your local disk, and this tool reads those local files directly.
>
> If you use an **official Claude subscription** (signing into your Anthropic account in the client), your conversations are **not stored this way locally**, so this tool **cannot read them and does not apply**. Please don't expect it to export your chats in that case.

纯 Python 标准库实现，无第三方依赖。全程在本机运行，以只读方式读取对话文件，本身不含任何联网功能。
Pure Python standard library, no third-party dependencies. Runs entirely on your machine, reads conversation files read-only, and includes no networking functionality.

> **状态 / Status**
>
> 🪟 **主要面向 Windows。** 目前仅在作者本人的 Windows 电脑上测试通过，虚拟机环境的兼容性测试正在进行中，届时会更新本说明。发布的 `.exe` 也仅限 Windows。
>
> 🍎 **macOS / Linux 未经验证。** 代码里为 Mac/Linux 预留了路径猜测，但作者没有 Mac/Linux 设备实测过，很可能需要手动指定目录、甚至改动代码才能跑起来，不保证可用。
>
> 🙋 作者是一名**计算机专业大二在读学生，能力有限**，这个工具是为解决自己的痛点顺手做的，也是**作者发布的第一个开源项目**。如果你遇到无法使用的情况，**非常欢迎提 [Issue](../../issues) 反馈**（附上系统、报错信息最好），也**欢迎 Fork 自行改进**，还请多多包涵。
>
> ---
>
> 🪟 **Windows-first.** So far verified only on the author's own Windows machine; compatibility testing in a clean VM is in progress and this README will be updated accordingly. The released `.exe` is Windows-only.
>
> 🍎 **macOS / Linux not verified.** The code includes guessed paths for Mac/Linux, but the author has no Mac/Linux device to test on — it may well need manual folder selection or even code changes, and is not guaranteed to work.
>
> 🙋 The author is a **second-year computer science undergraduate with limited experience**, and built this to scratch a personal itch — this is also the **author's first open-source project**. If it doesn't work for you, please **open an [Issue](../../issues)** (ideally with your OS and any error output) — and **feel free to Fork and improve it**. Thanks for your understanding.

---

## 中文说明

### 这个工具解决什么问题

在 Claude Desktop 的 **Gateway / 自接 API 模式**下，所有对话都存在本机，但要方便地回看和留存并不容易，尤其是：

- **想集中查看、检索、归档历史对话**——把本机所有会话列在一起浏览、搜索，比在客户端里一条条翻方便得多。
- **上下文压缩会"吃掉"早期内容**——一旦对话被自动压缩接续，界面里就再也翻不到最早的那些消息了。

本工具直接扫描本机会话目录，把**全部**对话列出来供浏览、搜索，并能一键导出成 Markdown 或 HTML 网页归档——**包括被上下文压缩掉的早期内容**。

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

- 以**只读**方式访问对话文件，不做任何写入或修改。
- 代码本身不含联网功能，所有处理都在本机完成，数据不离开你的电脑。
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

In Claude Desktop's **Gateway / bring-your-own-API mode**, all conversations are stored locally, but reviewing and preserving them isn't easy:

- **You want to browse, search, and archive past conversations in one place** — far handier than scrolling through them one by one in the client.
- **Context compaction "eats" early content** — once a conversation is auto-compacted, you can no longer scroll back to the earliest messages in the UI.

This tool scans your local session directory, lists **every** conversation for browsing and search, and exports any of them to Markdown or an HTML page for archiving — **including the early content lost to context compaction**.

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

- **Read-only** access to your conversation files; no writes or modifications.
- The code contains no networking functionality; all processing happens locally and your data never leaves your machine.
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
