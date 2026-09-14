"""生成《回响之刃》所需的背景音乐与战斗音效。

纯标准库实现（math / random / array / wave），不依赖 numpy 或音频引擎，
因此可以在任何 Python 3.12+ 环境下重新生成全部素材。

用法：
    .\\.venv\\Scripts\\python.exe generate_audio_assets.py              # 生成全部
    .\\.venv\\Scripts\\python.exe generate_audio_assets.py --only music # 只生成音乐
    .\\.venv\\Scripts\\python.exe generate_audio_assets.py --only sfx   # 只生成音效
    .\\.venv\\Scripts\\python.exe generate_audio_assets.py --preview    # 生成后试听

混音原则（供后续调整参考）：
* 音乐整体让出 2.2kHz~4.2kHz 的“确认感频段”，保证挥刀、命中与弹刀听得清。
* 弹刀音效是可听范围内最响的素材（约 -2.5 dBFS），并带延迟回声呼应“回响”主题。
* 音乐循环长度取整数小节，长音符与回声在循环点处环绕衔接，避免接缝。
"""

from __future__ import annotations

import argparse
import math
import random
import wave
from array import array
from pathlib import Path

RENDER_RATE = 44100
MUSIC_EXPORT_RATE = 22050
SFX_EXPORT_RATE = 44100

TAU = math.tau
TABLE_BITS = 12
TABLE_SIZE = 1 << TABLE_BITS
TABLE_MASK = TABLE_SIZE - 1

PROJECT_ROOT = Path(__file__).resolve().parent
SOUND_DIR = PROJECT_ROOT / "sounds"
MUSIC_DIR = SOUND_DIR / "music"
SFX_DIR = SOUND_DIR / "sfx"

NOTE_OFFSETS = {
    "C": 0,
    "C#": 1,
    "Db": 1,
    "D": 2,
    "D#": 3,
    "Eb": 3,
    "E": 4,
    "F": 5,
    "F#": 6,
    "Gb": 6,
    "G": 7,
    "G#": 8,
    "Ab": 8,
    "A": 9,
    "A#": 10,
    "Bb": 10,
    "B": 11,
}


def note_frequency(name: str) -> float:
    """把 A3 / F#4 / Bb1 这样的音名转成频率。"""
    letters = name[:-1]
    octave = int(name[-1])
    midi = (octave + 1) * 12 + NOTE_OFFSETS[letters]
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def pan_gains(pan: float) -> tuple[float, float]:
    """等功率声像，pan=-1 全左，pan=1 全右。"""
    clamped = max(-1.0, min(1.0, pan))
    angle = (clamped + 1.0) * math.pi / 4.0
    return math.cos(angle), math.sin(angle)


def _make_sine_table() -> array:
    return array("d", [math.sin(TAU * i / TABLE_SIZE) for i in range(TABLE_SIZE)])


def _make_harmonic_table(
    max_harmonic: int,
    *,
    odd_only: bool = False,
    rolloff: float = 1.0,
) -> array:
    """用有限谐波叠加出带限波形，避免高频采样时产生明显混叠。"""
    values = [0.0] * TABLE_SIZE
    for harmonic in range(1, max_harmonic + 1):
        if odd_only and harmonic % 2 == 0:
            continue
        amplitude = 1.0 / (harmonic**rolloff)
        for index in range(TABLE_SIZE):
            values[index] += amplitude * math.sin(
                TAU * harmonic * index / TABLE_SIZE
            )
    peak = max(abs(value) for value in values) or 1.0
    return array("d", [value / peak for value in values])


SINE = _make_sine_table()
BRIGHT_TABLE = _make_harmonic_table(16, rolloff=1.0)
WARM_TABLE = _make_harmonic_table(8, rolloff=1.2)
HOLLOW_TABLE = _make_harmonic_table(9, odd_only=True, rolloff=1.1)


class Buffer:
    """简单双声道浮点缓冲，内部用 array('d') 保存，便于纯 Python 快速累加。"""

    __slots__ = ("rate", "length", "left", "right")

    def __init__(self, seconds: float, rate: int = RENDER_RATE) -> None:
        self.rate = rate
        self.length = max(1, int(round(seconds * rate)))
        self.left = array("d", bytes(8 * self.length))
        self.right = array("d", bytes(8 * self.length))

    @property
    def seconds(self) -> float:
        return self.length / self.rate

    def slice_from(self, start_seconds: float) -> Buffer:
        offset = int(round(start_seconds * self.rate))
        offset = max(0, min(self.length - 1, offset))
        result = Buffer(0.0, self.rate)
        result.length = self.length - offset
        result.left = array("d", self.left[offset:])
        result.right = array("d", self.right[offset:])
        return result

    def mix_from(self, other: Buffer, gain: float = 1.0) -> None:
        count = min(self.length, other.length)
        left = self.left
        right = self.right
        other_left = other.left
        other_right = other.right
        for index in range(count):
            left[index] += other_left[index] * gain
            right[index] += other_right[index] * gain


def _span(buf: Buffer, start: float, duration: float) -> tuple[int, int, int]:
    """返回 (begin, first_index, end_index)，允许 start 为负（用于循环预滚）。"""
    begin = int(round(start * buf.rate))
    count = int(round(duration * buf.rate))
    end = min(begin + count, buf.length)
    return begin, max(0, begin), max(0, end)


# ---------------------------------------------------------------------------
# 乐器与打击乐
# ---------------------------------------------------------------------------


def add_pluck(
    buf: Buffer,
    start: float,
    duration: float,
    freq: float,
    gain: float,
    pan: float = 0.0,
    *,
    brightness: float = 5.0,
    decay: float = 1.8,
    attack: float = 0.004,
    detune_cents: float = 0.0,
    table: array = BRIGHT_TABLE,
) -> None:
    """拨弦音色：带限锯齿 + 随时间下落的低通 + 指数衰减，接近古筝/琵琶拨奏。"""
    if freq <= 0.0 or gain == 0.0:
        return
    rate = buf.rate
    begin, first, end = _span(buf, start, duration)
    if first >= end:
        return
    left = buf.left
    right = buf.right
    gain_l, gain_r = pan_gains(pan)
    gain_l *= gain
    gain_r *= gain

    inc = freq * TABLE_SIZE / rate
    inc2 = inc * (2.0 ** (detune_cents / 1200.0))
    phase = 0.0
    phase2 = 0.0
    attack_n = max(1, int(attack * rate))
    decay_factor = math.exp(-1.0 / (decay * rate))
    amp = 1.0
    lowpass = 0.0
    lowpass2 = 0.0
    cutoff_speed = 1.0 / (0.28 * rate)
    base_cutoff = max(120.0, freq)
    for idx in range(first, end):
        i = idx - begin
        if i % 64 == 0:
            progress = math.exp(-i * cutoff_speed)
            cutoff = base_cutoff * (1.0 + brightness * progress)
            coeff = 1.0 - math.exp(-TAU * min(cutoff, rate * 0.45) / rate)
        amplitude = amp if i >= attack_n else (i + 1) / attack_n
        sample = table[int(phase) & TABLE_MASK]
        lowpass += coeff * (sample - lowpass)
        if detune_cents:
            sample2 = table[int(phase2) & TABLE_MASK]
            lowpass2 += coeff * (sample2 - lowpass2)
            value = lowpass * 0.72 + lowpass2 * 0.36
        else:
            value = lowpass
        value *= amplitude
        left[idx] += value * gain_l
        right[idx] += value * gain_r
        phase += inc
        phase2 += inc2
        amp *= decay_factor
        if phase >= TABLE_SIZE:
            phase -= TABLE_SIZE
        if phase2 >= TABLE_SIZE:
            phase2 -= TABLE_SIZE


def add_pad(
    buf: Buffer,
    start: float,
    duration: float,
    freq: float,
    gain: float,
    pan: float = 0.0,
    *,
    attack: float = 1.2,
    release: float = 1.4,
    detune: float = 0.0045,
    tremolo: float = 0.07,
    tremolo_rate: float = 0.22,
    cutoff: float = 1700.0,
    table: array = WARM_TABLE,
) -> None:
    """铺底弦垫：三个微失谐振荡器 + 慢起音 + 轻微颤音，负责氛围不抢戏。"""
    if freq <= 0.0 or gain == 0.0:
        return
    rate = buf.rate
    begin, first, end = _span(buf, start, duration)
    if first >= end:
        return
    left = buf.left
    right = buf.right
    gain_l, gain_r = pan_gains(pan)
    gain_l *= gain
    gain_r *= gain

    inc_a = freq * TABLE_SIZE / rate
    inc_b = inc_a * (1.0 + detune)
    inc_c = inc_a * (1.0 - detune * 1.35)
    phase_a = 0.0
    phase_b = TABLE_SIZE * 0.31
    phase_c = TABLE_SIZE * 0.67
    attack_n = max(1, int(attack * rate))
    release_n = max(1, int(release * rate))
    lfo_inc = tremolo_rate / rate
    lfo_phase = 0.0
    coeff = 1.0 - math.exp(-TAU * min(cutoff, rate * 0.45) / rate)
    lowpass = 0.0
    for idx in range(first, end):
        i = idx - begin
        if i < attack_n:
            amplitude = (i + 1) / attack_n
        else:
            remaining = end - idx
            amplitude = 1.0 if remaining >= release_n else remaining / release_n
        if i % 128 == 0:
            lfo = 1.0 + tremolo * SINE[int(lfo_phase * TABLE_SIZE) & TABLE_MASK]
        sample = (
            table[int(phase_a) & TABLE_MASK]
            + table[int(phase_b) & TABLE_MASK] * 0.85
            + table[int(phase_c) & TABLE_MASK] * 0.7
        )
        lowpass += coeff * (sample - lowpass)
        value = lowpass * amplitude * lfo * 0.42
        left[idx] += value * gain_l
        right[idx] += value * gain_r
        phase_a += inc_a
        phase_b += inc_b
        phase_c += inc_c
        lfo_phase += lfo_inc
        if lfo_phase >= 1.0:
            lfo_phase -= 1.0
        if phase_a >= TABLE_SIZE:
            phase_a -= TABLE_SIZE
        if phase_b >= TABLE_SIZE:
            phase_b -= TABLE_SIZE
        if phase_c >= TABLE_SIZE:
            phase_c -= TABLE_SIZE


