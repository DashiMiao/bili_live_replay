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
  - ffmpeg / ffprobe     （如未安装，脚本会尝试自动下载到本地缓存；也可手动 sudo apt install ffmpeg）
  - aria2c（可选，用于加速下载；没有则用 Python 多线程下载）

用法示例：
  python3 bili_live_replay.py --room-id 9308312 --cookie-file cookie.txt 2026-11-10
  python3 bili_live_replay.py --room-id 9308312 --cookie "$COOKIE" 2026-11-10 2026-11-11
  python3 bili_live_replay.py --room-id 9308312 --cookie "$COOKIE" --out-dir ~/下载 2026-11-10

说明：
  - 下载他人直播间回放，需要你的账号已获得该主播的「剪辑权限（授权）」，
    否则接口会返回 301「没有剪辑权限」。
  - Cookie 里只需要 SESSDATA 即可登录；若复制出来的 Cookie 是 URL 编码过的
    （例如 SESSDATA 里含 %2C、%2A），脚本会自动尝试解码后再登录。
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
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


def _app_dir() -> Path:
    """程序所在目录（PyInstaller 冻结时为可执行文件所在目录，否则为脚本目录）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


# ffmpeg / aria2c 等工具二进制：下载到程序同目录下的 tools/，方便随程序一起拷贝
TOOLS_DIR = _app_dir() / "tools"
# 下载过程中的临时分片：仍放用户缓存目录（体量大、用完即删）
WORK_DIR = Path.home() / ".cache" / "bili-live-replay" / "work"


# --------------------------------------------------------------------------- #
# 多语言（根据操作系统语言自动选择 help/usage 语种）
# --------------------------------------------------------------------------- #
STRINGS = {
    "zh": {
        "description": "bilibili 直播回放下载工具",
        "dates_help": "日期列表，格式 YYYY-MM-DD（与 --recent 二选一）",
        "dates_metavar": "日期",
        "room_id_help": "直播间房间号",
        "cookie_help": "Cookie 字符串",
        "cookie_file_help": "从文件读取 Cookie",
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
        "cookie_help": "cookie string",
        "cookie_file_help": "read cookie from file",
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


def _proxies():
    if PROXY:
        return {"http": PROXY, "https": PROXY}
    # 显式置 None，强制绕过系统/环境变量代理（否则开“梯子”时 requests 会走代理导致下载失败）
    return {"http": None, "https": None}


def http_get(url, params=None, headers=None, timeout=30):
    r = requests.get(url, params=params, headers=headers, timeout=timeout,
                     proxies=_proxies())
    return r.json()


# --------------------------------------------------------------------------- #
# Cookie 处理（自动尝试 URL 解码）
# --------------------------------------------------------------------------- #
def load_cookie(cookie_str: str, cookie_file: str) -> str:
    if cookie_str:
        return cookie_str.strip()
    if cookie_file:
        p = Path(cookie_file)
        if not p.exists():
            sys.exit(f"Cookie 文件不存在: {cookie_file}")
        return p.read_text(encoding="utf-8").strip()
    sys.exit("必须提供 Cookie：--cookie 或 --cookie-file")


def resolve_cookie(raw: str):
    """返回一个能通过登录校验的 Cookie 字符串（必要时做 URL 解码）。"""
    candidates = [raw]
    if "%" in raw:
        candidates.append(urllib.parse.unquote(raw))
    for c in candidates:
        try:
            j = http_get(API_NAV, headers={"Cookie": c, "User-Agent": UA,
                                           "Referer": "https://www.bilibili.com/"})
            if j.get("code") == 0 and (j.get("data") or {}).get("isLogin"):
                return c
        except Exception:
            continue
    return None


# --------------------------------------------------------------------------- #
# 主播 uid 解析
# --------------------------------------------------------------------------- #
def resolve_uid(room_id: int, headers) -> int:
    j = http_get(API_ROOM, params={"room_id": room_id}, headers=headers)
    if j.get("code") != 0:
        sys.exit(f"获取房间信息失败: {j}")
    data = j["data"]
    uid = data.get("uid")
    if not uid:
        sys.exit("无法解析房间 uid")
    log(f"房间 {room_id} -> 主播 uid={uid}（{data.get('title', '')}）")
    return uid


# --------------------------------------------------------------------------- #
# 回放列表
# --------------------------------------------------------------------------- #
def get_replay_list(uid: int, headers) -> list:
    all_replays = []
    page = 1
    while True:
        j = http_get(API_LIST, params={"live_uid": uid, "time_range": 3,
                                       "page": page, "page_size": 30}, headers=headers)
        if j.get("code") != 0:
            sys.exit(f"获取回放列表失败: code={j.get('code')} message={j.get('message')}")
        data = j.get("data") or {}
        ri = data.get("replay_info") or []
        all_replays.extend(ri)
        total = (data.get("pagination") or {}).get("total", 0)
        if len(all_replays) >= total or not ri:
            break
        page += 1
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
def get_slices(replay: dict, uid: int, headers) -> list:
    j = http_get(API_STREAM,
                 params={"live_key": replay["live_key"],
                         "start_time": replay["start_time"],
                         "end_time": replay["end_time"],
                         "live_uid": uid},
                 headers=headers)
    if j.get("code") != 0:
        return []
    data = j.get("data") or {}
    return {"list": data.get("list") or [], "ban_list": data.get("ban_list")}


# --------------------------------------------------------------------------- #
# 下载（aria2c 优先，Python 多线程兜底）
# --------------------------------------------------------------------------- #
ARIA2C_VERSION = "1.37.0"


def ensure_aria2c():
    """返回 aria2c 可执行路径；找不到则尝试自动下载，仍失败返回 None（交给多线程兜底）。"""
    p = shutil.which("aria2c")
    if p:
        return p
    is_win = sys.platform == "win32"
    exe = "aria2c.exe" if is_win else "aria2c"
    cache_bin = TOOLS_DIR / "aria2c"
    local = cache_bin / exe
    if local.exists():
        return str(local)
    # 自动下载（Windows 用官方包、macOS 用第三方静态包；Linux 建议用包管理器）
    if is_win or sys.platform == "darwin":
        info("未检测到 aria2c，尝试自动下载...")
        if _fetch_aria2c_binary(cache_bin) and local.exists():
            return str(local)
        warn("aria2c 自动下载失败，改用 Python 多线程下载")
    return None


def _fetch_aria2c_binary(cache_bin: Path) -> bool:
    """按平台自动下载 aria2c 到 cache_bin（Windows 官方包 / macOS 第三方静态包）。"""
    cache_bin.mkdir(parents=True, exist_ok=True)
    system = sys.platform
    machine = platform.machine().lower()
    try:
        if system == "win32":
            return _download_aria2c_windows(cache_bin)
        if system == "darwin":
            arch = "arm64" if machine in ("aarch64", "arm64") else "x86_64"
            url = (f"https://github.com/AEPKILL/aria2c-binary/releases/download/"
                   f"release-{ARIA2C_VERSION}/aria2-macos-{arch}.tar.gz")
            tarball = cache_bin / "aria2.tar.gz"
            if not _download_file(url, tarball):
                return False
            with tarfile.open(tarball, "r:gz") as tf:
                for m in tf.getmembers():
                    if m.isfile() and os.path.basename(m.name) == "aria2c":
                        src = tf.extractfile(m)
                        with open(cache_bin / "aria2c", "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        os.chmod(cache_bin / "aria2c", 0o755)
                        break
            tarball.unlink(missing_ok=True)
            return (cache_bin / "aria2c").exists()
    except Exception as e:
        warn(f"aria2c 自动下载失败: {e}")
    return False


def _download_aria2c_windows(cache_bin: Path) -> bool:
    url = (f"https://github.com/aria2/aria2/releases/download/"
           f"release-{ARIA2C_VERSION}/aria2-{ARIA2C_VERSION}-win-64bit-build1.zip")
    zf = cache_bin / "aria2.zip"
    cache_bin.mkdir(parents=True, exist_ok=True)
    if not _download_file(url, zf):
        return False
    try:
        with zipfile.ZipFile(zf) as z:
            for n in z.namelist():
                if os.path.basename(n) == "aria2c.exe":
                    with z.open(n) as src, open(cache_bin / "aria2c.exe", "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    break
    except Exception as e:
        warn(f"解压 aria2c 失败: {e}")
        return False
    finally:
        zf.unlink(missing_ok=True)
    return (cache_bin / "aria2c.exe").exists()


def _print_progress(done: int, total: int, speed: float, elapsed: float):
    pct = done * 100.0 / total if total else 0.0
    mm = int(elapsed) // 60
    ss = int(elapsed) % 60
    sys.stdout.write(f"\r  下载中 {done}/{total} ({pct:.1f}%)  "
                     f"{speed / 1048576:.1f} MB/s  耗时 {mm:02d}:{ss:02d}    ")
    sys.stdout.flush()


def _scan_dir(outdir: Path):
    segs = list(outdir.glob("seg_*.m4s"))
    return len(segs), sum(s.stat().st_size for s in segs)


def _download_aria2c(urls: list, outdir: Path, referer: str, aria2c: str) -> bool:
    inp = outdir / "aria_input.txt"
    with open(inp, "w", encoding="utf-8") as f:
        for i, u in enumerate(urls, 1):
            f.write(u + "\n")
            f.write(f"  out=seg_{i:05d}.m4s\n")
            f.write("\n")
    cmd = [aria2c, "-i", str(inp), "-d", str(outdir),
           "--auto-file-renaming=false", "--allow-overwrite=true",
           "--file-allocation=none", "--max-tries=5", "--retry-wait=2",
           "--timeout=30", "--connect-timeout=15",
           "-j", "64", "-x", "1", "-s", "1",
           "--console-log-level=warn", "--summary-interval=10",
           "--user-agent", UA, "--referer", referer]
    logfile = outdir / "aria2c.log"
    total = len(urls)
    with open(logfile, "w", encoding="utf-8") as f:
        p = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT)
    t0 = time.time()
    last_bytes = 0
    last_t = t0
    try:
        while p.poll() is None:
            done, cur_bytes = _scan_dir(outdir)
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
    done, _ = _scan_dir(outdir)
    _print_progress(done, total, 0.0, time.time() - t0)
    sys.stdout.write("\n")
    sys.stdout.flush()
    return p.returncode == 0


def _download_one(args):
    u, out, headers = args
    for _ in range(3):
        try:
            r = requests.get(u, headers=headers, timeout=60, proxies=_proxies())
            if r.status_code == 200:
                with open(out, "wb") as f:
                    f.write(r.content)
                return True
        except Exception:
            pass
    return False


def _download_py(urls: list, outdir: Path, headers) -> bool:
    tasks = []
    for i, u in enumerate(urls, 1):
        tasks.append((u, outdir / f"seg_{i:05d}.m4s", headers))
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
                    done, cur_bytes = _scan_dir(outdir)
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
    return ok == len(urls)


def download_segments(urls: list, outdir: Path, headers, referer: str) -> bool:
    outdir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    aria2c = ensure_aria2c()
    if aria2c:
        info(f"开始并行下载 {len(urls)} 个分片（aria2c）...")
        ok = _download_aria2c(urls, outdir, referer, aria2c)
    else:
        info("未检测到 aria2c，使用 Python 多线程下载（较慢）")
        ok = _download_py(urls, outdir, headers)
    n = len(list(outdir.glob("seg_*.m4s")))
    log(f"  下载完成 {n}/{len(urls)} 个分片，耗时 {time.time()-t0:.0f}s")
    return ok and n == len(urls)


# --------------------------------------------------------------------------- #
# 解析 m3u8
# --------------------------------------------------------------------------- #
def parse_m3u8(text: str):
    extinfs, urls = [], []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("http"):
            urls.append(s)
        elif s.startswith("#EXTINF"):
            extinfs.append(s)
    return extinfs, urls


def fetch_m3u8(url: str, headers) -> str:
    for _ in range(3):
        try:
            r = requests.get(url, headers=headers, timeout=90, proxies=_proxies())
            if r.status_code == 200 and "#EXT-X-ENDLIST" in r.text:
                return r.text
        except Exception:
            pass
    return ""


def build_local_m3u8(extinfs: list, subdir: Path) -> Path:
    lines = ["#EXTM3U", "#EXT-X-VERSION:7", "#EXT-X-TARGETDURATION:5",
             "#EXT-X-PLAYLIST-TYPE:VOD"]
    for i, ext in enumerate(extinfs, 1):
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

    跨平台：先查 PATH，再查本地缓存，最后按平台自动下载静态 ffmpeg。
    """
    env = {}
    is_win = sys.platform == "win32"
    exe = ".exe" if is_win else ""

    # 1) 系统 PATH
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg and ffprobe:
        return ffmpeg, ffprobe, env

    # 2) 本地缓存
    cache_bin = TOOLS_DIR / "ffmpeg" / "bin"
    cf = cache_bin / f"ffmpeg{exe}"
    cp = cache_bin / f"ffprobe{exe}"
    if cf.exists() and cp.exists():
        return str(cf), str(cp), env

    # 3) Linux 且是 Debian/Ubuntu：优先走 apt 源（国内镜像快，无需下载国外静态包）
    if sys.platform == "linux" and shutil.which("apt-get") and shutil.which("dpkg"):
        r = _try_apt_ffmpeg()
        if r:
            return r

    # 4) 按平台自动下载静态 ffmpeg
    info("未找到 ffmpeg，尝试自动下载到本地缓存...")
    if _download_static_ffmpeg(cache_bin) and cf.exists() and cp.exists():
        return str(cf), str(cp), env

    hints = {
        "linux": "sudo apt install ffmpeg",
        "darwin": "brew install ffmpeg",
        "win32": "winget install Gyan.FFmpeg",
    }
    sys.exit(f"ffmpeg 自动下载失败，请手动安装：{hints.get(sys.platform, '安装 ffmpeg 并加入 PATH')}")


