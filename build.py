#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
跨平台打包脚本（Linux / macOS / Windows）。

用法：
    python3 build.py

它会：
  1. 在项目目录下创建虚拟环境 .build_venv（复用已有环境）；
  2. 在其中安装 PyInstaller 和 requests；
  3. 用 PyInstaller 把 bili_live_replay.py 打包成当前平台的单文件可执行程序；
  4. 产物输出到 dist/ 目录（Windows 下为 bili_live_replay.exe）。
"""

import os
import subprocess
import sys
import venv
from pathlib import Path

BASE = Path(__file__).resolve().parent
VENV = BASE / ".build_venv"


def run(cmd):
    print("+", " ".join(map(str, cmd)), flush=True)
    subprocess.check_call(cmd)


def venv_python():
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def main():
    py = venv_python()
    if not py.exists():
        print("创建虚拟环境 ...", flush=True)
        venv.create(VENV, with_pip=True)

    print("安装打包依赖（PyInstaller / requests）...", flush=True)
    run([str(py), "-m", "pip", "install", "--upgrade", "pyinstaller", "requests"])

    print("开始打包 ...", flush=True)
    run([str(py), "-m", "PyInstaller", "--onefile", "--name", "bili_live_replay",
         "--clean", str(BASE / "bili_live_replay.py")])

    exe = "bili_live_replay.exe" if os.name == "nt" else "bili_live_replay"
    out = BASE / "dist" / exe
    print(f"\n打包完成 ✅ 产物在：{out}", flush=True)
    print("可直接拷贝该文件到同平台的其他机器上运行。", flush=True)


if __name__ == "__main__":
    main()
