# -*- coding: utf-8 -*-
"""《玻璃之后》合成：Ken Burns 推镜 -> 拼接 -> 环境音 -> mp4"""
import os, sys, subprocess

BASE = os.path.dirname(os.path.abspath(__file__))
FRAMES = os.path.join(BASE, "frames")
TMP = os.path.join(BASE, "tmp")
os.makedirs(TMP, exist_ok=True)
FF = r"C:\Users\lcl13\.workbuddy\binaries\python\envs\video\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"

FPS = 24
W, H = 1280, 720

# 与脚本一致：镜号 + 时长(秒)
SHOTS = [(1,2.0),(2,1.0),(3,2.0),(4,1.0),(5,1.0),(6,2.0),(7,1.0),(8,1.0),(9,2.0),
         (10,1.0),(11,1.0),(12,2.0),(13,1.0),(14,1.0),(15,2.0),(16,1.0),(17,1.0),(18,2.0)]

def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        print("FFMPEG ERROR:", " ".join(cmd)[:260])
        print((p.stderr or "")[-1000:])
        raise SystemExit(1)

def clip(idx, dur):
    src = os.path.join(FRAMES, "shot%02d.jpg" % idx)
    if not os.path.exists(src):
        return None
    out = os.path.join(TMP, "c%02d.mp4" % idx)
    n = max(1, int(round(dur * FPS)))
    # 缓慢推近 + 居中；zoom 从 1 到 1.14
    vf = ("scale=%d:%d," % (W, H)
          + "zoompan=z='min(zoom+0.0016,1.14)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            ":d=%d:s=%dx%d:fps=%d," % (n, W, H, FPS)
          + "format=yuv420p")
    run([FF, "-y", "-loop", "1", "-i", src, "-t", str(dur), "-vf", vf,
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-an", out])
    return out

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "preview"
    clips, missing, total = [], [], 0.0
    for idx, dur in SHOTS:
        c = clip(idx, dur)
        if c:
            clips.append(c); total += dur
        else:
            missing.append(idx)
    print("clips=%d missing=%s total=%.1fs" % (len(clips), missing, total))
    if not clips:
        print("NO_CLIPS"); return

    lst = os.path.join(TMP, "list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for c in clips:
            f.write("file '%s'\n" % c.replace("\\", "/"))

    out = (os.path.join(BASE, "preview_%dshots.mp4" % len(clips)) if mode == "preview"
           else os.path.join(BASE, "玻璃之后_成片.mp4"))

    run([FF, "-y", "-f", "concat", "-safe", "0", "-i", lst,
         "-f", "lavfi", "-i", "anoisesrc=color=brown:amplitude=0.05:duration=%.2f" % total,
         "-f", "lavfi", "-i", "sine=frequency=98:duration=%.2f" % total,
         "-filter_complex",
         "[1:a]lowpass=1400,volume=0.5[rain];[2:a]volume=0.04[pad];"
         "[rain][pad]amix=inputs=2:duration=first,afade=t=in:st=0:d=1.5,"
         "afade=t=out:st=%.2f:d=2[aout]" % max(0.0, total - 2),
         "-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac",
         "-b:a", "128k", "-shortest", out])
    print("OUTPUT", out, os.path.getsize(out))

main()
