# -*- coding: utf-8 -*-
"""案例 05 · 阿马尔菲柠檬海岸 —— 43 秒成片拼装

一条命令出片：
    python make_final.py

管线：
  frames/shot01-24.png  WorkBuddy ImageGen 首帧（24 镜；仓库存档为压缩 jpg，脚本两者都认）
  videos/shotNN.mp4     WorkBuddy VideoGen 图生视频（14 个动态镜头）
  其余 10 镜为脚本标注的「固定机位」，用首帧 Ken Burns 微动补足，
  make_final.py 会自动识别 videos/ 下缺哪些镜号。

依赖：ffmpeg（优先 imageio-ffmpeg，回退系统 PATH）、Pillow、numpy。
输出：阿马尔菲海岸_成片.mp4、contact_sheet.png、clips_tmp/（中间产物）
"""
import os
import sys
import shutil
import subprocess
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.abspath(__file__))
FRAMES = os.path.join(BASE, "frames")
VIDEOS = os.path.join(BASE, "videos")
TMP = os.path.join(BASE, "clips_tmp")
os.makedirs(TMP, exist_ok=True)

W, H, FPS = 1280, 720, 24
FINAL = os.path.join(BASE, "阿马尔菲海岸_成片.mp4")
WATERMARK = os.path.join(TMP, "watermark.png")
BGM = os.path.join(TMP, "bgm.wav")

# 分镜表逐镜时长（秒），合计 43 秒
DUR = [1, 2, 2, 2, 2, 2, 2, 1, 2, 1, 2, 2, 2, 2, 2, 1, 1, 1, 2, 3, 2, 2, 2, 2]
TOTAL = sum(DUR)
assert TOTAL == 43, TOTAL

# 固定机位镜头的 Ken Burns 运动方式：in=缓慢推近 / up=缓慢上移 / left=缓慢左移
MOTION = {
    10: "in", 12: "in", 13: "left", 15: "in", 16: "in",
    18: "in", 19: "left", 20: "up", 21: "in", 22: "up",
}


def find_ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    p = shutil.which("ffmpeg")
    if not p:
        sys.exit("ffmpeg 未找到：pip install imageio-ffmpeg，或把 ffmpeg 加入 PATH")
    return p


FF = find_ffmpeg()


def run(args, label):
    p = subprocess.run(args, capture_output=True, text=True)
    if p.returncode != 0:
        print("ERR", label, ":\n", p.stderr[-1500:])
        sys.exit(1)


def make_watermark():
    """脚本固定要素：抖音 ID 常驻左下角，半透明白字。"""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font_path = "C:/Windows/Fonts/msyh.ttc"
    if not os.path.exists(font_path):
        font_path = "C:/Windows/Fonts/simhei.ttf"
    font = ImageFont.truetype(font_path, 25) if os.path.exists(font_path) else ImageFont.load_default()
    x, y = 38, H - 96
    for text, yy in (("抖音号：203388120", y), ("Q swing_窝", y + 36)):
        d.text((x + 2, yy + 2), text, font=font, fill=(0, 0, 0, 90))
        d.text((x, yy), text, font=font, fill=(255, 255, 255, 205))
    img.save(WATERMARK)


