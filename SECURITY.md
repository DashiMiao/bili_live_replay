# 安全策略

## 报告漏洞

请不要在公开 issue 中粘贴以下内容：

- Cookie、`SESSDATA`、`bili_jct`、`DedeUserID`
- 带签名的 CDN URL
- 完整的 API 响应或日志
- 可复现的账号接管步骤

请先撤销相关凭据（退出所有设备 / 修改密码），再通过 GitHub Security Advisory 或私下联系维护者。

## 凭据泄露应急流程

如果 `cookie.txt`、`.env` 或任何 Cookie 被提交到 git：

1. **先撤销凭据**：B 站 App/网页 → 账号安全 → 退出所有设备；修改密码。
2. 检查登录设备、绑定手机/邮箱、第三方授权和近期异常操作。
3. 再清理历史：
   ```bash
   git filter-repo --path cookie.txt --invert-paths --force
   git push --force --all
   git push --force --tags
   ```
   删除文件本身不够；旧提交仍然可以 `git show` 出来。
4. GitHub 可能缓存旧提交，必要时联系 GitHub Support；fork/clone 仍可能保留旧内容。
5. **撤销凭据永远优先于清理历史**，不要指望删历史让已泄露的 Cookie 失效。
6. CI 目前对已知历史提交 `a9fd6ad367a252edac4ad9134c24014588484268` 做了临时 Gitleaks 放行；它不会让 Cookie 失效，清理历史后必须删除 `.gitleaks.toml` 中的该 `commits` 项。

## 本仓库的凭据规则

- 只使用 `--cookie-file`（`chmod 600`）或 `--cookie-stdin`；`--cookie` 已废弃。
- 程序只提取 `SESSDATA`，不会把 `bili_jct` 等其它 Cookie 发给第三方。
- `cookie.txt`、`*.cookie`、`.env` 已在 `.gitignore` 中。
- 仓库包含 Gitleaks 配置和 pre-commit hook；请在 GitHub 仓库设置中开启 Secret scanning + Push protection。
- 不要以 root/sudo 运行本工具；不要从用户/组可写目录执行 ffmpeg/aria2c。

## 工具下载

- 自动下载只使用固定版本 + 固定 SHA256，校验失败不会执行。
- 下载只允许 HTTPS 和清单中的官方域名。
- 系统包管理器安装的 ffmpeg/aria2c 优先；macOS 不自动下载 ffmpeg，请用 Homebrew。

## 自动更新的信任边界

- 版本检查只访问固定的 `https://registry.npmjs.org`，不带 Cookie。
- 自动更新会校验 npm 平台包的 `dist.integrity`（SHA512）和包内 `SHA256SUMS`，校验失败不会替换当前程序。
- 源码更新只允许在 git 仓库干净时执行 `git pull --ff-only`，不会强拉或覆盖本地修改。
- Windows 单文件版无法覆盖正在运行的 exe，因此只下载并校验新文件，通常需要关闭程序后手动替换；npm 安装版使用 `npm install -g ... --ignore-scripts`。
- 默认强制在线检查：无法访问 npm registry 时直接拒绝运行。确需离线排障可设置 `BILI_ALLOW_OFFLINE=1`，但会使用缓存、可能继续使用旧版本，风险自负。
- 自动更新信任 npm registry 和 npm 发布账号。对供应链安全要求最高的环境，建议固定版本或使用系统包管理器。

