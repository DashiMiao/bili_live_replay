# bili_live_replay —— bilibili 直播回放下载工具

根据房间号 + 日期，下载指定直播回放，并自动按固定时长（默认 1 小时）切分。
若直播中途断流，会自动把断流前后的片段拼接起来，并在导出后告诉你断流原因。

## 跨平台支持

工具源码是纯 Python，可在 **Linux / macOS / Windows** 上运行；也可以打包成各平台的原生可执行文件。

### 支持的操作系统与架构

**npm 预编译包**（`npm install -g @miaodashi/bili_live_replay`，无需安装 Python）：

Linux 预编译二进制要求 **x86_64 架构 + glibc ≥ 2.38**（从 1.0.3 起在 Ubuntu 24.04 上构建），两者都满足才能运行：

| 发行版 | 版本 | glibc | npm 版 |
|--------|------|-------|--------|
| Ubuntu | 26.04 LTS | 2.43 | ✅ |
| Ubuntu | 24.04 LTS | 2.39 | ✅ |
| Ubuntu | 23.10 | 2.38 | ✅ |
| Ubuntu | 22.04 / 20.04 / 18.04 | 2.35 / 2.31 / 2.27 | ❌ |
| Debian | 13（trixie） | 2.41 | ✅ |
| Debian | 12（bookworm）/ 11 / 10 | 2.36 / 2.31 / 2.28 | ❌ |
| Fedora | 39 及以上 | ≥ 2.38 | ✅ |
| Fedora | 38 及以下 | ≤ 2.37 | ❌ |
| RHEL / Rocky Linux / AlmaLinux / Oracle Linux | 10 及以上 | 2.39 | ✅ |
| RHEL / Rocky Linux / AlmaLinux / Oracle Linux | 9 / 8 / 7 | 2.34 / 2.28 / 2.17 | ❌ |
| CentOS Stream | 10 | 2.39 | ✅ |
| CentOS / CentOS Stream | 7 / 8 / Stream 9 | ≤ 2.34 | ❌ |
| Amazon Linux | 2023 / 2 | 2.34 / 2.26 | ❌ |
| Linux Mint | 22 及以上 | ≥ 2.39 | ✅ |
| Linux Mint | 21 / 20 | 2.35 / 2.31 | ❌ |
| Pop!_OS | 24.04 及以上 | 2.39 | ✅ |
| Pop!_OS | 22.04 | 2.35 | ❌ |
| openSUSE Leap | 15.6 / 16 | 2.38 / 2.40 | ✅ |
| openSUSE Leap | 15.5 及更早 | ≤ 2.31 | ❌ |
| SUSE Linux Enterprise | 15 SP6 / 16 | 2.38 / 2.40 | ✅ |
| SUSE Linux Enterprise | 15 SP5 及更早 | ≤ 2.31 | ❌ |
| openSUSE Tumbleweed | 滚动更新 | ≥ 2.40 | ✅ |
| Arch Linux / Manjaro / EndeavourOS / Garuda / Kali Linux | 滚动更新 | ≥ 2.40 | ✅ |
| Alpine Linux | 全部版本 | musl libc | ❌ |
| 其他 glibc 发行版（Gentoo、NixOS、Deepin 等） | — | ≥ 2.38 | 视 glibc 版本 |

**其他系统与架构**：

| 系统 | 架构 | npm 版 | 说明 |
|------|------|--------|------|
| macOS | Intel（x64） | ✅ | 用 `-darwin-x64` 包 |
| macOS | Apple Silicon（arm64） | ✅ | 用 `-darwin-arm64` 包 |
| Windows 10 / 11 | x64 | ✅ | 用 `-win32-x64` 包 |
| Windows 7 / 8 / 8.1 | x64 | ❌ | Python 3.14 已不支持 |
| Windows on ARM | arm64 | ❌ | 没有对应包，可用源码方式 |
| Linux | arm64 / aarch64（树莓派、ARM 服务器） | ❌ | 没有对应包，可用源码方式 |
| Linux / Windows | 32 位 x86（i686） | ❌ | 没有对应包 |
| Linux | ARMv7 / armhf | ❌ | 没有对应包 |
| Linux | RISC-V / ppc64le / s390x | ❌ | 没有对应包 |
| FreeBSD / OpenBSD 等非 glibc 系统 | — | ❌ | 没有对应包，可用源码方式 |