def make_bgm():
    """轻柔钢琴 + 和弦垫 + 极轻海浪底噪；节奏前疏、中密、末段渐缓淡出。"""
    sr = 44100
    n = int(sr * TOTAL)
    t = np.arange(n) / sr
    audio = np.zeros(n, dtype=np.float64)

    def add(freq, start, dur, amp, piano=True):
        i0 = int(start * sr)
        m = int(dur * sr)
        if i0 >= n:
            return
        tt = np.arange(m) / sr
        if piano:
            env = np.exp(-tt * 6.5) * (1 - np.exp(-tt * 350))
            tone = (np.sin(2 * np.pi * freq * tt)
                    + 0.34 * np.sin(2 * np.pi * 2 * freq * tt)
                    + 0.11 * np.sin(2 * np.pi * 3 * freq * tt))
        else:
            env = np.exp(-tt * 0.8) * (1 - np.exp(-tt * 18))
            tone = np.sin(2 * np.pi * freq * tt) + 0.22 * np.sin(2 * np.pi * 2 * freq * tt)
        seg = amp * env * tone
        end = min(n, i0 + m)
        audio[i0:end] += seg[:end - i0]

    # 和弦垫：C - Am - F - G 循环，每 2 秒一换
    chords = [
        (261.63, 329.63, 392.00),
        (220.00, 261.63, 329.63),
        (174.61, 220.00, 261.63),
        (196.00, 246.94, 293.66),
    ]
    for k, start in enumerate(np.arange(0, TOTAL, 2.0)):
        for f in chords[k % 4]:
            add(f, float(start), 2.2, 0.030, piano=False)

    # 旋律：C 大调五声音阶，按段变速（脚本里的「节奏加快 → 渐缓 → 淡出」）
    scale = [523.25, 587.33, 659.25, 783.99, 880.00, 1046.50,
             783.99, 659.25, 587.33, 523.25, 659.25, 880.00]
    rng = np.random.default_rng(5)
    pos, idx = 0.0, 0
    while pos < TOTAL - 1.0:
        if pos < 5:
            step = 0.75
        elif pos < 11:
            step = 0.45
        elif pos < 30:
            step = 0.375
        else:
            step = 0.55 + (pos - 30) / 13 * 0.35
        f = scale[idx % len(scale)]
        amp = 0.085 if pos < 30 else 0.085 * max(0.25, 1 - (pos - 30) / 14)
        add(f, pos, 0.46, amp)
        if idx % 4 == 2 and pos < 30:
            add(f / 2, pos, 0.55, 0.028, piano=False)
        idx += 1
        pos += step + float(rng.uniform(-0.02, 0.02))

    # 海浪底噪（FFT 低通白噪 + 缓慢起伏）
    noise = rng.normal(0, 1, n)
    spec = np.fft.rfft(noise)
    freqs = np.fft.rfftfreq(n, 1 / sr)
    spec *= 1.0 / (1.0 + (freqs / 260.0) ** 2)
    noise = np.fft.irfft(spec, n)
    noise /= max(1e-9, np.max(np.abs(noise)))
    audio += 0.014 * noise * (0.6 + 0.4 * np.sin(2 * np.pi * 0.18 * t))

    audio *= np.clip(t / 1.5, 0, 1) * np.clip((TOTAL - t) / 3.0, 0, 1)
    peak = max(1e-9, float(np.max(np.abs(audio))))
    audio = audio / peak * 0.82
    pcm = (audio * 32767).astype(np.int16)
    stereo = np.repeat(pcm[:, None], 2, axis=1)
    with wave.open(BGM, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(stereo.tobytes())


def frame_path(i):
    """仓库里首帧以压缩 jpg 存档，本地原始 png 优先。"""
    for ext in (".png", ".jpg"):
        p = os.path.join(FRAMES, "shot%02d%s" % (i, ext))
        if os.path.exists(p):
            return p
    return os.path.join(FRAMES, "shot%02d.png" % i)


def make_contact_sheet():
    """24 镜首帧总览，审片用。"""
    cols, rows, cw, ch = 6, 4, 240, 135
    sheet = Image.new("RGB", (cols * cw, rows * (ch + 22)), (248, 248, 248))
    d = ImageDraw.Draw(sheet)
    for i in range(1, 25):
        src = frame_path(i)
        if not os.path.exists(src):
            continue
        im = Image.open(src).convert("RGB")
        iw, ih = im.size
        im = im.crop((0, (ih - iw * 9 / 16) / 2, iw, (ih + iw * 9 / 16) / 2)).resize((cw, ch))
        x, y = ((i - 1) % cols) * cw, ((i - 1) // cols) * (ch + 22)
        sheet.paste(im, (x, y))
        d.text((x + 6, y + ch + 3), "shot %02d  %ds" % (i, DUR[i - 1]), fill=(30, 30, 30))
    sheet.save(os.path.join(BASE, "contact_sheet.png"))


def zoom_expr(mode, frames):
    if mode == "up":
        return ("z='1.14':x='iw/2-(iw/zoom/2)':"
                "y='(ih-ih/zoom)*(1-on/%d)'" % frames)
    if mode == "left":
        return ("z='1.14':x='(iw-iw/zoom)*on/%d':"
                "y='ih/2-(ih/zoom/2)'" % frames)
    return ("z='min(zoom+0.0016,1.18)':x='iw/2-(iw/zoom/2)':"
            "y='ih/2-(ih/zoom/2)'")


def build_clips():
    clips = []
    grade = "eq=saturation=1.10:contrast=1.03:brightness=0.01"
    for i, d in enumerate(DUR, 1):
        out = os.path.join(TMP, "clip%02d.mp4" % i)
        vpath = os.path.join(VIDEOS, "shot%02d.mp4" % i)
        fpath = frame_path(i)
        # 统一裁成 16:9，同时裁掉生图右下角的模型水印
        crop = "crop=iw:iw*9/16:0:(ih-iw*9/16)/2"
        tail = ""
        if i == 1:
            tail = ",fade=t=in:st=0:d=0.4"
        if i == len(DUR):
            tail += ",fade=t=out:st=%.2f:d=0.6" % (d - 0.6)

        if os.path.exists(vpath):
            vf = "%s,scale=%d:%d,%s,fps=%d,format=yuv420p%s" % (crop, W, H, grade, FPS, tail)
            cmd = [FF, "-y", "-i", vpath, "-t", str(d), "-vf", vf, "-an",
                   "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-r", str(FPS), out]
            kind = "VideoGen"
        elif os.path.exists(fpath):
            mode = MOTION.get(i, "in")
            zp = "zoompan=%s:d=1:s=%dx%d:fps=%d" % (zoom_expr(mode, int(d * FPS)), W, H, FPS)
            vf = "%s,scale=1600:900,%s,%s,format=yuv420p%s" % (crop, zp, grade, tail)
            cmd = [FF, "-y", "-loop", "1", "-framerate", str(FPS), "-i", fpath,
                   "-t", str(d), "-vf", vf, "-an",
                   "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-r", str(FPS), out]
            kind = "KenBurns:" + mode
        else:
            sys.exit("缺少第 %02d 镜素材（frames/videos 都没有）" % i)

        run(cmd, "clip%02d" % i)
        clips.append(out)
        print("clip%02d  %-16s %ss  ok" % (i, kind, d))
    return clips


def main():
    print("总时长 %ds / %d 镜 / %dx%d / %dfps" % (TOTAL, len(DUR), W, H, FPS))
    make_watermark()
    make_bgm()
    make_contact_sheet()
    clips = build_clips()

    lst = os.path.join(TMP, "list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for c in clips:
            f.write("file '%s'\n" % c.replace("\\", "/"))

    cmd = [FF, "-y", "-f", "concat", "-safe", "0", "-i", lst,
           "-loop", "1", "-i", WATERMARK, "-i", BGM,
           "-filter_complex", "[0:v][1:v]overlay=0:0:shortest=1[v]",
           "-map", "[v]", "-map", "2:a",
           "-c:v", "libx264", "-preset", "medium", "-crf", "20",
           "-c:a", "aac", "-b:a", "192k", "-shortest",
           "-movflags", "+faststart", FINAL]
    run(cmd, "final")
    print("FINAL:", FINAL)


if __name__ == "__main__":
    main()
