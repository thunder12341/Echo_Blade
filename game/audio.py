"""运行时音频系统：音乐切换、总线音量、音效限流与闪避（ducking）。

设计要点：
* 音乐与音效分两条总线，音乐默认只占 55% 音量，保证刀剑音效始终清晰。
* 大厅与战斗音乐用两个保留声道做交叉淡化，切换不会出现空档或爆音。
* 弹刀、命中、受击会短暂压低音乐（ducking），强化确认感。
* 缺少素材或没有音频设备时自动降级为静音，不影响游戏逻辑与测试。
"""

from __future__ import annotations

import random
from pathlib import Path

import pygame

MUSIC_BUS = 0.55
# 音效总线留出约 1dB 余量：挥刀与命中可能同帧叠加，避免削顶
SFX_BUS = 0.88
DEFAULT_FADE = 1.0

# 音乐：键名 -> 相对 sounds/ 的文件
MUSIC_FILES = {
    "lobby": "music/lobby_theme.wav",
    "battle": "music/battle_theme.wav",
}

# 音效：逻辑名 -> 候选文件（多个文件时随机播放，避免连续重复感）
SFX_FILES = {
    "step": (
        "sfx/step_0.wav",
        "sfx/step_1.wav",
        "sfx/step_2.wav",
        "sfx/step_3.wav",
    ),
    "land": ("sfx/land.wav",),
    "jump": ("sfx/jump.wav",),
    "dash": ("sfx/dash.wav",),
    "swing_1": ("sfx/swing_1.wav",),
    "swing_2": ("sfx/swing_2.wav",),
    "swing_3": ("sfx/swing_3.wav",),
    "hit": ("sfx/hit.wav",),
    "enemy_attack": ("sfx/enemy_attack.wav",),
    "hurt": ("sfx/hurt.wav",),
    "parry": ("sfx/parry.wav",),
    "parry_ready": ("sfx/parry_ready.wav",),
    "spawn": ("sfx/spawn.wav",),
    "portal_open": ("sfx/portal_open.wav",),
    "portal_enter": ("sfx/portal_enter.wav",),
    "defeat": ("sfx/defeat.wav",),
}

# 各类音效在总线之上的相对音量：脚步这类高频重复的声音刻意压低
SFX_GAIN = {
    "step": 0.42,
    "land": 0.55,
    "jump": 0.62,
    "dash": 0.7,
    "swing_1": 0.72,
    "swing_2": 0.74,
    "swing_3": 0.76,
    "hit": 0.9,
    "enemy_attack": 0.95,
    "hurt": 0.9,
    "parry": 1.0,
    "parry_ready": 0.6,
    "spawn": 0.9,
    "portal_open": 0.9,
    "portal_enter": 0.9,
    "defeat": 0.85,
}

# 同一音效的最小触发间隔，避免同帧多段音效叠加后糊掉
SFX_MIN_INTERVAL = {
    "step": 0.14,
    "swing_1": 0.06,
    "swing_2": 0.06,
    "swing_3": 0.06,
    "enemy_attack": 0.09,
    "hit": 0.05,
}


