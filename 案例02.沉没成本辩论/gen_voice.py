"""Generate voiceovers: load raw float32 voice bin, repack as npz, run Kokoro."""
import os
import numpy as np
import soundfile as sf

os.environ["HTTP_PROXY"] = "http://127.0.0.1:7897"
os.environ["HTTPS_PROXY"] = "http://127.0.0.1:7897"

from kokoro_onnx import Kokoro

BASE = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(BASE, "assets", "models")
OUT_DIR = os.path.join(BASE, "assets")

# Load raw float32 voice bin (no numpy header)
raw = np.fromfile(os.path.join(MODEL_DIR, "voices", "zf_xiaobei.bin"), dtype=np.float32)
print(f"raw size: {raw.size} floats")
# Kokoro voice shape is (n_phonemes_max, 1, 256); 510*1*256 = 130560
voice_style = raw.reshape(510, 1, 256)
print(f"voice shape: {voice_style.shape}")

# Repack as npz with key zf_xiaobei
npz_path = os.path.join(MODEL_DIR, "voices.npz")
np.savez(npz_path, zf_xiaobei=voice_style)
print(f"saved npz: {npz_path}")

model_path = os.path.join(MODEL_DIR, "kokoro.onnx")
print(f"Loading model: {model_path}")
kokoro = Kokoro(model_path, npz_path)

scenes = [
    ("voice_01_hook.wav", "你有没有过这样的时刻？明明知道不对，却怎么也走不出来。五年撑不下去的感情，三年熬不出头的工作，两小时下不停的赌局。"),
    ("voice_02_anchor.wav", "舍不得。这就是沉没成本谬误。"),
    ("voice_03_pro.wav", "正方说：错一次，就完了。你投入的每一年、每一块钱，都会变成拖你下水的重物。协和飞机超支仍继续拨款，自助餐吃到胃痛也不肯停，等了四十分钟公交宁愿再等二十分。"),
    ("voice_04_con.wav", "反方说：沉没成本，不是成本。已经花出去的时间和感情，像泼出去的水。真正影响下一步的，只有从现在开始的未来。"),
    ("voice_05_clash.wav", "一边是为了不浪费过去五年，再赔上未来五年。另一边是承认选错了，把日子留给值得的事。你已经投入的，还能退回来吗？"),
    ("voice_06_reset.wav", "舍不得，不是深情，是损失厌恶。翻盘，不是否定过去，是不被过去绑架。"),
    ("voice_07_ending.wav", "沉没成本，不参与重大决策。错一次，不是终局，是重置键。"),
]

for fname, text in scenes:
    out_path = os.path.join(OUT_DIR, fname)
    print(f"Generating {fname}...")
    samples, sr = kokoro.create(text, voice="zf_xiaobei", speed=1.0, lang="cmn")
    sf.write(out_path, samples, sr)
    dur = len(samples) / sr
    print(f"  -> {out_path} ({dur:.1f}s)")

print("All voiceovers generated.")
