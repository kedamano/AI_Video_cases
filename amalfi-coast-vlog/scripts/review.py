# -*- coding: utf-8 -*-
"""审片清单自动化 · scripts/review.py

把主 README「审片清单」里可以客观量化的部分变成一条命令：

    python scripts/review.py                        # 审仓库里的默认成片
    python scripts/review.py --video 某成片.mp4 --dur 1,2,2,3
    python scripts/review.py --json scripts/review_report.json
    python scripts/review.py --tolerance 3          # 切点容差（帧）

自动检测三类硬指标：
  1. 时长分布 —— 总时长、逐镜时长（由真实切点反推，不是复读分镜表）、
                  最短/最长镜是否越界（清单「节奏」：<1s 会闪 / >3s 会拖）。
  2. 切换点   —— 解码低分辨率 RGB 逐帧差，定位硬切，与分镜表逐点比对，
                  并报告未登记的额外切点（清单「声画匹配」的客观部分）。
  3. 音轨峰值 —— 解码 PCM，测峰值 dBFS / 削波样本 / 逐秒 RMS / 静音段 /
                  首尾淡入淡出 / 逐镜峰值（清单「技术规格」+「声画匹配」）。

另外自动检查「首尾完整」：首帧是否黑场/脏帧、末帧是否停在有效画面上。
清单里剩下的（信息密度、前三秒钩子、叙事主线、跨镜一致性、TTS 读错）
仍需人工过，脚本会在报告末尾列出这些人工项。

依赖：Python 3.8+、numpy、ffmpeg/ffprobe（或 imageio-ffmpeg）。
退出码：0=全部通过（允许 WARN）；1=存在 FAIL；2=运行/参数错误。
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
PASS, WARN, FAIL, INFO = "PASS", "WARN", "FAIL", "INFO"
MANUAL_ITEMS = [
    "单帧信息密度：一帧文字是否超过 12 字",
    "前三秒钩子：是否说清谁 / 做了什么 / 冲突在哪",
    "叙事主线：是否只有一条主线",
    "一致性：脸 / 发型 / 服装 / 色调跨镜是否统一",
    "TTS 读错：人名、专有名词、数字",
]


# ---------------------------------------------------------------- 工具定位

def find_bin(name):
    p = shutil.which(name)
    if p:
        return p
    # imageio-ffmpeg 只带 ffmpeg，同目录通常也有 ffprobe
    try:
        import imageio_ffmpeg
        sibling = Path(imageio_ffmpeg.get_ffmpeg_exe()).with_name(
            name + (".exe" if sys.platform == "win32" else ""))
        if sibling.exists():
            return str(sibling)
    except Exception:
        pass
    if name == "ffmpeg":
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
    return None


def run_bin(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise RuntimeError("命令失败: %s\n%s" % (" ".join(map(str, cmd[:6])),
                                                 p.stderr.decode("utf-8", "replace")[-600:]))
    return p.stdout


def probe(ffprobe, ffmpeg, video):
    if ffprobe:
        data = json.loads(run_bin([ffprobe, "-v", "error", "-show_streams",
                                   "-show_format", "-of", "json", str(video)]))
        vs = next((s for s in data["streams"] if s["codec_type"] == "video"), {})
        aus = [s for s in data["streams"] if s["codec_type"] == "audio"]
        au = aus[0] if aus else {}
        fmt = data.get("format", {})
        num, den = (vs.get("r_frame_rate", "0/1").split("/") + ["1"])[:2]
        fps = float(num) / float(den) if float(den) else 0.0
        return {
            "duration": float(fmt.get("duration") or vs.get("duration") or 0),
            "size": int(fmt.get("size") or 0),
            "bit_rate": int(fmt.get("bit_rate") or 0),
            "video": {"codec": vs.get("codec_name"), "width": vs.get("width"),
                      "height": vs.get("height"), "fps": fps,
                      "nb_frames": vs.get("nb_frames")},
            "audio_streams": len(aus),
            "audio": {"codec": au.get("codec_name"), "sample_rate": au.get("sample_rate"),
                      "channels": au.get("channels"), "bit_rate": au.get("bit_rate"),
                      "duration": au.get("duration")},
        }
    # 无 ffprobe 时从 ffmpeg -i 的 stderr 里做最小解析
    p = subprocess.run([ffmpeg, "-hide_banner", "-i", str(video)],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    txt = p.stderr.decode("utf-8", "replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", txt)
    dur = (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))) if m else 0.0
    mv = re.search(r"Video:\s*(\w+).*?,\s*(\d+)x(\d+).*?([\d.]+)\s*fps", txt, re.S)
    ma = re.search(r"Audio:\s*(\w+).*?(\d+)\s*Hz,\s*([\w.]+)", txt, re.S)
    return {
        "duration": dur, "size": video.stat().st_size, "bit_rate": 0,
        "video": {"codec": mv.group(1) if mv else None,
                  "width": int(mv.group(2)) if mv else None,
                  "height": int(mv.group(3)) if mv else None,
                  "fps": float(mv.group(4)) if mv else 0.0, "nb_frames": None},
        "audio_streams": 1 if ma else 0,
        "audio": {"codec": ma.group(1) if ma else None,
                  "sample_rate": ma.group(2) if ma else None,
                  "channels": ma.group(3) if ma else None,
                  "bit_rate": None, "duration": None},
    }


def decode_frames(ffmpeg, video, w=80, h=45):
    """整片解码成低分辨率 RGB 序列：既算切点，也用来看首末帧。"""
    raw = run_bin([ffmpeg, "-v", "error", "-i", str(video),
                   "-vf", "scale=%d:%d" % (w, h), "-pix_fmt", "rgb24",
                   "-f", "rawvideo", "-"])
    bpf = w * h * 3
    n = len(raw) // bpf
    if n < 2:
        raise RuntimeError("解码不到视频帧")
    return np.frombuffer(raw[:n * bpf], dtype=np.uint8).reshape(n, h, w, 3)


def decode_audio(ffmpeg, video, sr=48000):
    raw = run_bin([ffmpeg, "-v", "error", "-i", str(video), "-map", "0:a:0",
                   "-ac", "1", "-ar", str(sr), "-acodec", "pcm_f32le",
                   "-f", "f32le", "-"])
    a = np.frombuffer(raw, dtype="<f4").astype(np.float64)
    if a.size == 0:
        raise RuntimeError("解码不到音轨")
    return a, sr


def db(x):
    return 20.0 * math.log10(max(float(x), 1e-12))


# ---------------------------------------------------------------- 分镜表

def load_plan(explicit, duration):
    """优先用 --dur；否则从案例 make_final.py 解析 DUR 并校验总时长。"""
    if explicit:
        dur = [float(x) for x in explicit.split(",") if x.strip()]
        return dur, "--dur 命令行"
    candidates = [ROOT / "amalfi-coast-vlog" / "make_final.py",
                  ROOT / "make_final.py"]
    for p in candidates:
        if not p.exists():
            continue
        m = re.search(r"DUR\s*=\s*\[([^\]]+)\]", p.read_text(encoding="utf-8"))
        if not m:
            continue
        dur = [float(x) for x in re.findall(r"[\d.]+", m.group(1))]
        if dur and abs(sum(dur) - duration) <= 1.0:
            return dur, str(p.relative_to(ROOT))
    return [], "未找到与成片时长匹配的分镜表"


# ---------------------------------------------------------------- 报告

class Review:
    def __init__(self, video, meta):
        self.video = str(video)
        self.meta = meta
        self.checks = []
        self.data = {}

    def add(self, name, status, summary, detail=None):
        self.checks.append({"name": name, "status": status,
                            "summary": summary, "detail": detail or {}})
        print("  [%s] %-14s %s" % (status, name, summary))

    @property
    def failed(self):
        return any(c["status"] == FAIL for c in self.checks)

    def to_dict(self):
        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "video": self.video,
            "meta": self.meta,
            "checks": self.checks,
            "data": self.data,
            "manual_checklist": MANUAL_ITEMS,
            "result": "FAIL" if self.failed else "PASS",
        }


# ---------------------------------------------------------------- 检测项

def check_spec(rp, dur, tol_f, fps):
    m = rp.meta
    v, a = m["video"], m["audio"]
    issues = []
    if abs(m["duration"] - dur) > max(0.05, tol_f / fps):
        issues.append("时长 %.3fs，期望 %.3fs" % (m["duration"], dur))
    if not v.get("codec") or not v.get("width") or not fps:
        issues.append("视频流信息不全")
    if m["audio_streams"] < 1:
        issues.append("没有音轨")
    if a.get("duration"):
        try:
            if abs(float(a["duration"]) - m["duration"]) > 0.2:
                issues.append("音轨时长与画面不一致")
        except (TypeError, ValueError):
            pass
    detail = {"duration_s": m["duration"], "resolution": "%sx%s" % (v.get("width"), v.get("height")),
              "fps": fps, "video_codec": v.get("codec"), "audio_codec": a.get("codec"),
              "sample_rate": a.get("sample_rate"), "channels": a.get("channels"),
              "size_bytes": m["size"], "bit_rate": m["bit_rate"]}
    rp.data["spec"] = detail
    rp.add("技术规格", FAIL if issues else PASS,
           "; ".join(issues) if issues else
           "%.3fs / %sx%s / %.0ffps / %s + %s / %sHz" %
           (m["duration"], v.get("width"), v.get("height"), fps,
            v.get("codec"), a.get("codec"), a.get("sample_rate")), detail)


def check_frames(rp, frames):
    """清单「首尾完整」：首帧不能黑场/脏帧，末帧要停在有效画面。"""
    first, last = frames[0].astype(np.float64), frames[-1].astype(np.float64)
    info = {}
    for tag, im in (("first", first), ("last", last)):
        info[tag] = {"luma_mean": round(float(im.mean()), 2),
                     "luma_std": round(float(im.std()), 2)}
    bad = []
    for tag in ("first", "last"):
        if info[tag]["luma_mean"] < 12 and info[tag]["luma_std"] < 12:
            bad.append("%s帧黑场" % ("首" if tag == "first" else "末"))
        elif info[tag]["luma_mean"] > 245 and info[tag]["luma_std"] < 12:
            bad.append("%s帧白场" % ("首" if tag == "first" else "末"))
    rp.data["first_last_frame"] = info
    rp.add("首尾完整", FAIL if bad else PASS,
           "; ".join(bad) if bad else
           "首帧亮度 %.1f / 末帧亮度 %.1f，均为有效画面" %
           (info["first"]["luma_mean"], info["last"]["luma_mean"]), info)


def detect_cuts(d, fps, expected, tol_f):
    """逐帧差定位硬切；在期望切点 ±3 帧窗口内取最强峰，顺带找额外峰。"""
    tol_s = tol_f / fps
    weak = max(3.0, float(np.median(d)) * 1.4)
    strong = max(8.0, float(np.percentile(d, 98)) * 0.5)
    rows, cuts = [], []
    for idx, t in enumerate(expected, 1):
        k0 = int(round(t * fps)) - 1
        lo, hi = max(0, k0 - 3), min(len(d) - 1, k0 + 3)
        window = d[lo:hi + 1]
        # 期望位置上只要有明显的帧差，就判定切点精确落在该帧；只有期望位置
        # 没有峰时才取窗口内最强峰，避免镜内运动把峰值拖到相邻帧造成 1 帧误判。
        if d[k0] >= weak and d[k0] >= 0.6 * float(window.max()):
            k = k0
        else:
            k = lo + int(np.argmax(window))
        actual = (k + 1) / fps
        delta = actual - t
        strength = float(d[k])
        ok = abs(delta) <= tol_s and strength >= weak
        rows.append({"idx": idx, "expected_s": round(float(t), 4),
                     "detected_s": round(actual, 4),
                     "delta_s": round(float(delta), 4),
                     "delta_frames": round(float(delta * fps), 2),
                     "strength": round(strength, 2), "ok": bool(ok)})
        cuts.append(actual if ok else float(t))
    peaks = [i for i in range(1, len(d) - 1)
             if d[i] >= d[i - 1] and d[i] > d[i + 1] and d[i] >= strong]
    extra = [{"time_s": round((i + 1) / fps, 3), "strength": round(float(d[i]), 2)}
             for i in peaks
             if all(abs((i + 1) / fps - t) > 0.5 for t in expected)]
    return rows, cuts, extra, {"weak": round(weak, 2), "strong": round(strong, 2),
                               "median_diff": round(float(np.median(d)), 2),
                               "p99_diff": round(float(np.percentile(d, 99)), 2)}


def check_cuts(rp, rows, extra, thresholds, tol_f, fps):
    bad = [r for r in rows if not r["ok"]]
    rp.data["cuts"] = {"rows": rows, "extra_peaks": extra, "thresholds": thresholds,
                       "tolerance_frames": tol_f,
                       "max_abs_delta_ms": round(max(abs(r["delta_s"]) for r in rows) * 1000, 1)
                       if rows else 0}
    rp.add("切换点", FAIL if bad else PASS,
           "%d/%d 个切点对齐，最大偏差 %.1f ms%s" %
           (len(rows) - len(bad), len(rows),
            max((abs(r["delta_s"]) for r in rows), default=0) * 1000,
            "；未对齐 " + ",".join("#%d" % r["idx"] for r in bad) if bad else ""),
           {"bad": bad, "tolerance_s": round(tol_f / fps, 4)})
    rp.add("额外切点", WARN if len(extra) > 3 else INFO,
           "%d 个未登记的强帧差峰（可能是镜头内剧烈运动）" % len(extra),
           {"peaks": extra[:20]})


def check_durations(rp, cuts, duration, dur, min_shot, max_shot, tol_f, fps):
    if not dur:
        rp.add("时长分布", WARN, "没有分镜表，跳过逐镜比对")
        return
    edges = [0.0] + list(cuts) + [duration]
    shots = [round(edges[i + 1] - edges[i], 4) for i in range(len(edges) - 1)]
    rows = [{"shot": i + 1, "expected_s": float(e), "actual_s": a,
             "delta_s": round(a - float(e), 4)}
            for i, (a, e) in enumerate(zip(shots, dur))]
    mis = [r for r in rows if abs(r["delta_s"]) > tol_f / fps + 1e-6]
    shortest, longest = min(shots), max(shots)
    dist = {}
    for s in shots:
        key = "%.0fs" % round(s)
        dist[key] = dist.get(key, 0) + 1
    issues = []
    if len(shots) != len(dur):
        issues.append("镜头数 %d，期望 %d" % (len(shots), len(dur)))
    if shortest < min_shot - 0.02:
        issues.append("最短镜 %.3fs < %.1fs（会闪）" % (shortest, min_shot))
    if longest > max_shot + 0.02:
        issues.append("最长镜 %.3fs > %.1fs（会拖）" % (longest, max_shot))
    if mis:
        issues.append("%d 镜时长偏离分镜表" % len(mis))
    rp.data["shot_durations"] = {"rows": rows, "distribution": dist,
                                 "total_s": round(sum(shots), 3),
                                 "shortest_s": shortest, "longest_s": longest,
                                 "misaligned": mis}
    rp.add("时长分布", FAIL if issues else PASS,
           "; ".join(issues) if issues else
           "%d 镜 / 总 %.3fs / 最短 %.2fs / 最长 %.2fs / 分布 %s / 全镜对齐" %
           (len(shots), sum(shots), shortest, longest,
            ", ".join("%s×%d" % (k, v) for k, v in sorted(dist.items()))),
           {"misaligned": mis[:8]})


def check_audio(rp, audio, sr, dur, peak_ceiling, cuts):
    peak = float(np.max(np.abs(audio)))
    peak_db = db(peak)
    rms_db = db(math.sqrt(float(np.mean(audio ** 2))))
    clipped = int(np.count_nonzero(np.abs(audio) >= 0.999))
    sec = int(math.ceil(len(audio) / sr))
    env = []
    for s in range(sec):
        seg = audio[s * sr:(s + 1) * sr]
        env.append(round(db(math.sqrt(float(np.mean(seg ** 2))) if seg.size else 0), 1))
    # 中间段静音（首尾 3s 是设计好的淡入淡出，不按故障计）
    silent, run, runs = 0, 0, []
    for s in range(3, max(3, sec - 3)):
        if env[s] < -50.0:
            run += 1
        else:
            if run:
                runs.append(run)
            run = 0
    if run:
        runs.append(run)
    longest_silence = max(runs, default=0)
    fade_in = round(sum(env[:2]) / 2 - np.median(env), 1) if len(env) > 5 else 0
    fade_out = round(sum(env[-3:]) / 3 - np.median(env), 1) if len(env) > 5 else 0
    # 逐镜峰值（按检测到的切点分段）
    edges = [0.0] + list(cuts) + [dur]
    per_shot = []
    for i in range(len(edges) - 1):
        seg = audio[int(edges[i] * sr):int(edges[i + 1] * sr)]
        per_shot.append(round(db(float(np.max(np.abs(seg))) if seg.size else 0), 1))
    issues = []
    if peak_db > peak_ceiling:
        issues.append("峰值 %.2f dBFS > %.1f dBFS" % (peak_db, peak_ceiling))
    if clipped:
        issues.append("%d 个采样削波" % clipped)
    if longest_silence >= 1:
        issues.append("中段连续静音 %ds" % longest_silence)
    if abs(len(audio) / sr - dur) > 0.2:
        issues.append("音轨时长 %.2fs 与画面 %.2fs 不符" % (len(audio) / sr, dur))
    rp.data["audio"] = {
        "peak": round(peak, 5), "peak_dbfs": round(peak_db, 2),
        "rms_dbfs": round(rms_db, 2), "clipped_samples": clipped,
        "per_second_rms_dbfs": env, "longest_mid_silence_s": longest_silence,
        "fade_in_delta_db": fade_in, "fade_out_delta_db": fade_out,
        "per_shot_peak_dbfs": per_shot, "seconds": round(len(audio) / sr, 3),
    }
    rp.add("音轨峰值", FAIL if issues else PASS,
           "; ".join(issues) if issues else
           "峰值 %.2f dBFS / RMS %.2f dBFS / 削波 %d / 中段静音 %ds / 首尾淡变 %.1f·%.1f dB" %
           (peak_db, rms_db, clipped, longest_silence, fade_in, fade_out),
           {"issues": issues})


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser(description="审片清单自动化：时长分布 / 切换点 / 音轨峰值")
    ap.add_argument("--video", help="成片路径（默认自动找仓库里的成片 mp4）")
    ap.add_argument("--dur", help="逐镜时长，逗号分隔；默认从 make_final.py 的 DUR 解析")
    ap.add_argument("--tolerance", type=int, default=2, help="切点容差（帧），默认 2")
    ap.add_argument("--min-shot", type=float, default=1.0, help="最短镜阈值，默认 1.0s")
    ap.add_argument("--max-shot", type=float, default=3.0, help="最长镜阈值，默认 3.0s")
    ap.add_argument("--peak-ceiling", type=float, default=-1.0, help="峰值上限 dBFS，默认 -1.0")
    ap.add_argument("--json", default="auto", help="报告路径；auto=scripts/review_report.json，off=不写")
    args = ap.parse_args()

    ffmpeg = find_bin("ffmpeg")
    ffprobe = find_bin("ffprobe")
    if not ffmpeg:
        print("找不到 ffmpeg（可 pip install imageio-ffmpeg）", file=sys.stderr)
        return 2

    if args.video:
        video = Path(args.video)
    else:
        cands = [ROOT / "amalfi-coast-vlog" / "阿马尔菲海岸_成片.mp4",
                 ROOT / "阿马尔菲海岸_成片.mp4"]
        cands += [p for p in ROOT.glob("*成片*.mp4") if "videos" not in p.parts]
        cands += [p for p in ROOT.glob("*/阿马尔菲海岸_成片.mp4")]
        video = next((p for p in cands if p.exists()), None)
    if not video or not video.exists():
        print("找不到成片：%s" % (video or args.video), file=sys.stderr)
        return 2
    video = video.resolve()

    print("审片目标：%s" % video)
    meta = probe(ffprobe, ffmpeg, video)
    fps = float(meta["video"]["fps"] or 0)
    if not fps:
        print("无法读取帧率", file=sys.stderr)
        return 2
    frames = decode_frames(ffmpeg, video)
    d = np.abs(frames[1:].astype(np.int16) - frames[:-1].astype(np.int16)).mean(axis=(1, 2, 3))
    dur_plan, plan_src = load_plan(args.dur, meta["duration"])
    audio, sr = decode_audio(ffmpeg, video)
    print("分镜表：%s（%d 镜 / %.2fs）\n" %
          (plan_src, len(dur_plan), sum(dur_plan) if dur_plan else 0))

    rp = Review(video, meta)
    rp.data["plan_source"] = plan_src
    rp.data["expected_durations"] = dur_plan
    check_spec(rp, sum(dur_plan) if dur_plan else meta["duration"],
               args.tolerance, fps)
    check_frames(rp, frames)

    expected = list(np.cumsum(dur_plan)[:-1]) if dur_plan else []
    if expected:
        rows, cuts, extra, th = detect_cuts(d, fps, expected, args.tolerance)
        rp.data["frame_diff"] = th
        check_cuts(rp, rows, extra, th, args.tolerance, fps)
        check_durations(rp, cuts, meta["duration"], dur_plan,
                        args.min_shot, args.max_shot, args.tolerance, fps)
    else:
        cuts = []
        rp.add("切换点", WARN, "没有分镜表，只做技术审片")

    check_audio(rp, audio, sr, meta["duration"], args.peak_ceiling, cuts)

    print("\n人工复核项（脚本不判定）：")
    for item in MANUAL_ITEMS:
        print("  - [ ] %s" % item)
    n_fail = sum(c["status"] == FAIL for c in rp.checks)
    n_warn = sum(c["status"] == WARN for c in rp.checks)
    print("\n结论：%s ｜ PASS %d / WARN %d / FAIL %d" %
          ("FAIL" if rp.failed else "PASS",
           sum(c["status"] == PASS for c in rp.checks), n_warn, n_fail))

    if args.json != "off":
        out = ROOT / "scripts" / "review_report.json" if args.json == "auto" else Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rp.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        print("报告：%s" % out)
    return 1 if rp.failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print("审片失败：%s" % e, file=sys.stderr)
        sys.exit(2)