class AudioManager:
    """封装 pygame.mixer，向游戏暴露“播音乐 / 播音效”两种操作。"""

    def __init__(
        self,
        sound_dir: Path | str,
        *,
        volume: int = 80,
        enabled: bool = True,
    ) -> None:
        self.sound_dir = Path(sound_dir)
        self.enabled = bool(enabled)
        self.requested_track: str | None = None
        self.current_track: str | None = None
        self.volume = max(0, min(100, int(volume)))
        self._sounds: dict[str, pygame.mixer.Sound] = {}
        self._music: dict[str, pygame.mixer.Sound] = {}
        self._music_channels: list[pygame.mixer.Channel] = []
        self._music_volume = [0.0, 0.0]
        self._music_target = [0.0, 0.0]
        self._active_music = 0
        self._last_played: dict[str, float] = {}
        self._duck_factor = 1.0
        self._duck_timer = 0.0
        self._duck_amount = 0.0
        self._fade_rate = 1.0 / DEFAULT_FADE
        self._rng = random.Random(20260914)
        self._missing_reported = False
        if self.enabled:
            self.enabled = self._start_mixer()
        if self.enabled:
            self._load_assets()

    # -- 初始化 -----------------------------------------------------------

    def _start_mixer(self) -> bool:
        try:
            if pygame.mixer.get_init() is None:
                pygame.mixer.pre_init(44100, -16, 2, 512)
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            pygame.mixer.set_num_channels(24)
            pygame.mixer.set_reserved(2)
            self._music_channels = [pygame.mixer.Channel(0), pygame.mixer.Channel(1)]
        except (pygame.error, AttributeError, OSError):
            return False
        return True

    def _load_assets(self) -> None:
        for key, relative in MUSIC_FILES.items():
            sound = self._load_sound(relative)
            if sound is not None:
                self._music[key] = sound
        for key, candidates in SFX_FILES.items():
            for relative in candidates:
                sound = self._load_sound(relative)
                if sound is not None:
                    self._sounds[relative] = sound

    def _load_sound(self, relative: str) -> pygame.mixer.Sound | None:
        path = self.sound_dir / relative
        if not path.is_file():
            if not self._missing_reported:
                print(f"[audio] 缺少音频素材: {path}（将静音运行）")
                self._missing_reported = True
            return None
        try:
            return pygame.mixer.Sound(str(path))
        except (pygame.error, OSError):
            return None

    # -- 音量 -------------------------------------------------------------

    def set_volume(self, percent: int) -> None:
        self.volume = max(0, min(100, int(percent)))

    @property
    def music_gain(self) -> float:
        return (self.volume / 100.0) * MUSIC_BUS * self._duck_factor

    @property
    def sfx_gain(self) -> float:
        return (self.volume / 100.0) * SFX_BUS

    def duck(self, amount: float = 0.45, duration: float = 0.28) -> None:
        """短暂压低音乐，突出关键音效。"""
        if not self.enabled:
            return
        self._duck_amount = max(self._duck_amount, max(0.0, min(0.9, amount)))
        self._duck_timer = max(self._duck_timer, duration)

    # -- 音乐 -------------------------------------------------------------

    def play_music(self, track: str | None, fade: float = DEFAULT_FADE) -> None:
        """请求播放某条音乐；重复请求同一首会被忽略。"""
        if track == self.requested_track:
            return
        self.requested_track = track
        if not self.enabled:
            return
        if track is None:
            self._music_target = [-1.0, -1.0]
            self.current_track = None
            return
        sound = self._music.get(track)
        if sound is None:
            self.current_track = None
            return
        index = 1 - self._active_music
        channel = self._music_channels[index]
        try:
            channel.play(sound, loops=-1)
        except (pygame.error, AttributeError):
            return
        self._music_volume[index] = 0.0
        self._music_target[index] = 1.0
        self._music_target[self._active_music] = 0.0
        self._active_music = index
        self.current_track = track
        self._fade_rate = 1.0 / max(0.05, fade)

    def update(self, dt: float) -> None:
        """每帧调用：推进交叉淡化与闪避恢复。"""
        if not self.enabled:
            return
        if self._duck_timer > 0.0:
            self._duck_timer = max(0.0, self._duck_timer - dt)
            target = 1.0 - self._duck_amount
            self._duck_factor += (target - self._duck_factor) * min(1.0, dt * 18.0)
        else:
            self._duck_factor += (1.0 - self._duck_factor) * min(1.0, dt * 3.2)
            if self._duck_factor > 0.995:
                self._duck_factor = 1.0
                self._duck_amount = 0.0

        fade_rate = self._fade_rate
        gain = self.music_gain
        for index, channel in enumerate(self._music_channels):
            target = self._music_target[index]
            if target < 0.0:
                self._music_volume[index] = 0.0
                channel.stop()
                self._music_target[index] = 0.0
                continue
            current = self._music_volume[index]
            if current != target:
                step = fade_rate * dt
                current = (
                    min(target, current + step)
                    if current < target
                    else max(target, current - step)
                )
                self._music_volume[index] = current
            if current <= 0.0 and target == 0.0 and channel.get_busy():
                channel.stop()
            channel.set_volume(current * gain)

    def stop_music(self, fade: float = DEFAULT_FADE) -> None:
        self.play_music(None, fade)

    # -- 音效 -------------------------------------------------------------

    def play(self, name: str, volume: float = 1.0) -> None:
        if not self.enabled or self.volume <= 0:
            return
        candidates = SFX_FILES.get(name)
        if not candidates:
            return
        now = pygame.time.get_ticks() / 1000.0
        interval = SFX_MIN_INTERVAL.get(name, 0.03)
        if now - self._last_played.get(name, -99.0) < interval:
            return
        relative = (
            candidates[0] if len(candidates) == 1 else self._rng.choice(candidates)
        )
        sound = self._sounds.get(relative)
        if sound is None:
            return
        self._last_played[name] = now
        gain = SFX_GAIN.get(name, 0.8) * max(0.0, min(1.0, volume)) * self.sfx_gain
        try:
            sound.set_volume(gain)
            sound.play()
        except (pygame.error, AttributeError):
            return

    def play_swing(self, stage: int) -> None:
        self.play(f"swing_{max(1, min(3, int(stage)))}")

    def shutdown(self) -> None:
        if not self.enabled:
            return
        try:
            for channel in self._music_channels:
                channel.stop()
        except (pygame.error, AttributeError):
            pass
        self._music_target = [0.0, 0.0]
        self.current_track = None
        self.enabled = False
