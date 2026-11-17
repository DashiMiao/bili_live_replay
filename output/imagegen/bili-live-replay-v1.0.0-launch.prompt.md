# bili_live_replay v1.0.0 宣传图

生成方式：内置 imagegen。

输出：`bili-live-replay-v1.0.0-launch.png`

参考图：用户提供的两张终端截图，以及 DashiLIVE 项目中的原始 `client/src/assets/logo.svg`（栅格化后作为 logo 参考）。

## 最终生成提示词

```text
Use case: ads-marketing
Asset type: a polished minimal wide landscape launch announcement image for the command-line project bili_live_replay. Output a crisp high-resolution raster, approximately 3072×1280, wide 2.4:1 composition.

Reference images and roles:
1. /tmp/codex-clipboard-b49fcd86-95a9-4f5f-8b34-b92b053c7afa.png — COLOR AND TYPE reference. Match this image's warm ivory/light cream terminal text on colored prompt segments, and charcoal background. Do not use black text.
2. /tmp/codex-clipboard-e9f51611-53de-4b30-a544-b3f7cfecb9b7.png — STRUCTURE reference only: fully expanded Powerline prompt with joined right-pointing chevron segments. Replace all original content with the exact specified content below.
3. /tmp/dashilive-logo-reference.png — the authentic DashiLIVE brand mark, an elegant outlined cat integrated into a serif M. Faithfully reproduce its recognizable silhouette as a small monochrome warm ivory icon in the first prompt segment. Remove its white reference background. Do not use the Ubuntu logo.

Scene/backdrop: near-black charcoal #17191c, clean flat color. One large elegant front-facing terminal window centered in generous empty space. Window body #1d1f21, thin subtle grey border, softly rounded corners, restrained shadow. A modest title bar with three tiny muted dots at upper left; optional tiny centered title "bili_live_replay" in muted grey. Professional developer-tool launch aesthetic, sharp clean UI graphic, no photography, no perspective, no 3D.

Composition: The actual terminal content is the hero, large and comfortably readable. There are exactly TWO content sections: a fully expanded five-part prompt strip, then two command lines underneath. Keep balanced horizontal margins. The prompt and both command lines align left within the terminal. Keep the entire long second command on ONE line, without wrapping, using a slightly smaller consistent monospace font for BOTH command lines if needed. All content must fit within the canvas with room at the right. Very clean whitespace above and below.

Prompt strip: exactly FIVE connected Powerline segments, warm ivory #fff2cd medium-bold monospace text throughout, rounded cap on far left and right-pointing chevron separators, final right end rounded. From left to right:
1. burnt orange #df6400 background: the faithful DashiLIVE M/cat logo icon followed by exact lowercase text "dashimiao"
2. mustard yellow #d49a17 background: exact lowercase text "dashilive"
3. muted leaf green #699e6e background: exact text "bili_live_replay"
4. desaturated teal #4b8588 background: exact text "v1.0.0"
5. warm dark grey #45413d background: a tiny soft green live-status dot followed by exact text "live now!!!"
Keep the strip continuous, no gaps. All 5 segments clearly visible and horizontally expanded. Text in these segments must be light warm ivory, never black, exactly as reference 1.

Command input section: exactly two lines of crisp warm off-white monospace text. A small red-orange right arrow in the separate left gutter precedes each line; the arrows are not part of the command text. Both lines use the same clear type size and comfortable line spacing. End of second line has a small solid ivory block cursor with a little breathing room.
Line 1 (verbatim):
npm install -g @miaodashi/bili_live_replay
Line 2 (verbatim, one physical line):
bili_live_replay --room-id 9308312 --cookie-file '/home/desktop/cookie.txt' --out-dir '\~/下载' --recent 1

Text accuracy: Preserve all underscores, slashes, hyphens, the @ symbol, double-hyphen flags, straight ASCII single quotes, Chinese characters 下载, and the ONE literal backslash directly before the tilde in '\~/下载'. Room ID must be 9308312. The name in orange is dashimiao; the npm scope in line 1 is @miaodashi. Version is v1.0.0. End status has exactly three exclamation marks. Do not reproduce any old usernames, paths, branch names, timestamps, or Python version from the reference images.

Constraints: minimal, refined, calm, excellent legibility, authentic terminal feel, no clutter, no mascots other than the provided small logo, no gradients, no neon glow, no extra slogans, no QR code, no watermark, no extra command-output lines. The colored Powerline strip and exact two-line commands are the entire focus.
```