def add_breath_lead(
    buf: Buffer,
    start: float,
    duration: float,
    freq: float,
    gain: float,
    pan: float = 0.0,
    *,
    attack: float = 0.06,
    release: float = 0.16,
    vibrato_rate: float = 4.6,
    vibrato_depth: float = 0.0035,
    breath: float = 0.05,
    rng: random.Random | None = None,
) -> None:
    """气声主旋律：基音 + 少量二次谐波 + 颤音与呼吸噪声，类似尺八/长笛。"""
    if freq <= 0.0 or gain == 0.0:
        return
    rate = buf.rate
    begin, first, end = _span(buf, start, duration)
    if first >= end:
        return
    left = buf.left
    right = buf.right
    gain_l, gain_r = pan_gains(pan)
    gain_l *= gain
    gain_r *= gain
    noise = (rng or random.Random(7)).uniform

    inc = freq * TABLE_SIZE / rate
    inc_h2 = inc * 2.0
    inc_h3 = inc * 3.0
    phase = 0.0
    phase_h2 = 0.0
    phase_h3 = 0.0
    attack_n = max(1, int(attack * rate))
    release_n = max(1, int(release * rate))
    vibrato_inc = vibrato_rate / rate
    vibrato_phase = 0.0
    breath_state = 0.0
    breath_coeff = 1.0 - math.exp(-TAU * 2600.0 / rate)
    for idx in range(first, end):
        i = idx - begin
        if i < attack_n:
            amplitude = (i + 1) / attack_n
        else:
            remaining = end - idx
            amplitude = 1.0 if remaining >= release_n else remaining / release_n
        if i % 96 == 0:
            vibrato = 1.0 + vibrato_depth * SINE[
                int(vibrato_phase * TABLE_SIZE) & TABLE_MASK
            ]
        breath_state += breath_coeff * (noise(-1.0, 1.0) - breath_state)
        value = (
            SINE[int(phase) & TABLE_MASK]
            + 0.22 * SINE[int(phase_h2) & TABLE_MASK]
            + 0.1 * SINE[int(phase_h3) & TABLE_MASK]
            + breath * breath_state
        ) * amplitude
        left[idx] += value * gain_l
        right[idx] += value * gain_r
        phase += inc * vibrato
        phase_h2 += inc_h2 * vibrato
        phase_h3 += inc_h3 * vibrato
        vibrato_phase += vibrato_inc
        if vibrato_phase >= 1.0:
            vibrato_phase -= 1.0
        if phase >= TABLE_SIZE:
            phase -= TABLE_SIZE
        if phase_h2 >= TABLE_SIZE:
            phase_h2 -= TABLE_SIZE
        if phase_h3 >= TABLE_SIZE:
            phase_h3 -= TABLE_SIZE


def add_bass(
    buf: Buffer,
    start: float,
    duration: float,
    freq: float,
    gain: float,
    pan: float = 0.0,
    *,
    attack: float = 0.008,
    release: float = 0.06,
    warmth: float = 0.3,
    cutoff: float = 620.0,
) -> None:
    """低频基础音：正弦为主，混入少量温暖锯齿，并做低通避免浑浊。"""
    if freq <= 0.0 or gain == 0.0:
        return
    rate = buf.rate
    begin, first, end = _span(buf, start, duration)
    if first >= end:
        return
    left = buf.left
    right = buf.right
    gain_l, gain_r = pan_gains(pan)
    gain_l *= gain
    gain_r *= gain

    inc = freq * TABLE_SIZE / rate
    phase = 0.0
    phase_saw = 0.0
    attack_n = max(1, int(attack * rate))
    release_n = max(1, int(release * rate))
    coeff = 1.0 - math.exp(-TAU * cutoff / rate)
    lowpass = 0.0
    for idx in range(first, end):
        i = idx - begin
        if i < attack_n:
            amplitude = (i + 1) / attack_n
        else:
            remaining = end - idx
            amplitude = 1.0 if remaining >= release_n else remaining / release_n
        lowpass += coeff * (
            WARM_TABLE[int(phase_saw) & TABLE_MASK]
            - lowpass
        )
        value = (
            SINE[int(phase) & TABLE_MASK] + lowpass * warmth
        ) * amplitude
        left[idx] += value * gain_l
        right[idx] += value * gain_r
        phase += inc
        phase_saw += inc
        if phase >= TABLE_SIZE:
            phase -= TABLE_SIZE
        if phase_saw >= TABLE_SIZE:
            phase_saw -= TABLE_SIZE


def add_bell(
    buf: Buffer,
    start: float,
    freq: float,
    gain: float,
    pan: float = 0.0,
    *,
    ratios: tuple[float, ...] = (1.0, 2.01, 2.97, 4.24),
    taus: tuple[float, ...] | None = None,
    attack: float = 0.002,
) -> None:
    """非谐分音钟体，用于弹刀与回响点缀。"""
    if freq <= 0.0 or gain == 0.0:
        return
    rate = buf.rate
    decays = taus or tuple(0.7 / (index + 1) ** 0.8 for index in range(len(ratios)))
    for order, (ratio, tau) in enumerate(zip(ratios, decays)):
        partial_gain = gain / (order * 0.55 + 1.0)
        duration = max(0.05, tau * 4.2)
        begin, first, end = _span(buf, start, duration)
        if first >= end:
            continue
        left = buf.left
        right = buf.right
        gain_l, gain_r = pan_gains(pan * (1.0 if order % 2 == 0 else -1.0))
        gain_l *= partial_gain
        gain_r *= partial_gain
        inc = freq * ratio * TABLE_SIZE / rate
        phase = 0.0
        attack_n = max(1, int(attack * rate))
        decay_factor = math.exp(-1.0 / (tau * rate))
        amplitude = 1.0
        for idx in range(first, end):
            i = idx - begin
            value = SINE[int(phase) & TABLE_MASK] * (
                amplitude if i >= attack_n else (i + 1) / attack_n
            )
            left[idx] += value * gain_l
            right[idx] += value * gain_r
            phase += inc
            if phase >= TABLE_SIZE:
                phase -= TABLE_SIZE
            amplitude *= decay_factor


def add_kick(
    buf: Buffer,
    start: float,
    gain: float,
    *,
    start_freq: float = 130.0,
    end_freq: float = 46.0,
    decay: float = 0.2,
    click: float = 0.25,
    rng: random.Random | None = None,
) -> None:
    """底鼓：音高下滑正弦 + 极短瞬态。"""
    rate = buf.rate
    begin, first, end = _span(buf, start, decay * 4.0)
    if first >= end:
        return
    left = buf.left
    right = buf.right
    sweep = 1.0 / max(1, int(0.06 * rate))
    decay_factor = math.exp(-1.0 / (decay * rate))
    amplitude = 1.0
    phase = 0.0
    noise = (rng or random.Random(11)).uniform
    for idx in range(first, end):
        progress = (idx - begin) * sweep
        freq = end_freq + (start_freq - end_freq) * math.exp(-progress * 6.0)
        value = math.sin(phase) * amplitude
        if idx - begin < int(0.004 * rate):
            value += noise(-1.0, 1.0) * click
        left[idx] += value * gain
        right[idx] += value * gain
        phase += TAU * freq / rate
        amplitude *= decay_factor


def add_taiko(
    buf: Buffer,
    start: float,
    gain: float,
    pan: float = 0.0,
    *,
    freq: float = 165.0,
    end_freq: float = 88.0,
    decay: float = 0.32,
    noise_mix: float = 0.35,
    rng: random.Random | None = None,
) -> None:
    """太鼓：厚实但不轰鸣，低频集中在 90~170Hz，不与刀音争抢。"""
    rate = buf.rate
    begin, first, end = _span(buf, start, decay * 4.0)
    if first >= end:
        return
    left = buf.left
    right = buf.right
    gain_l, gain_r = pan_gains(pan)
    gain_l *= gain
    gain_r *= gain
    decay_factor = math.exp(-1.0 / (decay * rate))
    amplitude = 1.0
    phase = 0.0
    noise_state = 0.0
    coeff = 1.0 - math.exp(-TAU * 900.0 / rate)
    noise = (rng or random.Random(13)).uniform
    for idx in range(first, end):
        progress = (idx - begin) / rate
        freq_now = end_freq + (freq - end_freq) * math.exp(-progress * 12.0)
        noise_state += coeff * (noise(-1.0, 1.0) - noise_state)
        value = (
            math.sin(phase) * amplitude
            + noise_state * amplitude * noise_mix
        )
        left[idx] += value * gain_l
        right[idx] += value * gain_r
        phase += TAU * freq_now / rate
        amplitude *= decay_factor


def add_tick(
    buf: Buffer,
    start: float,
    gain: float,
    pan: float = 0.0,
    *,
    decay: float = 0.09,
    tone: float = 210.0,
    noise_mix: float = 0.7,
    rng: random.Random | None = None,
) -> None:
    """木质/金属边击，担当战斗音乐的军鼓位，力度刻意压低。"""
    rate = buf.rate
    begin, first, end = _span(buf, start, decay * 5.0)
    if first >= end:
        return
    left = buf.left
    right = buf.right
    gain_l, gain_r = pan_gains(pan)
    gain_l *= gain
    gain_r *= gain
    decay_factor = math.exp(-1.0 / (decay * rate))
    amplitude = 1.0
    phase = 0.0
    noise_state = 0.0
    coeff = 1.0 - math.exp(-TAU * 1900.0 / rate)
    noise = (rng or random.Random(17)).uniform
    for idx in range(first, end):
        noise_state += coeff * (noise(-1.0, 1.0) - noise_state)
        value = (
            math.sin(phase) * (1.0 - noise_mix) + noise_state * noise_mix
        ) * amplitude
        left[idx] += value * gain_l
        right[idx] += value * gain_r
        phase += TAU * tone / rate
        amplitude *= decay_factor


