#!/usr/bin/env python3
"""Locate xelis_compile_tool. Override with XELIS_COMPILE_TOOL."""
from __future__ import annotations

import os
import shutil
from pathlib import Path


def find_compile_tool() -> Path:
    env = os.environ.get("XELIS_COMPILE_TOOL", "").strip()
    candidates = []
    if env:
        candidates.append(Path(env).expanduser())
    which = shutil.which("xelis_compile_tool")
    if which:
        candidates.append(Path(which))
    home = Path.home()
    candidates.extend([
        home / "opencode" / "xelis-compile-tool" / "target" / "release" / "xelis_compile_tool",
        home / "xelis-compile-tool" / "target" / "release" / "xelis_compile_tool",
        Path("/usr/local/bin/xelis_compile_tool"),
        Path("/opt/xelis/xelis_compile_tool"),
    ])
    for p in candidates:
        if p.is_file() and os.access(p, os.X_OK):
            return p
    raise FileNotFoundError(
        "xelis_compile_tool not found. Set XELIS_COMPILE_TOOL or install the binary on PATH."
    )


if __name__ == "__main__":
    print(find_compile_tool())
