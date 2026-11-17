# bili_live_replay —— bilibili 直播回放下载工具

根据房间号 + 日期，下载指定直播回放，并自动按固定时长（默认 1 小时）切分。
若直播中途断流，会自动把断流前后的片段拼接起来，并在导出后告诉你断流原因。

## 跨平台支持

工具源码是纯 Python，可在 **Linux / macOS / Windows** 上运行；也可以打包成各平台的原生可执行文件。

### 支持的操作系统与架构

**npm 预编译包**（`npm install -g @miaodashi/bili_live_replay`，无需安装 Python）：

| 系统 | npm 版能否运行 |
|------|----------------|
| Ubuntu 24.04 / 26.04 | ✅ |
| Ubuntu 22.04（glibc 2.35） | ❌ |
| Debian 13+ | ✅ |
| Debian 12（glibc 2.36） | ❌ |
| Fedora 39+、RHEL 10+ | ✅ |
| RHEL / CentOS 8、9、Amazon Linux 2023（glibc ≤ 2.34） | ❌ |
| Linux Mint 22+、Pop!_OS 24.04+ | ✅ |
| Arch Linux / Manjaro / openSUSE Tumbleweed | ✅ |
| openSUSE Leap 16+ | ✅ |
| openSUSE Leap 15.x | ❌ |
| Alpine Linux（musl libc） | ❌ |
| Linux ARM64 / aarch64（树莓派、ARM 服务器） | ❌ 没有对应包 |
| 32 位 x86、ARMv7 | ❌ 没有对应包 |
| macOS（Intel / Apple Silicon） | ✅ |
| Windows 10 / 11（x64） | ✅ |
| Windows on ARM（arm64） | ❌ 没有对应包 |

> 所有 Linux 发行版共用同一个 `@miaodashi/bili_live_replay-linux-x64` 包。从 1.0.2 起，该二进制在 Ubuntu 24.04 上构建，要求系统 **glibc ≥ 2.38**。低于该版本的发行版（Ubuntu 22.04、Debian 12、RHEL 8/9、Amazon Linux 2023 等）运行时会报 `GLIBC_2.38 not found`，Alpine 则会因 musl libc 不兼容而无法运行；这些系统请改用下面的源码方式。

**源码运行 / 自行打包**：Linux、macOS、Windows 都支持（包括上表中 ❌ 的系统：旧版本发行版、Alpine、ARM64 等），CPU 架构跟随本机 Python（x64 / arm64 均可），要求 Python 3.8+ 和 `requests`。`build.py` 只能打包当前运行平台的产物，不支持交叉编译。

```bash
# Debian / Ubuntu / Linux Mint / Pop!_OS
sudo apt install python3 python3-requests
# Fedora / RHEL / Rocky / AlmaLinux / CentOS Stream
sudo dnf install python3 python3-requests
# Arch Linux / Manjaro
sudo pacman -S python python-requests
# openSUSE
sudo zypper install python3 python3-requests
# Alpine（还需用 apk 装 ffmpeg，工具会自动使用系统 ffmpeg）
sudo apk add python3 py3-requests ffmpeg
```

**工具自动下载的架构支持**（系统里找不到 ffmpeg / aria2c 时）：

| 工具 | Linux | macOS | Windows |
|------|-------|-------|---------|
| ffmpeg | x86_64 / arm64（glibc 发行版） | Intel / Apple Silicon | x64 |
| aria2c | 不自动下载（建议 `sudo apt install aria2`，否则回退 Python 多线程） | Intel / Apple Silicon | x64 |

> Linux 上 ffmpeg 会优先尝试从 apt 源下载（x86_64），失败再回退到 johnvansickle 的静态包。

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
> **aria2c 自动下载**：Windows / macOS 上找不到 aria2c 时会自动下载静态 aria2c 到 `tools/`（Windows 用官方包，macOS 用第三方静态包 `AEPKILL/aria2c-binary`，自动区分 Intel / Apple Silicon）；下载失败或 Linux 上找不到时，自动回退为 Python 多线程下载（慢一点，但能用）。
> 下载的工具二进制优先放在程序旁边的 `tools/` 目录里，方便连同程序一起拷贝到别的机器；如果程序目录不可写（例如用 `npm install -g` 装到 `/usr/local/lib` 或 Windows 的 `Program Files`），会自动回退到用户缓存目录 `~/.cache/bili-live-replay/tools/`。

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

## 分片下载失败

回放视频由几千个几秒长的分片组成，长时间下载过程中偶尔会有个别分片失败（CDN 限流、连接重置、临时 404 等）。工具的处理方式：

1. 第一轮按 64 并发下载全部分片；
2. 若有分片缺失/为空，自动用低并发再重试一轮；
3. 重试后仍缺失的少量分片（≤ 总数 1%，最多 50 个）会直接跳过，继续合成其余内容，并提示缺失数量和大致时长；
4. 缺失过多（超过上限，通常是网络整体不通）才会跳过该段。

## 说明

- 下载他人直播间回放，需要你的账号已获得该主播的「剪辑权限（授权）」，否则接口返回 `301 没有剪辑权限`。
- Cookie 只需要 `SESSDATA` 即可登录；若从浏览器复制的 Cookie 是 URL 编码过的（含 `%2C`、`%2A` 等），脚本会自动尝试解码后登录。
- 接口最多返回近 14 天的回放。
- 下载过程中按 `Ctrl+C` 可立即中断（会自动结束 aria2c 子进程并清理临时文件）。
- 默认直连下载（绕过系统代理）；若开了代理/梯子导致问题，默认已不受影响，如确需走代理用 `--proxy` 指定。

## 发布到 npm

通过 GitHub Actions 自动把各平台预编译二进制发布到 npm，安装后用户无需装 Python 即可运行：

```bash
npm install -g @miaodashi/bili_live_replay
bili_live_replay --version
```

结构说明：

- `npm/bili_live_replay/`：主包，只放一个 JS 启动器，声明 `bin`；
- `npm/{linux-x64,darwin-x64,darwin-arm64,win32-x64}/`：各平台的 PyInstaller 产物包，靠 `os`/`cpu` 字段让 npm 按平台自动选装；
- `.github/workflows/publish.yml`：`push tag v*`（或手动触发）时编译并发布。

包使用 npm 作用域 `@miaodashi`。首次发布时，这 5 个包在 npm 上尚不存在，需要先完成一次引导发布：

1. 注册 npm 账号 `miaodashi` 并开启 2FA；
2. 创建一个短期 Granular Access Token，赋予 `@miaodashi` 作用域读写权限并开启 Bypass 2FA；
3. 把 Token 存到 GitHub 仓库的 Secret `NPM_TOKEN`；
4. 在 GitHub Actions 手动运行 `publish`，输入版本号，例如 `1.0.2`。

首次发布成功后，在 npm 上分别打开主包和 4 个平台包的 Settings → Trusted Publishing，每个包都配置：

- Provider：GitHub Actions
- Organization or user：`DashiMiao`
- Repository：`bili_live_replay`
- Workflow filename：`publish.yml`
- Allowed actions：允许 `npm publish`

在创建 Trusted Publisher 后的 2 天内，删除 GitHub 中的 `NPM_TOKEN` 和 npm 上的短期 Token，再发布一个新版本（例如 `1.0.2`）以完成 OIDC 验证。之后打版本 tag 即可自动发布：

```bash
git tag v1.0.2
git push origin v1.0.2
```

> 注意：主包、平台包及主包的 `optionalDependencies` 版本号必须保持一致；工作流会以 tag 中 `v` 后面的版本号统一设置。npm 不允许覆盖已发布的同版本内容。