def add_hat(
    buf: Buffer,
    start: float,
    gain: float,
    pan: float = 0.0,
    *,
    decay: float = 0.045,
    highpass: float = 6200.0,
    rng: random.Random | None = None,
) -> None:
    """踩镲：高通过滤的短噪声，只在 6kHz 以上，给节奏提供推进感。"""
    rate = buf.rate
    begin, first, end = _span(buf, start, decay * 5.0)
    if first >= end:
        return
    left = buf.left
    right = buf.right
    gain_l, gain_r = pan_gains(pan)
    gain_l *= gain
    gain_r *= gain
    decay_factor = math.exp(-1.0 / (decay * rate))
    amplitude = 1.0
    noise = (rng or random.Random(19)).uniform
    coeff = 1.0 - math.exp(-TAU * highpass / rate)
    lowpass = 0.0
    for idx in range(first, end):
        sample = noise(-1.0, 1.0)
        lowpass += coeff * (sample - lowpass)
        value = (sample - lowpass) * amplitude
        left[idx] += value * gain_l
        right[idx] += value * gain_r
        amplitude *= decay_factor


def add_whoosh(
    buf: Buffer,
    start: float,
    duration: float,
    gain: float,
    pan: float = 0.0,
    *,
    freq_start: float = 700.0,
    freq_end: float = 2800.0,
    attack: float = 0.22,
    shape: float = 1.6,
    resonance: float = 0.0,
    rng: random.Random | None = None,
) -> None:
    """挥击/位移用的气声：噪声经随时间移动的带通，避免低频轰鸣。"""
    rate = buf.rate
    begin, first, end = _span(buf, start, duration)
    if first >= end:
        return
    left = buf.left
    right = buf.right
    gain_l, gain_r = pan_gains(pan)
    gain_l *= gain
    gain_r *= gain
    noise = (rng or random.Random(23)).uniform
    attack_n = max(1, int(attack * duration * rate))
    total = max(1, end - begin)
    lowpass = 0.0
    bandpass = 0.0
    coeff = 0.0
    for idx in range(first, end):
        i = idx - begin
        if i % 64 == 0:
            progress = i / total
            freq_now = freq_start * ((freq_end / freq_start) ** (progress**0.85))
            coeff = 1.0 - math.exp(-TAU * min(freq_now, rate * 0.45) / rate)
        sample = noise(-1.0, 1.0)
        lowpass += coeff * (sample - lowpass)
        if resonance > 0.0:
            bandpass += coeff * (lowpass - bandpass)
            sample = lowpass + bandpass * resonance
        else:
            sample = lowpass
        if i < attack_n:
            amplitude = (i + 1) / attack_n
        else:
            amplitude = ((total - i) / (total - attack_n)) ** shape
        value = sample * amplitude
        left[idx] += value * gain_l
        right[idx] += value * gain_r


def add_tone_sweep(
    buf: Buffer,
    start: float,
    duration: float,
    gain: float,
    pan: float = 0.0,
    *,
    freq_start: float = 760.0,
    freq_end: float = 210.0,
    table: array = WARM_TABLE,
    attack: float = 0.004,
    shape: float = 2.0,
    curve: float = 1.0,
    block: int = 64,
) -> None:
    """扫频音调：为刀身与冲击提供中频核心，避免音效只剩噪声的“沙”感。"""
    rate = buf.rate
    begin, first, end = _span(buf, start, duration)
    if first >= end or gain == 0.0:
        return
    left = buf.left
    right = buf.right
    gain_l, gain_r = pan_gains(pan)
    gain_l *= gain
    gain_r *= gain
    total = max(1, end - begin)
    attack_n = max(1, int(attack * rate))
    phase = 0.0
    inc = freq_start * TABLE_SIZE / rate
    for idx in range(first, end):
        i = idx - begin
        if i % block == 0:
            progress = i / total
            freq_now = freq_start + (freq_end - freq_start) * (progress**curve)
            inc = max(10.0, freq_now) * TABLE_SIZE / rate
        if i < attack_n:
            amplitude = (i + 1) / attack_n
        else:
            amplitude = ((total - i) / (total - attack_n)) ** shape
        value = table[int(phase) & TABLE_MASK] * amplitude
        left[idx] += value * gain_l
        right[idx] += value * gain_r
        phase += inc
        if phase >= TABLE_SIZE:
            phase -= TABLE_SIZE


def add_bandpass_sweep(
    buf: Buffer,
    start: float,
    duration: float,
    gain: float,
    pan: float = 0.0,
    *,
    freq_start: float = 600.0,
    freq_end: float = 2400.0,
    q: float = 3.0,
    attack: float = 0.08,
    shape: float = 1.8,
    stages: int = 2,
    rng: random.Random | None = None,
    block: int = 32,
) -> None:
    """高 Q 带通扫频噪声：把宽带噪声收成有音高的刀风，听感更“锐”而不是“沙”。"""
    rate = buf.rate
    begin, first, end = _span(buf, start, duration)
    if first >= end or gain == 0.0:
        return
    left = buf.left
    right = buf.right
    gain_l, gain_r = pan_gains(pan)
    gain_l *= gain
    gain_r *= gain
    noise = (rng or random.Random(31)).uniform
    total = max(1, end - begin)
    attack_n = max(1, int(attack * duration * rate))
    state = [[0.0, 0.0, 0.0, 0.0] for _ in range(max(1, stages))]
    b0 = 0.0
    b2 = 0.0
    a1 = 0.0
    a2 = 0.0
    for idx in range(first, end):
        i = idx - begin
        if i % block == 0:
            progress = i / total
            freq_now = freq_start * ((freq_end / freq_start) ** (progress**0.9))
            omega = TAU * min(max(freq_now, 20.0), rate * 0.45) / rate
            sin_w = math.sin(omega)
            cos_w = math.cos(omega)
            alpha = sin_w / (2.0 * q)
            norm = 1.0 + alpha
            b0 = alpha / norm
            b2 = -alpha / norm
            a1 = -2.0 * cos_w / norm
            a2 = (1.0 - alpha) / norm
        sample = noise(-1.0, 1.0)
        for stage in state:
            v = sample - a1 * stage[2] - a2 * stage[3]
            value = b0 * v + b2 * stage[1]
            stage[1] = stage[0]
            stage[0] = v
            stage[3] = stage[2]
            stage[2] = value
            sample = value
        if i < attack_n:
            amplitude = (i + 1) / attack_n
        else:
            amplitude = ((total - i) / (total - attack_n)) ** shape
        sample *= amplitude
        left[idx] += sample * gain_l
        right[idx] += sample * gain_r


def add_swell(
    buf: Buffer,
    start: float,
    duration: float,
    gain: float,
    pan: float = 0.0,
    *,
    cutoff: float = 3000.0,
    release: float = 0.14,
    rng: random.Random | None = None,
) -> None:
    """反向膨胀噪声，用于段落转换或受击前的紧张感。

    末尾自动做短促收尾，避免在循环点被硬切出咔哒声。
    """
    rate = buf.rate
    begin, first, end = _span(buf, start, duration)
    if first >= end:
        return
    left = buf.left
    right = buf.right
    gain_l, gain_r = pan_gains(pan)
    gain_l *= gain
    gain_r *= gain
    noise = (rng or random.Random(29)).uniform
    total = max(1, end - begin)
    release_n = max(1, int(release * rate))
    coeff = 1.0 - math.exp(-TAU * cutoff / rate)
    lowpass = 0.0
    for idx in range(first, end):
        i = idx - begin
        progress = i / total
        lowpass += coeff * (noise(-1.0, 1.0) - lowpass)
        tail = min(1.0, (total - i) / release_n)
        value = lowpass * (progress**2.2) * tail
        left[idx] += value * gain_l
        right[idx] += value * gain_r


# ---------------------------------------------------------------------------
# 效果处理
# ---------------------------------------------------------------------------


def lowpass(buf: Buffer, cutoff: float, passes: int = 1) -> None:
    rate = buf.rate
    coeff = 1.0 - math.exp(-TAU * min(cutoff, rate * 0.45) / rate)
    for _ in range(passes):
        for channel in (buf.left, buf.right):
            state = 0.0
            for index in range(buf.length):
                state += coeff * (channel[index] - state)
                channel[index] = state


def highpass(buf: Buffer, cutoff: float, passes: int = 1) -> None:
    rate = buf.rate
    coeff = math.exp(-TAU * min(cutoff, rate * 0.45) / rate)
    for _ in range(passes):
        for channel in (buf.left, buf.right):
            previous_in = channel[0]
            state = 0.0
            for index in range(buf.length):
                sample = channel[index]
                state = coeff * (state + sample - previous_in)
                previous_in = sample
                channel[index] = state


def peaking_eq(
    buf: Buffer,
    freq: float,
    q: float,
    gain_db: float,
) -> None:
    """RBJ 峰值均衡，用来给音效腾出频段（gain_db 为负即挖坑）。"""
    rate = buf.rate
    amplitude = 10.0 ** (gain_db / 40.0)
    omega = TAU * freq / rate
    alpha = math.sin(omega) / (2.0 * q)
    cos_omega = math.cos(omega)
    b0 = 1.0 + alpha * amplitude
    b1 = -2.0 * cos_omega
    b2 = 1.0 - alpha * amplitude
    a0 = 1.0 + alpha / amplitude
    a1 = -2.0 * cos_omega
    a2 = 1.0 - alpha / amplitude
    b0 /= a0
    b1 /= a0
    b2 /= a0
    a1 /= a0
    a2 /= a0
    for channel in (buf.left, buf.right):
        x1 = x2 = y1 = y2 = 0.0
        for index in range(buf.length):
            sample = channel[index]
            value = (
                b0 * sample + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
            )
            x2, x1 = x1, sample
            y2, y1 = y1, value
            channel[index] = value


def high_shelf_eq(
    buf: Buffer,
    freq: float,
    gain_db: float,
    q: float = 0.9,
) -> None:
    """RBJ 高架均衡：用来压掉刀剑音效里多余的嘶声，让能量落回中频。"""
    if abs(gain_db) < 0.01:
        return
    rate = buf.rate
    amplitude = 10.0 ** (gain_db / 40.0)
    omega = TAU * freq / rate
    sin_w = math.sin(omega)
    cos_w = math.cos(omega)
    alpha = sin_w / (2.0 * q)
    sqrt_a = math.sqrt(amplitude)
    b0 = amplitude * (
        (amplitude + 1.0)
        + (amplitude - 1.0) * cos_w
        + 2.0 * sqrt_a * alpha
    )
    b1 = -2.0 * amplitude * (
        (amplitude - 1.0) + (amplitude + 1.0) * cos_w
    )
    b2 = amplitude * (
        (amplitude + 1.0)
        + (amplitude - 1.0) * cos_w
        - 2.0 * sqrt_a * alpha
    )
    a0 = (
        (amplitude + 1.0)
        - (amplitude - 1.0) * cos_w
        + 2.0 * sqrt_a * alpha
    )
    a1 = 2.0 * ((amplitude - 1.0) - (amplitude + 1.0) * cos_w)
    a2 = (
        (amplitude + 1.0)
        - (amplitude - 1.0) * cos_w
        - 2.0 * sqrt_a * alpha
    )
    b0 /= a0
    b1 /= a0
    b2 /= a0
    a1 /= a0
    a2 /= a0
    for channel in (buf.left, buf.right):
        x1 = x2 = y1 = y2 = 0.0
        for index in range(buf.length):
            sample = channel[index]
            value = b0 * sample + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
            x2, x1 = x1, sample
            y2, y1 = y1, value
            channel[index] = value


