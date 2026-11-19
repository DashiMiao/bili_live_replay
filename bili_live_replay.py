#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bilibili 直播回放下载工具
========================

功能：
  1. 根据房间号 + 日期，下载指定直播回放；
  2. 每个回放按固定时长（默认 1 小时）切分为独立片段；
  3. 命名规则：yyyy_mm_dd_partN（N 从 1 开始，最后一小时不足的部分单独成段）；
  4. 若某场直播中途断流（回放被切成多段），自动把断流前后的片段拼接起来；
  5. 视频导出后，在终端中说明断流原因（网络/推流问题 还是 违规封禁）。

依赖：
  - python3 (>=3.8)
  - requests            （pip install requests）
  - ffmpeg / ffprobe     （优先使用系统包管理器安装；未安装时仅下载固定版本并校验 SHA256）
  - aria2c（可选，用于加速下载；没有则用 Python 多线程下载）

用法示例：
  python3 bili_live_replay.py --room-id 9308312 --cookie-file cookie.txt 2026-11-10
  python3 bili_live_replay.py --room-id 9308312 --cookie-stdin 2026-11-10 2026-11-11
  python3 bili_live_replay.py --room-id 9308312 --cookie-file cookie.txt --out-dir ~/下载 2026-11-10

说明：
  - 下载他人直播间回放，需要你的账号已获得该主播的「剪辑权限（授权）」，
    否则接口会返回 301「没有剪辑权限」。
  - 只需要 SESSDATA 即可登录；程序会从完整 Cookie 中只提取 SESSDATA，
    不会把 bili_jct 等其它字段发送给任何第三方。
  - Cookie 文件请使用 chmod 600；请勿提交到 git。
