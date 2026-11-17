# 提示符缩小与 logo 间距调整版

生成方式：内置 imagegen 编辑。

输出：`bili-live-replay-v1.0.0-launch-v3.png`

## 最终编辑提示词

```text
Use case: precise-object-edit.
Edit the supplied wide terminal launch graphic. Make only these two related layout adjustments to the colored five-segment Powerline prompt strip:
1. Uniformly scale the ENTIRE colored prompt strip to 80% of its present size in BOTH width and height. Scale all five segment backgrounds, all lettering, logo, status dot, chevrons, end caps, and internal paddings together by the SAME factor; do not simply shrink the font or compress the shapes. The original strip spans approximately x=77 to1836 and y=298 to370 in this 1944×809 reference. After scaling it should be approximately 1407 px wide and 58 px tall, anchored at the SAME LEFT EDGE x=77, with its vertical center still around y=334. Its right end should end around x=1484, leaving a generous empty area to the right inside the terminal. It MUST be visibly shorter and smaller than the current strip, occupying only about three quarters of the terminal's inner width, NOT stretching across the entire window. Do not center the strip horizontally.
2. Within the first orange segment, further reduce the gap between the DashiLIVE M/cat logo and the word "dashimiao": make the final visible horizontal gap only about 10–12 pixels. The current gap is too large. Shift the username left toward the icon; shorten that orange segment and shift the following joined segments left by the removed gap as appropriate. Preserve the logo design and warm ivory color. This spacing adjustment is in addition to the overall uniform 80% scaling.

Keep the exact five labels unchanged and readable: "dashimiao", "dashilive", "bili_live_replay", "v1.0.0", "live now!!!". Keep the original orange, yellow, green, teal and grey colors and ivory text.

All content OUTSIDE the colored prompt strip must stay unchanged, particularly both command lines: their existing text, type size, positions, arrows and block cursor. Preserve the whole dark background, terminal window size and position, header bar, title, three dots, border and canvas aspect ratio. Reconstruct plain dark terminal background wherever the previously larger strip used to be. Do NOT scale the terminal window or the entire image. Do NOT change or retype any command text. Do NOT add any objects or extra text.

The only intended visual difference is a more compact, proportionately smaller left-aligned prompt strip, and a tighter logo-to-name gap.
```