def low_shelf_eq(
    buf: Buffer,
    freq: float,
    gain_db: float,
    q: float = 0.9,
) -> None:
    """RBJ 低架均衡：把重量集中到中低频“胸腔”区，是调整厚实感的主要旋钮。

    相比单纯加大低频层的音量，低架提升不会让噪声变成轰鸣，
    在笔记本扬声器这类低频衰减严重的设备上也更容易听出厚度。
    """
    if abs(gain_db) < 0.01:
        return
    rate = buf.rate
    amplitude = 10.0 ** (gain_db / 40.0)
    omega = TAU * freq / rate
    sin_w = math.sin(omega)
    cos_w = math.cos(omega)
    alpha = sin_w / (2.0 * q)
    sqrt_a = math.sqrt(amplitude)
    b0 = amplitude * (
        (amplitude + 1.0)
        - (amplitude - 1.0) * cos_w
        + 2.0 * sqrt_a * alpha
    )
    b1 = 2.0 * amplitude * (
        (amplitude - 1.0) - (amplitude + 1.0) * cos_w
    )
    b2 = amplitude * (
        (amplitude + 1.0)
        - (amplitude - 1.0) * cos_w
        - 2.0 * sqrt_a * alpha
    )
    a0 = (
        (amplitude + 1.0)
        + (amplitude - 1.0) * cos_w
        + 2.0 * sqrt_a * alpha
    )
    a1 = -2.0 * ((amplitude - 1.0) + (amplitude + 1.0) * cos_w)
    a2 = (
        (amplitude + 1.0)
        + (amplitude - 1.0) * cos_w
        - 2.0 * sqrt_a * alpha
    )
    b0 /= a0
    b1 /= a0
    b2 /= a0
    a1 /= a0
    a2 /= a0
    for channel in (buf.left, buf.right):
        x1 = x2 = y1 = y2 = 0.0
        for index in range(buf.length):
            sample = channel[index]
            value = b0 * sample + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
            x2, x1 = x1, sample
            y2, y1 = y1, value
            channel[index] = value


def delay_echo(
    buf: Buffer,
    delay: float,
    feedback: float,
    mix: float,
    *,
    wrap: bool = False,
    ping_pong: float = 0.0,
) -> None:
    """反馈延迟。wrap=True 时尾部回声绕回开头，保证音乐循环无接缝。"""
    rate = buf.rate
    offset = max(1, int(round(delay * rate)))
    for channel_index, channel in enumerate((buf.left, buf.right)):
        source = array("d", channel)
        other = buf.right if channel_index == 0 else buf.left
        for repeat in range(0, 8):
            gain = feedback**repeat
            if gain < 0.02:
                break
            if repeat == 0:
                cross_source = source
            elif ping_pong > 0.0:
                cross_source = other
            else:
                cross_source = source
            step = offset * repeat
            if wrap:
                for index in range(buf.length):
                    target = index - step
                    if target < 0:
                        target += buf.length
                    channel[index] += cross_source[target] * mix * gain
            else:
                for index in range(step, buf.length):
                    channel[index] += cross_source[index - step] * mix * gain


def soft_clip(buf: Buffer, drive: float = 1.4) -> None:
    for channel in (buf.left, buf.right):
        for index in range(buf.length):
            value = channel[index] * drive
            channel[index] = value / (1.0 + abs(value) * 0.55)


def apply_fades(
    buf: Buffer,
    fade_in: float = 0.002,
    fade_out: float = 0.02,
) -> None:
    rate = buf.rate
    fade_in_n = max(1, int(fade_in * rate))
    fade_out_n = max(1, int(fade_out * rate))
    for channel in (buf.left, buf.right):
        for index in range(min(fade_in_n, buf.length)):
            channel[index] *= index / fade_in_n
        for index in range(min(fade_out_n, buf.length)):
            position = buf.length - 1 - index
            channel[position] *= index / fade_out_n


def normalize(buf: Buffer, peak_db: float) -> None:
    peak = 0.0
    for channel in (buf.left, buf.right):
        for value in channel:
            magnitude = abs(value)
            if magnitude > peak:
                peak = magnitude
    if peak <= 0.0:
        return
    target = 10.0 ** (peak_db / 20.0)
    scale = target / peak
    for channel in (buf.left, buf.right):
        for index in range(buf.length):
            channel[index] *= scale


def measure(buf: Buffer) -> tuple[float, float]:
    """返回 (峰值 dBFS, 有效值 dBFS)。"""
    peak = 0.0
    energy = 0.0
    count = 0
    for channel in (buf.left, buf.right):
        for value in channel:
            magnitude = abs(value)
            if magnitude > peak:
                peak = magnitude
            energy += value * value
            count += 1
    rms = math.sqrt(energy / max(1, count))
    to_db = lambda value: 20.0 * math.log10(value) if value > 1e-9 else -120.0
    return to_db(peak), to_db(rms)


def downsample(buf: Buffer, factor: int, *, wrap: bool = False) -> Buffer:
    """带 FIR 抗混叠的整数倍降采样，wrap=True 时按循环缓冲处理边界。"""
    if factor <= 1:
        return buf
    target_rate = buf.rate // factor
    taps = 15
    center = taps // 2
    cutoff = 0.45 * target_rate / buf.rate
    kernel = []
    for index in range(taps):
        x = index - center
        if x == 0:
            value = 2.0 * cutoff
        else:
            value = math.sin(TAU * cutoff * x) / (math.pi * x)
        window = 0.54 - 0.46 * math.cos(TAU * index / (taps - 1))
        kernel.append(value * window)
    total = sum(kernel)
    kernel = [value / total for value in kernel]

    out_length = buf.length // factor
    result = Buffer(0.0, target_rate)
    result.length = out_length
    result.left = array("d", bytes(8 * out_length))
    result.right = array("d", bytes(8 * out_length))
    for channel_in, channel_out in (
        (buf.left, result.left),
        (buf.right, result.right),
    ):
        for index in range(out_length):
            base = index * factor - center
            accumulator = 0.0
            for tap in range(taps):
                position = base + tap
                if 0 <= position < buf.length:
                    accumulator += channel_in[position] * kernel[tap]
                elif wrap:
                    accumulator += channel_in[position % buf.length] * kernel[tap]
            channel_out[index] = accumulator
    return result