def _try_apt_ffmpeg():
    """Debian/Ubuntu：从 apt 源下载 ffmpeg 到本地缓存。返回 (ffmpeg, ffprobe, env) 或 None。"""
    try:
        cache = TOOLS_DIR / "ffmpeg"
        bin_ffmpeg = cache / "root/usr/bin/ffmpeg"
        bin_ffprobe = cache / "root/usr/bin/ffprobe"
        libdir = cache / "root/usr/lib/x86_64-linux-gnu"
        if bin_ffmpeg.exists() and bin_ffprobe.exists():
            return str(bin_ffmpeg), str(bin_ffprobe), {"LD_LIBRARY_PATH": str(libdir)}
        cache.mkdir(parents=True, exist_ok=True)
        pkgs = ["ffmpeg", "libavdevice62", "libplacebo360", "libsdl2-2.0-0"]
        subprocess.run(["apt-get", "download"] + pkgs, cwd=cache, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for deb in cache.glob("*.deb"):
            subprocess.run(["dpkg", "-x", str(deb), str(cache / "root")], check=True,
                           stdout=subprocess.DEVNULL)
        if bin_ffmpeg.exists() and bin_ffprobe.exists():
            info("已通过 apt 源准备好 ffmpeg")
            return str(bin_ffmpeg), str(bin_ffprobe), {"LD_LIBRARY_PATH": str(libdir)}
    except Exception:
        pass
    return None


def _download_file(url: str, dest: Path) -> bool:
    """用 requests 下载单个文件（带简单进度显示）。"""
    try:
        r = requests.get(url, timeout=300, stream=True, proxies=_proxies())
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0)) or 0
        done = 0
        last_pct = -1
        t0 = time.time()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total > 0:
                    pct = done * 100 // total
                    if pct >= last_pct + 10:
                        last_pct = pct
                        speed = done / max(time.time() - t0, 0.1) / 1048576
                        info(f"下载 {dest.name}: {pct}%  {done/1048576:.1f}/{total/1048576:.1f} MB  {speed:.1f} MB/s")
        return True
    except Exception as e:
        warn(f"下载失败 {url}: {e}")
        return False


