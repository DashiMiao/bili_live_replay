# 输出目录反斜杠修正版

生成方式：内置 imagegen 编辑。

输出：`bili-live-replay-v1.0.0-launch-v4.png`

## 最终编辑提示词

```text
Use case: text-localization / precise-object-edit.
Edit the supplied terminal launch graphic with exactly ONE tiny text correction. On the second command line, change the output-directory argument from:
--out-dir '\~/下载'
to:
--out-dir '~/下载'

Remove the single backslash character immediately before the tilde. Keep the tilde, forward slash, Chinese characters 下载, and surrounding straight single quotation marks. The resulting argument must read EXACTLY --out-dir '~/下载' with NO backslash anywhere in that argument. Close the removed character's space naturally and let the trailing " --recent 1" and cursor shift left by one character width.

The exact corrected second command, preserved as one physical line, is:
bili_live_replay --room-id 9308312 --cookie-file '/home/desktop/cookie.txt' --out-dir '~/下载' --recent 1

Preserve everything else in the input image: full wide canvas, backdrop, terminal window, header, title and dots, compact five-segment prompt strip with its current scale, placement, colors and spacing, small DashiLIVE cat/M logo and tight gap to dashimiao, all fonts and font sizes, the first install command, arrows, and all other text. No resizing, re-layout, embellishment or added text. This is only deletion of one unwanted backslash character.
```

