# bili_live_replay —— bilibili 直播回放下载工具

根据房间号 + 日期，下载指定直播回放，并自动按固定时长（默认 1 小时）切分。
若直播中途断流，会自动把断流前后的片段拼接起来，并在导出后告诉你断流原因。

## 跨平台支持

工具源码是纯 Python，可在 **Linux / macOS / Windows** 上运行；也可以打包成各平台的原生可执行文件。

### 方式一：直接跑源码（通用）

任意系统，装好 Python 3.8+ 和一个依赖即可：

```bash
pip3 install requests
python3 bili_live_replay.py --room-id 9308312 --cookie-file cookie.txt 2026-11-10
```

### 方式二：打包成当前平台的可执行文件

在对应系统的机器上执行：

```bash
python3 build.py
```

会在 `dist/` 目录生成当前平台的可执行文件（Linux 为 `bili_live_replay`，Windows 为 `bili_live_replay.exe`，macOS 为 `bili_live_replay`）。

### 各平台依赖说明

| 依赖 | Linux | macOS | Windows |
|------|-------|-------|---------|
| Python | `sudo apt install python3` | `brew install python` | 官网下载安装包 |
| requests | `pip3 install requests` | 同左 | 同左 |
| ffmpeg | 脚本自动下载 | 脚本自动下载 | 脚本自动下载 |
| aria2c（可选） | `sudo apt install aria2` | `brew install aria2` | `winget install aria2` |

> **ffmpeg 自动下载**：脚本会在系统里找不到 ffmpeg 时，按平台自动下载静态 ffmpeg 到「程序同目录下的 `tools/`」（Linux 用 apt 源、失败回退 johnvansickle；macOS 用 evermeet.cx；Windows 用 gyan.dev）。下载优先用 aria2c 多连接加速，没有 aria2c 时用 requests 单线程并显示进度。
> **aria2c 自动下载**：Windows 上找不到 aria2c 时会自动从 GitHub 下载 aria2c.exe 到 `tools/`；下载失败或 Linux/macOS 上找不到时，自动回退为 Python 多线程下载（慢一点，但能用）。
> 下载的工具二进制都放在程序旁边的 `tools/` 目录里，方便连同程序一起拷贝到别的机器。

## 用法

```bash
# 单个日期
bili_live_replay --room-id 9308312 --cookie-file cookie.txt 2026-11-10

# 多个日期
bili_live_replay --room-id 9308312 --cookie "$COOKIE" 2026-11-10 2026-11-11

# 指定输出目录
bili_live_replay --room-id 9308312 --cookie "$COOKIE" --out-dir ~/下载 2026-11-10

# 一键下载最近 N 场回放（自动跳过没开播的日期）
bili_live_replay --room-id 9308312 --cookie-file cookie.txt --recent 3
```

### 参数说明

| 参数 | 说明 |
|------|------|
| `dates`（位置参数） | 要下载的日期，格式 `YYYY-MM-DD`，可多个 |
| `--room-id` | 直播间房间号（必填） |
| `--cookie` | Cookie 字符串 |
| `--cookie-file` | 从文件读取 Cookie（与 `--cookie` 二选一） |
| `--out-dir` | 输出目录，默认当前目录 |
| `--part-seconds` | 每个片段时长（秒），默认 3600（1 小时） |
| `--live-uid` | 主播 uid（可选，跳过房间号解析） |
| `--keep-temp` | 保留临时分片（默认自动清理） |
| `--recent N` | 下载最近 N 场回放（与日期列表二选一） |
| `--proxy URL` | 指定代理（如 `http://127.0.0.1:7890`）；默认直连、自动绕过系统代理 |

## 输出与命名

- 文件名：`yyyy_mm_dd_partN.mp4`，`N` 从 1 开始。
- 每小时一个片段，结尾不足 1 小时的单独成一个片段。

例如：

```
2026_11_10_part1.mp4
2026_11_10_part2.mp4
2026_11_10_part3.mp4
2026_11_10_part4.mp4
2026_11_10_part5.mp4   <- 结尾不足 1 小时的余量
```

## 断流处理

若某场直播中途断流（回放被切成多段），工具会：

1. 打印每一段的起止时间；
2. 下载并拼接断流前后的内容（视频连续无缺）；
3. 导出后调用接口分析断流原因，并在终端中说明，例如：

```
断流原因分析：
  断流时段: 18:03:47 ~ 18:07:30 （约 3 分 43 秒）
  断流原因: 推流网络问题（主播端推流掉线后重新推流；断流期间直播间与弹幕仍在，非违规封禁）
```

判定的依据：
- `ban_list` / `is_ban_publish`：是否为平台违规封禁；
- `alert_message`：平台提示（如“请关注直播时网络状况”）；
- 会话弹幕数据：断流期间弹幕是否仍在（仍在则说明只是推流断了、直播间没关）。

## 说明

- 下载他人直播间回放，需要你的账号已获得该主播的「剪辑权限（授权）」，否则接口返回 `301 没有剪辑权限`。
- Cookie 只需要 `SESSDATA` 即可登录；若从浏览器复制的 Cookie 是 URL 编码过的（含 `%2C`、`%2A` 等），脚本会自动尝试解码后登录。
- 接口最多返回近 14 天的回放。
- 下载过程中按 `Ctrl+C` 可立即中断（会自动结束 aria2c 子进程并清理临时文件）。
- 默认直连下载（绕过系统代理）；若开了代理/梯子导致问题，默认已不受影响，如确需走代理用 `--proxy` 指定。
