"""Small sound effects made by ffmpeg itself (no files, no licences): footsteps, knock, ding, pop, whoosh, birds..."""
from __future__ import annotations

from pathlib import Path

from app.services.media import run_ffmpeg

SFX: dict[str, list[str]] = {
    "footsteps": ["-f", "lavfi", "-i", "aevalsrc='0.8*sin(2*PI*90*t)*exp(-25*mod(t,0.42))':d=1.7:s=44100"],
    "knock": ["-f", "lavfi", "-i", "aevalsrc='0.9*sin(2*PI*180*t)*exp(-40*mod(t,0.22))*lt(t,0.66)':d=0.8:s=44100"],
    "ding": ["-f", "lavfi", "-i", "aevalsrc='0.5*sin(2*PI*1320*t)*exp(-3*t)+0.2*sin(2*PI*2640*t)*exp(-4*t)':d=1.4:s=44100"],
    "pop": ["-f", "lavfi", "-i", "aevalsrc='0.8*sin(2*PI*(700-2400*t)*t)*exp(-30*t)':d=0.25:s=44100"],
    "boing": ["-f", "lavfi", "-i", "aevalsrc='0.6*sin(2*PI*(220+120*sin(2*PI*9*t))*t)*exp(-3*t)':d=0.9:s=44100"],
    "birds": ["-f", "lavfi", "-i", "aevalsrc='0.35*sin(2*PI*(2600+700*sin(2*PI*14*t))*t)*lt(mod(t,0.55),0.16)':d=2.2:s=44100"],
    "whoosh": ["-f", "lavfi", "-i", "anoisesrc=d=0.7:c=pink:r=44100:a=0.6", "-af", "bandpass=f=900:w=600,afade=t=in:d=0.3,afade=t=out:st=0.4:d=0.3"],
    "thunder": ["-f", "lavfi", "-i", "anoisesrc=d=2.5:c=brown:r=44100:a=0.9", "-af", "lowpass=f=180,afade=t=in:d=0.05,afade=t=out:st=0.3:d=2.2"],
    "rain": ["-f", "lavfi", "-i", "anoisesrc=d=3:c=pink:r=44100:a=0.25", "-af", "highpass=f=1200,afade=t=in:d=0.5,afade=t=out:st=2.3:d=0.7"],
    "bell": ["-f", "lavfi", "-i", "aevalsrc='0.4*sin(2*PI*880*t)*exp(-2*t)+0.3*sin(2*PI*1320*t)*exp(-2.5*t)+0.2*sin(2*PI*1760*t)*exp(-3*t)':d=2:s=44100"],
    "phone": ["-f", "lavfi", "-i", "aevalsrc='0.4*sin(2*PI*480*t)*sin(2*PI*620*t)*lt(mod(t,1),0.6)':d=2:s=44100"],
    "horn": ["-f", "lavfi", "-i", "aevalsrc='0.35*(sin(2*PI*400*t)+sin(2*PI*500*t))*lt(mod(t,0.7),0.45)':d=1.4:s=44100"],
    "drumroll": ["-f", "lavfi", "-i", "anoisesrc=d=1.6:c=brown:r=44100:a=0.8", "-af", "volume='0.5+0.5*sin(2*PI*18*t)':eval=frame,lowpass=f=300,afade=t=in:d=1.2"],
    "magic": ["-f", "lavfi", "-i", "aevalsrc='0.3*sin(2*PI*(1200+900*t)*t)*exp(-1.5*t)*(0.6+0.4*sin(2*PI*20*t))':d=1.5:s=44100"],
    "slide": ["-f", "lavfi", "-i", "aevalsrc='0.5*sin(2*PI*(300+1200*t)*t)':d=0.8:s=44100", "-af", "afade=t=out:st=0.6:d=0.2"],
    "fall": ["-f", "lavfi", "-i", "aevalsrc='0.5*sin(2*PI*(1500-1300*t)*t)':d=1:s=44100", "-af", "afade=t=out:st=0.8:d=0.2"],
    "explosion": ["-f", "lavfi", "-i", "anoisesrc=d=1.8:c=brown:r=44100:a=1", "-af", "lowpass=f=400,afade=t=out:st=0.1:d=1.7"],
    "wind": ["-f", "lavfi", "-i", "anoisesrc=d=3:c=pink:r=44100:a=0.3", "-af", "bandpass=f=500:w=400,volume='0.6+0.4*sin(2*PI*0.5*t)':eval=frame,afade=t=in:d=0.6,afade=t=out:st=2.3:d=0.7"],
    "heartbeat": ["-f", "lavfi", "-i", "aevalsrc='0.9*sin(2*PI*60*t)*(exp(-30*mod(t,0.9))+0.7*exp(-30*mod(t-0.22,0.9))*gt(mod(t,0.9),0.22))':d=2.7:s=44100"],
    "tick": ["-f", "lavfi", "-i", "aevalsrc='0.6*sin(2*PI*2000*t)*exp(-200*mod(t,0.5))':d=2:s=44100"],
    "drop": ["-f", "lavfi", "-i", "aevalsrc='0.6*sin(2*PI*(900-600*t*4)*t)*exp(-12*t)':d=0.35:s=44100"],
    "applause": ["-f", "lavfi", "-i", "anoisesrc=d=2.5:c=white:r=44100:a=0.25", "-af", "highpass=f=800,volume='0.5+0.5*sin(2*PI*9*t)':eval=frame,afade=t=out:st=1.8:d=0.7"],
    "creak": ["-f", "lavfi", "-i", "aevalsrc='0.3*sin(2*PI*(120+80*sin(2*PI*3*t))*t)*(0.5+0.5*sin(2*PI*35*t))':d=1.4:s=44100"],
    "splash": ["-f", "lavfi", "-i", "anoisesrc=d=0.9:c=white:r=44100:a=0.7", "-af", "bandpass=f=1500:w=1200,afade=t=out:st=0.05:d=0.85"],
    "whistle": ["-f", "lavfi", "-i", "aevalsrc='0.4*sin(2*PI*(2200+300*sin(2*PI*6*t))*t)':d=1:s=44100"],
    "snore": ["-f", "lavfi", "-i", "anoisesrc=d=3:c=brown:r=44100:a=0.6", "-af", "lowpass=f=250,volume='max(0,sin(2*PI*0.4*t))':eval=frame"],
    "kiss": ["-f", "lavfi", "-i", "aevalsrc='0.6*sin(2*PI*(1800-1400*t*6)*t)*exp(-25*t)':d=0.2:s=44100"],
    "coin": ["-f", "lavfi", "-i", "aevalsrc='0.4*sin(2*PI*988*t)*lt(t,0.08)+0.4*sin(2*PI*1319*t)*gt(t,0.08)*exp(-6*(t-0.08))':d=0.6:s=44100"],
}
NAMES = tuple(SFX)
LABELS = {"footsteps": "👣 Kadam", "knock": "🚪 Khatkhat", "ding": "🔔 Ding", "pop": "💥 Pop", "boing": "🤸 Boing", "birds": "🐦 Chidiya",
          "whoosh": "💨 Whoosh", "thunder": "⛈ Bijli", "rain": "🌧 Baarish", "bell": "🛕 Ghanti", "phone": "📞 Phone", "horn": "🚗 Horn",
          "drumroll": "🥁 Drum roll", "magic": "✨ Jaadu", "slide": "📈 Upar", "fall": "📉 Neeche girna", "explosion": "💣 Dhamaka",
          "wind": "🌬 Hawa", "heartbeat": "💓 Dhadkan", "tick": "⏰ Tik-tik", "drop": "💧 Boond", "applause": "👏 Taaliyan",
          "creak": "🚪 Charr", "splash": "🌊 Chhapaak", "whistle": "😗 Seeti", "snore": "😴 Kharrate", "kiss": "😘 Pucchi", "coin": "🪙 Sikka"}


