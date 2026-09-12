# -*- coding: utf-8 -*-
"""把 scanner.py + exporter.py + app.py 合并成单文件 claude_history_tool.py。

合并策略:
  - scanner / exporter 的模块级代码直接拼进来(它们只依赖标准库)。
  - app.py 里的 `import scanner` / `import exporter` 换成
    `scanner = _sys.modules[__name__]` 别名，使 app 中的 scanner.xxx()
    调用解析到本文件顶层同名函数。
  - 重复的 `import os/re/json/...` 保留无妨(幂等)。
"""
import io, os, re, sys

# GitHub Windows runner 默认 stdout 用 cp1252，打印非 ASCII 会崩。强制 UTF-8。
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))


def read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


def strip_coding(src):
    # 去掉每个模块开头的 coding 声明，最终文件只保留一个
    lines = src.splitlines()
    out = []
    for ln in lines:
        if ln.strip().startswith("# -*- coding"):
            continue
        out.append(ln)
    return "\n".join(out)


def strip_main_block(src):
    """删除模块末尾的 `if __name__ == \"__main__\":` 自测块，
    避免合并后 scanner/exporter 的自测代码在直接运行时被执行。"""
    lines = src.splitlines()
    out = []
    skipping = False
    for ln in lines:
        if not skipping and re.match(r'^if __name__ == ["\']__main__["\']:\s*$', ln):
            skipping = True
            continue
        if skipping:
            # 块内(缩进行或空行)全部跳过；遇到顶格非空行则结束(通常不会有)
            if ln.strip() == "" or ln[:1] in (" ", "\t"):
                continue
            skipping = False
            out.append(ln)
        else:
            out.append(ln)
    return "\n".join(out)


def main():
    scanner = strip_main_block(strip_coding(read("scanner.py")))
    exporter = strip_main_block(strip_coding(read("exporter.py")))
    app = strip_coding(read("app.py"))

    # 从 app 中移除 `import scanner` / `import exporter`
    app = re.sub(r"(?m)^import scanner\s*$", "", app)
    app = re.sub(r"(?m)^import exporter\s*$", "", app)

    parts = []
    parts.append("# -*- coding: utf-8 -*-")
    parts.append('"""Claude 对话历史浏览与导出工具 (单文件版, 便于 PyInstaller 打包)。"""')
    parts.append("import sys as _sys")
    parts.append("")
    parts.append("# ===== scanner.py =====")
    parts.append(scanner)
    parts.append("")
    parts.append("# ===== exporter.py =====")
    parts.append(exporter)
    parts.append("")
    parts.append("# 让 app 段里的 scanner./exporter. 调用解析到本文件顶层函数")
    parts.append("scanner = _sys.modules[__name__]")
    parts.append("exporter = _sys.modules[__name__]")
    parts.append("")
    parts.append("# ===== app.py =====")
    parts.append(app)

    out = "\n".join(parts)
    with open(os.path.join(HERE, "claude_history_tool.py"), "w", encoding="utf-8") as f:
        f.write(out)
    print("Generated claude_history_tool.py -", len(out.splitlines()), "lines")


if __name__ == "__main__":
    main()
