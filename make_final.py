import subprocess, os, sys

FF = r"C:\Users\lcl13\.workbuddy\binaries\python\envs\video\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"
BASE = r"D:/work/AI TEST/glass_after"
VID = os.path.join(BASE, "videos")
TMP = os.path.join(BASE, "clips_tmp")
os.makedirs(TMP, exist_ok=True)

# scripted durations per shot (seconds) -> total 25s
DUR = [2, 1, 2, 1, 1, 2, 1, 1, 2, 1, 1, 2, 1, 1, 2, 1, 1, 2]
TOTAL = sum(DUR)
print("total seconds:", TOTAL)


def run(args, label):
    p = subprocess.run(args, capture_output=True, text=True)
    if p.returncode != 0:
        print("ERR", label, ":\n", p.stderr[-1200:])
        sys.exit(1)


# 1) trim each WorkBuddy clip to scripted duration, normalize to 1080p/24fps
concat_files = []
for i, d in enumerate(DUR, 1):
    src = os.path.join(VID, "shot%02d.mp4" % i)
    out = os.path.join(TMP, "clip%02d.mp4" % i)
    vf = ("scale=1920:1080:force_original_aspect_ratio=decrease,"
          "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24,format=yuv420p")
    if i == 1:
        vf += ",fade=t=in:st=0:d=0.5"
    run([FF, "-y", "-i", src, "-t", str(d), "-vf", vf, "-an",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", out], "trim%d" % i)
    concat_files.append(out)
    print("clip%02d (%ss) ok" % (i, d))

# 2) concat (all hard cuts)
lst = os.path.join(TMP, "list.txt")
with open(lst, "w", encoding="utf-8") as f:
    for c in concat_files:
        f.write("file '%s'\n" % c.replace("\\", "/"))
silent = os.path.join(TMP, "silent.mp4")
run([FF, "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", silent], "concat")
print("concat ok")

# 3) ambient bed: brown-noise rain + soft sine pad, faded
amb = os.path.join(TMP, "ambient.wav")
af = (
    "[0:a]lowpass=f=1300,highpass=f=110,volume=1.0[rain];"
    "[1:a]volume=0.06[pad1];"
    "[2:a]volume=0.045[pad2];"
    "[rain][pad1][pad2]amix=inputs=3:duration=longest:normalize=0,"
    "afade=t=in:st=0:d=1.5,afade=t=out:st=%d:d=2.0[aout]" % (TOTAL - 2)
)
run([FF, "-y",
     "-f", "lavfi", "-i", "anoisesrc=color=brown:duration=%d:amplitude=0.06" % TOTAL,
     "-f", "lavfi", "-i", "sine=frequency=220:duration=%d" % TOTAL,
     "-f", "lavfi", "-i", "sine=frequency=329.63:duration=%d" % TOTAL,
     "-filter_complex", af, "-map", "[aout]",
     "-ar", "44100", "-ac", "2", amb], "ambient")
print("ambient ok")

# 4) mux
final = os.path.join(BASE, "玻璃之后_成片.mp4")
run([FF, "-y", "-i", silent, "-i", amb, "-c:v", "copy",
     "-c:a", "aac", "-b:a", "192k", "-shortest", final], "mux")
print("FINAL:", final)