async def make_sfx(name: str, out: Path) -> Path | None:
    args = SFX.get((name or "").lower())
    if not args:
        return None
    await run_ffmpeg(args + ["-ac", "1", "-c:a", "pcm_s16le", str(out)], timeout=60)
    return out


async def mix_sfx(scene_wav: Path, events: list[tuple[str, float]], workdir: Path, tag: str, volume: float = 0.55) -> Path:
    """Lay the effects over the scene audio at their start times; returns a new wav (or the old one)."""
    files: list[tuple[Path, float]] = []
    for k, (name, start) in enumerate(events):
        p = await make_sfx(name, workdir / f"sfx_{tag}_{k}.wav")
        if p is not None:
            files.append((p, max(0.0, start)))
    if not files:
        return scene_wav
    args = ["-i", str(scene_wav)]
    parts = []
    for k, (p, start) in enumerate(files, 1):
        args += ["-i", str(p)]
        parts.append(f"[{k}:a]aresample=44100,aformat=channel_layouts=mono,volume={volume},adelay={int(start * 1000)}:all=1[s{k}]")
    mix = "[0:a]aresample=44100,aformat=channel_layouts=mono[m0];[m0]" + "".join(f"[s{k}]" for k in range(1, len(files) + 1))
    mix += f"amix=inputs={len(files) + 1}:duration=first:normalize=0[a]"
    out = workdir / f"{scene_wav.stem}_sfx.wav"
    await run_ffmpeg(args + ["-filter_complex", ";".join(parts + [mix]), "-map", "[a]", "-c:a", "pcm_s16le", str(out)], timeout=120)
    return out