> - 所有 Linux 发行版共用同一个 `@miaodashi/bili_live_replay-linux-x64` 包；低于 glibc 2.38 时会报 `GLIBC_2.38 not found`，Alpine 则是 musl libc 不兼容。
> - WSL2 按里面装的发行版判断（如 Ubuntu 24.04 ✅、Ubuntu 22.04 ❌）；Docker / Podman 请选 glibc ≥ 2.38 的基础镜像（如 `ubuntu:24.04`、`debian:13`）。
> - 查看自己的系统：`uname -m` 看架构（`x86_64` / `aarch64`），`ldd --version | head -1` 看 glibc 版本。

**源码运行 / 自行打包**：Linux、macOS、Windows 都支持（包括上表中 ❌ 的系统：旧版本发行版、Alpine、ARM64、32 位等），CPU 架构跟随本机 Python。源码运行要求 Python 3.8+ 和 `requests`；自行打包（`build.py` + PyInstaller）要求 Python 3.10+。`build.py` 只能打包当前运行平台的产物，不支持交叉编译。

```bash
# Debian / Ubuntu / Linux Mint / Pop!_OS
sudo apt install python3 python3-requests
# Fedora / RHEL / Rocky / AlmaLinux / CentOS Stream
sudo dnf install python3 python3-requests
# Arch Linux / Manjaro
sudo pacman -S python python-requests
# openSUSE / SLES
sudo zypper install python3 python3-requests
# Alpine（还需用 apk 装 ffmpeg，工具会自动使用系统 ffmpeg）
sudo apk add python3 py3-requests ffmpeg
```

**工具准备方式**（系统里找不到 ffmpeg / aria2c 时）：

| 工具 | Linux | macOS | Windows |
|------|-------|-------|---------|
| ffmpeg | 固定版本 7.0.2，x86_64 / arm64，SHA256 校验 | 请用 `brew install ffmpeg`（不自动下载） | 固定版本 8.1.2，x64，SHA256 校验 |
| aria2c | 不自动下载（建议 `sudo apt install aria2`，否则回退 Python 多线程） | 固定版本 1.37.0，Intel / Apple Silicon，SHA256 校验 | 固定版本 1.37.0，x64，SHA256 校验 |

> 自动下载只使用固定版本和固定 SHA256：先校验压缩包，再校验解压出的二进制，任何一步失败都不会执行。
> 下载目录为 `~/.cache/bili-live-replay/tools`（0700）；系统 PATH 里已有 ffmpeg/aria2c 时优先使用系统版本。
> 程序拒绝以 root/sudo 运行，也拒绝从组/其他用户可写目录执行工具。

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
| ffmpeg | 优先 `sudo apt install ffmpeg`；否则下载固定版本并校验 SHA256 | `brew install ffmpeg`（不自动下载） | 优先 `winget install Gyan.FFmpeg`；否则下载固定版本并校验 SHA256 |
| aria2c（可选） | `sudo apt install aria2`（不自动下载） | 自动下载固定版本并校验 SHA256，或 `brew install aria2` | 自动下载固定版本并校验 SHA256，或 `winget install aria2` |

> **工具安全**：所有自动下载都固定版本 + 固定 SHA256，校验失败不会解压或执行；下载只允许 HTTPS 和官方来源。
> **存放位置**：工具只放在用户私有缓存目录 `~/.cache/bili-live-replay/tools/`（0700），不再放到程序目录。
> **不要用 sudo 运行**：程序会拒绝 root；如确需 root，请自行确保程序目录和工具目录均为 root-owned 且普通用户不可写。
> **macOS 的 ffmpeg**：为了避免不可验证的第三方静态包，macOS 不自动下载 ffmpeg，请用 Homebrew 安装。

## 用法

```bash
# 推荐：Cookie 文件只给当前用户读写
chmod 600 cookie.txt

# 单个日期
bili_live_replay --room-id 9308312 --cookie-file cookie.txt 2026-11-10

# 多个日期（从 stdin 读取，不进入 shell 历史/进程列表）
printf '%s' "$SESSDATA" | bili_live_replay --room-id 9308312 --cookie-stdin 2026-11-10 2026-11-11

# 指定输出目录
bili_live_replay --room-id 9308312 --cookie-file cookie.txt --out-dir ~/下载 2026-11-10

# 一键下载最近 N 场回放（自动跳过没开播的日期）
bili_live_replay --room-id 9308312 --cookie-file cookie.txt --recent 3

# 追加自定义 CDN 域名（默认只允许 B 站常见 CDN 域名）
bili_live_replay --room-id 9308312 --cookie-file cookie.txt \
  --cdn-host example-cdn.com 2026-11-10
```