def write_wav(path: Path, buf: Buffer, *, channels: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = array("h", bytes(2 * buf.length * channels))
    left = buf.left
    right = buf.right
    if channels == 2:
        for index in range(buf.length):
            data[2 * index] = _to_pcm(left[index])
            data[2 * index + 1] = _to_pcm(right[index])
    else:
        for index in range(buf.length):
            data[index] = _to_pcm((left[index] + right[index]) * 0.5)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(buf.rate)
        handle.writeframes(data.tobytes())


def _to_pcm(value: float) -> int:
    scaled = int(round(value * 32767.0))
    if scaled > 32767:
        return 32767
    if scaled < -32768:
        return -32768
    return scaled


# ---------------------------------------------------------------------------
# 音乐：大厅主题
# ---------------------------------------------------------------------------


LOBBY_BPM = 62.0
LOBBY_BARS = 16

# 每小节一个和弦（音名沿用科学音高记号，数字为八度）
LOBBY_PROGRESSION: tuple[tuple[str, ...], ...] = (
    ("A2", "E3", "A3", "C4", "G4"),  # Am7
    ("F2", "C3", "A3", "E4", "G4"),  # Fmaj7(9)
    ("C3", "G3", "C4", "E4", "B4"),  # Cmaj7
    ("G2", "D3", "B3", "D4", "E4"),  # G6
    ("A2", "E3", "A3", "C4", "G4"),  # Am7
    ("F2", "C3", "A3", "E4", "G4"),  # Fmaj7(9)
    ("D3", "A3", "D4", "F4", "C5"),  # Dm7
    ("G2", "D3", "B3", "D4", "E4"),  # G6
    ("F2", "C3", "F3", "A3", "E4"),  # Fmaj7
    ("G2", "D3", "G3", "B3", "D4"),  # G
    ("E2", "B2", "E3", "G3", "D4"),  # Em7
    ("A2", "E3", "A3", "C4", "G4"),  # Am7
    ("A2", "E3", "A3", "C4", "E4"),  # Am
    ("F2", "C3", "A3", "C4", "E4"),  # Fmaj7
    ("C3", "G3", "C4", "E4", "B4"),  # Cmaj7
    ("G2", "D3", "B3", "D4", "F4"),  # G7，导向下一轮 Am
)

LOBBY_BASS: tuple[str, ...] = (
    "A1",
    "F1",
    "C2",
    "G1",
    "A1",
    "F1",
    "D2",
    "G1",
    "F1",
    "G1",
    "E1",
    "A1",
    "A1",
    "F1",
    "C2",
    "G1",
)

# 主旋律采用 A 小调五声音阶，分句留白，避免循环时显得拥挤
LOBBY_MELODY: tuple[tuple[float, str, float], ...] = (
    (4.0, "E4", 1.5),
    (5.5, "G4", 1.0),
    (6.5, "A4", 0.5),
    (7.0, "C5", 1.0),
    (8.0, "G4", 2.0),
    (10.0, "E4", 0.5),
    (10.5, "D4", 1.0),
    (11.5, "E4", 0.5),
    (12.0, "A4", 2.0),
    (14.0, "G4", 1.0),
    (15.0, "D4", 1.0),
    (16.0, "E4", 1.5),
    (17.5, "D4", 0.5),
    (18.0, "C4", 2.0),
    (20.0, "A3", 1.5),
    (21.5, "C4", 0.5),
    (22.0, "D4", 2.0),
    (24.0, "E4", 1.0),
    (25.0, "G4", 1.0),
    (26.0, "A4", 1.5),
    (27.5, "G4", 0.5),
    (28.0, "E4", 2.0),
    (30.0, "D4", 1.0),
    (31.0, "C4", 1.0),
    (32.0, "A3", 3.0),
    (36.0, "C5", 1.0),
    (37.0, "B4", 1.0),
    (38.0, "A4", 1.5),
    (39.5, "G4", 0.5),
    (40.0, "E4", 2.0),
    (42.0, "G4", 1.0),
    (43.0, "A4", 3.0),
    (48.0, "C5", 1.0),
    (49.0, "D5", 1.0),
    (50.0, "E5", 2.0),
    (52.0, "D5", 1.0),
    (53.0, "C5", 1.0),
    (54.0, "A4", 2.0),
    (56.0, "G4", 1.0),
    (57.0, "E4", 1.0),
    (58.0, "D4", 2.0),
    (60.0, "E4", 1.5),
)


def _lobby_arp_pattern(chord: tuple[str, ...], bar_index: int) -> list[str]:
    """按和弦音级生成八分音符分解和弦，不同小节换方向以增加变化。"""
    tones = [chord[2], chord[3], chord[4], chord[3]] if bar_index % 2 else [
        chord[4],
        chord[3],
        chord[2],
        chord[3],
    ]
    upper = [chord[3], chord[4], chord[2], chord[4]]
    return tones + upper


def build_lobby_theme() -> Buffer:
    beat = 60.0 / LOBBY_BPM
    bar = beat * 4.0
    loop_seconds = bar * LOBBY_BARS
    preroll = 3.0
    buf = Buffer(loop_seconds + preroll)
    offset = preroll
    rng = random.Random(311)

    for bar_index, chord in enumerate(LOBBY_PROGRESSION):
        start = offset + bar_index * bar
        section = bar_index // 4
        root = note_frequency(LOBBY_BASS[bar_index])
        pad_gain = 0.30 + 0.03 * min(section, 3)
        for voice_index, name in enumerate(chord[:4]):
            detune = (-1.0) ** voice_index * 0.004
            pan = (-0.55, -0.2, 0.2, 0.55)[voice_index]
            add_pad(
                buf,
                start + rng.uniform(-0.004, 0.004),
                bar + 1.6,
                note_frequency(name),
                pad_gain * (0.9 if voice_index else 1.0),
                pan,
                attack=1.1 + 0.25 * voice_index,
                release=1.5,
                detune=0.0035 + 0.0008 * voice_index,
                cutoff=1500.0 + 260.0 * voice_index,
            )
        add_bass(
            buf,
            start,
            bar * 0.92,
            root,
            0.26 + 0.05 * min(section, 3),
            attack=0.06,
            release=0.9,
            cutoff=520.0,
        )
        # 第五音作为高音点缀，不常出现
        if bar_index % 4 == 3:
            add_pad(
                buf,
                start + beat * 2.0,
                beat * 1.6,
                note_frequency(chord[4]) * 2.0,
                0.09,
                0.3,
                attack=0.5,
                release=1.0,
                cutoff=2600.0,
                table=HOLLOW_TABLE,
            )

    # 分解和弦层：前 4 小节稀疏，之后逐步加入
    for bar_index, chord in enumerate(LOBBY_PROGRESSION):
        section = bar_index // 4
        if bar_index >= 12 and bar_index % 4 == 3:
            continue
        pattern = _lobby_arp_pattern(chord, bar_index)
        density = 0.6 if section == 0 else 0.85
        for step_index, name in enumerate(pattern):
            if bar_index < 4 and step_index % 2 == 1:
                continue
            if rng.random() > density + 0.15:
                continue
            start = (
                offset
                + bar_index * bar
                + step_index * beat * 0.5
                + rng.uniform(-0.012, 0.012)
            )
            gain = (0.06 if section == 0 else 0.085) * rng.uniform(0.75, 1.15)
            if step_index >= 6:
                gain *= 0.72
            add_pluck(
                buf,
                start,
                1.1,
                note_frequency(name) * 2.0,
                gain,
                pan=rng.uniform(-0.35, 0.35),
                brightness=6.5,
                decay=1.35,
                detune_cents=rng.uniform(-4.0, 4.0),
            )
        # 后半段的空气感高频点缀，避免整体听感发闷
        if bar_index >= 8 and bar_index % 2 == 0:
            add_pluck(
                buf,
                offset + bar_index * bar + beat * 2.0,
                2.4,
                note_frequency(chord[4]) * 4.0,
                0.022,
                pan=0.42,
                brightness=8.0,
                decay=2.4,
                table=HOLLOW_TABLE,
            )

    # 主旋律
    for time_in_beats, name, length_beats in LOBBY_MELODY:
        start = offset + time_in_beats * beat + rng.uniform(-0.015, 0.015)
        duration = length_beats * beat * 0.92
        add_breath_lead(
            buf,
            start,
            duration,
            note_frequency(name),
            0.115,
            pan=0.12,
            attack=0.09,
            release=0.28,
            vibrato_depth=0.0032,
            breath=0.045,
            rng=rng,
        )
        # 旋律的低八度轻叠，让线条更厚但依然柔和
        add_pluck(
            buf,
            start,
            duration * 0.9,
            note_frequency(name) * 0.5,
            0.05,
            pan=-0.15,
            brightness=3.0,
            decay=1.4,
        )

    # “回响”钟声点缀
    for bar_index, name in ((4, "A5"), (8, "E5"), (12, "C5"), (15, "G4")):
        add_bell(
            buf,
            offset + bar_index * bar,
            note_frequency(name),
            0.055,
            pan=0.25 if bar_index % 8 else -0.25,
            ratios=(1.0, 2.02, 2.98, 4.21, 5.4),
            taus=(1.6, 1.0, 0.7, 0.45, 0.3),
        )

    # 中低音对位线，只在后半段出现
    for bar_index in range(8, LOBBY_BARS):
        chord = LOBBY_PROGRESSION[bar_index]
        start = offset + bar_index * bar + beat * 2.0
        add_pluck(
            buf,
            start,
            beat * 1.7,
            note_frequency(chord[2]) * 0.5,
            0.06,
            pan=rng.uniform(-0.3, 0.3),
            brightness=2.6,
            decay=1.6,
            table=WARM_TABLE,
        )

    # 循环预滚裁剪 + 环绕回声，保证接缝处自然
    loop = buf.slice_from(preroll)
    delay_echo(loop, beat * 0.75, 0.34, 0.2, wrap=True, ping_pong=0.3)
    lowpass(loop, 9000.0)
    highpass(loop, 42.0)
    normalize(loop, -7.0)
    return downsample(loop, RENDER_RATE // MUSIC_EXPORT_RATE, wrap=True)


# ---------------------------------------------------------------------------
# 音乐：战斗主题
# ---------------------------------------------------------------------------


BATTLE_BPM = 140.0
BATTLE_BARS = 32

# 每小节一个和弦，E 大调属和弦提供张力，最后导向 Am
BATTLE_PROGRESSION: tuple[tuple[str, ...], ...] = (
    ("A2", "E3", "A3", "C4"),  # Am
    ("F2", "C3", "A3", "F4"),  # F
    ("C3", "G3", "C4", "E4"),  # C
    ("G2", "D3", "B3", "D4"),  # G
    ("A2", "E3", "A3", "C4"),
    ("F2", "C3", "A3", "F4"),
    ("D3", "A3", "D4", "F4"),  # Dm
    ("E2", "B2", "G#3", "E4"),  # E
    ("A2", "E3", "A3", "C4"),
    ("F2", "C3", "A3", "F4"),
    ("C3", "G3", "C4", "E4"),
    ("G2", "D3", "B3", "D4"),
    ("A2", "E3", "A3", "C4"),
    ("F2", "C3", "A3", "F4"),
    ("D3", "A3", "D4", "F4"),
    ("E2", "B2", "G#3", "E4"),
    ("A2", "E3", "A3", "C4"),
    ("A2", "E3", "A3", "C4"),
    ("F2", "C3", "A3", "F4"),
    ("F2", "C3", "A3", "F4"),
    ("C3", "G3", "C4", "E4"),
    ("G2", "D3", "B3", "D4"),
    ("D3", "A3", "D4", "F4"),
    ("E2", "B2", "G#3", "E4"),
    ("A2", "E3", "A3", "C4"),
    ("F2", "C3", "A3", "F4"),
    ("C3", "G3", "C4", "E4"),
    ("G2", "D3", "B3", "D4"),
    ("A2", "E3", "A3", "C4"),
    ("F2", "C3", "A3", "F4"),
    ("G2", "D3", "B3", "D4"),
    ("E2", "B2", "G#3", "E4"),
)

BATTLE_LEAD: tuple[tuple[float, str, float], ...] = (
    (4.0, "A4", 0.5),
    (4.5, "C5", 0.5),
    (5.0, "E5", 1.0),
    (6.0, "D5", 0.5),
    (6.5, "C5", 0.5),
    (7.0, "A4", 1.0),
    (8.0, "C5", 0.5),
    (8.5, "E5", 0.5),
    (9.0, "G5", 1.0),
    (10.0, "E5", 0.5),
    (10.5, "C5", 0.5),
    (11.0, "A4", 1.0),
    (12.0, "D5", 0.5),
    (12.5, "E5", 0.5),
    (13.0, "F5", 1.0),
    (14.0, "E5", 0.5),
    (14.5, "D5", 0.5),
    (15.0, "B4", 1.0),
    (16.0, "A4", 0.5),
    (16.5, "B4", 0.5),
    (17.0, "C5", 1.5),
    (19.0, "A4", 1.0),
    (20.0, "G4", 0.5),
    (20.5, "A4", 0.5),
    (21.0, "C5", 1.5),
    (23.0, "D5", 1.0),
    (24.0, "E5", 0.5),
    (24.5, "F5", 0.5),
    (25.0, "E5", 1.5),
    (27.0, "C5", 1.0),
    (28.0, "D5", 0.5),
    (28.5, "E5", 0.5),
    (29.0, "B4", 1.5),
    (31.0, "G#4", 1.0),
    (32.0, "A4", 1.5),
    (34.0, "C5", 0.5),
    (34.5, "B4", 0.5),
    (35.0, "A4", 1.5),
    (37.0, "G4", 0.5),
    (37.5, "A4", 0.5),
    (38.0, "C5", 2.0),
    (40.0, "B4", 0.5),
    (40.5, "C5", 0.5),
    (41.0, "D5", 1.5),
    (43.0, "E5", 1.0),
    (44.0, "D5", 0.5),
    (44.5, "C5", 0.5),
    (45.0, "B4", 1.0),
    (46.0, "A4", 2.0),
    (48.0, "C5", 0.5),
    (48.5, "D5", 0.5),
    (49.0, "E5", 1.0),
    (50.0, "G5", 1.0),
    (51.0, "E5", 1.0),
    (52.0, "F5", 0.5),
    (52.5, "E5", 0.5),
    (53.0, "D5", 1.5),
    (55.0, "B4", 1.0),
    (56.0, "E5", 0.5),
    (56.5, "D5", 0.5),
    (57.0, "C5", 1.5),
    (59.0, "B4", 0.5),
    (59.5, "C5", 0.5),
    (60.0, "A4", 2.0),
    (62.0, "G#4", 1.0),
    (63.0, "A4", 1.0),
)


def build_battle_theme() -> Buffer:
    """战斗背景：节奏推进明确，但把 2kHz~4kHz 让给攻击与弹刀音效。"""
    beat = 60.0 / BATTLE_BPM
    bar = beat * 4.0
    loop_seconds = bar * BATTLE_BARS
    preroll = 3.5
    buf = Buffer(loop_seconds + preroll)
    lead_buf = Buffer(loop_seconds + preroll)
    offset = preroll
    rng = random.Random(907)

    def place_pad(start: float, chord: tuple[str, ...], gain: float) -> None:
        for voice_index, name in enumerate(chord[:3]):
            add_pad(
                buf,
                start,
                bar * 1.05,
                note_frequency(name),
                gain * (0.85**voice_index),
                pan=(-0.4, 0.0, 0.4)[voice_index],
                attack=0.35,
                release=0.3,
                detune=0.005,
                tremolo=0.05,
                cutoff=1550.0,
            )

    for bar_index, chord in enumerate(BATTLE_PROGRESSION):
        start = offset + bar_index * bar
        section = bar_index // 8
        breakdown = 16 <= bar_index < 20
        build_up = 20 <= bar_index < 24
        root = note_frequency(chord[0])

        # 铺底：低音量长音，填补中低频
        place_pad(start, chord, 0.16 if breakdown else 0.12)

        # 八分音符低音 ostinato
        for step in range(8):
            if breakdown and step % 2 == 1:
                continue
            accent = 1.0 if step % 4 == 0 else 0.78
            octave_up = 1.0 if step % 4 == 2 else 0.5
            note_start = (
                start + step * beat * 0.5 + rng.uniform(-0.006, 0.006)
            )
            add_bass(
                buf,
                note_start,
                beat * 0.42,
                root * octave_up,
                0.085 * accent,
                attack=0.006,
                release=0.04,
                warmth=0.42,
                cutoff=760.0,
            )

        # 节奏：太鼓 + 边击 + 踩镲
        if not breakdown:
            add_taiko(buf, start, 0.14, -0.1, decay=0.3, rng=rng)
            add_taiko(buf, start + beat * 2.0, 0.115, 0.1, decay=0.26, rng=rng)
            add_taiko(buf, start + beat * 3.5, 0.08, -0.15, decay=0.22, rng=rng)
            add_tick(buf, start + beat * 1.0, 0.115, 0.22, rng=rng)
            add_tick(buf, start + beat * 3.0, 0.12, -0.18, rng=rng)
            if build_up:
                add_tick(buf, start + beat * 2.5, 0.06, 0.3, rng=rng)
                add_kick(
                    buf, start + beat * 3.75, 0.16, decay=0.16, rng=rng
                )
            if bar_index % 4 == 3:
                for fill in range(4):
                    add_tick(
                        buf,
                        start + beat * 3.0 + fill * beat * 0.25,
                        0.07 + 0.025 * fill,
                        0.3 - 0.15 * fill,
                        decay=0.05,
                        tone=240.0 + 40.0 * fill,
                        rng=rng,
                    )
            for step in range(8):
                if step % 2 == 1:
                    add_hat(
                        buf,
                        start + step * beat * 0.5,
                        0.08 if not build_up else 0.095,
                        pan=-0.25 + 0.5 * (step % 2),
                        rng=rng,
                    )
        else:
            add_kick(buf, start, 0.2, decay=0.26, start_freq=110.0, click=0.15, rng=rng)
            add_taiko(buf, start + beat * 2.5, 0.13, 0.12, decay=0.3, rng=rng)

        # 和弦短促点缀：走高音区，与刀音分离
        if not breakdown:
            for step in (1, 3, 5, 7):
                note_name = chord[(step // 2) % len(chord)]
                add_pluck(
                    lead_buf,
                    start + step * beat * 0.5 + rng.uniform(-0.008, 0.008),
                    beat * 0.4,
                    note_frequency(note_name) * 2.0,
                    0.09 * rng.uniform(0.8, 1.15),
                    pan=rng.uniform(-0.45, 0.45) * -1.0,
                    brightness=3.4,
                    decay=0.34,
                    table=HOLLOW_TABLE,
                )

    # 主旋律
    for time_in_beats, name, length_beats in BATTLE_LEAD:
        start = offset + time_in_beats * beat + rng.uniform(-0.01, 0.01)
        add_breath_lead(
            lead_buf,
            start,
            length_beats * beat * 0.95,
            note_frequency(name),
            0.16,
            pan=rng.uniform(-0.2, 0.2),
            attack=0.03,
            release=0.12,
            vibrato_depth=0.004,
            breath=0.06,
            rng=rng,
        )

    # 段落转换的膨胀噪声与低音鼓滚动
    for bar_index, duration in ((15, 1.6), (19, 1.2), (23, 1.6), (31, 1.2)):
        start = offset + bar_index * bar + bar - duration
        add_swell(buf, start, duration, 0.09, pan=0.0, cutoff=3400.0, rng=rng)

    # 循环衔接：把上一轮最后两小节的铺底尾巴补进开头，避免接缝处被硬切
    for bar_index in range(BATTLE_BARS - 2, BATTLE_BARS):
        place_pad(
            offset + bar_index * bar - loop_seconds,
            BATTLE_PROGRESSION[bar_index],
            0.12,
        )

    add_bell(
        buf,
        offset,
        note_frequency("A5"),
        0.075,
        pan=0.3,
        ratios=(1.0, 2.01, 2.97, 4.24),
        taus=(0.9, 0.6, 0.4, 0.25),
    )
    add_bell(
        buf,
        offset + 16 * bar,
        note_frequency("E5"),
        0.065,
        pan=-0.3,
        ratios=(1.0, 2.01, 2.97, 4.24),
        taus=(0.9, 0.6, 0.4, 0.25),
    )

    # 仅对旋律与点缀层施加回声，避免鼓组被糊掉
    delay_echo(lead_buf, beat * 0.75, 0.3, 0.22, wrap=True, ping_pong=0.5)
    lowpass(lead_buf, 5200.0)
    buf.mix_from(lead_buf.slice_from(preroll), 0.9)
    loop = buf.slice_from(preroll)

    # 关键处理：给音效让出确认感频段
    peaking_eq(loop, 3000.0, 0.9, -5.0)
    peaking_eq(loop, 4200.0, 1.1, -2.0)
    lowpass(loop, 8200.0, passes=2)
    highpass(loop, 36.0)
    normalize(loop, -6.5)
    return downsample(loop, RENDER_RATE // MUSIC_EXPORT_RATE, wrap=True)


# ---------------------------------------------------------------------------
# 音效
# ---------------------------------------------------------------------------


def build_step_sfx(variant: int) -> Buffer:
    rng = random.Random(1200 + variant)
    buf = Buffer(0.11)
    add_whoosh(
        buf,
        0.0,
        0.09,
        0.5,
        pan=0.0,
        freq_start=520.0 + 90.0 * variant,
        freq_end=260.0,
        attack=0.06,
        shape=2.4,
        rng=rng,
    )
    add_kick(
        buf,
        0.0,
        0.18,
        start_freq=110.0,
        end_freq=72.0,
        decay=0.028,
        click=0.06,
        rng=rng,
    )
    normalize(buf, -20.0)
    apply_fades(buf, 0.001, 0.02)
    return buf


def build_land_sfx() -> Buffer:
    rng = random.Random(1301)
    buf = Buffer(0.24)
    add_kick(
        buf,
        0.0,
        0.5,
        start_freq=120.0,
        end_freq=58.0,
        decay=0.075,
        click=0.12,
        rng=rng,
    )
    add_whoosh(
        buf,
        0.0,
        0.16,
        0.32,
        freq_start=1500.0,
        freq_end=380.0,
        attack=0.04,
        shape=2.6,
        rng=rng,
    )
    normalize(buf, -13.0)
    apply_fades(buf, 0.0015, 0.03)
    return buf


def build_jump_sfx() -> Buffer:
    rng = random.Random(1409)
    buf = Buffer(0.28)
    rate = buf.rate
    # 轻微上扬的气声，避免做成沉重的“起跳
    add_whoosh(
        buf,
        0.0,
        0.19,
        0.34,
        freq_start=620.0,
        freq_end=2100.0,
        attack=0.18,
        shape=2.0,
        rng=rng,
    )
    # 柔和的音高上滑主体
    length = int(0.17 * rate)
    phase = 0.0
    for index in range(length):
        progress = index / length
        freq = 250.0 + 320.0 * (progress**1.3)
        amplitude = (progress**0.6) * ((1.0 - progress) ** 1.4)
        buf.left[index] += math.sin(phase) * amplitude * 0.32
        buf.right[index] += math.sin(phase) * amplitude * 0.32
        phase += TAU * freq / rate
    normalize(buf, -16.0)
    apply_fades(buf, 0.0015, 0.03)
    return buf


def build_dash_sfx() -> Buffer:
    rng = random.Random(1511)
    buf = Buffer(0.3)
    add_whoosh(
        buf,
        0.0,
        0.26,
        0.55,
        freq_start=780.0,
        freq_end=3200.0,
        attack=0.26,
        shape=1.8,
        resonance=0.35,
        rng=rng,
    )
    add_whoosh(
        buf,
        0.02,
        0.2,
        0.22,
        freq_start=2600.0,
        freq_end=900.0,
        attack=0.3,
        shape=1.5,
        rng=rng,
    )
    normalize(buf, -15.0)
    apply_fades(buf, 0.002, 0.04)
    return buf


def build_swing_sfx(stage: int) -> Buffer:
    """挥刀：宽频气流为主体，三段连击音高逐级升高。

    上一版用低 Q 带通共振堆低频，容易听成“管子里吹气”。现版本改为：
    气流层用低通扫频（宽频、无共振峰）提供厚度，高频层用温和带通给出刀锋，
    再用一个短促的金属刃鸣收尾。三段连击整体音高按 1.0 / 1.26 / 1.58 倍提升，
    让三连击听起来是一次比一次高、一次比一次快。
    """
    rng = random.Random(1607 + stage)
    buf = Buffer(0.4)
    # 三段连击的音高倍数：+6 半音、+12 半音，一耳可辨
    pitch = (1.0, 1.41, 2.0)[stage - 1]
    span = 0.26 - 0.02 * (stage - 1)

    # 1) 刀风主体：宽频气流由亮到暗扫过，是“挥刀”的主要识别音
    add_whoosh(
        buf,
        0.0,
        span,
        1.0,
        freq_start=5200.0 * pitch,
        freq_end=950.0 * pitch,
        attack=0.08,
        shape=1.9,
        rng=rng,
    )
    # 2) 刀身重量：中低频气流，提供“推开空气”的厚度
    add_whoosh(
        buf,
        0.0,
        span * 1.2,
        1.3,
        freq_start=1100.0 * pitch,
        freq_end=320.0 * pitch,
        attack=0.11,
        shape=1.5,
        rng=rng,
    )
    # 3) 刃鸣：非常短的一下金属声，点到为止
    add_bell(
        buf,
        0.003,
        3000.0 * pitch,
        0.34,
        pan=0.15,
        ratios=(1.0, 1.5),
        taus=(0.075, 0.045),
    )
    # 4) 音高线索：短促的音调下扫，让三段连击的高低差异明确可辨
    add_tone_sweep(
        buf,
        0.0,
        0.16,
        0.4,
        freq_start=740.0 * pitch,
        freq_end=380.0 * pitch,
        table=WARM_TABLE,
        attack=0.01,
        shape=1.8,
    )
    # 频谱塑形：这是“厚实而不嘶”的关键。
    # 噪声天然是每升高一个八度能量更多，必须显式压掉高频、抬起中低频。
    highpass(buf, 140.0, passes=2)
    low_shelf_eq(buf, 350.0 * pitch, 6.0, 0.8)
    peaking_eq(buf, 900.0 * pitch, 0.8, 5.0)
    high_shelf_eq(buf, 4000.0 * pitch, -9.0, 0.7)
    soft_clip(buf, 1.6)
    normalize(buf, -7.5 + 0.5 * (stage - 1))
    apply_fades(buf, 0.0008, 0.05)
    return buf


def build_hit_sfx() -> Buffer:
    """命中敌人的额外确认音：硬、短、带碎裂感的“哐”。

    之前偏软的原因是金属层衰减太长（听起来像共鸣而不是撞击）。
    现在所有层的衰减都在 80ms 以内：4ms 硬瞬态 + 失真碎裂噪声 + 极短金属声
    + 紧实低频冲击，整体是一个干脆的撞击脉冲。
    """
    rng = random.Random(1709)
    buf = Buffer(0.34)
    # 1) 硬起音：4ms 全频瞬态，决定“打上去”的第一下硬度
    add_whoosh(
        buf,
        0.0,
        0.006,
        1.2,
        freq_start=12000.0,
        freq_end=4000.0,
        attack=0.4,
        shape=1.3,
        rng=rng,
    )
    # 2) 碎裂噪声：中高频短促爆发，制造“打碎”的质感
    add_bandpass_sweep(
        buf,
        0.0,
        0.075,
        2.2,
        freq_start=4300.0,
        freq_end=1500.0,
        q=1.5,
        attack=0.04,
        shape=2.4,
        rng=rng,
    )
    # 3) 金属撞击：极短的一下“当”，只做确认，不做共鸣
    add_bell(
        buf,
        0.0,
        2900.0,
        0.7,
        pan=0.1,
        ratios=(1.0, 1.48, 2.2, 3.15),
        taus=(0.055, 0.038, 0.026, 0.018),
    )
    add_bell(
        buf,
        0.001,
        1850.0,
        0.4,
        pan=-0.12,
        ratios=(1.0, 1.75, 2.55),
        taus=(0.05, 0.034, 0.022),
    )
    # 3.5) 中频爆裂：500~1500Hz 的短促层，这是“硬”的关键（缺了它只剩轰响+脆响）
    add_whoosh(
        buf,
        0.0,
        0.11,
        2.6,
        freq_start=1800.0,
        freq_end=650.0,
        attack=0.05,
        shape=1.8,
        rng=rng,
    )
    # 4) 紧实冲击：短促有力，收得干净
    add_kick(
        buf,
        0.0,
        0.6,
        start_freq=280.0,
        end_freq=78.0,
        decay=0.05,
        click=0.7,
        rng=rng,
    )
    # 5) 频谱塑形：补足 500~1500Hz 的中频“咔嚓”，避免只剩轰响加脆响
    low_shelf_eq(buf, 300.0, -2.0, 0.85)
    peaking_eq(buf, 900.0, 0.9, 4.0)
    high_shelf_eq(buf, 5000.0, -6.0, 0.8)
    # 6) 硬度：较强软削波增加谐波，让撞击更硬更实
    soft_clip(buf, 2.6)
    highpass(buf, 60.0)
    normalize(buf, -4.5)
    apply_fades(buf, 0.0004, 0.05)
    return buf


def build_enemy_attack_sfx() -> Buffer:
    """敌人发动攻击时的提示音：比玩家挥刀更暗、更低，便于分辨。"""
    rng = random.Random(1811)
    buf = Buffer(0.36)
    add_whoosh(
        buf,
        0.0,
        0.24,
        0.55,
        freq_start=300.0,
        freq_end=1250.0,
        attack=0.16,
        shape=1.7,
        resonance=0.3,
        rng=rng,
    )
    add_whoosh(
        buf,
        0.1,
        0.2,
        0.32,
        freq_start=1200.0,
        freq_end=420.0,
        attack=0.3,
        shape=1.8,
        rng=rng,
    )
    # 低沉的脉动，暗示“即将命中”的威胁
    length = int(0.24 * buf.rate)
    phase = 0.0
    for index in range(length):
        progress = index / length
        freq = 190.0 - 60.0 * progress
        amplitude = (progress**0.5) * ((1.0 - progress) ** 1.2)
        value = math.sin(phase) * amplitude * 0.3
        buf.left[index] += value * 0.8
        buf.right[index] += value
        phase += TAU * freq / buf.rate
    normalize(buf, -14.0)
    apply_fades(buf, 0.002, 0.045)
    return buf


def build_hurt_sfx() -> Buffer:
    """角色被命中造成伤害的额外音效：闷响 + 短促失真，力度克制。"""
    rng = random.Random(1907)
    buf = Buffer(0.42)
    add_kick(
        buf,
        0.0,
        0.45,
        start_freq=170.0,
        end_freq=64.0,
        decay=0.11,
        click=0.2,
        rng=rng,
    )
    add_whoosh(
        buf,
        0.0,
        0.16,
        0.4,
        freq_start=900.0,
        freq_end=240.0,
        attack=0.06,
        shape=2.0,
        resonance=0.25,
        rng=rng,
    )
    # 低沉的短促人声感：锯齿 + 带通
    rate = buf.rate
    length = int(0.16 * rate)
    phase = 0.0
    for index in range(length):
        progress = index / length
        freq = 220.0 - 70.0 * progress
        amplitude = (progress**0.35) * ((1.0 - progress) ** 1.6)
        value = (
            SINE[int(phase) & TABLE_MASK] * 0.6
            + WARM_TABLE[int(phase) & TABLE_MASK] * 0.4
        ) * amplitude
        buf.left[index] += value * 0.22
        buf.right[index] += value * 0.22
        phase += TAU * freq / rate
        if phase >= TABLE_SIZE:
            phase -= TABLE_SIZE
    soft_clip(buf, 1.25)
    normalize(buf, -10.5)
    apply_fades(buf, 0.0012, 0.05)
    return buf


def build_parry_sfx() -> Buffer:
    """弹刀：干脆利落的金属撞击，不是敲钟。

    上一版主钟体衰减 0.9 秒、还带一串 0.19 秒延迟回声，听感变成“敲钟”。
    现在把所有分音的衰减压到 0.03~0.16 秒，去掉延迟回声，
    只保留短促的中频躯干（620Hz，0.085 秒）来维持厚度，
    整体在 0.3 秒内基本衰减干净，但起音依然是全套最亮最响的。
    """
    rng = random.Random(2026)
    buf = Buffer(0.42)
    # 主金属体：2450Hz 基音 + 非谐分音，快速衰落的“叮”
    add_bell(
        buf,
        0.0,
        2450.0,
        1.15,
        pan=0.08,
        ratios=(1.0, 1.66, 2.44, 3.3, 4.6),
        taus=(0.095, 0.065, 0.045, 0.03, 0.02),
        attack=0.0008,
    )
    # 微失谐第二钟体（相差约 26Hz）：闪一下的金属质感，不再形成长尾
    add_bell(
        buf,
        0.0012,
        2480.0,
        0.5,
        pan=-0.08,
        ratios=(1.0, 1.64, 2.4, 3.25),
        taus=(0.08, 0.055, 0.036, 0.024),
        attack=0.001,
    )
    # 中频躯干：一小拍 760Hz，给厚度但收得极快
    add_bell(
        buf,
        0.0,
        760.0,
        0.5,
        pan=0.0,
        ratios=(1.0, 1.5, 2.2),
        taus=(0.085, 0.055, 0.035),
        attack=0.0012,
    )
    # 低频冲击体：一小拍 220Hz，提供“重”的实感（衰减 75ms，不会变闷闷的钟）
    add_bell(
        buf,
        0.0,
        220.0,
        0.62,
        pan=0.0,
        ratios=(1.0, 1.6, 2.4),
        taus=(0.06, 0.04, 0.026),
        attack=0.0015,
    )
    # 高频咬合层：5200Hz 的短促一亮，增加“锋利”的存在感
    add_bell(
        buf,
        0.0,
        5200.0,
        0.5,
        pan=-0.05,
        ratios=(1.0, 1.5),
        taus=(0.035, 0.022),
        attack=0.0006,
    )
    # 硬起音：12ms 高频瞬态，决定“利落”的第一印象
    add_whoosh(
        buf,
        0.0,
        0.012,
        1.1,
        freq_start=13000.0,
        freq_end=5400.0,
        attack=0.25,
        shape=2.0,
        rng=rng,
    )
    # 高频碎响：短促的火花，替代原来的回声串
    add_bandpass_sweep(
        buf,
        0.0,
        0.08,
        1.0,
        freq_start=8200.0,
        freq_end=5200.0,
        q=2.6,
        attack=0.05,
        shape=2.6,
        stages=1,
        rng=rng,
    )
    # 极短拍击：32ms 的单次拍击（无反馈）提升密度与“厚”，不会拖尾
    delay_echo(buf, 0.032, 0.0, 0.25, ping_pong=0.5)
    # 密度与硬度：软削波提高有效音量感，而不是把峰值继续拉高
    soft_clip(buf, 2.2)
    # 去掉低频轰鸣与中频浑浊，但保留一段中低躯干避免变薄
    highpass(buf, 100.0, passes=2)
    low_shelf_eq(buf, 400.0, 3.8, 0.9)
    peaking_eq(buf, 330.0, 0.8, -1.5)
    peaking_eq(buf, 2450.0, 1.1, 4.0)
    normalize(buf, -1.5)
    apply_fades(buf, 0.0005, 0.04)
    return buf


def build_parry_ready_sfx() -> Buffer:
    """举刀架势：极短的金属轻响，提示弹刀窗口已开启。"""
    buf = Buffer(0.22)
    add_bell(
        buf,
        0.0,
        2680.0,
        0.35,
        pan=0.1,
        ratios=(1.0, 2.2),
        taus=(0.075, 0.04),
    )
    add_bandpass_sweep(
        buf,
        0.0,
        0.1,
        0.3,
        freq_start=3200.0,
        freq_end=5200.0,
        q=3.6,
        attack=0.16,
        shape=2.2,
    )
    highpass(buf, 500.0)
    normalize(buf, -16.0)
    apply_fades(buf, 0.001, 0.03)
    return buf


def build_spawn_sfx() -> Buffer:
    """敌人登场：低位膨胀噪声“接近”+ 落地冲击 + 金属余韵。"""
    rng = random.Random(2213)
    buf = Buffer(0.9)
    add_swell(buf, 0.0, 0.5, 0.55, pan=0.0, cutoff=2400.0, rng=rng)
    add_kick(
        buf,
        0.48,
        0.6,
        start_freq=150.0,
        end_freq=60.0,
        decay=0.17,
        click=0.18,
        rng=rng,
    )
    add_bell(
        buf,
        0.48,
        960.0,
        0.24,
        pan=0.0,
        ratios=(1.0, 1.62, 2.4),
        taus=(0.32, 0.19, 0.11),
    )
    normalize(buf, -13.0)
    apply_fades(buf, 0.002, 0.1)
    return buf


def build_portal_open_sfx() -> Buffer:
    """回响之门开启：上升的膨胀噪声 + 明亮钟体，像门被推开。"""
    rng = random.Random(2311)
    buf = Buffer(1.1)
    add_swell(buf, 0.0, 0.55, 0.6, pan=0.0, cutoff=3200.0, rng=rng)
    add_bell(
        buf,
        0.42,
        1320.0,
        0.5,
        pan=0.06,
        ratios=(1.0, 1.5, 2.25, 3.4),
        taus=(0.42, 0.26, 0.16, 0.1),
    )
    add_bell(
        buf,
        0.5,
        1980.0,
        0.3,
        pan=-0.08,
        ratios=(1.0, 1.48, 2.2),
        taus=(0.3, 0.18, 0.11),
    )
    add_whoosh(
        buf,
        0.4,
        0.3,
        0.35,
        freq_start=900.0,
        freq_end=4200.0,
        attack=0.35,
        shape=1.6,
        rng=rng,
    )
    normalize(buf, -11.0)
    apply_fades(buf, 0.002, 0.12)
    return buf


def build_portal_enter_sfx() -> Buffer:
    """进入传送门：气流被吸入门内 + 明亮钟体 + 低频收束。"""
    rng = random.Random(2317)
    buf = Buffer(1.0)
    add_whoosh(
        buf,
        0.0,
        0.5,
        0.7,
        freq_start=5200.0,
        freq_end=700.0,
        attack=0.12,
        shape=1.7,
        rng=rng,
    )
    add_bell(
        buf,
        0.1,
        1560.0,
        0.55,
        pan=0.0,
        ratios=(1.0, 1.52, 2.3, 3.5),
        taus=(0.4, 0.25, 0.15, 0.09),
    )
    add_kick(
        buf,
        0.42,
        0.5,
        start_freq=190.0,
        end_freq=64.0,
        decay=0.2,
        click=0.12,
        rng=rng,
    )
    normalize(buf, -10.0)
    apply_fades(buf, 0.002, 0.14)
    return buf


def build_defeat_sfx() -> Buffer:
    """敌人被击败：回响碎裂，短促但明确。"""
    """敌人被击败：回响碎裂，短促但明确。"""
    rng = random.Random(2113)
    buf = Buffer(0.7)
    add_kick(
        buf,
        0.0,
        0.5,
        start_freq=150.0,
        end_freq=52.0,
        decay=0.16,
        click=0.12,
        rng=rng,
    )
    add_whoosh(
        buf,
        0.0,
        0.34,
        0.4,
        freq_start=4200.0,
        freq_end=700.0,
        attack=0.05,
        shape=2.0,
        rng=rng,
    )
    add_bell(
        buf,
        0.02,
        1560.0,
        0.22,
        pan=-0.2,
        ratios=(1.0, 2.4, 3.7),
        taus=(0.28, 0.16, 0.09),
    )
    normalize(buf, -12.0)
    apply_fades(buf, 0.001, 0.06)
    return buf


MONO_SFX = {
    "step_0",
    "step_1",
    "step_2",
    "step_3",
    "land",
    "jump",
    "dash",
    "swing_1",
    "swing_2",
    "swing_3",
    "enemy_attack",
    "hurt",
}


def build_sfx() -> dict[str, Buffer]:
    items: dict[str, Buffer] = {}
    for variant in range(4):
        items[f"step_{variant}"] = build_step_sfx(variant)
    items["land"] = build_land_sfx()
    items["jump"] = build_jump_sfx()
    items["dash"] = build_dash_sfx()
    for stage in (1, 2, 3):
        items[f"swing_{stage}"] = build_swing_sfx(stage)
    items["hit"] = build_hit_sfx()
    items["enemy_attack"] = build_enemy_attack_sfx()
    items["hurt"] = build_hurt_sfx()
    items["parry"] = build_parry_sfx()
    items["parry_ready"] = build_parry_ready_sfx()
    items["spawn"] = build_spawn_sfx()
    items["portal_open"] = build_portal_open_sfx()
    items["portal_enter"] = build_portal_enter_sfx()
    items["defeat"] = build_defeat_sfx()
    return items


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def _report(path: Path, buf: Buffer, channels: int) -> None:
    peak_db, rms_db = measure(buf)
    size_kb = path.stat().st_size / 1024.0
    print(
        f"  {path.name:<20} {buf.seconds:6.2f}s  "
        f"{buf.rate:>5}Hz x{channels}  峰值 {peak_db:6.2f}dB  "
        f"有效值 {rms_db:6.2f}dB  {size_kb:8.1f}KB"
    )


def generate(kind: str) -> None:
    if kind in {"all", "music"}:
        print("生成背景音乐：")
        lobby = build_lobby_theme()
        lobby_path = MUSIC_DIR / "lobby_theme.wav"
        write_wav(lobby_path, lobby, channels=2)
        _report(lobby_path, lobby, 2)
        battle = build_battle_theme()
        battle_path = MUSIC_DIR / "battle_theme.wav"
        write_wav(battle_path, battle, channels=2)
        _report(battle_path, battle, 2)
    if kind in {"all", "sfx"}:
        print("生成音效：")
        for name, buf in build_sfx().items():
            channels = 1 if name in MONO_SFX else 2
            path = SFX_DIR / f"{name}.wav"
            write_wav(path, buf, channels=channels)
            _report(path, buf, channels)


def preview() -> None:
    import pygame

    pygame.mixer.pre_init(SFX_EXPORT_RATE, -16, 2, 512)
    pygame.mixer.init()
    print("试听音效序列……")
    order = [
        "step_0",
        "step_2",
        "jump",
        "land",
        "dash",
        "swing_1",
        "swing_2",
        "swing_3",
        "hit",
        "enemy_attack",
        "hurt",
        "parry_ready",
        "parry",
        "defeat",
    ]
    for name in order:
        path = SFX_DIR / f"{name}.wav"
        if not path.exists():
            continue
        print(f"  {name}")
        sound = pygame.mixer.Sound(str(path))
        channel = sound.play()
        pygame.time.wait(int(sound.get_length() * 1000) + 120)
        if channel is not None:
            channel.stop()
    print("试听音乐（各 12 秒）……")
    for name in ("lobby_theme", "battle_theme"):
        path = MUSIC_DIR / f"{name}.wav"
        if not path.exists():
            continue
        print(f"  {name}")
        pygame.mixer.music.load(str(path))
        pygame.mixer.music.set_volume(0.7)
        pygame.mixer.music.play()
        pygame.time.wait(12000)
        pygame.mixer.music.stop()
    pygame.mixer.quit()


def main() -> None:
    parser = argparse.ArgumentParser(description="生成《回响之刃》音频素材")
    parser.add_argument(
        "--only",
        choices=("all", "music", "sfx"),
        default="all",
        help="只生成指定类型的素材",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="生成后立刻用 pygame 试听（需要可用的音频设备）",
    )
    arguments = parser.parse_args()
    generate(arguments.only)
    print(f"素材目录：{SOUND_DIR}")
    if arguments.preview:
        preview()


if __name__ == "__main__":
    main()
