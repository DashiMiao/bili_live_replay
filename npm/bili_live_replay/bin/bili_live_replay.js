#!/usr/bin/env node
"use strict";

const { spawn } = require("child_process");

// 各平台的预编译二进制包
const PACKAGES = {
  "linux-x64": "@miaodashi/bili_live_replay-linux-x64",
  "darwin-x64": "@miaodashi/bili_live_replay-darwin-x64",
  "darwin-arm64": "@miaodashi/bili_live_replay-darwin-arm64",
  "win32-x64": "@miaodashi/bili_live_replay-win32-x64",
};

const key = `${process.platform}-${process.arch}`;
const pkgName = PACKAGES[key];

if (!pkgName) {
  console.error(`不支持当前平台: ${process.platform}-${process.arch}`);
  process.exit(1);
}

let binaryPath;
try {
  binaryPath = require(pkgName);
} catch (err) {
  console.error(`缺少平台二进制包 ${pkgName}，请手动安装: npm install ${pkgName}`);
  process.exit(1);
}

const child = spawn(binaryPath, process.argv.slice(2), { stdio: "inherit" });

// 转发 Ctrl+C / 终止信号，让 Python 端能正常清理临时文件
for (const sig of ["SIGINT", "SIGTERM"]) {
  process.on(sig, () => {
    if (!child.killed) {
      child.kill(sig);
    }
  });
}

child.on("error", (err) => {
  console.error(`无法运行 ${binaryPath}: ${err.message}`);
  process.exit(1);
});

child.on("close", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code == null ? 1 : code);
});