### 参数说明

| 参数 | 说明 |
|------|------|
| `dates`（位置参数） | 要下载的日期，格式 `YYYY-MM-DD`，可多个 |
| `--room-id` | 直播间房间号（必填） |
| `--cookie-file` | 从文件读取 Cookie（建议 `chmod 600`；组/其他用户可读会直接拒绝） |
| `--cookie-stdin` | 从标准输入读取 Cookie |
| `--out-dir` | 输出目录，默认当前目录 |
| `--part-seconds` | 每个片段时长（秒，必须为正整数），默认 3600（1 小时） |
| `--live-uid` | 主播 uid（可选，跳过房间号解析） |
| `--keep-temp` | 保留临时视频分片（默认自动清理；aria2c 日志/输入文件始终清理） |
| `--recent N` | 下载最近 N 场回放（与日期列表二选一，最多 1000） |
| `--proxy URL` | 指定代理（如 `http://127.0.0.1:7890`）；默认直连、自动绕过系统代理 |
| `--cdn-host HOST` | 追加允许的 CDN 域名后缀（可重复；默认只允许 B 站常见 CDN） |

## 版本检查与自动更新

正常运行时（`--help` / `--version` 除外）会先检查 npm 上的最新版本：

```text
npm registry: @miaodashi/bili_live_replay
```

如果当前版本较旧：

- **源码运行**：仅当仓库干净时执行 `git pull --ff-only`，然后重新启动；有本地修改则拒绝运行。
- **npm 安装版（Linux / macOS）**：优先 `npm install ... --ignore-scripts`；失败则下载平台包，校验 npm `dist.integrity` 和包内 `SHA256SUMS` 后原子替换二进制并重启。
- **单文件 PyInstaller 二进制（Linux / macOS）**：下载平台包并校验后原子替换当前可执行文件并重启。
- **Windows**：npm 安装版会尝试 `npm install ... --ignore-scripts`；单文件版受 Windows 文件锁限制，会自动下载并校验新文件，但可能需要关闭程序后手动替换。
- **更新失败**：直接退出，不再继续运行旧版本。

默认是**强制在线检查**：每次启动都必须能访问 npm registry；离线、registry 不可达、或无法确认最新版本时会直接退出，缓存不能绕过。

如确需离线运行（会使用缓存，可能继续使用旧版本，风险自负）：

```bash
export BILI_ALLOW_OFFLINE=1
```

版本检查结果仍会缓存 1 小时，但缓存只用于显式允许离线时的回退。`BILI_STRICT_UPDATE=0` 是允许离线的旧别名，建议使用 `BILI_ALLOW_OFFLINE=1`。

> 1.0.3 及更早版本不包含此逻辑；必须手动升级到 1.1.0，之后才会开始强制检查和自动更新。

自动更新信任 npm registry 的 TLS + `dist.integrity` + 平台包内 `SHA256SUMS`。如果 npm 发布账号被攻破，仍可能发布恶意版本；对供应链安全要求最高的环境，建议固定版本或使用系统包管理器。

## 输出与命名

- 文件名：`yyyy_mm_dd_partN.mp4`，`N` 从 1 开始。
- 每小时一个片段，结尾不足 1 小时的单独成一个片段。
- 同一天有多场直播时，按开始时间从早到晚命名为 `yyyy_mm_dd_1_partN.mp4`、`yyyy_mm_dd_2_partN.mp4`……，不会互相覆盖。

例如：

```
2026_11_10_part1.mp4
2026_11_10_part2.mp4
2026_11_10_part3.mp4
2026_11_10_part4.mp4
2026_11_10_part5.mp4   <- 结尾不足 1 小时的余量
```

如果 2026-11-11 直播了两场：