def _download_binary(url: str, dest: Path) -> bool:
    """下载单个二进制文件：优先 aria2c（多连接），失败自动回退 requests 单线程。"""
    aria2c = ensure_aria2c()
    if aria2c:
        dest.parent.mkdir(parents=True, exist_ok=True)
        # 依次尝试：4 连接 → 单连接+跳过证书校验（解决 Windows 下 aria2c 多连接/SSL 偶发失败）
        for extra in (["-x", "4", "-s", "4"], ["-x", "1", "--check-certificate=false"]):
            cmd = [aria2c, *extra, "-d", str(dest.parent), "-o", dest.name,
                   "--allow-overwrite=true", "--max-tries=3", "--timeout=30",
                   "--user-agent", UA, url]
            try:
                r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if r.returncode == 0 and dest.exists():
                    return True
            except Exception:
                pass
        warn("aria2c 下载该文件失败，已自动改用单线程下载（不影响运行，仅稍慢）")
    return _download_file(url, dest)


def _download_static_ffmpeg(cache_bin: Path) -> bool:
    """按平台下载静态 ffmpeg/ffprobe 到 cache_bin，成功返回 True。"""
    cache_bin.mkdir(parents=True, exist_ok=True)
    system = sys.platform
    machine = platform.machine().lower()
    tmp = cache_bin.parent
    try:
        if system == "linux":
            arch = "arm64" if machine in ("aarch64", "arm64") else "amd64"
            url = f"https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-{arch}-static.tar.xz"
            tarball = tmp / "ffmpeg.tar.xz"
            if not _download_binary(url, tarball):
                return False
            with tarfile.open(tarball, "r:xz") as tf:
                for m in tf.getmembers():
                    base = os.path.basename(m.name)
                    if base in ("ffmpeg", "ffprobe") and m.isfile():
                        src = tf.extractfile(m)
                        with open(cache_bin / base, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        os.chmod(cache_bin / base, 0o755)
            tarball.unlink(missing_ok=True)

        elif system == "darwin":
            for name in ("ffmpeg", "ffprobe"):
                url = f"https://evermeet.cx/ffmpeg/getrelease/{name}/zip"
                zf = tmp / f"{name}.zip"
                if not _download_binary(url, zf):
                    return False
                with zipfile.ZipFile(zf) as z:
                    with z.open(name) as src, open(cache_bin / name, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                zf.unlink(missing_ok=True)
                os.chmod(cache_bin / name, 0o755)

        elif system == "win32":
            url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
            zf = tmp / "ffmpeg.zip"
            if not _download_binary(url, zf):
                return False
            with zipfile.ZipFile(zf) as z:
                for n in z.namelist():
                    base = os.path.basename(n)
                    if base in ("ffmpeg.exe", "ffprobe.exe"):
                        with z.open(n) as src, open(cache_bin / base, "wb") as dst:
                            shutil.copyfileobj(src, dst)
            zf.unlink(missing_ok=True)

        else:
            return False
    except Exception as e:
        warn(f"ffmpeg 自动下载失败: {e}")
        return False
    return (cache_bin / ("ffmpeg.exe" if system == "win32" else "ffmpeg")).exists() and \
           (cache_bin / ("ffprobe.exe" if system == "win32" else "ffprobe")).exists()


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
def analyze_interruptions(replay, slices, uid, headers) -> list:
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
        j = http_get(API_SESSION,
                     params={"live_key": replay["live_key"],
                             "start_tm": fmt_ts(replay["start_time"]),
                             "end_tm": fmt_ts(replay["end_time"]),
                             "live_uid": uid},
                     headers=headers)
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
def process_replay(replay, uid, date_str, prefix, headers, referer,
                   ffmpeg, ffprobe, env,
                   outdir: Path, workdir: Path, part_seconds: int):
    log(f"\n{'=' * 60}")
    log(f"日期 {date_str} 回放  replay_id={replay['replay_id']}")
    log(f"  直播时间 {fmt_ts(replay['start_time'])} ~ {fmt_ts(replay['end_time'])}")

    slices = get_slices(replay, uid, headers)
    if not slices or not slices["list"]:
        warn("未获取到切片视频流（可能回放尚未合成完成），跳过")
        return False

    n_slice = len(slices["list"])
    if n_slice > 1:
        log(f"  [!] 检测到断流：回放被切成 {n_slice} 段")
    for i, s in enumerate(slices["list"]):
        log(f"    段{i+1}: {fmt_ts(s['start_time'], '%H:%M:%S')} ~ "
            f"{fmt_ts(s['end_time'], '%H:%M:%S')} "
            f"({(s['end_time'] - s['start_time']) // 60}分"
            f"{(s['end_time'] - s['start_time']) % 60}秒)")

    # 逐段下载 + 转封装
    slice_mp4s = []
    for i, s in enumerate(slices["list"]):
        subdir = workdir / f"slice{i}"
        subdir.mkdir(parents=True, exist_ok=True)
        m3u8_text = fetch_m3u8(s["stream"], headers)
        if not m3u8_text:
            warn(f"段{i+1} 的 m3u8 获取失败，跳过该段")
            continue
        extinfs, urls = parse_m3u8(m3u8_text)
        log(f"  段{i+1}: 共 {len(urls)} 个分片，开始下载...")
        if not download_segments(urls, subdir, headers, referer):
            warn(f"段{i+1} 下载不完整，跳过该段")
            continue
        local = build_local_m3u8(extinfs, subdir)
        out_mp4 = workdir / f"slice{i}.mp4"
        if not remux_to_mp4(ffmpeg, env, local, out_mp4):
            warn(f"段{i+1} 转封装失败")
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
        reasons = analyze_interruptions(replay, slices, uid, headers)
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
    ap.add_argument("--cookie", default="", help=S["cookie_help"])
    ap.add_argument("--cookie-file", default="", help=S["cookie_file_help"])
    ap.add_argument("--out-dir", default=".", help=S["out_dir_help"])
    ap.add_argument("--part-seconds", type=int, default=3600, help=S["part_seconds_help"])
    ap.add_argument("--live-uid", type=int, default=0, help=S["live_uid_help"])
    ap.add_argument("--keep-temp", action="store_true", help=S["keep_temp_help"])
    ap.add_argument("--recent", type=int, default=0, help=S["recent_help"])
    ap.add_argument("--proxy", default="", help=S["proxy_help"])
    args = ap.parse_args()

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

    # 校验日期格式
    for d in args.dates:
        try:
            datetime.strptime(d, "%Y-%m-%d")
        except ValueError:
            sys.exit(S["err_date"].format(d=d))

    outdir = Path(args.out_dir).expanduser()
    outdir.mkdir(parents=True, exist_ok=True)

    # Cookie
    raw_cookie = load_cookie(args.cookie, args.cookie_file)
    cookie = resolve_cookie(raw_cookie)
    if not cookie:
        sys.exit("登录校验失败：Cookie 无效或已过期，请重新提供")
    log("登录成功 ✅")
    referer = f"https://live.bilibili.com/{args.room_id}"
    headers = {"Cookie": cookie, "User-Agent": UA, "Referer": referer}

    # uid
    uid = args.live_uid or resolve_uid(args.room_id, headers)

    # 回放列表
    log("获取回放列表...")
    replays = get_replay_list(uid, headers)

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
        return

    # ffmpeg
    ffmpeg, ffprobe, env = ensure_ffmpeg()

    # 临时工作目录（放在系统磁盘，避免占用 /tmp 的 tmpfs）
    workdir = WORK_DIR
    workdir.mkdir(parents=True, exist_ok=True)

    t_start = time.time()
    success_count = 0
    total_video_sec = 0
    for r, d, prefix in to_process:
        day_work = workdir / prefix
        if day_work.exists():
            shutil.rmtree(day_work)
        day_work.mkdir(parents=True, exist_ok=True)
        ok = process_replay(r, uid, d, prefix, headers, referer, ffmpeg, ffprobe, env,
                            outdir, day_work, args.part_seconds)
        if not args.keep_temp:
            shutil.rmtree(day_work, ignore_errors=True)
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
