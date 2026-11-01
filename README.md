# AI_Video_cases

收集用 WorkBuddy 内置模型（ImageGen / VideoGen）完成的 AI 视频案例与可复用经验。

所有产出均只消耗 WorkBuddy 积分，不依赖任何第三方生图/生视频服务（如 Pollinations、LibTV 等）。

---

## 案例一：玻璃之后（glass_after）

一个「真实摄影女主」风格的都市纪实短片，25 秒 / 18 镜 / 1080p。

### 工作流（端到端）

1. **写脚本**：`玻璃之后_视频脚本提示词.html` — 18 镜分镜表（画面、运动、时长、色调、BGM）。
2. **首帧生图**：WorkBuddy `ImageGen`，每个镜头一张 1280×720 首帧，`frames/shotNN.png`。
3. **图生视频**：WorkBuddy `VideoGen`（`image=首帧, enable_audio=false, seconds=5`），`videos/shotNN.mp4`。
4. **拼装**：`make_final.py`（ffmpeg）按分镜时长逐段 trim → concat 硬切 → 叠雨声底噪 → 混音输出 `玻璃之后_成片.mp4`。

### 关键经验（踩过的坑）

- **面部干净感**：在「真实摄影 / 纪实」取向里，**不要写** `visible freckles` / `fine skin pores` / `real skin texture` / `no beauty retouch`，否则脸会被画成灰浊、油高光、颗粒叠满。改用固定词块：
  > `CLEAN BEAUTY face - flawless porcelain fair skin, perfectly even tone, matte finish with zero oily sheen, no freckles, no blemishes, no dirt, no blotchy patches, refined delicate features, sculpted nose bridge, neatly shaped straight brows, natural dusty-rose lips, glossy black hair smooth and softly wavy, clean luminous complexion` + `clean image, no CGI`
  `ImageGen` 没有 `negative_prompt` 参数，负面词只能写进正向 prompt；`VideoGen` 有 `negative_prompt` 但写进 prompt 末尾同样生效。

- **ImageGen 并行出图**：并行多张时即使传不同的 `output_dir`，工具也会把它们合并到同一目录，文件名只按 prompt 前缀派生。**做法**：并行 3 张最稳，每张 prompt 用不同的前置词（如 `Window profile:` / `Eye macro:` / `Night portrait:`）保证前缀不撞车；生成后按返回的 `localPath` 精确 `mv` 到 `shotNN.png`，不要靠文件名猜。

- **VideoGen 图生视频**：`aspect_ratio` 参数对图生视频**无效**（画幅由输入首帧决定），传了会直接报错，去掉即可。图生视频稳定输出 ~5.04s / 1920×1080 / 24fps / 无音轨。

- **本地拼装**：用 `imageio-ffmpeg` 自带的 ffmpeg 即可，无需系统安装 ffmpeg；Windows 下 venv 用 Python 3.13（3.14 的 numpy 轮子不兼容）。

### 目录结构

```
glass_after/
├── 玻璃之后_视频脚本提示词.html   # 分镜脚本
├── make_final.py                  # ffmpeg 拼装+混音脚本（可复现）
├── frames/shot01–18.png          # WorkBuddy 首帧
├── videos/shot01–18.mp4          # WorkBuddy 图生视频原片
├── 玻璃之后_成片.mp4              # 成品（25s / 1080p）
├── contact_sheet.png             # 18 镜首帧总览
└── 面部优化_7镜首帧.png          # 面部优化后 7 镜对比
```

### 复现

```bash
# 1) 首帧（WorkBuddy ImageGen，见脚本每镜 prompt + CLEAN BEAUTY 词块）→ frames/shotNN.png
# 2) 图生视频（WorkBuddy VideoGen, image=首帧, enable_audio=false, seconds=5）→ videos/shotNN.mp4
# 3) 拼装
python make_final.py
# 产出 玻璃之后_成片.mp4
```

> 注：`frames/shotNN.png` 与 `videos/shotNN.mp4` 为 WorkBuddy 生成资产，体积较大，已用 Git LFS 托管（见 `.gitattributes`）。