```
2026_11_11_1_part1.mp4   <- 第一场（较早）
2026_11_11_1_part2.mp4
2026_11_11_2_part1.mp4   <- 第二场（较晚）
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
- 只需要 `SESSDATA` 即可登录。程序会从完整 Cookie 中**只提取 SESSDATA**，不会把 `bili_jct` 等其它字段发送给 B 站接口或任何第三方。
- Cookie 只放在 API 会话的 cookie jar 中，作用域限制为 `.bilibili.com`；m3u8 和分片请求不携带 Cookie。
- 接口最多返回近 14 天的回放。
- 下载过程中按 `Ctrl+C` 可立即中断（会自动结束 aria2c 子进程并清理临时文件）。
- 默认直连下载（绕过系统代理）；若开了代理/梯子导致问题，默认已不受影响，如确需走代理用 `--proxy` 指定。
- **不要以 root/sudo 运行本工具**；程序会直接拒绝 root。
- **不要把 Cookie 提交到 git**；`cookie.txt`、`*.cookie`、`.env` 已加入 `.gitignore`。
- `--keep-temp` 只保留视频分片；含签名 URL 的 aria2c 日志/输入文件始终会删除。

## 安全

- 建议使用 `--cookie-file`（`chmod 600`）或 `--cookie-stdin`。
- 工具下载固定版本 + 固定 SHA256，校验失败不会执行；下载来源只允许 HTTPS 和官方域名。
- 仓库包含 Gitleaks 配置和 pre-commit hook，CI 会扫描新增变更；也建议在 GitHub 仓库设置中开启 Secret scanning + Push protection。
- 如果你曾在任何提交中放入过 `cookie.txt`：请立即在 B 站「退出所有设备」并修改密码，然后清理 git 历史（删除文件本身不够）。撤销凭据永远优先于清理历史。
- 发现安全问题请不要在公开 issue 中粘贴 Cookie、`SESSDATA`、`bili_jct` 或完整日志；请先撤销凭据再联系维护者。

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

包使用 npm 作用域 `@miaodashi`。

### 当前 1.x：NPM_TOKEN

1.x 暂时使用 **NPM_TOKEN** 发布：

1. npm → Access Tokens → 创建 Granular Access Token：
   - 权限：`@miaodashi` 读写
   - 需要时开启 Bypass 2FA（短期使用）
2. GitHub 仓库 → Settings → Secrets and variables → Actions → 新建 `NPM_TOKEN`
3. 工作流使用 `NODE_AUTH_TOKEN` + `npm publish --access public`

当前 1.x 仍会生成 `SHA256SUMS` 并放进各平台包，但不使用 cosign/provenance；这些会在 2.0.0 恢复。

### 2.0.0：切回 Trusted Publishing

到 2.0.0 时，删除 `publish.yml` 里的 `NODE_AUTH_TOKEN`，恢复 `id-token: write`、cosign 和 `npm publish --provenance`，然后在 npm 上分别打开主包和 4 个平台包的 **Settings → Trusted publishing**，每个包都配置：

- Provider：GitHub Actions
- Organization or user：`DashiMiao`（大小写必须完全一致）
- Repository：`bili_live_replay`
- Workflow filename：`publish.yml`（只填文件名，必须带 `.yml`；大小写敏感）
- Environment name：留空（工作流没有使用 environment）
- Allowed actions：**必须勾选 `npm publish`**；`npm stage publish` 默认允许，但 2026-09-03 之后创建的配置默认不允许直接 `npm publish`

注意事项：

- 5 个包必须**分别**配置；只配置主包会导致平台包发布时返回 404。
- Trusted Publisher 配置创建后必须 **2 天内完成首次成功发布**，否则会过期；过期后不能修改，只能删除重建。
- 配置创建后字段不可修改；写错了要删除后重建。
- 工作流必须运行在 GitHub 托管的 runner 上（本项目用的是 `ubuntu-latest` / `macos-*` / `windows-latest`），不支持 self-hosted runner。
- 需要 npm CLI ≥ 11.5.1、Node ≥ 22.14；工作流使用 Node 24，满足要求。
- `package.json` 的 `repository.url` 必须精确匹配 GitHub 仓库；本项目已统一为 `git+https://github.com/DashiMiao/bili_live_replay.git`。
- Trusted Publishing 验证成功后，建议到每个包的 **Settings → Publishing access** 选择 **Require two-factor authentication and disallow tokens**，彻底关闭长期 token 发布。

配置完成后，在 GitHub Actions 手动运行 `publish` 并输入版本号，或直接打版本 tag：

```bash
git tag v1.1.1
git push origin v1.1.1
```

工作流会：

- 用 `requirements-build.txt` 固定版本 + `--require-hashes` 安装构建依赖；
- 生成 `SHA256SUMS` 并放进各平台包；
- 1.x 使用 `NPM_TOKEN` + `npm publish --access public`；2.0.0 恢复 cosign 签名和 `npm publish --provenance`。

> 注意：主包、平台包及主包的 `optionalDependencies` 版本号必须保持一致；工作流会以 tag 中 `v` 后面的版本号统一设置。npm 不允许覆盖已发布的同版本内容。
> 不要把 npm token 写进仓库、README 或 CI 日志；只放在 GitHub Actions Secret 里。
