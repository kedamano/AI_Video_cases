# -*- coding: utf-8 -*-
"""案例6《海风来信》成片拼装脚本。
按分镜时长 trim + concat，镜头13用首帧 Ken Burns 补位，叠加海浪环境音。
用法: python make_final6.py
"""
import os
import shutil
import subprocess
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))


def get_ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        path = shutil.which("ffmpeg")
        if path:
            return path
        raise RuntimeError("未找到 ffmpeg，请 pip install imageio-ffmpeg 或安装 ffmpeg")

# 分镜时长（秒），与分镜脚本一致，总长 22s
DURATIONS = [4, 2, 1, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
FPS = 24
W, H = 1920, 1080


def run(cmd):
    print(">>", " ".join(cmd[:8]), "...")
    subprocess.run(cmd, check=True, capture_output=True)


def main():
    ffmpeg = get_ffmpeg()
    tmp = tempfile.mkdtemp(prefix="case6_")
    parts = []

    for i, dur in enumerate(DURATIONS, start=1):
        n = f"{i:02d}"
        out = os.path.join(tmp, f"part{n}.mp4")
        vid = os.path.join(BASE, "videos", f"shot{n}.mp4")
        img = os.path.join(BASE, "frames", f"shot{n}.png")
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
              f"crop={W}:{H},setsar=1,fps={FPS},format=yuv420p")
        if os.path.exists(vid):
            # trim 到目标时长（生成片段约 5s，按分镜取前 dur 秒）
            run([ffmpeg, "-y", "-i", vid, "-t", str(dur),
                 "-vf", vf, "-an", "-c:v", "libx264", "-preset", "medium",
                 "-crf", "18", out])
        else:
            # 镜头13补位：首帧 Ken Burns 缓推
            vf_kb = (f"scale={W * 2}:{H * 2},"
                     f"zoompan=z='min(zoom+0.0008,1.12)':d={dur * FPS}:"
                     f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS},"
                     f"setsar=1,format=yuv420p")
            run([ffmpeg, "-y", "-loop", "1", "-i", img, "-t", str(dur),
                 "-vf", vf_kb, "-c:v", "libx264", "-preset", "medium",
                 "-crf", "18", out])
        parts.append(out)

    # concat 清单
    lst = os.path.join(tmp, "list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for p in parts:
            f.write(f"file '{p}'\n")

    silent = os.path.join(tmp, "silent.mp4")
    run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", lst,
         "-c", "copy", silent])

    # 环境音：海浪棕噪（低通）+ 轻柔正弦 pad，淡入淡出
    total = sum(DURATIONS)
    final = os.path.join(BASE, "海风来信_成片.mp4")
    af = (
        f"anoisesrc=color=brown:amplitude=0.35:duration={total},"
        f"lowpass=f=600,volume=0.55[nz];"
        f"sine=frequency=220:duration={total},volume=0.05[s1];"
        f"sine=frequency=329.63:duration={total},volume=0.04[s2];"
        f"[nz][s1][s2]amix=inputs=3:normalize=0,"
        f"afade=t=in:d=2,afade=t=out:st={total - 3}:d=3[a]"
    )
    run([ffmpeg, "-y", "-i", silent, "-filter_complex", af,
         "-map", "0:v", "-map", "[a]", "-c:v", "copy",
         "-c:a", "aac", "-b:a", "128k", "-shortest", final])

    print("DONE:", final, f"{total}s")


if __name__ == "__main__":
    main()