"""

import argparse
import base64
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.parse
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import requests
except ImportError:
    sys.stderr.write("缺少 requests 库，请先安装：pip install requests\n")
    sys.exit(1)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
CST = timezone(timedelta(hours=8))

API_LIST = "https://api.live.bilibili.com/xlive/web-room/v1/videoService/GetOtherSliceList"
API_STREAM = "https://api.live.bilibili.com/xlive/web-room/v1/videoService/GetUserSliceStream"
API_SESSION = "https://api.live.bilibili.com/xlive/web-room/v1/videoService/GetUserLiveSessionData"
API_ROOM = "https://api.live.bilibili.com/room/v1/Room/get_info"
API_NAV = "https://api.bilibili.com/x/web-interface/nav"

VERSION = "1.1.0"
AUTHOR = "dashimiao"


# 所有可执行文件和临时分片只放用户私有缓存目录（0700），
# 不再从程序目录或任何用户/组可写目录执行二进制。
CACHE_DIR = Path.home() / ".cache" / "bili-live-replay"
TOOLS_DIR = CACHE_DIR / "tools"
WORK_DIR = CACHE_DIR / "work"

# 版本检查 / 自动更新（只信任 npm registry + 包内 SHA256SUMS）
NPM_PACKAGE = "@miaodashi/bili_live_replay"
NPM_REGISTRY = "https://registry.npmjs.org"
NPM_PLATFORM_PACKAGES = {
    ("linux", "amd64"): "@miaodashi/bili_live_replay-linux-x64",
    ("darwin", "x86_64"): "@miaodashi/bili_live_replay-darwin-x64",
    ("darwin", "arm64"): "@miaodashi/bili_live_replay-darwin-arm64",
    ("win32", "amd64"): "@miaodashi/bili_live_replay-win32-x64",
}
UPDATE_CACHE = CACHE_DIR / "update-check.json"
UPDATE_CACHE_TTL = 3600
UPDATE_CHECK_TIMEOUT = 5
UPDATE_MAX_BYTES = 256 * 1024 * 1024

# 下载上限：防止恶意服务器/播放列表耗尽磁盘或内存
MAX_TOOL_BYTES = 256 * 1024 * 1024
MAX_SEGMENT_BYTES = 64 * 1024 * 1024
MAX_M3U8_BYTES = 16 * 1024 * 1024
MAX_SEGMENTS = 100_000
MAX_REPLAY_PAGES = 1000

# B 站 CDN 域名后缀；可用 --cdn-host 追加。
# 只允许 HTTPS + 这些域名，避免把请求发到任意主机。
DEFAULT_CDN_SUFFIXES = (
    "bilivideo.com",
    "bilivideo.cn",
    "hdslb.com",
    "szbdyd.com",
    "bilibili.com",
)

# 工具下载只允许这些官方/固定来源（重定向后也会校验）
TOOL_DOWNLOAD_SUFFIXES = (
    "github.com",
    "githubusercontent.com",
    "johnvansickle.com",
    "gyan.dev",
)

# 固定版本 + 固定 SHA256 的工具清单。
# 没有清单条目的平台一律不自动下载，提示用户用系统包管理器安装。
FFMPEG_MANIFEST = {
    ("linux", "amd64"): {
        "version": "7.0.2",
        "url": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-7.0.2-amd64-static.tar.xz",
        "archive": "ffmpeg-7.0.2-amd64-static.tar.xz",
        "sha256": "abda8d77ce8309141f83ab8edf0596834087c52467f6badf376a6a2a4c87cf67",
        "kind": "tar.xz",
        "members": {
            "ffmpeg": "e7e7fb30477f717e6f55f9180a70386c62677ef8a4d4d1a5d948f4098aa3eb99",
            "ffprobe": "4f231a1960d83e403d08f7971e271707bec278a9ae18e21b8b5b03186668450d",
        },
    },
    ("linux", "arm64"): {
        "version": "7.0.2",
        "url": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-7.0.2-arm64-static.tar.xz",
        "archive": "ffmpeg-7.0.2-arm64-static.tar.xz",
        "sha256": "f4149bb2b0784e30e99bdda85471c9b5930d3402014e934a5098b41d0f7201b1",
        "kind": "tar.xz",
        "members": {
            "ffmpeg": "6bb182d0d75d23028db82e9e4f723ca69b853d055698486e6984ddb2c06fb8ce",
            "ffprobe": "d17ae9b4c297d48e2521ba14e417bb0537c6ff77c584cdbcd6bb0d8d0307a2e8",
        },
    },
    ("win32", "amd64"): {
        "version": "8.1.2",
        "url": "https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-8.1.2-essentials_build.zip",
        "archive": "ffmpeg-8.1.2-essentials_build.zip",
        "sha256": "db580001caa24ac104c8cb856cd113a87b0a443f7bdf47d8c12b1d740584a2ec",
        "kind": "zip",
        "members": {
            "ffmpeg.exe": "1326dde4c84ff1f96fe6b8916c5bed29e163e9b5dccf995f6f3db069d143ec5e",
            "ffprobe.exe": "b49ccc7c6547b141ad5a2f6ec69cc04323d7133d7704d70b331b904c63eecb07",
        },
    },
}

ARIA2C_MANIFEST = {
    ("win32", "amd64"): {
        "version": "1.37.0",
        "url": "https://github.com/aria2/aria2/releases/download/release-1.37.0/aria2-1.37.0-win-64bit-build1.zip",
        "archive": "aria2-1.37.0-win-64bit-build1.zip",
        "sha256": "67d015301eef0b612191212d564c5bb0a14b5b9c4796b76454276a4d28d9b288",
        "kind": "zip",
        "members": {
            "aria2c.exe": "be2099c214f63a3cb4954b09a0becd6e2e34660b886d4c898d260febfe9d70c2",
        },
    },
    ("darwin", "x86_64"): {
        "version": "1.37.0",
        "url": "https://github.com/AEPKILL/aria2c-binary/releases/download/release-1.37.0/aria2-macos-x86_64.tar.gz",
        "archive": "aria2-macos-x86_64.tar.gz",
        "sha256": "b10a2101daa98da3ded6ed5118c06c35b9e719b022275921e3192908fc80ee4d",
        "kind": "tar.gz",
        "members": {
            "aria2c": "ced387d829e3742dd75313df95aa801b41d2fe66e7c892eda8e3d97aec958877",
        },
    },
    ("darwin", "arm64"): {
        "version": "1.37.0",
        "url": "https://github.com/AEPKILL/aria2c-binary/releases/download/release-1.37.0/aria2-macos-arm64.tar.gz",
        "archive": "aria2-macos-arm64.tar.gz",
        "sha256": "582351ffa14bbc8203a19af6a2a2f94bc7aed3f438c1cffaeae55b25ba263757",
        "kind": "tar.gz",
        "members": {
            "aria2c": "a81557b99c9c6e9f2408489bfe8f379f25b98d1e6ddb399c3c4ad048e0647611",
        },
    },
}


def _arch_key() -> str:
    """把 platform.machine() 归一化成清单里使用的架构名。"""
    m = platform.machine().lower()
    if m in ("x86_64", "amd64", "x64"):
        return "x86_64" if sys.platform == "darwin" else "amd64"
    if m in ("aarch64", "arm64"):
        return "arm64"
    return m


def _platform_key():
    return (sys.platform, _arch_key())


def _ensure_private_dir(p: Path):
    """创建/校验 0700 私有目录，拒绝符号链接和过宽权限。"""
    if p.is_symlink():
        raise RuntimeError(f"拒绝使用符号链接目录: {p}")
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise RuntimeError(f"无法创建目录 {p}: {e}") from e
    if os.name != "nt":
        st = p.stat()
        if not stat.S_ISDIR(st.st_mode):
            raise RuntimeError(f"不是目录: {p}")
        if hasattr(os, "geteuid") and st.st_uid != os.geteuid():
            raise RuntimeError(f"目录不属于当前用户，拒绝使用: {p}")
        if stat.S_IMODE(st.st_mode) & 0o077:
            try:
                os.chmod(p, 0o700)
            except OSError as e:
                raise RuntimeError(f"无法收紧目录权限 {p}: {e}") from e
    # 使用随机临时文件探测可写性，避免固定文件名被符号链接利用
    with tempfile.NamedTemporaryFile(dir=p, prefix=".probe-", delete=True):
        pass


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_sha256(path: Path, expected: str) -> bool:
    try:
        actual = _sha256_file(path)
    except OSError as e:
        warn(f"无法读取 {path.name}: {e}")
        return False
    if actual.lower() != expected.lower():
        warn(f"哈希校验失败: {path.name}（期望 {expected[:12]}…，实际 {actual[:12]}…）")
        return False
    return True


def _safe_system_tool(path: str) -> bool:
    """系统 PATH 里的工具：拒绝从组/其他用户可写位置执行。"""
    try:
        p = Path(path).resolve()
        st = p.stat()
    except OSError:
        return False
    if not stat.S_ISREG(st.st_mode):
        return False
    if os.name == "nt":
        return True
    if hasattr(os, "geteuid") and st.st_uid not in (0, os.geteuid()):
        warn(f"工具所有者不可信，拒绝使用: {p}")
        return False
    if stat.S_IMODE(st.st_mode) & 0o022:
        warn(f"工具可被组/其他用户修改，拒绝使用: {p}")
        return False
    try:
        parent_mode = stat.S_IMODE(p.parent.stat().st_mode)
    except OSError:
        return False
    if parent_mode & 0o022:
        warn(f"工具所在目录可被组/其他用户修改，拒绝使用: {p.parent}")
        return False
    return True


def _redact_url(url: str) -> str:
    """日志里去掉查询串和用户信息，避免泄露签名 URL。"""
    try:
        p = urllib.parse.urlparse(url)
        host = p.hostname or ""
        return f"{p.scheme}://{host}{p.path}"
    except Exception:
        return "<invalid-url>"


def _host_allowed(host: str, suffixes) -> bool:
    host = host.lower().rstrip(".")
    return any(host == s or host.endswith("." + s) for s in suffixes)


def _validate_cdn_url(url: str, suffixes) -> bool:
    """只允许 HTTPS / 443 / 白名单域名，阻止 SSRF 和明文传输。"""
    try:
        p = urllib.parse.urlparse(url)
    except ValueError:
        return False
    if p.scheme != "https" or not p.hostname:
        return False
    if p.username or p.password:
        return False
    try:
        port = p.port
    except ValueError:
        return False
    if port not in (None, 443):
        return False
    return _host_allowed(p.hostname, suffixes)


def _build_cdn_hosts(extra) -> tuple:
    suffixes = list(DEFAULT_CDN_SUFFIXES)
    for raw in extra or []:
        h = raw.strip().lower().lstrip(".")
        if h.startswith("*."):
            h = h[2:]
        if not h or any(c in h for c in "/:@ ") or ".." in h:
            sys.exit(f"无效的 CDN 域名: {raw}")
        suffixes.append(h)
    return tuple(dict.fromkeys(suffixes))


# --------------------------------------------------------------------------- #
# 版本检查 / 自动更新
# --------------------------------------------------------------------------- #
_SAFE_VERSION_RE = re.compile(r"^[vV]?\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def _parse_version(value):
    if not value:
        return None
    match = re.match(r"^[vV]?(\d+)\.(\d+)\.(\d+)", str(value).strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def _is_safe_version(value) -> bool:
    """版本号会用于路径和 npm 参数，必须严格限制字符集。"""
    return bool(_SAFE_VERSION_RE.fullmatch(str(value or "").strip()))


def _npm_platform_package():
    return NPM_PLATFORM_PACKAGES.get(_platform_key())


def _fetch_registry_json(url: str):
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return None
    if parsed.scheme != "https" or parsed.hostname != "registry.npmjs.org":
        return None
    session = _new_session()
    try:
        response = session.get(url, timeout=UPDATE_CHECK_TIMEOUT,
                               headers={"Accept": "application/json"})
        response.raise_for_status()
        if len(response.content) > 2 * 1024 * 1024:
            return None
        return response.json()
    except Exception:
        return None
    finally:
        session.close()


def _read_update_cache():
    try:
        data = json.loads(UPDATE_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or "checked_at" not in data:
        return None
    return data


def _write_update_cache(latest_version: str):
    data = {"checked_at": time.time(), "latest": latest_version}
    tmp = None
    try:
        _ensure_private_dir(UPDATE_CACHE.parent)
        fd, tmp_name = tempfile.mkstemp(dir=UPDATE_CACHE.parent,
                                        prefix=".update-check.", suffix=".tmp")
        tmp = Path(tmp_name)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.chmod(tmp, 0o600)
        os.replace(tmp, UPDATE_CACHE)
        tmp = None
    except Exception:
        pass
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def _verify_npm_integrity(path: Path, integrity: str) -> bool:
    if not integrity:
        return False
    for token in integrity.split():
        algo, sep, expected = token.partition("-")
        if not sep or not expected or algo not in ("sha512", "sha384", "sha256", "sha1"):
            continue
        try:
            hasher = hashlib.new(algo)
        except ValueError:
            continue
        try:
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    hasher.update(chunk)
        except OSError:
            return False
        if base64.b64encode(hasher.digest()).decode() == expected:
            return True
    return False


def _extract_npm_binary(tarball: Path, dest_dir: Path, exe_name: str):
    """从 npm 平台包中只提取指定二进制，并核对包内 SHA256SUMS。"""
    try:
        with tarfile.open(tarball, "r:gz") as tf:
            checksums_file = tf.extractfile("package/SHA256SUMS")
            if checksums_file is None:
                warn("更新包缺少 SHA256SUMS，拒绝自动更新")
                return None
            text = checksums_file.read(1 << 20).decode("utf-8", "replace")
            expected = None
            for line in text.splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[1].lstrip("*") == f"bin/{exe_name}":
                    expected = parts[0].lower()
                    break
            if not expected or not re.fullmatch(r"[0-9a-f]{64}", expected):
                warn("更新包 SHA256SUMS 中没有有效的二进制哈希")
                return None
            source = tf.extractfile(f"package/bin/{exe_name}")
            if source is None:
                warn("更新包中缺少平台二进制")
                return None
            dest = dest_dir / exe_name
            fd, tmp_name = tempfile.mkstemp(dir=dest_dir,
                                            prefix=f".{exe_name}.", suffix=".tmp")
            tmp = Path(tmp_name)
            hasher = hashlib.sha256()
            total = 0
            try:
                with os.fdopen(fd, "wb") as out:
                    for chunk in iter(lambda: source.read(1 << 20), b""):
                        total += len(chunk)
                        if total > UPDATE_MAX_BYTES:
                            warn("更新包二进制超过大小上限")
                            return None
                        out.write(chunk)
                        hasher.update(chunk)
                if hasher.hexdigest().lower() != expected:
                    warn("更新包二进制 SHA256 校验失败")
                    return None
                os.chmod(tmp, 0o755)
                os.replace(tmp, dest)
                return dest
            finally:
                tmp.unlink(missing_ok=True)
    except Exception as e:
        warn(f"解压更新包失败: {e}")
        return None


def _is_npm_install() -> bool:
    path = str(Path(sys.executable).resolve()).replace("\\", "/")
    return "node_modules/@miaodashi/bili_live_replay-" in path


def _installed_package_version():
    try:
        executable = Path(sys.executable).resolve()
    except OSError:
        return None
    for parent in [executable.parent] + list(executable.parents):
        package_json = parent / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text(encoding="utf-8"))
                return str(data.get("version") or "")
            except Exception:
                return None
    return None


def _npm_install_command(version: str):
    npm = shutil.which("npm")
    if not npm or not _safe_system_tool(npm):
        return None
    try:
        executable = Path(sys.executable).resolve()
    except OSError:
        return None
    try:
        root = subprocess.run([npm, "root", "-g"], capture_output=True,
                              text=True, timeout=30, stdin=subprocess.DEVNULL)
        global_root = Path(root.stdout.strip()).resolve() \
            if root.returncode == 0 and root.stdout.strip() else None
    except Exception:
        global_root = None
    if global_root and (executable == global_root or global_root in executable.parents):
        return [npm, "install", "-g", f"{NPM_PACKAGE}@{version}", "--ignore-scripts"]
    for parent in executable.parents:
        if parent.name == "node_modules":
            return [npm, "install", "--prefix", str(parent.parent), "--no-save",
                    f"{NPM_PACKAGE}@{version}", "--ignore-scripts"]
    return [npm, "install", "-g", f"{NPM_PACKAGE}@{version}", "--ignore-scripts"]


def _run_npm_update(version: str) -> bool:
    command = _npm_install_command(version)
    if not command:
        return False
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=600, stdin=subprocess.DEVNULL)
    except Exception as e:
        warn(f"npm 更新失败: {e}")
        return False
    if result.returncode == 0:
        log("npm 更新完成")
        return True
    warn(f"npm 更新失败: {(result.stderr or result.stdout).strip()[:300]}")
    return False


def _npm_update_and_verify(version: str, new_binary: Path) -> bool:
    if not _run_npm_update(version):
        return False
    if _installed_package_version() != version:
        warn("npm 更新后 package.json 版本不一致")
        return False
    try:
        same_binary = _sha256_file(Path(sys.executable)) == _sha256_file(new_binary)
    except OSError:
        same_binary = False
    if not same_binary:
        warn("npm 更新后二进制哈希不一致（可能被正在运行的程序锁定）")
        return False
    return True


def _update_source() -> bool:
    root = Path(__file__).resolve().parent
    git = shutil.which("git")
    if not git or not _safe_system_tool(git) or not (root / ".git").exists():
        warn("源码运行且不是可用的 git 仓库，无法自动更新")
        return False
    try:
        status = subprocess.run([git, "-C", str(root), "status", "--porcelain"],
                                capture_output=True, text=True, timeout=30,
                                stdin=subprocess.DEVNULL)
    except Exception as e:
        warn(f"检查源码状态失败: {e}")
        return False
    if status.returncode != 0 or status.stdout.strip():
        warn("源码目录有本地修改，无法自动更新；请先提交或暂存")
        return False
    try:
        pull = subprocess.run([git, "-C", str(root), "pull", "--ff-only"],
                              capture_output=True, text=True, timeout=120,
                              stdin=subprocess.DEVNULL)
    except Exception as e:
        warn(f"git pull 失败: {e}")
        return False
    if pull.returncode != 0:
        warn(f"git pull 失败: {(pull.stderr or pull.stdout).strip()[:300]}")
        return False
    os.environ["BILI_LIVE_REPLAY_UPDATED"] = "1"
    os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve()),
                              *sys.argv[1:]])
    return True


def _auto_update(latest_version: str) -> bool:
    latest_version = str(latest_version or "").strip()
    if latest_version[:1] in ("v", "V"):
        latest_version = latest_version[1:]
    if not _is_safe_version(latest_version):
        warn("自动更新版本号格式异常，拒绝更新")
        return False
    # 源码运行：直接 fast-forward 更新源码，不需要下载平台二进制
    if not getattr(sys, "frozen", False):
        return _update_source()

    platform_package = _npm_platform_package()
    if not platform_package:
        warn(f"当前平台不支持自动更新，请手动更新：npm install -g {NPM_PACKAGE}@latest")
        return False
    meta = _fetch_registry_json(f"{NPM_REGISTRY}/{platform_package}/{latest_version}")
    if not meta:
        warn("无法获取平台包元数据，自动更新失败")
        return False
    dist = meta.get("dist") or {}
    tarball = dist.get("tarball")
    integrity = dist.get("integrity")
    if not tarball or not integrity:
        warn("平台包缺少 tarball/integrity，拒绝自动更新")
        return False
    try:
        parsed = urllib.parse.urlparse(tarball)
    except ValueError:
        return False
    if parsed.scheme != "https" or parsed.hostname != "registry.npmjs.org" or \
            parsed.username or parsed.password:
        warn("平台包下载地址不在 npm registry，拒绝自动更新")
        return False

    exe_name = "bili_live_replay.exe" if sys.platform == "win32" else "bili_live_replay"
    update_dir = CACHE_DIR / "update" / latest_version
    try:
        _ensure_private_dir(update_dir)
    except Exception as e:
        warn(f"无法准备更新目录: {e}")
        return False
    tarball_path = update_dir / f"{platform_package.rsplit('/', 1)[-1]}-{latest_version}.tgz"
    if not _download_file(tarball, tarball_path, max_bytes=UPDATE_MAX_BYTES,
                          allowed_suffixes=("npmjs.org",)):
        tarball_path.unlink(missing_ok=True)
        return False
    if not _verify_npm_integrity(tarball_path, integrity):
        warn("npm 包 integrity 校验失败，拒绝自动更新")
        tarball_path.unlink(missing_ok=True)
        return False
    new_binary = _extract_npm_binary(tarball_path, update_dir, exe_name)
    tarball_path.unlink(missing_ok=True)
    if not new_binary:
        return False

    if os.name != "nt":
        target = Path(sys.executable).resolve()
        # npm 安装版优先用 npm 更新（同时更新 JS 启动器）；失败则直接替换二进制
        if _is_npm_install() and _npm_update_and_verify(latest_version, new_binary):
            os.environ["BILI_LIVE_REPLAY_UPDATED"] = "1"
            try:
                os.execv(sys.executable, [sys.executable, *sys.argv[1:]])
            except OSError as e:
                sys.exit(f"更新完成但重启失败: {e}；请重新运行命令")
        try:
            os.replace(new_binary, target)
        except OSError as e:
            warn(f"无法替换当前可执行文件: {e}")
            warn(f"请手动更新：npm install -g {NPM_PACKAGE}@{latest_version}")
            return False
        os.environ["BILI_LIVE_REPLAY_UPDATED"] = "1"
        try:
            os.execv(str(target), [str(target), *sys.argv[1:]])
        except OSError as e:
            sys.exit(f"更新完成但重启失败: {e}；请重新运行命令")
        return True

    # Windows 不能覆盖正在运行的 exe：优先用 npm 更新，否则给出已校验的新文件
    if _is_npm_install() and _npm_update_and_verify(latest_version, new_binary):
        sys.exit(0)
    warn(f"新版本已下载并校验到: {new_binary}")
    warn(f"Windows 下无法替换正在运行的 exe，请关闭程序后手动替换，"
         f"或运行: npm install -g {NPM_PACKAGE}@{latest_version}")
    return False


def _enforce_latest_version():
    current = _parse_version(VERSION)
    if current is None:
        return
    # 默认强制在线检查：离线/registry 不可达直接拒绝运行。
    # 只有显式设置 BILI_ALLOW_OFFLINE=1 才允许使用缓存离线运行。
    allow_offline = os.environ.get("BILI_ALLOW_OFFLINE") == "1" or \
                    os.environ.get("BILI_STRICT_UPDATE") == "0"
    strict = not allow_offline
    cached = None if strict else _read_update_cache()
    data = None
    from_cache = False
    if cached:
        try:
            cache_age = time.time() - float(cached.get("checked_at", 0))
        except (TypeError, ValueError):
            cache_age = UPDATE_CACHE_TTL + 1
        if cache_age <= UPDATE_CACHE_TTL:
            data = cached
            from_cache = True
    if data is None:
        data = _fetch_registry_json(f"{NPM_REGISTRY}/{NPM_PACKAGE}/latest")
        from_cache = False
        if data is None:
            data = cached
            from_cache = True
            if data is None:
                if strict:
                    sys.exit("无法检查最新版本（网络不可用），已拒绝运行。"
                             "如确需离线运行，请设置 BILI_ALLOW_OFFLINE=1。")
                warn("无法检查最新版本（网络不可用），按 BILI_ALLOW_OFFLINE=1 "
                     "继续运行；可能正在使用旧版本，请尽快联网更新")
                return
            age = max(0, int(time.time() - float(data.get("checked_at", 0))))
            warn(f"npm registry 不可用，使用 {age // 60} 分钟前的缓存版本检查结果")
    latest_raw = str(data.get("version") or data.get("latest") or "").strip()
    if not _is_safe_version(latest_raw):
        sys.exit("npm registry 返回了无效的版本号，拒绝运行；请稍后重试或手动更新。")
    latest = _parse_version(latest_raw)
    if latest is None:
        warn("无法解析最新版本，跳过版本检查")
        return
    if latest <= current:
        if not from_cache:
            _write_update_cache(latest_raw)
        return
    if os.environ.get("BILI_LIVE_REPLAY_UPDATED") == "1":
        sys.exit("自动更新后版本仍不是最新，已停止以避免循环；请手动更新。")
    log(f"检测到新版本 {latest_raw}（当前 {VERSION}），正在自动更新...")
    if _auto_update(latest_raw):
        sys.exit("自动更新已下载，但未能重启；请重新运行命令。")
    sys.exit(f"当前版本 {VERSION} 已过期，自动更新失败。"
             f"请手动更新：npm install -g {NPM_PACKAGE}@latest")


# --------------------------------------------------------------------------- #
# 多语言（根据操作系统语言自动选择 help/usage 语种）
# --------------------------------------------------------------------------- #
STRINGS = {
    "zh": {
        "description": "bilibili 直播回放下载工具",
        "dates_help": "日期列表，格式 YYYY-MM-DD（与 --recent 二选一）",
        "dates_metavar": "日期",
        "room_id_help": "直播间房间号",
        "cookie_file_help": "从文件读取 Cookie（建议 chmod 600）",
        "cookie_stdin_help": "从标准输入读取 Cookie",
        "cdn_host_help": "追加允许的 CDN 域名后缀（可重复，例如 example.com）",
        "out_dir_help": "输出目录（默认当前目录）",
        "part_seconds_help": "每片段时长（秒，默认 3600）",
        "live_uid_help": "主播 uid（可选，跳过房间号解析）",
        "keep_temp_help": "保留临时分片",
        "recent_help": "下载最近 N 场回放（与日期列表二选一）",
        "proxy_help": "代理地址（如 http://127.0.0.1:7890；默认直连、绕过系统代理）",
        "usage": "用法",
        "positional_title": "位置参数",
        "optional_title": "选项",
        "help_help": "显示帮助信息并退出",
        "version_help": "显示版本号并退出",
        "err_recent_and_dates": "--recent 与日期列表不能同时使用",
        "err_nothing": "请提供日期列表（YYYY-MM-DD）或使用 --recent N",
        "err_recent_pos": "--recent 必须为正整数",
        "err_date": "日期格式错误: {d}（应为 YYYY-MM-DD）",
        "interrupted": "已中断（Ctrl+C），已清理临时文件",
    },
    "en": {
        "description": "bilibili live replay downloader",
        "dates_help": "date list, format YYYY-MM-DD (mutually exclusive with --recent)",
        "dates_metavar": "DATE",
        "room_id_help": "live room id",
        "cookie_file_help": "read cookie from file (chmod 600 recommended)",
        "cookie_stdin_help": "read cookie from stdin",
        "cdn_host_help": "extra allowed CDN host suffix (repeatable, e.g. example.com)",
        "out_dir_help": "output directory (default: current dir)",
        "part_seconds_help": "seconds per segment (default: 3600)",
        "live_uid_help": "anchor uid (optional, skip room resolution)",
        "keep_temp_help": "keep temporary segments",
        "recent_help": "download the most recent N replays (mutually exclusive with dates)",
        "proxy_help": "proxy URL (e.g. http://127.0.0.1:7890; default direct, bypass system proxy)",
        "usage": "usage",
        "positional_title": "positional arguments",
        "optional_title": "options",
        "help_help": "show this help message and exit",
        "version_help": "show program's version number and exit",
        "err_recent_and_dates": "--recent and date list cannot be used together",
        "err_nothing": "please provide dates (YYYY-MM-DD) or use --recent N",
        "err_recent_pos": "--recent must be a positive integer",
        "err_date": "invalid date: {d} (expected YYYY-MM-DD)",
        "interrupted": "interrupted (Ctrl+C), temporary files cleaned",
    },
}


def detect_language() -> str:
    """根据操作系统语言返回语言代码（zh / en / ...，未知回退到 en）。"""
    lang = ""
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(var, "")
        if v:
            lang = v
            break
    lang = lang.lower()
    if lang.startswith("zh"):
        return "zh"
    # 需要扩展其它语种时，在这里继续加分支即可
    return "en"


def get_strings():
    lang = detect_language()
    return STRINGS.get(lang, STRINGS["en"])


class LocalizedArgumentParser(argparse.ArgumentParser):
    """本地化的 ArgumentParser：usage 前缀、分组标题、-h 帮助文案随语言切换。"""

    def __init__(self, strings, *args, **kwargs):
        self._s = strings
        kwargs.setdefault("add_help", False)
        super().__init__(*args, **kwargs)
        self.add_argument("-h", "--help", action="help", help=self._s["help_help"])
        self._positionals.title = self._s["positional_title"]
        self._optionals.title = self._s["optional_title"]

    def format_help(self):
        formatter = self._get_formatter()
        formatter.add_usage(self.usage, self._actions, self._mutually_exclusive_groups,
                            prefix=self._s["usage"] + ": ")
        formatter.add_text(self.description)
        for action_group in self._action_groups:
            formatter.start_section(action_group.title)
            formatter.add_text(action_group.description)
            formatter.add_arguments(action_group._group_actions)
            formatter.end_section()
        formatter.add_text(self.epilog)
        return formatter.format_help()


class _AuthorAction(argparse.Action):
    """打印作者名并退出（彩蛋）。"""

    def __init__(self, option_strings, dest=argparse.SUPPRESS,
                 default=argparse.SUPPRESS, help=None):
        super().__init__(option_strings=option_strings, dest=dest,
                         default=default, nargs=0, help=help)

    def __call__(self, parser, namespace, values, option_string=None):
        print(AUTHOR)
        parser.exit()


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
def log(msg: str):
    print(msg, flush=True)


def info(msg: str):
    print(f"  [i] {msg}", flush=True)


def warn(msg: str):
    print(f"  [!] {msg}", flush=True)


def fmt_ts(ts: int, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return datetime.fromtimestamp(ts, CST).strftime(fmt)


# --------------------------------------------------------------------------- #
# 代理处理：默认直连（绕过系统代理，与 aria2c 一致），可用 --proxy 显式指定
# --------------------------------------------------------------------------- #
PROXY = None


def _new_session():
    """新建 requests 会话；默认直连，显式 --proxy 时才走代理。"""
    s = requests.Session()
    # 不读取 HTTP(S)_PROXY / REQUESTS_CA_BUNDLE 等环境变量
    s.trust_env = False
    if PROXY:
        s.proxies = {"http": PROXY, "https": PROXY}
    s.headers.update({"User-Agent": UA})
    return s


def api_headers(referer: str = "https://www.bilibili.com/") -> dict:
    # Cookie 只放在 api_session 的 cookie jar 里，且作用域限制为 .bilibili.com
    return {"User-Agent": UA, "Referer": referer}


def cdn_headers(referer: str) -> dict:
    # CDN / m3u8 / 分片请求绝对不携带 Cookie
    return {"User-Agent": UA, "Referer": referer}


def http_get(session, url, params=None, headers=None, timeout=30):
    r = session.get(url, params=params, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()


# --------------------------------------------------------------------------- #
# Cookie 处理：只提取 SESSDATA，并尽量用 URL 解码后的值登录
# --------------------------------------------------------------------------- #
def load_cookie(cookie_file: str, cookie_stdin: bool) -> str:
    if cookie_file and cookie_stdin:
        sys.exit("--cookie-file / --cookie-stdin 只能选择一个")
    if cookie_file:
        p = Path(cookie_file)
        if not p.exists() or not p.is_file():
            sys.exit(f"Cookie 文件不存在或不是普通文件: {cookie_file}")
        if os.name != "nt":
            try:
                mode = stat.S_IMODE(p.stat().st_mode)
            except OSError as e:
                sys.exit(f"无法读取 Cookie 文件权限: {e}")
            if mode & (stat.S_IRWXG | stat.S_IRWXO):
                sys.exit(f"Cookie 文件权限过宽（组/其他用户可访问），"
                         f"请执行: chmod 600 {cookie_file}")
        try:
            return p.read_text(encoding="utf-8").strip()
        except OSError as e:
            sys.exit(f"无法读取 Cookie 文件: {e}")
    if cookie_stdin:
        return sys.stdin.read().strip()
    sys.exit("必须提供 Cookie：--cookie-file 或 --cookie-stdin")


def extract_sessdata(raw: str) -> str:
    """从完整 Cookie 或裸 SESSDATA 中只提取 SESSDATA，丢弃其它字段。"""
    raw = raw.strip()
    if not raw:
        sys.exit("Cookie 为空")
    for part in raw.split(";"):
        key, sep, value = part.strip().partition("=")
        if sep and key.strip() == "SESSDATA":
            value = value.strip()
            if not value:
                sys.exit("SESSDATA 为空")
            return value
    # 允许用户直接粘贴裸 SESSDATA 值
    if "=" not in raw:
        return raw
    sys.exit("Cookie 中未找到 SESSDATA")


def resolve_sessdata(sessdata: str):
    """返回能通过登录校验的 SESSDATA（必要时尝试 URL 解码）。"""
    candidates = [sessdata]
    if "%" in sessdata:
        candidates.append(urllib.parse.unquote(sessdata))
    for candidate in candidates:
        session = _new_session()
        session.cookies.set("SESSDATA", candidate, domain=".bilibili.com", path="/")
        try:
            j = http_get(session, API_NAV, headers=api_headers())
            if j.get("code") == 0 and (j.get("data") or {}).get("isLogin"):
                return candidate
        except Exception:
            continue
        finally:
            session.close()
    return None


# --------------------------------------------------------------------------- #
# 主播 uid 解析
# --------------------------------------------------------------------------- #
def resolve_uid(room_id: int, session, referer: str) -> int:
    j = http_get(session, API_ROOM, params={"room_id": room_id},
                 headers=api_headers(referer))
    if j.get("code") != 0:
        sys.exit(f"获取房间信息失败: code={j.get('code')} message={j.get('message')}")
    data = j["data"]
    uid = data.get("uid")
    if not uid:
        sys.exit("无法解析房间 uid")
    log(f"房间 {room_id} -> 主播 uid={uid}（{data.get('title', '')}）")
    return uid


# --------------------------------------------------------------------------- #
# 回放列表
# --------------------------------------------------------------------------- #
def get_replay_list(uid: int, session, referer: str) -> list:
    all_replays = []
    page = 1
    while page <= MAX_REPLAY_PAGES:
        j = http_get(session, API_LIST, params={"live_uid": uid, "time_range": 3,
                                                "page": page, "page_size": 30},
                     headers=api_headers(referer))
        if j.get("code") != 0:
            sys.exit(f"获取回放列表失败: code={j.get('code')} message={j.get('message')}")
        data = j.get("data") or {}
        ri = data.get("replay_info") or []
        all_replays.extend(ri)
        total = (data.get("pagination") or {}).get("total", 0)
        if len(all_replays) >= total or not ri:
            break
        page += 1
    else:
        warn(f"回放列表超过 {MAX_REPLAY_PAGES} 页，已截断")
    return all_replays


def filter_by_dates(replays: list, dates: list) -> dict:
    """按直播开始时间（CST）筛选回放，返回 {date_str: replay}。"""
    wanted = set(dates)
    result = {}
    for r in replays:
        d = fmt_ts(r["start_time"], "%Y-%m-%d")
        if d in wanted and d not in result:
            result[d] = r
    return result


# --------------------------------------------------------------------------- #
# 切片流 & 断流检测
# --------------------------------------------------------------------------- #
def get_slices(replay: dict, uid: int, session, referer: str) -> list:
    j = http_get(session, API_STREAM,
                 params={"live_key": replay["live_key"],
                         "start_time": replay["start_time"],
                         "end_time": replay["end_time"],
                         "live_uid": uid},
                 headers=api_headers(referer))
    if j.get("code") != 0:
        warn(f"获取切片流失败: code={j.get('code')} message={j.get('message')}")
        return []
    data = j.get("data") or {}
    return {"list": data.get("list") or [], "ban_list": data.get("ban_list")}


# --------------------------------------------------------------------------- #
# 工具下载：固定版本 + SHA256 校验，校验失败绝不执行
# --------------------------------------------------------------------------- #
def _copy_verified_stream(src, dest: Path, expected_sha256: str) -> bool:
    """把 src 写到 dest 的临时文件，校验通过后再原子替换。"""
    fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=f".{dest.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    h = hashlib.sha256()
    try:
        with os.fdopen(fd, "wb") as out:
            for chunk in iter(lambda: src.read(1 << 20), b""):
                out.write(chunk)
                h.update(chunk)
        actual = h.hexdigest()
        if actual.lower() != expected_sha256.lower():
            warn(f"文件哈希校验失败: {dest.name}（期望 {expected_sha256[:12]}…，"
                 f"实际 {actual[:12]}…）")
            return False
        os.chmod(tmp, 0o755)
        os.replace(tmp, dest)
        return True
    except Exception as e:
        warn(f"写入工具文件失败: {e}")
        return False
    finally:
        tmp.unlink(missing_ok=True)


def _extract_verified(archive: Path, kind: str, dest_dir: Path, members: dict) -> bool:
    """只解压清单里指定的文件名，并逐个校验 SHA256；不使用 extractall。"""
    found = set()
    try:
        if kind == "zip":
            with zipfile.ZipFile(archive) as z:
                for name in z.namelist():
                    base = os.path.basename(name)
                    if base in members and base not in found:
                        with z.open(name) as src:
                            if not _copy_verified_stream(src, dest_dir / base, members[base]):
                                return False
                        found.add(base)
        elif kind in ("tar.xz", "tar.gz", "tar"):
            mode = {"tar.xz": "r:xz", "tar.gz": "r:gz", "tar": "r:"}[kind]
            with tarfile.open(archive, mode) as tf:
                for m in tf.getmembers():
                    base = os.path.basename(m.name)
                    if m.isfile() and base in members and base not in found:
                        src = tf.extractfile(m)
                        if src is None:
                            return False
                        with src:
                            if not _copy_verified_stream(src, dest_dir / base, members[base]):
                                return False
                        found.add(base)
        else:
            warn(f"不支持的工具压缩格式: {kind}")
            return False
    except Exception as e:
        warn(f"解压工具失败: {e}")
        return False
    missing = set(members) - found
    if missing:
        warn(f"压缩包中缺少预期文件: {', '.join(sorted(missing))}")
        return False
    return True


def _install_verified_tool(entry: dict, dest_dir: Path) -> bool:
    """下载固定版本压缩包 -> 校验压缩包 -> 解压指定文件 -> 校验文件哈希。"""
    try:
        _ensure_private_dir(dest_dir.parent)
        _ensure_private_dir(dest_dir)
    except Exception as e:
        warn(str(e))
        return False
    archive = dest_dir / entry["archive"]
    if not _download_file(entry["url"], archive,
                          expected_sha256=entry["sha256"],
                          max_bytes=MAX_TOOL_BYTES):
        archive.unlink(missing_ok=True)
        return False
    ok = _extract_verified(archive, entry["kind"], dest_dir, entry["members"])
    archive.unlink(missing_ok=True)
    return ok


def ensure_aria2c():
    """返回 aria2c 路径；系统自带优先，否则按清单下载固定版本并校验。"""
    p = shutil.which("aria2c")
    if p and _safe_system_tool(p):
        return p

    entry = ARIA2C_MANIFEST.get(_platform_key())
    if not entry:
        info("未检测到 aria2c，使用 Python 多线程下载（当前平台不自动下载）")
        return None

    cache_bin = TOOLS_DIR / "aria2c"
    member, expected = next(iter(entry["members"].items()))
    local = cache_bin / member
    try:
        _ensure_private_dir(cache_bin)
    except Exception as e:
        warn(f"无法准备 aria2c 目录: {e}")
        return None
    if local.exists():
        if _verify_sha256(local, expected):
            return str(local)
        warn("本地 aria2c 哈希不匹配，重新下载固定版本")
    info(f"未检测到 aria2c，下载并校验固定版本 {entry['version']} ...")
    if _install_verified_tool(entry, cache_bin) and local.exists() and _verify_sha256(local, expected):
        return str(local)
    warn("aria2c 自动下载/校验失败，改用 Python 多线程下载")
    return None


def _print_progress(done: int, total: int, speed: float, elapsed: float):
    pct = done * 100.0 / total if total else 0.0
    mm = int(elapsed) // 60
    ss = int(elapsed) % 60
    sys.stdout.write(f"\r  下载中 {done}/{total} ({pct:.1f}%)  "
                     f"{speed / 1048576:.1f} MB/s  耗时 {mm:02d}:{ss:02d}    ")
    sys.stdout.flush()


def _scan_items(outdir: Path, items: list):
    """统计本批 items 中已存在的分片数量与总字节数（用于进度显示）。"""
    n, size = 0, 0
    for i, _ in items:
        try:
            size += (outdir / f"seg_{i:05d}.m4s").stat().st_size
            n += 1
        except OSError:
            pass
    return n, size


def _download_aria2c(items: list, outdir: Path, referer: str, aria2c: str,
                     jobs: int = 64, tries: int = 5, retry_wait: int = 2,
                     logname: str = "aria2c.log") -> bool:
    """用 aria2c 批量下载分片。items 为 [(序号, url), ...]，序号用于生成文件名。"""
    inp = outdir / f"{logname.replace('.log', '')}_input.txt"
    with open(inp, "w", encoding="utf-8") as f:
        for i, u in items:
            f.write(u + "\n")
            f.write(f"  out=seg_{i:05d}.m4s\n")
            f.write("\n")
    cmd = [aria2c, "-i", str(inp), "-d", str(outdir),
           "--auto-file-renaming=false", "--allow-overwrite=true",
           "--file-allocation=none", f"--max-tries={tries}", f"--retry-wait={retry_wait}",
           "--timeout=30", "--connect-timeout=15", "--check-certificate=true",
           "-j", str(jobs), "-x", "1", "-s", "1",
           "--console-log-level=warn", "--summary-interval=10",
           "--user-agent", UA, "--referer", referer]
    logfile = outdir / logname
    total = len(items)
    try:
        with open(logfile, "w", encoding="utf-8") as f:
            p = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT)
        t0 = time.time()
        last_bytes = 0
        last_t = t0
        try:
            while p.poll() is None:
                done, cur_bytes = _scan_items(outdir, items)
                now = time.time()
                dt = now - last_t
                if dt >= 1.0:
                    speed = (cur_bytes - last_bytes) / dt if dt > 0 else 0.0
                    last_bytes = cur_bytes
                    last_t = now
                    _print_progress(done, total, speed, now - t0)
                time.sleep(0.5)
        except KeyboardInterrupt:
            # 用户按了 Ctrl+C：先结束 aria2c 子进程再抛出，交给顶层处理
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
            sys.stdout.write("\n")
            sys.stdout.flush()
            raise
        done, _ = _scan_items(outdir, items)
        _print_progress(done, total, 0.0, time.time() - t0)
        sys.stdout.write("\n")
        sys.stdout.flush()
        return p.returncode == 0
    finally:
        # 输入文件和日志可能含带签名的 CDN URL，无论是否 --keep-temp 都清理
        inp.unlink(missing_ok=True)
        logfile.unlink(missing_ok=True)


def safe_cdn_get(session, url: str, headers: dict, timeout: int,
                 cdn_hosts, stream: bool = False, max_redirects: int = 3):
    """只请求 HTTPS + 白名单域名；逐跳校验重定向，且不带任何 Cookie。"""
    for _ in range(max_redirects + 1):
        if not _validate_cdn_url(url, cdn_hosts):
            raise ValueError(f"拒绝非允许的 CDN URL: {_redact_url(url)}")
        r = session.get(url, headers=headers, timeout=timeout,
                        allow_redirects=False, stream=stream)
        if r.status_code in (301, 302, 303, 307, 308):
            location = r.headers.get("Location")
            r.close()
            if not location:
                raise ValueError("重定向缺少 Location")
            url = urllib.parse.urljoin(url, location)
            continue
        return r
    raise ValueError("重定向次数过多")


def _download_one(args):
    u, out, session, headers, cdn_hosts = args
    tmp = out.with_name(out.name + ".part")
    for _ in range(3):
        r = None
        try:
            r = safe_cdn_get(session, u, headers, timeout=60,
                             cdn_hosts=cdn_hosts, stream=True)
            if r.status_code != 200:
                continue
            content_length = int(r.headers.get("content-length", 0) or 0)
            if content_length > MAX_SEGMENT_BYTES:
                raise ValueError("分片超过大小上限")
            total = 0
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    total += len(chunk)
                    if total > MAX_SEGMENT_BYTES:
                        raise ValueError("分片超过大小上限")
                    f.write(chunk)
            os.replace(tmp, out)
            return True
        except Exception:
            tmp.unlink(missing_ok=True)
        finally:
            if r is not None:
                r.close()
    return False


def _download_py(items: list, outdir: Path, session, headers, cdn_hosts) -> bool:
    tasks = []
    for i, u in items:
        tasks.append((u, outdir / f"seg_{i:05d}.m4s", session, headers, cdn_hosts))
    total = len(tasks)
    ok = 0
    t0 = time.time()
    last_bytes = 0
    last_t = t0
    with ThreadPoolExecutor(max_workers=32) as ex:
        futures = [ex.submit(_download_one, t) for t in tasks]
        try:
            for fut in as_completed(futures):
                ok += 1 if fut.result() else 0
                now = time.time()
                dt = now - last_t
                if dt >= 1.0:
                    _, cur_bytes = _scan_items(outdir, items)
                    speed = (cur_bytes - last_bytes) / dt if dt > 0 else 0.0
                    last_bytes = cur_bytes
                    last_t = now
                    _print_progress(ok, total, speed, now - t0)
        except KeyboardInterrupt:
            for fut in futures:
                fut.cancel()
            ex.shutdown(wait=False, cancel_futures=True)
            sys.stdout.write("\n")
            sys.stdout.flush()
            raise
    _print_progress(ok, total, 0.0, time.time() - t0)
    sys.stdout.write("\n")
    sys.stdout.flush()
    return ok == total


def _missing_segments(outdir: Path, total: int) -> list:
    """返回缺失、空文件或超过大小上限的分片序号（1 起）。"""
    missing = []
    for i in range(1, total + 1):
        p = outdir / f"seg_{i:05d}.m4s"
        try:
            if not p.exists() or p.stat().st_size == 0:
                missing.append(i)
            elif p.stat().st_size > MAX_SEGMENT_BYTES:
                p.unlink(missing_ok=True)
                warn(f"分片 {i} 超过大小上限，已删除")
                missing.append(i)
        except OSError:
            missing.append(i)
    return missing


def download_segments(urls: list, outdir: Path, session, headers, referer: str,
                      cdn_hosts) -> list:
    """下载全部分片，返回最终仍缺失的序号（1 起）；全部成功返回空列表。"""
    try:
        _ensure_private_dir(outdir)
    except Exception as e:
        warn(f"无法准备分片目录: {e}")
        return list(range(1, len(urls) + 1))
    t0 = time.time()
    total = len(urls)
    aria2c = ensure_aria2c()
    if aria2c:
        info(f"开始并行下载 {total} 个分片（aria2c）...")
        _download_aria2c(list(enumerate(urls, 1)), outdir, referer, aria2c)
    else:
        info("未检测到 aria2c，使用 Python 多线程下载（较慢）")
        _download_py(list(enumerate(urls, 1)), outdir, session, headers, cdn_hosts)
    n = total - len(_missing_segments(outdir, total))
    log(f"  下载完成 {n}/{total} 个分片，耗时 {time.time()-t0:.0f}s")

    # 个别分片偶发失败（CDN 限流 / 连接重置 / 临时 404）时，单独低并发重试一轮
    missing = _missing_segments(outdir, total)
    if not missing:
        return []
    for i in missing:
        (outdir / f"seg_{i:05d}.m4s").unlink(missing_ok=True)  # 丢弃可能存在的空文件
    warn(f"{len(missing)} 个分片未下载成功，正在低并发重试 ...")
    items = [(i, urls[i - 1]) for i in missing]
    if aria2c:
        _download_aria2c(items, outdir, referer, aria2c,
                         jobs=4 if len(items) <= 50 else 16,
                         tries=6, retry_wait=3, logname="aria2c_retry.log")
    else:
        _download_py(items, outdir, session, headers, cdn_hosts)
    missing = _missing_segments(outdir, total)
    if missing:
        preview = "、".join(str(i) for i in missing[:10])
        warn(f"重试后仍有 {len(missing)} 个分片缺失：{preview}"
             f"{' ...' if len(missing) > 10 else ''}")
    else:
        log("  重试后已补齐全部分片")
    return missing


# --------------------------------------------------------------------------- #
# 解析 m3u8
# --------------------------------------------------------------------------- #
def parse_m3u8(text: str):
    """返回 [(EXTINF, url), ...]；限制分片数量，并保留 EXTINF 对齐。"""
    entries = []
    pending = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#EXTINF"):
            pending = s
        elif s.startswith("http"):
            entries.append((pending or "#EXTINF:0,", s))
            pending = None
            if len(entries) > MAX_SEGMENTS:
                raise ValueError(f"m3u8 分片数量超过上限 {MAX_SEGMENTS}")
    return entries


def fetch_m3u8(session, url: str, headers, cdn_hosts) -> str:
    for _ in range(3):
        r = None
        try:
            r = safe_cdn_get(session, url, headers, timeout=90,
                             cdn_hosts=cdn_hosts, stream=True)
            if r.status_code != 200:
                continue
            content_length = int(r.headers.get("content-length", 0) or 0)
            if content_length > MAX_M3U8_BYTES:
                warn(f"m3u8 过大，已拒绝: {_redact_url(url)}")
                return ""
            data = bytearray()
            for chunk in r.iter_content(1 << 16):
                data.extend(chunk)
                if len(data) > MAX_M3U8_BYTES:
                    warn(f"m3u8 超过大小上限，已拒绝: {_redact_url(url)}")
                    return ""
            text = data.decode("utf-8", "replace")
            if "#EXT-X-ENDLIST" in text:
                return text
        except Exception:
            pass
        finally:
            if r is not None:
                r.close()
    warn(f"m3u8 获取失败: {_redact_url(url)}")
    return ""


def build_local_m3u8(extinfs: list, subdir: Path, skip=()) -> Path:
    """生成本地 m3u8；skip 中的分片序号（1 起）不会写入，用于容忍个别缺失分片。"""
    skip = set(skip)
    lines = ["#EXTM3U", "#EXT-X-VERSION:7", "#EXT-X-TARGETDURATION:5",
             "#EXT-X-PLAYLIST-TYPE:VOD"]
    for i, ext in enumerate(extinfs, 1):
        if i in skip:
            continue
        lines.append(ext)
        lines.append(f"seg_{i:05d}.m4s")
    lines.append("#EXT-X-ENDLIST")
    p = subdir / "local.m3u8"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


# --------------------------------------------------------------------------- #
# ffmpeg 自动准备
# --------------------------------------------------------------------------- #
def _run(cmd, cwd=None, env=None):
    e = os.environ.copy()
    if env:
        e.update(env)
    return subprocess.run(cmd, cwd=cwd, env=e).returncode == 0


def ensure_ffmpeg():
    """返回 (ffmpeg_path, ffprobe_path, env) 或 sys.exit。

    优先使用系统包管理器安装的 ffmpeg；否则只下载清单里固定版本并校验 SHA256。
    macOS 不自动下载，请用 Homebrew 安装。
    """
    env = {}
    is_win = sys.platform == "win32"
    exe = ".exe" if is_win else ""

    # 1) 系统 PATH（拒绝组/其他用户可写位置）
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg and ffprobe and _safe_system_tool(ffmpeg) and _safe_system_tool(ffprobe):
        return ffmpeg, ffprobe, env

    # 2) 本地缓存：必须通过固定 SHA256 校验
    cache_bin = TOOLS_DIR / "ffmpeg" / "bin"
    try:
        _ensure_private_dir(cache_bin.parent)
        _ensure_private_dir(cache_bin)
    except Exception as e:
        sys.exit(f"无法准备 ffmpeg 缓存目录: {e}")
    cf = cache_bin / f"ffmpeg{exe}"
    cp = cache_bin / f"ffprobe{exe}"
    entry = FFMPEG_MANIFEST.get(_platform_key())
    if entry and cf.exists() and cp.exists():
        expected = entry["members"]
        if _verify_sha256(cf, expected[cf.name]) and _verify_sha256(cp, expected[cp.name]):
            return str(cf), str(cp), env
        warn("本地 ffmpeg/ffprobe 哈希不匹配，将重新下载固定版本")

    # 3) 固定版本下载 + 校验；没有清单条目的平台直接提示用户安装
    if entry:
        info(f"未找到 ffmpeg，下载并校验固定版本 {entry['version']} ...")
        if _install_verified_tool(entry, cache_bin):
            if cf.exists() and cp.exists() and \
                    _verify_sha256(cf, entry["members"][cf.name]) and \
                    _verify_sha256(cp, entry["members"][cp.name]):
                return str(cf), str(cp), env

    hints = {
        "linux": "sudo apt install ffmpeg",
        "darwin": "brew install ffmpeg",
        "win32": "winget install Gyan.FFmpeg",
    }
    sys.exit(f"未找到可用的 ffmpeg/ffprobe，请用系统包管理器安装："
             f"{hints.get(sys.platform, '安装 ffmpeg 并加入 PATH')}")


def _download_file(url: str, dest: Path, expected_sha256: str = None,
                   max_bytes: int = MAX_TOOL_BYTES, timeout: int = 300,
                   allowed_suffixes=TOOL_DOWNLOAD_SUFFIXES) -> bool:
    """下载文件：限制大小、TLS 校验、可选 SHA256、原子替换。"""
    session = _new_session()
    tmp = None
    try:
        _ensure_private_dir(dest.parent)
        initial = urllib.parse.urlparse(url)
        if initial.scheme != "https" or not initial.hostname or \
                not _host_allowed(initial.hostname, allowed_suffixes):
            raise ValueError(f"不允许的下载地址: {_redact_url(url)}")
        with session.get(url, timeout=timeout, stream=True, allow_redirects=True) as r:
            r.raise_for_status()
            final = urllib.parse.urlparse(r.url)
            if final.scheme != "https" or not final.hostname or \
                    not _host_allowed(final.hostname, allowed_suffixes):
                raise ValueError(f"下载重定向到不允许的地址: {_redact_url(r.url)}")
            total = int(r.headers.get("content-length", 0) or 0)
            if total > max_bytes:
                warn(f"文件超过大小上限，已拒绝下载: {dest.name}")
                return False
            fd, tmp_name = tempfile.mkstemp(dir=dest.parent,
                                            prefix=f".{dest.name}.", suffix=".part")
            tmp = Path(tmp_name)
            done = 0
            last_pct = -1
            h = hashlib.sha256()
            t0 = time.time()
            with os.fdopen(fd, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    done += len(chunk)
                    if done > max_bytes:
                        warn(f"下载超过大小上限，已中止: {dest.name}")
                        return False
                    f.write(chunk)
                    h.update(chunk)
                    if total > 0:
                        pct = done * 100 // total
                        if pct >= last_pct + 10:
                            last_pct = pct
                            speed = done / max(time.time() - t0, 0.1) / 1048576
                            info(f"下载 {dest.name}: {pct}%  "
                                 f"{done/1048576:.1f}/{total/1048576:.1f} MB  "
                                 f"{speed:.1f} MB/s")
            actual = h.hexdigest()
            if expected_sha256 and actual.lower() != expected_sha256.lower():
                warn(f"下载文件哈希校验失败: {dest.name}"
                     f"（期望 {expected_sha256[:12]}…，实际 {actual[:12]}…）")
                return False
            os.replace(tmp, dest)
            tmp = None
            return True
    except Exception as e:
        warn(f"下载失败 {_redact_url(url)}: {e}")
        return False
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
        session.close()


# --------------------------------------------------------------------------- #
# 视频处理：转封装 -> 拼接 -> 切分
# --------------------------------------------------------------------------- #
def remux_to_mp4(ffmpeg, env, m3u8: Path, out_mp4: Path) -> bool:
    return _run([ffmpeg, "-y", "-v", "warning", "-i", str(m3u8),
                 "-map", "0", "-c", "copy", "-reset_timestamps", "1",
                 "-avoid_negative_ts", "make_zero", str(out_mp4)],
                cwd=str(m3u8.parent), env=env)


def concat_mp4s(ffmpeg, env, mp4s: list, out: Path, workdir: Path) -> bool:
    listfile = workdir / "concat.txt"
    listfile.write_text("".join(f"file '{p.name}'\n" for p in mp4s), encoding="utf-8")
    return _run([ffmpeg, "-y", "-v", "warning", "-f", "concat", "-safe", "0",
                 "-i", str(listfile), "-c", "copy", str(out)], cwd=str(workdir), env=env)


def split_mp4(ffmpeg, env, inp: Path, prefix: str, outdir: Path, part_seconds: int) -> bool:
    out_pat = str(outdir / f"{prefix}_part%d.mp4")
    return _run([ffmpeg, "-y", "-v", "warning", "-i", str(inp),
                 "-map", "0", "-c", "copy", "-f", "segment",
                 "-segment_time", str(part_seconds),
                 "-reset_timestamps", "1", "-avoid_negative_ts", "make_zero",
                 "-segment_start_number", "1", out_pat], env=env)


def probe_duration(ffprobe, env, path: Path) -> float:
    r = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                       capture_output=True, text=True, env={**os.environ, **env})
    try:
        return float(r.stdout.strip().splitlines()[-1])
    except Exception:
        return 0.0


# --------------------------------------------------------------------------- #
# 断流原因分析
# --------------------------------------------------------------------------- #
def analyze_interruptions(replay, slices, uid, session, referer: str) -> list:
    """返回 [(gap_start, gap_end, gap_seconds, reason_str), ...]"""
    lst = slices["list"]
    ban_list = slices.get("ban_list") or []
    if len(lst) < 2:
        return []

    reasons = []
    vi = replay.get("video_info") or {}
    ai = replay.get("alarm_info") or {}
    alert_msg = vi.get("alert_message", "")
    is_ban = ai.get("is_ban_publish", False)

    # 拉取会话数据（弹幕，每分钟采样），用于判断断流期间直播间是否仍“在线”
    danmaku = {}
    try:
        j = http_get(session, API_SESSION,
                     params={"live_key": replay["live_key"],
                             "start_tm": fmt_ts(replay["start_time"]),
                             "end_tm": fmt_ts(replay["end_time"]),
                             "live_uid": uid},
                     headers=api_headers(referer))
        for s in (j.get("data") or {}).get("session_data") or []:
            danmaku[s.get("ts")] = s.get("value", 0)
    except Exception:
        pass

    for i in range(len(lst) - 1):
        gap_start = lst[i]["end_time"]
        gap_end = lst[i + 1]["start_time"]
        gap_sec = gap_end - gap_start
        if gap_sec <= 0:
            continue

        in_ban = any(b["start_time"] <= gap_start and gap_end <= b["end_time"]
                     for b in ban_list)

        # 断流期间弹幕是否仍在活跃（说明直播间没关、只是画面断了）
        active = 0
        for ts, v in danmaku.items():
            if gap_start <= ts <= gap_end and v > 0:
                active += 1

        if in_ban or is_ban:
            reason = "违规封禁（平台判定直播内容违规，该时段被掐掉）"
        elif active > 0:
            reason = ("推流网络问题（主播端推流掉线后重新推流；"
                      "断流期间直播间与弹幕仍在，非违规封禁）")
        elif "网络" in alert_msg:
            reason = ("推流网络问题（主播端推流掉线/网络波动，后重新推流），"
                      "非违规封禁")
        else:
            reason = ("直播中断（可能为推流网络问题或主播主动重开，"
                      "平台未判定违规）")

        reasons.append((gap_start, gap_end, gap_sec, reason))

    return reasons


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def process_replay(replay, uid, date_str, prefix, api_session, cdn_session, referer,
                   cdn_hosts, ffmpeg, ffprobe, env,
                   outdir: Path, workdir: Path, part_seconds: int):
    log(f"\n{'=' * 60}")
    log(f"日期 {date_str} 回放  replay_id={replay['replay_id']}")
    log(f"  直播时间 {fmt_ts(replay['start_time'])} ~ {fmt_ts(replay['end_time'])}")

    slices = get_slices(replay, uid, api_session, referer)
    if not slices or not slices["list"]:
        warn("未获取到切片视频流（可能回放尚未合成完成），跳过")
        return False

    n_slice = len(slices["list"])
    if n_slice > 1:
        log(f"  [!] 检测到断流：回放被切成 {n_slice} 段")
    for idx, s in enumerate(slices["list"]):
        log(f"    段{idx+1}: {fmt_ts(s['start_time'], '%H:%M:%S')} ~ "
            f"{fmt_ts(s['end_time'], '%H:%M:%S')} "
            f"({(s['end_time'] - s['start_time']) // 60}分"
            f"{(s['end_time'] - s['start_time']) % 60}秒)")

    # 逐段下载 + 转封装
    slice_mp4s = []
    for slice_idx, s in enumerate(slices["list"]):
        subdir = workdir / f"slice{slice_idx}"
        try:
            _ensure_private_dir(subdir)
        except Exception as e:
            warn(f"段{slice_idx+1} 无法准备临时目录: {e}")
            continue
        if not _validate_cdn_url(s["stream"], cdn_hosts):
            warn(f"段{slice_idx+1} 的 stream 不是 HTTPS/白名单地址，已跳过")
            continue
        m3u8_text = fetch_m3u8(cdn_session, s["stream"], cdn_headers(referer), cdn_hosts)
        if not m3u8_text:
            warn(f"段{slice_idx+1} 的 m3u8 获取失败，跳过该段")
            continue
        try:
            entries = parse_m3u8(m3u8_text)
        except ValueError as e:
            warn(f"段{slice_idx+1} 的 m3u8 无效: {e}")
            continue

        allowed = []
        rejected = 0
        for ext, url in entries:
            if _validate_cdn_url(url, cdn_hosts):
                allowed.append((ext, url))
            else:
                rejected += 1
        if rejected:
            warn(f"段{slice_idx+1}: 跳过 {rejected} 个非 HTTPS/非白名单分片")
        if not allowed:
            warn(f"段{slice_idx+1}: 没有可用的分片，跳过该段")
            continue
        extinfs = [ext for ext, _ in allowed]
        urls = [url for _, url in allowed]

        log(f"  段{slice_idx+1}: 共 {len(urls)} 个分片，开始下载...")
        missing = download_segments(urls, subdir, cdn_session,
                                    cdn_headers(referer), referer, cdn_hosts)
        if missing:
            # 偶发失败的分片没必要让整场几小时的回放作废：少量缺失就跳过这些位置继续合成
            limit = min(50, max(3, len(urls) // 100))
            if len(missing) > limit:
                warn(f"段{slice_idx+1} 缺失 {len(missing)}/{len(urls)} 个分片，"
                     f"超过容忍上限（{limit}），跳过该段")
                continue
            gap = 0.0
            for mi in missing:
                if mi <= len(extinfs):
                    try:
                        gap += float(extinfs[mi - 1].split(":")[1].split(",")[0])
                    except (IndexError, ValueError):
                        pass
            warn(f"段{slice_idx+1} 缺失 {len(missing)} 个分片（约 {gap:.0f} 秒），"
                 f"已跳过这些位置继续合成")
        local = build_local_m3u8(extinfs, subdir, skip=missing)
        out_mp4 = workdir / f"slice{slice_idx}.mp4"
        if not remux_to_mp4(ffmpeg, env, local, out_mp4):
            warn(f"段{slice_idx+1} 转封装失败")
            continue
        # 释放磁盘：删除已下载分片
        for seg in subdir.glob("seg_*.m4s"):
            seg.unlink()
        slice_mp4s.append(out_mp4)

    if not slice_mp4s:
        warn("没有可用的视频段，跳过")
        return False

    # 拼接（多段时）
    if len(slice_mp4s) == 1:
        combined = slice_mp4s[0]
    else:
        combined = workdir / "combined.mp4"
        log("  拼接断流前后的片段...")
        if not concat_mp4s(ffmpeg, env, slice_mp4s, combined, workdir):
            warn("拼接失败，将仅用第一段")
            combined = slice_mp4s[0]

    # 切分为 1 小时片段
    log(f"  切分为每 {part_seconds // 60} 分钟一个片段...")
    if not split_mp4(ffmpeg, env, combined, prefix, outdir, part_seconds):
        warn("切分失败")
        return False

    # 列出产物
    parts = sorted(outdir.glob(f"{prefix}_part*.mp4"))
    log(f"  导出完成，共 {len(parts)} 个片段：")
    for p in parts:
        dur = probe_duration(ffprobe, env, p)
        log(f"    {p.name}  {p.stat().st_size/1048576:.1f} MB  {dur/60:.1f} 分钟")

    # 断流原因分析 + 报告
    if n_slice > 1:
        reasons = analyze_interruptions(replay, slices, uid, api_session, referer)
        if reasons:
            log(f"\n  {'=' * 40}")
            log("  断流原因分析：")
            for gs, ge, sec, reason in reasons:
                log(f"    断流时段: {fmt_ts(gs, '%H:%M:%S')} ~ {fmt_ts(ge, '%H:%M:%S')} "
                    f"（约 {sec // 60} 分 {sec % 60} 秒）")
                log(f"    断流原因: {reason}")
            log("  （已自动拼接断流前后的内容，视频连续无缺）")
            log(f"  {'=' * 40}")
        else:
            log("  检测到断流，但未获取到具体原因信息。")

    return True


def main():
    S = get_strings()
    ap = LocalizedArgumentParser(S, description=S["description"])
    ap.add_argument("dates", nargs="*", metavar=S["dates_metavar"], help=S["dates_help"])
    ap.add_argument("--room-id", type=int, required=True, help=S["room_id_help"])
    ap.add_argument("--cookie-file", default="", help=S["cookie_file_help"])
    ap.add_argument("--cookie-stdin", action="store_true", help=S["cookie_stdin_help"])
    ap.add_argument("--out-dir", default=".", help=S["out_dir_help"])
    ap.add_argument("--part-seconds", type=int, default=3600, help=S["part_seconds_help"])
    ap.add_argument("--live-uid", type=int, default=0, help=S["live_uid_help"])
    ap.add_argument("--keep-temp", action="store_true", help=S["keep_temp_help"])
    ap.add_argument("--recent", type=int, default=0, help=S["recent_help"])
    ap.add_argument("--proxy", default="", help=S["proxy_help"])
    ap.add_argument("--cdn-host", action="append", default=[], help=S["cdn_host_help"])
    ap.add_argument("--version", action="version",
                    version=f"%(prog)s {VERSION}", help=S["version_help"])
    ap.add_argument("--author", action=_AuthorAction, help=argparse.SUPPRESS)
    args = ap.parse_args()

    # 拒绝 root/管理员：用户可写目录里的 ffmpeg/aria2c 不应由高权限执行
    if os.name != "nt" and hasattr(os, "geteuid") and os.geteuid() == 0:
        sys.exit("出于安全考虑，请勿以 root/sudo 运行本工具；请用普通用户运行。")
    if os.name == "nt":
        try:
            import ctypes
            if ctypes.windll.shell32.IsUserAnAdmin():
                sys.exit("出于安全考虑，请勿以管理员身份运行本工具；请用普通用户运行。")
        except Exception:
            pass

    # 全局代理设置
    global PROXY
    PROXY = args.proxy or None

    # 参数校验：日期 与 --recent 二选一
    if args.recent and args.dates:
        sys.exit(S["err_recent_and_dates"])
    if not args.recent and not args.dates:
        sys.exit(S["err_nothing"])
    if args.recent and args.recent <= 0:
        sys.exit(S["err_recent_pos"])
    if args.recent > 1000:
        sys.exit("--recent 过大（最多 1000）")
    if args.part_seconds <= 0:
        sys.exit("--part-seconds 必须为正整数")

    # 校验日期格式
    for d in args.dates:
        try:
            datetime.strptime(d, "%Y-%m-%d")
        except ValueError:
            sys.exit(S["err_date"].format(d=d))

    cdn_hosts = _build_cdn_hosts(args.cdn_host)

    # 所有缓存/工具/临时目录必须是当前用户私有的 0700 目录
    try:
        _ensure_private_dir(CACHE_DIR)
        _ensure_private_dir(TOOLS_DIR)
        _ensure_private_dir(WORK_DIR)
    except Exception as e:
        sys.exit(f"无法准备私有缓存目录: {e}")

    # 先自查版本：旧版本自动更新；更新失败则拒绝继续运行
    _enforce_latest_version()

    outdir = Path(args.out_dir).expanduser()
    outdir.mkdir(parents=True, exist_ok=True)

    # Cookie：只保留 SESSDATA，其它字段（包括 bili_jct）立即丢弃
    raw_cookie = load_cookie(args.cookie_file, args.cookie_stdin)
    sessdata = extract_sessdata(raw_cookie)
    del raw_cookie
    sessdata = resolve_sessdata(sessdata)
    if not sessdata:
        sys.exit("登录校验失败：Cookie 无效或已过期，请重新提供")
    log("登录成功 ✅")

    referer = f"https://live.bilibili.com/{args.room_id}"
    api_session = _new_session()
    api_session.cookies.set("SESSDATA", sessdata, domain=".bilibili.com", path="/")
    cdn_session = _new_session()

    # uid
    uid = args.live_uid or resolve_uid(args.room_id, api_session, referer)

    # 回放列表
    log("获取回放列表...")
    replays = get_replay_list(uid, api_session, referer)

    # 决定要处理哪些回放：[(replay, date_str, prefix), ...]
    if args.recent:
        replays_sorted = sorted(replays, key=lambda r: r["start_time"], reverse=True)
        selected = replays_sorted[:args.recent]
        log(f"选取最近 {len(selected)} 场回放：")
        for r in selected:
            log(f"    {fmt_ts(r['start_time'], '%Y-%m-%d %H:%M')} ~ "
                f"{fmt_ts(r['end_time'], '%H:%M')}")
        to_process = [(r, fmt_ts(r["start_time"], "%Y-%m-%d"),
                       fmt_ts(r["start_time"], "%Y_%m_%d")) for r in selected]
    else:
        matched = filter_by_dates(replays, args.dates)
        to_process = []
        for d in args.dates:
            r = matched.get(d)
            if not r:
                warn(f"未找到 {d} 的回放")
                continue
            to_process.append((r, d, d.replace("-", "_")))

    if not to_process:
        log("没有可下载的回放。")
        log("（注意：接口最多返回近 14 天的回放）")
        api_session.close()
        cdn_session.close()
        return

    # ffmpeg：系统包管理器优先，否则只接受固定 SHA256 的版本
    ffmpeg, ffprobe, env = ensure_ffmpeg()

    # 临时工作目录（放在系统磁盘，避免占用 /tmp 的 tmpfs）
    workdir = WORK_DIR
    _ensure_private_dir(workdir)
    if args.keep_temp:
        warn("--keep-temp 会保留视频分片；aria2c 日志/输入文件仍会被删除")

    t_start = time.time()
    success_count = 0
    total_video_sec = 0
    for r, d, prefix in to_process:
        day_work = workdir / prefix
        if day_work.is_symlink():
            sys.exit(f"临时目录不能是符号链接: {day_work}")
        if day_work.exists():
            shutil.rmtree(day_work)
        _ensure_private_dir(day_work)
        ok = process_replay(r, uid, d, prefix, api_session, cdn_session, referer,
                            cdn_hosts, ffmpeg, ffprobe, env,
                            outdir, day_work, args.part_seconds)
        # 无论是否 --keep-temp，都清理可能含签名 URL 的日志/输入文件
        for pattern in ("aria2c*.log", "*_input.txt", "concat.txt"):
            for f in day_work.rglob(pattern):
                try:
                    f.unlink(missing_ok=True)
                except OSError:
                    pass
        if not args.keep_temp:
            shutil.rmtree(day_work, ignore_errors=True)
        elif ok:
            warn(f"已保留临时视频分片: {day_work}（签名 URL 日志已清理）")
        if ok:
            success_count += 1
            dur = (r.get("video_info") or {}).get("duration")
            if not dur:
                dur = r["end_time"] - r["start_time"]
            total_video_sec += int(dur)

    # 总时长汇总
    elapsed = time.time() - t_start
    vh, vm = total_video_sec // 3600, (total_video_sec % 3600) // 60
    eh, em, es = int(elapsed) // 3600, (int(elapsed) % 3600) // 60, int(elapsed) % 60
    log(f"\n{'=' * 40}")
    log("  下载汇总：")
    log(f"    成功下载: {success_count} 场回放")
    log(f"    视频总时长: {vh} 时 {vm} 分")
    log(f"    总耗时: {eh} 时 {em} 分 {es} 秒" if eh else f"    总耗时: {em} 分 {es} 秒")
    log(f"{'=' * 40}")

    api_session.close()
    cdn_session.close()
    log("\n全部完成 ✅")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        msg = "\n" + get_strings()["interrupted"] + "\n"
        sys.stderr.write(msg)
        sys.stderr.flush()
        # 清理临时文件
        shutil.rmtree(WORK_DIR, ignore_errors=True)
        # 用 os._exit 立即退出，避免被卡住的下载线程/子进程拖住（否则 Ctrl+C 停不下来）
        os._exit(130)
