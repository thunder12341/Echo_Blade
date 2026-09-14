from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

import pygame

from game.audio import AudioManager
from game.entities import AttackProfile, Chaser, Enemy, Hitbox, Player, SpearThrower
from settings import (
    COLORS,
    FPS,
    IMAGE_DIR,
    LOGICAL_SIZE,
    SAVE_FILE,
    SOUND_DIR,
    WINDOW_TITLE,
)

# 近战完美弹刀提示：闪光出现的提前量，同时决定弹刀窗口长度
MELEE_FLASH_LEAD = 0.45
# 远程弹道的可弹刀范围（像素）：子弹进入角色身边这个范围内按下弹刀即成功
PROJECTILE_PARRY_RANGE = 170.0
# 弹开的子弹飞回敌人的速度（像素/秒）
REFLECTED_PROJECTILE_SPEED = 900.0
# 进入关卡后敌人登场延迟（秒）
ENEMY_SPAWN_DELAY = 3.0
# 闪避残影的生成间隔与存在时间
DASH_TRAIL_INTERVAL = 0.035
DASH_TRAIL_LIFE = 0.32
# 关卡胜利后出现的传送门
PORTAL_WIDTH = 96
PORTAL_HEIGHT = 160
PORTAL_CENTER_X = 1150.0
PORTAL_GROUND_Y = 566.0
PORTAL_APPEAR_TIME = 0.8
PORTAL_ENTER_TIME = 0.75
PORTAL_RETRIGGER_LOCK = 0.6


@dataclass(frozen=True)
class MenuItem:
    label: str
    action: str
    enabled: bool = True


@dataclass(frozen=True)
class TutorialStep:
    title: str
    objective: str
    hint: str
    action: str


@dataclass
class PendingEnemyAttack:
    enemy: Enemy
    profile: AttackProfile
    remaining: float
    # 远程弹道起点/终点：用于绘制弹道与“贴身范围内可弹刀”判定
    origin: tuple[float, float] | None = None
    target: tuple[float, float] | None = None


@dataclass
class AttackImpact:
    x: float
    y: float
    parried: bool
    parryable: bool
    dodged: bool = False
    remaining: float = 0.24


@dataclass
class DashTrail:
    """闪避残影：记录生成时的位置与朝向。"""

    x: float
    y: float
    facing: int
    sprite: str
    remaining: float
    total: float


@dataclass
class ReflectedProjectile:
    """被弹开的子弹：飞回射击者的途中，命中后才结算伤害。"""

    x: float
    y: float
    target: Enemy
    damage: int
    speed: float = REFLECTED_PROJECTILE_SPEED


@dataclass(frozen=True)
class ProgressionNode:
    node_id: str
    branch: str
    title: str
    prerequisite: str | None
    requirement: str
    cost: int
    effect: str


PROGRESSION_NODES = (
    ProgressionNode(
        "aftershock_calibration",
        "锻刃谱系",
        "余震校准",
        None,
        "完成新手教程",
        40,
        "将「镜面余震」纳入临时强化池。",
    ),
    ProgressionNode(
        "refracted_afterglow",
        "锻刃谱系",
        "折光余温",
        "aftershock_calibration",
        "累计完成 3 次完美弹刀",
        70,
        "每局开场选择：普通攻击 +5% 或冲刺距离 +8%。",
    ),
    ProgressionNode(
        "twin_blade_license",
        "锻刃谱系",
        "双刃许可",
        "refracted_afterglow",
        "击破锈冠骑士 1 次",
        120,
        "解锁双短刃武器，形成高速连击分支。",
    ),
    ProgressionNode(
        "white_window_record",
        "共鸣谱系",
        "白窗记录",
        None,
        "完成新手教程",
        40,
        "训练房显示攻击前摇、完美窗口与反应时间。",
    ),
    ProgressionNode(
        "perfect_circuit",
        "共鸣谱系",
        "完美回路",
        "white_window_record",
        "累计完成 20 次完美弹刀",
        80,
        "每局首次完美弹刀额外获得 1 点回响能量。",
    ),
    ProgressionNode(
        "resonance_protocol",
        "共鸣谱系",
        "反响协议",
        "perfect_circuit",
        "单局反射 10 枚可反射投射物",
        130,
        "解锁回响枪与投射物构筑。",
    ),
    ProgressionNode(
        "route_cartography",
        "远征谱系",
        "路线测绘",
        None,
        "首次抵达第二区域",
        40,
        "预示下一层节点类型、危险标签与遗晶倍率。",
    ),
    ProgressionNode(
        "reserve_carry",
        "远征谱系",
        "余量携行",
        "route_cartography",
        "累计完成 3 次商店购买",
        70,
        "每局开场获得 20 点战时铸币。",
    ),
    ProgressionNode(
        "risk_covenant",
        "远征谱系",
        "风险契约",
        "reserve_carry",
        "热度 1 无伤完成精英房",
        110,
        "可主动提高威胁值，成功清房获得额外遗晶。",
    ),
    ProgressionNode(
        "city_seal",
        "终局节点",
        "城心钥印",
        None,
        "两条谱系各激活 2 个节点，并完成 10 次结算",
        180,
        "开放第五区域、城市心脏与终局热度层。",
    ),
)


class AssetStore:
    def __init__(self) -> None:
        self.background = self._load("title_background.png", alpha=False)
        self.logo = self._load("logo_emblem.png")
        self.player = self._load("player_idle.png")
        self.panel = self._load("menu_panel.png")
        self.cursor = self._load("menu_cursor.png")
        self.spark = self._load("parry_spark.png")
        self.player_sprites = {
            name: self._load_optional(filename)
            for name, filename in {
                "idle": "player_idle_v2.png",
                "run_0": "player_run_0.png",
                "run_1": "player_run_1.png",
                "jump": "player_jump.png",
                "fall": "player_fall.png",
                "attack_side": "player_attack_side.png",
                "attack_up": "player_attack_up.png",
                "attack_down": "player_attack_down.png",
            }.items()
        }
        self.enemy_sprites = {
            name: self._load_optional(filename)
            for name, filename in {
                "chaser": "enemy_chaser.png",
                "spear_thrower": "enemy_spear_thrower.png",
                "shield_guard": "enemy_shield_guard.png",
                "rift_worm": "enemy_rift_worm.png",
                "resonance_mage": "enemy_resonance_mage.png",
            }.items()
        }
        self.slash_sprites = {
            name: self._load_optional(filename)
            for name, filename in {
                "side": "slash_side.png",
                "up": "slash_up.png",
                "down": "slash_down.png",
            }.items()
        }
        self.portal_idle = [
            image
            for image in (
                self._load_optional("portal_idle_0.png"),
                self._load_optional("portal_idle_1.png"),
            )
            if image is not None
        ]
        self.portal_enter = [
            image
            for image in (
                self._load_optional(f"portal_enter_{index}.png")
                for index in range(4)
            )
            if image is not None
        ]

    @staticmethod
    def _load(filename: str, alpha: bool = True) -> pygame.Surface:
        path = IMAGE_DIR / filename
        if not path.exists():
            raise FileNotFoundError(f"找不到界面素材: {path}")
        image = pygame.image.load(path)
        return image.convert_alpha() if alpha else image.convert()

    @staticmethod
    def _load_optional(filename: str) -> pygame.Surface | None:
        path = IMAGE_DIR / filename
        if not path.exists():
            return None
        return pygame.image.load(path).convert_alpha()


class StartScreen:
    """Start menu plus the first playable room and result screen."""

    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self.canvas = pygame.Surface(LOGICAL_SIZE)
        self.assets = AssetStore()
        self.running = True
        self.clock = pygame.time.Clock()
        self.elapsed = 0.0
        self.notification = ""
        self.notification_timer = 0.0

        # page is the active full-screen state; overlay is kept for compatibility
        # with the original tests and makes the two menu panels easy to inspect.
        self.page = "menu"
        self.overlay: str | None = None
        self.return_page = "menu"
        self.overlay_selected = 0
        self.keybind_selected = 0
        self.rebinding_action: str | None = None
        self.confirm_exit = False
        self.pressed_item: int | None = None
        self.pressed_button: str | None = None
        self.pressed_keys: set[int] = set()
        self.tutorial_steps: list[TutorialStep] = []
        self.tutorial_index = 0
        self.tutorial_start_x = 0.0
        self.tutorial_move_distance = 0.0
        self.lobby_selected = 0
        self.progression_selected = 0
        self.is_tutorial_run = False

        self.profile = self._load_profile()
        saved_settings = self.profile.get("settings", {})
        if not isinstance(saved_settings, dict):
            saved_settings = {}
        self.settings = {
            "fullscreen": bool(saved_settings.get("fullscreen", False)),
            "assist_mode": bool(saved_settings.get("assist_mode", False)),
            "volume": max(0, min(100, int(saved_settings.get("volume", 80)))),
        }
        self.keybinds = self._load_keybinds(saved_settings.get("keybinds", {}))
        self._refresh_tutorial_hints()
        # 音频：音乐与音效分总线，音量沿用设置里的单一滑杆
        self.audio = AudioManager(SOUND_DIR, volume=self.settings["volume"])
        self._step_timer = 0.0
        self.audio.play_music(self._music_for_page())
        if self.settings["fullscreen"]:
            self._apply_display_mode()
        self.has_save = self._load_save()
        self.items = self._build_items()
        self.selected = next(
            (index for index, item in enumerate(self.items) if item.enabled),
            0,
        )

        self.run_floor = max(1, int(self.profile.get("best_floor", 1) or 1))
        self.run_score = 0
        self.run_combo = 0
        self.run_max_combo = 0
        self.run_parries = 0
        self.run_currency = 0
        self.player = Player(230, 566)
        self._attack_hits: set[tuple[int, int]] = set()
        self._defeated_enemies: set[int] = set()
        self.room_enemies: list[Enemy] = []
        self.pending_enemy_attacks: list[PendingEnemyAttack] = []
        self.attack_impacts: list[AttackImpact] = []
        self.dash_trails: list[DashTrail] = []
        self._dash_trail_timer = 0.0
        self._dash_was_active = False
        self._trail_surface_cache: dict[tuple[str, int], pygame.Surface] = {}
        self.reflected_projectiles: list[ReflectedProjectile] = []
        self.pending_spawn: list[Enemy] = []
        self.enemy_spawn_timer = 0.0
        self.portal_open = False
        self.portal_appear = 0.0
        self.portal_enter_timer = 0.0
        self.portal_lock_timer = 0.0
        self.portal_choice_index = 0
        self.result_score = 0
        self.result_new_record = False
        self.result_relics = 0

        self.title_font = self._font(56, bold=True)
        self.subtitle_font = self._font(18, bold=True)
        self.menu_font = self._font(25, bold=True)
        self.small_font = self._font(16)
        self.overlay_title_font = self._font(30, bold=True)
        self.overlay_body_font = self._font(19)
        self.lobby_title_font = self._font(34, bold=True)
        self.lobby_node_font = self._font(17, bold=True)

    @staticmethod
    def _font(size: int, bold: bool = False) -> pygame.font.Font:
        pygame.font.init()
        windows_dir = Path(os.environ.get("WINDIR", "C:/Windows"))
        filenames = (
            ("msyhbd.ttc", "simhei.ttf", "msyh.ttc")
            if bold
            else ("msyh.ttc", "simhei.ttf", "simsun.ttc")
        )
        for filename in filenames:
            font_path = windows_dir / "Fonts" / filename
            if not font_path.is_file():
                continue
            try:
                return pygame.font.Font(str(font_path), size)
            except (OSError, TypeError, pygame.error):
                continue

        # On non-Windows platforms SysFont is still useful, but malformed
        # Windows font registry values can make pygame's enumeration fail.
        try:
            return pygame.font.SysFont(
                ("microsoftyahei", "simhei", "noto sans cjk sc", "arial"),
                size,
                bold=bold,
            )
        except (OSError, TypeError, pygame.error):
            return pygame.font.Font(None, size)

    def _load_profile(self) -> dict:
        if not SAVE_FILE.exists():
            return {}
        try:
            data = json.loads(SAVE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        if "echo_relics" not in data:
            data["echo_relics"] = max(
                0,
                int(data.get("echo_tokens", data.get("permanent_memory", 0)) or 0),
            )
        if not isinstance(data.get("progression"), dict):
            data["progression"] = {
                "unlocked_nodes": [],
                "equipped_start_module": None,
            }
        if not isinstance(data.get("lifetime_stats"), dict):
            data["lifetime_stats"] = {}
        return data

    def _load_save(self) -> bool:
        return bool(
            self.profile.get("best_score")
            or self.profile.get("best_floor")
            or self.profile.get("scores")
            or self.profile.get("tutorial_completed")
        )

    @property
    def tutorial_completed(self) -> bool:
        return bool(self.profile.get("tutorial_completed", False))

    @property
    def echo_relics(self) -> int:
        return max(0, int(self.profile.get("echo_relics", 0) or 0))

    def _progression(self) -> dict:
        progression = self.profile.get("progression", {})
        return progression if isinstance(progression, dict) else {}

    def _unlocked_nodes(self) -> set[str]:
        unlocked = self._progression().get("unlocked_nodes", [])
        if not isinstance(unlocked, list):
            return set()
        return {node_id for node_id in unlocked if isinstance(node_id, str)}

    def _stat(self, name: str) -> int:
        stats = self.profile.get("lifetime_stats", {})
        if not isinstance(stats, dict):
            return 0
        return max(0, int(stats.get(name, 0) or 0))

    @staticmethod
    def _default_keybinds() -> dict[str, int]:
        return {
            "left": pygame.K_a,
            "right": pygame.K_d,
            "attack": pygame.K_j,
            "parry": pygame.K_k,
            "dash": pygame.K_l,
            "jump": pygame.K_SPACE,
        }

    def _load_keybinds(self, saved: object) -> dict[str, int]:
        keybinds = self._default_keybinds()
        if isinstance(saved, dict):
            for action in keybinds:
                value = saved.get(action)
                if isinstance(value, int) and value >= 0:
                    keybinds[action] = value
        return keybinds

    @staticmethod
    def _key_name(key: int) -> str:
        return pygame.key.name(key).upper() or "未设置"

    def _save_profile(self) -> None:
        data = {
            "version": 2,
            "best_score": int(self.profile.get("best_score", 0) or 0),
            "best_floor": int(self.profile.get("best_floor", 0) or 0),
            "scores": self.profile.get("scores", []),
            "tutorial_completed": bool(
                self.profile.get("tutorial_completed", False)
            ),
            "echo_relics": self.echo_relics,
            "progression": self._progression(),
            "lifetime_stats": self.profile.get("lifetime_stats", {}),
            "settings": self.settings.copy(),
        }
        data["settings"]["keybinds"] = self.keybinds.copy()
        try:
            SAVE_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self.profile = data
        except OSError:
            self._notify("设置无法保存，请检查文件权限")

    def _build_items(self) -> list[MenuItem]:
        return [
            MenuItem("继续游戏", "continue", enabled=self.has_save),
            MenuItem("开始游戏", "start"),
            MenuItem("本地排行榜", "leaderboard"),
            MenuItem("设置", "settings"),
            MenuItem("退出游戏", "quit"),
        ]

    def run(self) -> None:
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0
            self.elapsed += dt
            self._handle_events()
            self._update(dt)
            self._sync_music()
            self.audio.update(dt)
            self._draw()
            pygame.display.flip()
        self.audio.shutdown()

    def _music_for_page(self) -> str:
        """进入关卡（含新手教学关卡）使用战斗音乐，其余界面保持大厅音乐。"""
        return "battle" if self.page == "game" else "lobby"

    def _sync_music(self) -> None:
        self.audio.play_music(self._music_for_page())

    def _set_volume(self, percent: int) -> None:
        self.settings["volume"] = max(0, min(100, int(percent)))
        self.audio.set_volume(self.settings["volume"])
        self._save_profile()
        self._notify(f"音量 {self.settings['volume']}%")

    def _handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                self.pressed_keys.add(event.key)
                self._handle_key(event.key)
            elif event.type == pygame.KEYUP:
                self.pressed_keys.discard(event.key)
            elif event.type == pygame.WINDOWFOCUSLOST:
                self.pressed_keys.clear()
            elif event.type == pygame.MOUSEMOTION:
                self._handle_mouse_motion(event.pos)
            elif event.type == pygame.VIDEORESIZE:
                if not self.settings["fullscreen"]:
                    self.screen = pygame.display.set_mode(event.size, pygame.RESIZABLE)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.confirm_exit:
                    self.pressed_button = self._exit_button_at(event.pos)
                elif self.overlay is not None:
                    self._handle_overlay_click(event.pos)
                elif self.page == "menu":
                    self.pressed_item = self._item_at(event.pos)
                elif self.page == "game":
                    if self._settings_icon_rect().collidepoint(
                        self._to_logical(event.pos)
                    ):
                        self._open_overlay("settings", return_page="game")
                    else:
                        self._start_player_attack(self._attack_direction_from_input())
                elif self.page == "lobby":
                    logical = self._to_logical(event.pos)
                    for index, (_, _, rect) in enumerate(self._lobby_actions()):
                        if rect.collidepoint(logical):
                            self.pressed_button = str(index)
                            break
                else:
                    self.pressed_button = self._page_button_at(event.pos)
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                if self.confirm_exit:
                    button = self._exit_button_at(event.pos)
                    if self.pressed_button is not None and button == self.pressed_button:
                        self._activate_exit_button(button)
                    self.pressed_button = None
                elif self.overlay is None and self.page == "menu":
                    index = self._item_at(event.pos)
                    if self.pressed_item is not None and index == self.pressed_item:
                        self._activate(index)
                    self.pressed_item = None
                elif self.overlay is None and self.page == "lobby":
                    logical = self._to_logical(event.pos)
                    index = next(
                        (
                            index
                            for index, (_, _, rect) in enumerate(self._lobby_actions())
                            if rect.collidepoint(logical)
                        ),
                        None,
                    )
                    if self.pressed_button is not None and str(index) == self.pressed_button:
                        self._activate_lobby_action(index)
                    self.pressed_button = None
                elif self.overlay is None:
                    button = self._page_button_at(event.pos)
                    if self.pressed_button is not None and button == self.pressed_button:
                        self._activate_page_button(button)
                    self.pressed_button = None

    def _handle_key(self, key: int) -> None:
        if self.confirm_exit:
            if key in (pygame.K_y, pygame.K_RETURN):
                self._activate_exit_button("confirm")
            elif key in (pygame.K_n, pygame.K_ESCAPE):
                self.confirm_exit = False
            return

        if self.overlay == "keybinds":
            if self.rebinding_action is not None:
                if key == pygame.K_ESCAPE:
                    self.rebinding_action = None
                    self._notify("已取消键位设置")
                elif key in self.keybinds.values() and key != self.keybinds[self.rebinding_action]:
                    self._notify("这个按键已经被其他操作使用")
                else:
                    self.keybinds[self.rebinding_action] = key
                    action_name = dict(self._keybind_actions())[self.rebinding_action]
                    self.rebinding_action = None
                    self._refresh_tutorial_hints()
                    self._save_profile()
                    self._notify(f"{action_name} 已绑定为 {self._key_name(key)}")
                return
            if key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                self._close_overlay()
            elif key in (pygame.K_UP, pygame.K_w):
                self.keybind_selected = (self.keybind_selected - 1) % 7
            elif key in (pygame.K_DOWN, pygame.K_s):
                self.keybind_selected = (self.keybind_selected + 1) % 7
            elif key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_j):
                if self.keybind_selected == 6:
                    self._close_overlay()
                else:
                    self.rebinding_action = self._keybind_actions()[self.keybind_selected][0]
                    self._notify("请按下新的键位，Esc 取消")
            return

        if self.overlay == "settings":
            if key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                self._close_overlay()
            elif key in (pygame.K_UP, pygame.K_w):
                self.overlay_selected = (self.overlay_selected - 1) % 6
            elif key in (pygame.K_DOWN, pygame.K_s):
                self.overlay_selected = (self.overlay_selected + 1) % 6
            elif key in (pygame.K_LEFT, pygame.K_RIGHT):
                self._change_setting(
                    self.overlay_selected,
                    5 if key == pygame.K_RIGHT else -5,
                )
            elif key == pygame.K_a:
                self._activate_setting(1)
            elif key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_j):
                self._activate_setting(self.overlay_selected)
            return

        if self.overlay == "leaderboard":
            if key in (pygame.K_ESCAPE, pygame.K_BACKSPACE, pygame.K_RETURN, pygame.K_SPACE):
                self._close_overlay()
            return

        if self.overlay == "portal":
            if key in (pygame.K_LEFT, pygame.K_a, pygame.K_RIGHT, pygame.K_d):
                self.portal_choice_index = 1 - self.portal_choice_index
            elif key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_j):
                self._activate_portal_choice(self.portal_choice_index)
            elif key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                self._leave_portal_choice()
            return

        if self.overlay == "progression":
            if key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                self._close_overlay()
            elif key in (pygame.K_UP, pygame.K_w):
                self.progression_selected = (
                    self.progression_selected - 1
                ) % len(PROGRESSION_NODES)
            elif key in (pygame.K_DOWN, pygame.K_s):
                self.progression_selected = (
                    self.progression_selected + 1
                ) % len(PROGRESSION_NODES)
            elif key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_j):
                self._activate_progression_node(self.progression_selected)
            return

        if self.page == "game":
            if key == self.keybinds["attack"]:
                self._start_player_attack(self._attack_direction_from_input())
            elif key == self.keybinds["parry"]:
                if self.player.start_parry():
                    self.audio.play("parry_ready")
                    self._try_projectile_parry()
                    self._notify("弹刀架势")
            elif key in (pygame.K_LSHIFT, self.keybinds["dash"]):
                if self.player.dash():
                    self.audio.play("dash")
                    self._dash_trail_timer = 0.0
                    self._notify("闪避")
            elif key == self.keybinds["jump"]:
                if self.player.request_jump():
                    self.audio.play("jump")
                    self._notify("跳跃")
            elif key == pygame.K_ESCAPE:
                self._open_overlay("settings", return_page="game")
            return

        if self.page == "result":
            if key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_j):
                self._activate_page_button("restart")
            elif key == pygame.K_ESCAPE:
                self.page = "menu"
            return

        if self.page == "failure":
            if key in (
                pygame.K_RETURN,
                pygame.K_SPACE,
                pygame.K_j,
                pygame.K_ESCAPE,
            ):
                self._activate_page_button("lobby")
            return

        if self.page == "lobby":
            if key in (pygame.K_LEFT, pygame.K_a, pygame.K_UP, pygame.K_w):
                self.lobby_selected = (self.lobby_selected - 1) % len(
                    self._lobby_actions()
                )
            elif key in (pygame.K_RIGHT, pygame.K_d, pygame.K_DOWN, pygame.K_s):
                self.lobby_selected = (self.lobby_selected + 1) % len(
                    self._lobby_actions()
                )
            elif key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_j):
                self._activate_lobby_action(self.lobby_selected)
            elif key == pygame.K_ESCAPE:
                self.page = "menu"
            return

        if key in (pygame.K_UP, pygame.K_w):
            self._move_selection(-1)
        elif key in (pygame.K_DOWN, pygame.K_s):
            self._move_selection(1)
        elif key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_j):
            self._activate(self.selected)
        elif key == pygame.K_ESCAPE:
            self.confirm_exit = True

    def _handle_mouse_motion(self, position: tuple[int, int]) -> None:
        if self.confirm_exit:
            return
        if self.overlay == "keybinds":
            logical = self._to_logical(position)
            for index, rect in enumerate(self._keybind_rects()):
                if rect.collidepoint(logical):
                    self.keybind_selected = index
                    return
        if self.overlay == "settings":
            logical = self._to_logical(position)
            for index, rect in enumerate(self._setting_rects()):
                if rect.collidepoint(logical):
                    self.overlay_selected = index
                    return
        if self.overlay == "progression":
            logical = self._to_logical(position)
            for index, rect in enumerate(self._progression_node_rects()):
                if rect.collidepoint(logical):
                    self.progression_selected = index
                    return
        elif self.overlay is None and self.page == "menu":
            self._select_from_mouse(position)
        elif self.overlay is None and self.page == "lobby":
            logical = self._to_logical(position)
            for index, (_, _, rect) in enumerate(self._lobby_actions()):
                if rect.collidepoint(logical):
                    self.lobby_selected = index
                    return

    def _move_selection(self, direction: int) -> None:
        enabled = [i for i, item in enumerate(self.items) if item.enabled]
        if not enabled:
            return
        current = self.selected
        for _ in range(len(self.items)):
            current = (current + direction) % len(self.items)
            if self.items[current].enabled:
                self.selected = current
                return

    def _select_from_mouse(self, position: tuple[int, int]) -> None:
        logical = self._to_logical(position)
        index = self._item_at_logical(logical)
        if index is not None and self.items[index].enabled:
            self.selected = index

    def _item_at(self, position: tuple[int, int]) -> int | None:
        return self._item_at_logical(self._to_logical(position))

    def _item_at_logical(self, position: tuple[int, int]) -> int | None:
        x, y = position
        for index in range(len(self.items)):
            if self._menu_rect(index).collidepoint(x, y):
                return index
        return None

    def _to_logical(self, position: tuple[int, int]) -> tuple[int, int]:
        width, height = self.screen.get_size()
        scale = min(width / LOGICAL_SIZE[0], height / LOGICAL_SIZE[1])
        offset_x = (width - LOGICAL_SIZE[0] * scale) / 2
        offset_y = (height - LOGICAL_SIZE[1] * scale) / 2
        return (
            int((position[0] - offset_x) / scale),
            int((position[1] - offset_y) / scale),
        )

    def _activate(self, index: int) -> None:
        if index < 0 or index >= len(self.items) or not self.items[index].enabled:
            return
        action = self.items[index].action
        if action == "quit":
            self.confirm_exit = True
        elif action == "start":
            if self.tutorial_completed:
                self._enter_lobby()
            else:
                self._start_run(1, tutorial=True)
        elif action == "continue":
            self._enter_lobby()
        elif action == "leaderboard":
            self._open_overlay("leaderboard")
        elif action == "settings":
            self._open_overlay("settings")

    @staticmethod
    def _lobby_actions() -> list[tuple[str, str, pygame.Rect]]:
        return [
            ("gate", "开启远征", pygame.Rect(490, 414, 300, 72)),
            ("nexus", "进入回响中枢", pygame.Rect(485, 196, 310, 100)),
            ("smith", "铸刃师", pygame.Rect(78, 420, 260, 86)),
            ("records", "查看远征记录", pygame.Rect(920, 420, 280, 86)),
        ]

    def _enter_lobby(self) -> None:
        self.page = "lobby"
        self.overlay = None
        self.confirm_exit = False
        self.lobby_selected = 0
        self.run_currency = 0
        self._notify("灰塔大厅已就绪")

    def _activate_lobby_action(self, index: int) -> None:
        actions = self._lobby_actions()
        if index < 0 or index >= len(actions):
            return
        action = actions[index][0]
        if action == "gate":
            self._start_run(
                max(1, int(self.profile.get("best_floor", 1) or 1)),
                tutorial=False,
            )
        elif action == "nexus":
            self._open_overlay("progression", return_page="lobby")
        elif action == "smith":
            self._notify("铸刃师：武装谱系将在后续版本接入")
        elif action == "records":
            self._open_overlay("leaderboard", return_page="lobby")

    def _node_requirement_met(self, node: ProgressionNode) -> bool:
        if node.node_id in {"aftershock_calibration", "white_window_record"}:
            return self.tutorial_completed
        if node.node_id == "refracted_afterglow":
            return self._stat("parries") >= 3
        if node.node_id == "twin_blade_license":
            return self._stat("boss_kills") >= 1
        if node.node_id == "perfect_circuit":
            return self._stat("parries") >= 20
        if node.node_id == "resonance_protocol":
            return self._stat("reflections") >= 10
        if node.node_id == "route_cartography":
            return int(self.profile.get("best_floor", 0) or 0) >= 2
        if node.node_id == "reserve_carry":
            return self._stat("shop_purchases") >= 3
        if node.node_id == "risk_covenant":
            return self._stat("elite_flawless") >= 1
        if node.node_id == "city_seal":
            unlocked = self._unlocked_nodes()
            branches = {
                branch: sum(
                    1
                    for item in PROGRESSION_NODES
                    if item.branch == branch and item.node_id in unlocked
                )
                for branch in ("锻刃谱系", "共鸣谱系", "远征谱系")
            }
            return (
                sum(value >= 2 for value in branches.values()) >= 2
                and self._stat("settlements") >= 10
                and self._stat("boss_kills") >= 2
            )
        return False

    def _node_available(self, node: ProgressionNode) -> bool:
        unlocked = self._unlocked_nodes()
        return (
            node.node_id not in unlocked
            and (node.prerequisite is None or node.prerequisite in unlocked)
            and self._node_requirement_met(node)
        )

    def _activate_progression_node(self, index: int) -> None:
        if index < 0 or index >= len(PROGRESSION_NODES):
            return
        node = PROGRESSION_NODES[index]
        unlocked = self._unlocked_nodes()
        if node.node_id in unlocked:
            self._notify("该节点已经铭刻在回响中枢")
            return
        if node.prerequisite and node.prerequisite not in unlocked:
            self._notify("前置节点尚未激活")
            return
        if not self._node_requirement_met(node):
            self._notify(f"尚未满足解锁门槛：{node.requirement}")
            return
        if self.echo_relics < node.cost:
            self._notify(f"回响遗晶不足，还需 {node.cost - self.echo_relics}")
            return
        unlocked.add(node.node_id)
        progression = self._progression().copy()
        progression["unlocked_nodes"] = sorted(unlocked)
        progression.setdefault("equipped_start_module", None)
        self.profile["progression"] = progression
        self.profile["echo_relics"] = self.echo_relics - node.cost
        self._save_profile()
        self._notify(f"已激活：{node.title}")

    def _open_overlay(self, overlay: str, return_page: str | None = None) -> None:
        self.overlay = overlay
        self.return_page = return_page or self.page
        self.overlay_selected = 0
        self.keybind_selected = 0
        self.rebinding_action = None

    def _close_overlay(self) -> None:
        self.overlay = None
        self.page = self.return_page

    def _handle_overlay_click(self, position: tuple[int, int]) -> None:
        logical = self._to_logical(position)
        if self.overlay == "keybinds":
            rects = self._keybind_rects()
            if self._overlay_back_rect().collidepoint(logical):
                self._close_overlay()
                return
            for index, rect in enumerate(rects):
                if rect.collidepoint(logical):
                    self.keybind_selected = index
                    if index == len(rects) - 1:
                        self._close_overlay()
                    else:
                        self.rebinding_action = self._keybind_actions()[index][0]
                        self._notify("请按下新的键位，Esc 取消")
                    return
            if not self._overlay_rect().collidepoint(logical):
                self._close_overlay()
            return
        if self.overlay == "settings":
            rects = self._setting_rects()
            for index, rect in enumerate(rects[:4]):
                if rect.collidepoint(logical):
                    self.overlay_selected = index
                    if index == 0:
                        ratio = (logical[0] - (rect.x + 190)) / 270
                        self._set_volume(int(round(ratio * 20) * 5))
                    else:
                        self._activate_setting(index)
                    return
            if rects[4].collidepoint(logical):
                self.overlay_selected = 4
                self._activate_setting(4)
                return
            if rects[5].collidepoint(logical):
                self.overlay_selected = 5
                self._close_overlay()
                return
            if not self._overlay_rect().collidepoint(logical):
                self._close_overlay()
        elif self.overlay == "leaderboard":
            if (
                self._overlay_back_rect().collidepoint(logical)
                or not self._overlay_rect().collidepoint(logical)
            ):
                self._close_overlay()
        elif self.overlay == "portal":
            for index, choice_rect in enumerate(self._portal_choice_rects()):
                if choice_rect.collidepoint(logical):
                    self.portal_choice_index = index
                    self._activate_portal_choice(index)
                    return
            if not self._overlay_rect().collidepoint(logical):
                self._leave_portal_choice()
        elif self.overlay == "progression":
            if self._overlay_back_rect().collidepoint(logical):
                self._close_overlay()
            elif self._progression_activate_rect().collidepoint(logical):
                self._activate_progression_node(self.progression_selected)
            elif not self._overlay_rect().collidepoint(logical):
                self._close_overlay()

    def _update(self, dt: float) -> None:
        if self.notification_timer > 0:
            self.notification_timer = max(0.0, self.notification_timer - dt)

        if self.page != "game" or self.overlay is not None or self.confirm_exit:
            return

        fixed_dt = min(max(0.0, dt), 1.0 / 30.0)
        previous_x = self.player.x
        # 进入传送门时锁住操作，由动画把角色吸向门心
        move_axis = 0.0 if self.portal_enter_timer > 0.0 else self._move_axis()
        self.player.update(fixed_dt, move_axis)
        self._update_attack_impacts(fixed_dt)
        self._update_dash_trails(fixed_dt)
        self._update_enemy_spawn(fixed_dt)
        self._update_reflected_projectiles(fixed_dt)
        self._update_portal(fixed_dt)
        self._update_movement_audio(fixed_dt)
        self.tutorial_move_distance += abs(self.player.x - previous_x)
        if abs(self.player.x - self.tutorial_start_x) >= 80 or (
            self._current_tutorial_step.action == "move"
            and self.tutorial_move_distance >= 48
        ):
            self._complete_tutorial_action("move")
        if not self.player.grounded:
            self._complete_tutorial_action("jump")
        self._resolve_player_attack()
        if not self.is_tutorial_run or self._current_tutorial_step.action == "parry":
            self._update_enemy_attacks(fixed_dt)

    def _move_axis(self) -> float:
        left = (
            self._is_key_down(pygame.K_LEFT)
            or self._is_key_down(pygame.K_a)
            or self._is_key_down(self.keybinds["left"])
        )
        right = (
            self._is_key_down(pygame.K_RIGHT)
            or self._is_key_down(pygame.K_d)
            or self._is_key_down(self.keybinds["right"])
        )
        return float(right) - float(left)

    def _update_movement_audio(self, dt: float) -> None:
        """按实际移动速度累积脚步节拍，落地时补一次轻柔的落地音。"""
        player = self.player
        if player.landed_this_frame:
            self.audio.play("land")
        if player.grounded and abs(player.velocity_x) > 40.0:
            self._step_timer += dt * abs(player.velocity_x) / Player.MOVE_SPEED
            if self._step_timer >= 0.33:
                self._step_timer = 0.0
                self.audio.play("step")
        else:
            self._step_timer = min(self._step_timer, 0.2)

    def _player_sprite_name(self) -> str:
        if self.player.attack_in_progress:
            return f"attack_{self.player.attack_direction}"
        if not self.player.grounded:
            return "jump" if self.player.velocity_y < 0 else "fall"
        if abs(self.player.velocity_x) > 20:
            return f"run_{int(self.elapsed * 10) % 2}"
        return "idle"

    def _spawn_dash_trail(self) -> None:
        """记录一格闪避残影。"""
        self.dash_trails.append(
            DashTrail(
                self.player.x,
                self.player.y,
                self.player.facing,
                self._player_sprite_name(),
                DASH_TRAIL_LIFE,
                DASH_TRAIL_LIFE,
            )
        )

    def _update_dash_trails(self, dt: float) -> None:
        if self.dash_trails:
            for trail in self.dash_trails:
                trail.remaining -= dt
            self.dash_trails = [
                trail for trail in self.dash_trails if trail.remaining > 0.0
            ]
        if self.player.dash_active:
            if not self._dash_was_active:
                # 冲刺起手立刻留下一格残影
                self._dash_trail_timer = DASH_TRAIL_INTERVAL
                self._spawn_dash_trail()
            else:
                self._dash_trail_timer -= dt
                if self._dash_trail_timer <= 0.0:
                    self._dash_trail_timer = DASH_TRAIL_INTERVAL
                    self._spawn_dash_trail()
            self._dash_was_active = True
        else:
            self._dash_trail_timer = 0.0
            self._dash_was_active = False

    def _spawn_pending_enemies(self) -> None:
        """立刻让待登场的敌人出现。"""
        if not self.pending_spawn:
            return
        self.room_enemies.extend(self.pending_spawn)
        self.pending_spawn.clear()
        self.enemy_spawn_timer = 0.0

    # -- 关卡胜利与传送门 -------------------------------------------------

    def _portal_rect(self) -> pygame.Rect:
        return pygame.Rect(
            round(PORTAL_CENTER_X - PORTAL_WIDTH / 2),
            round(PORTAL_GROUND_Y - PORTAL_HEIGHT),
            PORTAL_WIDTH,
            PORTAL_HEIGHT,
        )

    def _room_cleared(self) -> bool:
        """敌人全部清空（教学关还要等教学步骤走完）才算房间胜利。"""
        if self.pending_spawn or self.room_enemies:
            return False
        if self.is_tutorial_run and self._current_tutorial_step.action != "finish":
            return False
        return True

    def _player_in_portal(self) -> bool:
        body = self.player.body_hitbox
        portal = self._portal_rect()
        return (
            body.left < portal.right
            and body.right > portal.left
            and body.top < portal.bottom
            and body.bottom > portal.top
        )

    def _update_portal(self, dt: float) -> None:
        if self.portal_lock_timer > 0.0:
            self.portal_lock_timer = max(0.0, self.portal_lock_timer - dt)

        if self.portal_enter_timer > 0.0:
            self.portal_enter_timer = max(0.0, self.portal_enter_timer - dt)
            # 把角色吸向门心
            self.player.x += (PORTAL_CENTER_X - self.player.x) * min(1.0, dt * 7.0)
            self.player.velocity_x = 0.0
            if self.portal_enter_timer <= 0.0:
                self._open_portal_choice()
            return

        if not self.portal_open:
            if self._room_cleared():
                self.portal_open = True
                self.portal_appear = 0.0
                self.audio.play("portal_open")
                self._notify("回响之门已开启")
            return

        if self.portal_appear < 1.0:
            self.portal_appear = min(
                1.0,
                self.portal_appear + dt / max(0.05, PORTAL_APPEAR_TIME),
            )
        if (
            self.portal_appear >= 1.0
            and self.portal_lock_timer <= 0.0
            and self.overlay is None
            and not self.confirm_exit
            and self._player_in_portal()
        ):
            self.portal_enter_timer = PORTAL_ENTER_TIME
            self.audio.play("portal_enter")
            self.pressed_keys.clear()

    def _open_portal_choice(self) -> None:
        """进入动画结束后弹出「返回主菜单 / 下一关」选择。"""
        self.portal_choice_index = 0
        self._open_overlay("portal", return_page="game")
        self._notify("回响之门：选择去向")

    def _leave_portal_choice(self) -> None:
        """取消选择：把角色推回门的左侧，避免立刻再次触发。"""
        self.overlay = None
        self.page = "game"
        self.player.x = PORTAL_CENTER_X - 120.0
        self.player.velocity_x = 0.0
        self.portal_lock_timer = PORTAL_RETRIGGER_LOCK
        self._notify("继续探索当前房间")

    def _portal_choice_rects(self) -> list[pygame.Rect]:
        return [
            pygame.Rect(392, 404, 236, 62),
            pygame.Rect(652, 404, 236, 62),
        ]

    def _portal_choice_labels(self) -> tuple[str, str]:
        if self.is_tutorial_run:
            return ("返回主菜单", "进入灰塔大厅")
        return ("返回主菜单", f"进入第 {self.run_floor + 1} 层")

    def _activate_portal_choice(self, index: int) -> None:
        if index < 0 or index > 1:
            return
        relics = self._settle_run()
        self.overlay = None
        if index == 0:
            self.page = "menu"
            self.confirm_exit = False
            self._notify(f"远征已结算，凝结回响遗晶 +{relics}")
            return
        if self.is_tutorial_run:
            self._enter_lobby()
            self._notify(f"远征已结算，凝结回响遗晶 +{relics}")
            return
        next_floor = self.run_floor + 1
        self._start_run(next_floor, tutorial=False)
        self._notify(f"进入第 {next_floor} 层  遗晶 +{relics}")

    def _update_enemy_spawn(self, dt: float) -> None:
        """进入关卡后延迟刷怪，给玩家观察场地的时间。"""
        if not self.pending_spawn:
            return
        self.enemy_spawn_timer = max(0.0, self.enemy_spawn_timer - dt)
        if self.enemy_spawn_timer > 0.0:
            return
        self._spawn_pending_enemies()
        self.audio.play("spawn")
        self._notify("敌人出现")

    def _update_reflected_projectiles(self, dt: float) -> None:
        """被弹开的子弹飞回射击者，命中后才结算伤害。"""
        if not self.reflected_projectiles:
            return
        active: list[ReflectedProjectile] = []
        for bullet in self.reflected_projectiles:
            target = bullet.target
            if target.defeated or target not in self.room_enemies:
                continue  # 目标已消失，弹体自然消散
            target_x = target.x
            target_y = target.y - 30
            dx = target_x - bullet.x
            dy = target_y - bullet.y
            distance = math.hypot(dx, dy)
            step = bullet.speed * dt
            if distance > step and distance > 0.0:
                bullet.x += dx / distance * step
                bullet.y += dy / distance * step
                active.append(bullet)
                continue
            self._resolve_reflected_hit(target, bullet.damage)
        self.reflected_projectiles = active
        self._remove_defeated_enemies()

    def _resolve_reflected_hit(self, enemy: Enemy, damage: int) -> None:
        dealt = enemy.take_damage(damage, source_x=self.player.x)
        self.audio.play("hit")
        self.audio.duck(0.22, 0.18)
        self.attack_impacts.append(
            AttackImpact(enemy.x, enemy.y - 44, False, True)
        )
        if dealt <= 0:
            return
        self.run_score += 120
        self.run_combo += 1
        self.run_max_combo = max(self.run_max_combo, self.run_combo)
        self.run_currency += 2
        if enemy.defeated:
            self._award_enemy_defeat(enemy)
        else:
            self._notify(f"反弹命中 {enemy.display_name}  -{dealt}")

    def _dash_trail_surface(self, sprite: str, facing: int) -> pygame.Surface:
        """把角色贴图染成青色并缓存，用于闪避残影。"""
        key = (sprite, facing)
        cached = self._trail_surface_cache.get(key)
        if cached is not None:
            return cached
        image = self.assets.player_sprites.get(sprite) or self.assets.player
        if facing < 0:
            image = pygame.transform.flip(image, True, False)
        ghost = pygame.transform.scale(image, (96, 120)).copy()
        ghost.fill((70, 200, 235), special_flags=pygame.BLEND_RGB_MULT)
        self._trail_surface_cache[key] = ghost
        return ghost

    def _projectile_position(self, pending: PendingEnemyAttack) -> tuple[float, float]:
        """弹道当前位置：从出膛点线性飞向锁定点，命中时正好到达角色。"""
        duration = max(0.001, pending.profile.telegraph_time)
        progress = max(0.0, min(1.0, 1.0 - pending.remaining / duration))
        origin = pending.origin or (pending.enemy.x, pending.enemy.y - 52)
        target = pending.target or (self.player.x, self.player.y - 54)
        return (
            origin[0] + (target[0] - origin[0]) * progress,
            origin[1] + (target[1] - origin[1]) * progress,
        )

    def _try_projectile_parry(self) -> bool:
        """远程弹刀：子弹进入角色身边范围时按下弹刀键即直接弹开。"""
        player_center = (self.player.x, self.player.y - 54)
        for pending in list(self.pending_enemy_attacks):
            if pending.enemy.defeated or not pending.profile.parryable:
                continue
            if pending.profile.projectile_speed is None:
                continue
            position = self._projectile_position(pending)
            distance = math.hypot(
                position[0] - player_center[0],
                position[1] - player_center[1],
            )
            if distance > PROJECTILE_PARRY_RANGE:
                continue
            self.pending_enemy_attacks.remove(pending)
            self._perfect_parry(pending, reflect=True)
            return True
        return False

    def _perfect_parry(
        self,
        pending: PendingEnemyAttack,
        *,
        reflect: bool = False,
    ) -> None:
        enemy = pending.enemy
        reflected_damage = enemy.on_parried(perfect=True)
        if reflect:
            # 远程弹刀：子弹原样打回去，命中敌人才造成伤害
            self.reflected_projectiles.append(
                ReflectedProjectile(
                    self.player.x,
                    self.player.y - 54,
                    enemy,
                    reflected_damage,
                )
            )
        else:
            enemy.take_damage(reflected_damage, source_x=self.player.x)
        self.audio.play("parry")
        self.audio.duck(0.5, 0.45)
        self.run_score += 260
        self.run_combo += 2
        self.run_max_combo = max(self.run_max_combo, self.run_combo)
        self.run_parries += 1
        self.run_currency += 5
        self.attack_impacts.append(
            AttackImpact(self.player.x, self.player.y - 58, True, True)
        )
        if reflect:
            self._notify(f"PERFECT  弹开子弹  反弹 {reflected_damage}")
        else:
            self._notify(f"PERFECT  弹刀成功  反震 {reflected_damage}")
        self._complete_tutorial_action("parry")
        if enemy.defeated:
            self._award_enemy_defeat(enemy)

    def _is_key_down(self, key: int) -> bool:
        if key in self.pressed_keys:
            return True
        try:
            return bool(pygame.key.get_pressed()[key])
        except (IndexError, KeyError):
            return False

    def _attack_direction_from_input(self) -> str:
        up = self._is_key_down(pygame.K_UP) or self._is_key_down(pygame.K_w)
        down = self._is_key_down(pygame.K_DOWN) or self._is_key_down(pygame.K_s)
        if up and not down:
            return "up"
        if down and not up:
            return "down"
        return "side"

    def _start_player_attack(self, direction: str = "side") -> None:
        if self.player.start_attack(direction):
            self.audio.play_swing(self.player.attack_stage)
            direction_name = {
                "side": f"第 {self.player.attack_stage} 段",
                "up": "上劈",
                "down": "下劈",
            }[direction]
            self._notify(f"折光长刃：{direction_name}")
            if direction == "side":
                self._complete_tutorial_action("attack")
            elif direction == "up":
                self._complete_tutorial_action("up_attack")

    def _resolve_player_attack(self) -> None:
        attack_hitbox = self.player.attack_hitbox
        if attack_hitbox is None:
            return

        for enemy in list(self.room_enemies):
            enemy_id = id(enemy)
            if enemy.defeated or (self.player.attack_id, enemy_id) in self._attack_hits:
                continue
            enemy_hitbox = Hitbox(enemy.x - 18, enemy.y - 44, 36, 44)
            if not attack_hitbox.overlaps(enemy_hitbox):
                continue

            self._attack_hits.add((self.player.attack_id, enemy_id))
            damage = enemy.take_damage(
                self.player.attack_damage,
                source_x=self.player.x,
                posture_damage=self.player.posture_damage,
            )
            if damage <= 0:
                continue
            self.audio.play("hit")
            self.audio.duck(0.22, 0.18)
            if self.player.attack_direction == "down":
                self.player.bounce_from_down_attack()
                self._complete_tutorial_action("down_attack")
            self.run_score += 120
            self.run_combo += 1
            self.run_max_combo = max(self.run_max_combo, self.run_combo)
            self.run_currency += 2
            if enemy.defeated:
                self._award_enemy_defeat(enemy)
            else:
                self._notify(f"命中 {enemy.display_name}  -{damage}")

        self._remove_defeated_enemies()

    def _update_enemy_attacks(self, dt: float) -> None:
        pending_enemy_ids = {
            id(pending.enemy) for pending in self.pending_enemy_attacks
        }
        for enemy in list(self.room_enemies):
            if enemy.defeated:
                continue
            intent = enemy.update(dt, self.player.position)
            if intent.attack is not None and id(enemy) not in pending_enemy_ids:
                pending = PendingEnemyAttack(
                    enemy,
                    intent.attack,
                    intent.attack.telegraph_time,
                    origin=(enemy.x, enemy.y - 52),
                    target=(self.player.x, self.player.y - 54),
                )
                self.pending_enemy_attacks.append(pending)
                pending_enemy_ids.add(id(enemy))
                # 敌人起手就给出提示音，命中与否由后续音效补充确认
                self.audio.play("enemy_attack")

        unresolved: list[PendingEnemyAttack] = []
        for pending in self.pending_enemy_attacks:
            if pending.enemy.defeated or pending.enemy not in self.room_enemies:
                continue
            pending.remaining -= dt
            if pending.remaining > 0.0:
                unresolved.append(pending)
                continue
            self._resolve_enemy_attack(pending)
            if self.player.hp <= 0:
                self.pending_enemy_attacks.clear()
                self._fail_run()
                return
        self.pending_enemy_attacks = unresolved
        self._remove_defeated_enemies()

    def _update_attack_impacts(self, dt: float) -> None:
        for impact in self.attack_impacts:
            impact.remaining -= dt
        self.attack_impacts = [
            impact for impact in self.attack_impacts if impact.remaining > 0.0
        ]

    def _resolve_enemy_attack(self, pending: PendingEnemyAttack) -> None:
        enemy = pending.enemy
        profile = pending.profile
        is_projectile = profile.projectile_speed is not None

        # 近战：金色闪光亮起后的窗口内按下弹刀即为完美弹刀。
        # 远程弹刀在按下瞬间按“贴身范围”判定（见 _try_projectile_parry），
        # 因此这里不再用时间缓冲补判，避免离得很远也能弹。
        if profile.parryable and not is_projectile and self.player.parry_buffered:
            self._perfect_parry(pending)
            return

        # 闪避期间无敌：不受伤害，也不中断连击
        if self.player.invulnerable:
            self.audio.play("dash", 0.45)
            self.run_score += 40
            self.attack_impacts.append(
                AttackImpact(
                    self.player.x,
                    self.player.y - 54,
                    False,
                    profile.parryable,
                    dodged=True,
                )
            )
            self._notify(f"闪避成功  躲开 {enemy.display_name}")
            return

        damage = self.player.take_damage(profile.damage)
        self.audio.play("hurt")
        self.audio.duck(0.34, 0.3)
        self.run_combo = 0
        self.attack_impacts.append(
            AttackImpact(
                self.player.x,
                self.player.y - 54,
                False,
                profile.parryable,
            )
        )
        if profile.parryable and self.player.parry_active:
            self._notify(f"弹刀过早  受到 {damage} 伤害")
        elif not profile.parryable and self.player.parry_active:
            self._notify(f"不可弹反攻击  受到 {damage} 伤害")
        else:
            self._notify(f"受到 {enemy.display_name} {damage} 点伤害")

    def _award_enemy_defeat(self, enemy: Enemy) -> None:
        enemy_id = id(enemy)
        if enemy_id in self._defeated_enemies:
            return
        self._defeated_enemies.add(enemy_id)
        self.run_score += enemy.bounty_score
        self.run_currency += max(4, enemy.bounty_score // 20)
        self.audio.play("defeat")
        self._notify(f"击败 {enemy.display_name}")

    def _remove_defeated_enemies(self) -> None:
        self.room_enemies = [enemy for enemy in self.room_enemies if not enemy.defeated]
        self.pending_enemy_attacks = [
            pending
            for pending in self.pending_enemy_attacks
            if not pending.enemy.defeated and pending.enemy in self.room_enemies
        ]

    @property
    def _current_tutorial_step(self) -> TutorialStep:
        return self.tutorial_steps[self.tutorial_index]

    def _complete_tutorial_action(self, action: str) -> None:
        if self.page != "game" or self.tutorial_index >= len(self.tutorial_steps) - 1:
            return
        if self._current_tutorial_step.action != action:
            return
        self.tutorial_index += 1
        if self._current_tutorial_step.action == "attack" and not self.room_enemies:
            self.room_enemies = self._build_training_room_enemies()
            self._notify("战斗训练目标已投放")
            return
        if self._current_tutorial_step.action == "parry":
            self._prepare_tutorial_parry_target()
        if self._current_tutorial_step.action == "finish":
            self._notify("教学完成，回响之门已开启")
        else:
            self._notify(f"下一步：{self._current_tutorial_step.title}")

    def _prepare_tutorial_parry_target(self) -> None:
        target = next(
            (enemy for enemy in self.room_enemies if enemy.can_be_parried()),
            None,
        )
        if target is None:
            target = Chaser(self.player.x + 46, 522)
            self.room_enemies.append(target)
        target.x = self.player.x + self.player.facing * 46
        self.pending_enemy_attacks.clear()

    def _draw(self) -> None:
        self.canvas.blit(self.assets.background, (0, 0))
        self._draw_atmosphere()
        if self.page == "menu":
            self._draw_branding()
            self._draw_menu()
            self._draw_footer()
        elif self.page == "lobby":
            self._draw_lobby()
        elif self.page == "game":
            self._draw_game()
        elif self.page == "result":
            self._draw_result()
        elif self.page == "failure":
            self._draw_failure()
        if self.overlay is not None:
            self._draw_overlay()
        if self.confirm_exit:
            self._draw_exit_confirmation()

        self.screen.fill(COLORS["ink"])
        width, height = self.screen.get_size()
        scale = min(width / LOGICAL_SIZE[0], height / LOGICAL_SIZE[1])
        scaled_size = (int(LOGICAL_SIZE[0] * scale), int(LOGICAL_SIZE[1] * scale))
        scaled = pygame.transform.scale(self.canvas, scaled_size)
        self.screen.blit(
            scaled,
            ((width - scaled_size[0]) // 2, (height - scaled_size[1]) // 2),
        )

    def _draw_atmosphere(self) -> None:
        shimmer = 0.78 + 0.22 * math.sin(self.elapsed * 2.1)
        glow = self.assets.spark.copy()
        glow.set_alpha(int(170 * shimmer) if self.elapsed % 3.2 < 0.24 else 0)
        self.canvas.blit(glow, (466, 165))

    def _draw_branding(self) -> None:
        logo = pygame.transform.scale(self.assets.logo, (144, 144))
        logo_y = 46 + int(math.sin(self.elapsed * 1.3) * 3)
        self.canvas.blit(logo, (568, logo_y))

        title = self.title_font.render("回响之刃", True, COLORS["ice"])
        self.canvas.blit(title, title.get_rect(center=(640, 218)))

        subtitle = self.subtitle_font.render("E C H O   B L A D E", True, COLORS["cyan"])
        self.canvas.blit(subtitle, subtitle.get_rect(center=(640, 254)))

        line = pygame.Rect(522, 275, 236, 2)
        pygame.draw.rect(self.canvas, COLORS["cyan"], line)
        pygame.draw.rect(self.canvas, COLORS["ice"], (line.x + 72, line.y, 92, 2))

        player = pygame.transform.scale(self.assets.player, (72, 90))
        self.canvas.blit(player, (604, 486))

    def _draw_lobby(self) -> None:
        # The lobby is drawn from simple architectural shapes so it remains
        # usable even when the prototype asset pack is replaced.
        self.canvas.fill((8, 18, 31))
        for y, color in ((92, (12, 35, 47)), (300, (10, 29, 41)), (520, (7, 20, 31))):
            pygame.draw.rect(self.canvas, color, (0, y, 1280, 220))
        pygame.draw.rect(self.canvas, (18, 52, 60), (0, 540, 1280, 180))
        pygame.draw.line(self.canvas, COLORS["cyan"], (0, 540), (1280, 540), 2)
        for x in range(24, 1280, 64):
            pygame.draw.line(self.canvas, (23, 70, 75), (x, 540), (x + 22, 720), 1)

        title = self.lobby_title_font.render("灰塔 · 回响大厅", True, COLORS["ice"])
        self.canvas.blit(title, (52, 34))
        subtitle = self.small_font.render(
            "远征归航站  /  记忆重构区", True, COLORS["cyan"]
        )
        self.canvas.blit(subtitle, (56, 78))

        relics = self.overlay_body_font.render(
            f"回响遗晶  {self.echo_relics:04d}", True, COLORS["gold"]
        )
        self.canvas.blit(relics, (930, 44))
        stats = self.small_font.render(
            f"远征 {self._stat('settlements')}  ·  最高层数 {int(self.profile.get('best_floor', 0) or 0)}",
            True,
            COLORS["muted"],
        )
        self.canvas.blit(stats, (930, 78))
        if self.result_relics:
            settlement = self.small_font.render(
                f"本次远征凝结 +{self.result_relics} 遗晶",
                True,
                COLORS["gold"],
            )
            self.canvas.blit(settlement, (930, 104))

        # Central gate: the primary interaction in the room.
        pygame.draw.rect(self.canvas, (7, 17, 28), (480, 286, 320, 254))
        pygame.draw.rect(self.canvas, (38, 104, 105), (480, 286, 320, 254), 2)
        pygame.draw.rect(self.canvas, (15, 48, 56), (545, 330, 190, 210))
        pygame.draw.rect(self.canvas, COLORS["cyan"], (545, 330, 190, 210), 2)
        gate = pygame.transform.scale(self.assets.logo, (92, 92))
        gate.set_alpha(190 + int(45 * math.sin(self.elapsed * 2.0)))
        self.canvas.blit(gate, gate.get_rect(center=(640, 394)))
        gate_label = self.overlay_body_font.render("远征城门", True, COLORS["ice"])
        self.canvas.blit(gate_label, gate_label.get_rect(center=(640, 565)))

        # Echo nexus above the gate.
        pygame.draw.circle(self.canvas, (13, 47, 57), (640, 238), 66)
        pygame.draw.circle(self.canvas, COLORS["cyan"], (640, 238), 66, 2)
        nexus = pygame.transform.scale(self.assets.logo, (78, 78))
        nexus.set_alpha(220)
        self.canvas.blit(nexus, nexus.get_rect(center=(640, 238)))
        self.canvas.blit(
            self.small_font.render("回响中枢", True, COLORS["ice"]),
            (587, 304),
        )

        # Left smith and right archive are NPC/building interaction points.
        self._draw_lobby_smith()
        self._draw_lobby_archive()
        for index, (_, label, rect) in enumerate(self._lobby_actions()):
            selected = index == self.lobby_selected
            if selected:
                pygame.draw.rect(self.canvas, (27, 78, 79), rect, 2)
                marker = self.assets.cursor.get_rect(midright=(rect.left - 12, rect.centery))
                self.canvas.blit(pygame.transform.scale(self.assets.cursor, (24, 24)), marker)
            if index == 0:
                text_rect = pygame.Rect(rect.x, rect.bottom + 4, rect.width, 32)
                self.canvas.blit(
                    self.small_font.render(label, True, COLORS["gold"] if selected else COLORS["muted"]),
                    self.small_font.render(label, True, COLORS["gold"] if selected else COLORS["muted"]).get_rect(center=text_rect.center),
                )

        hint = self.small_font.render(
            "方向键 / WASD 选择交互点    Enter 进入    Esc 返回主菜单",
            True,
            COLORS["muted"],
        )
        self.canvas.blit(hint, hint.get_rect(center=(640, 688)))
        self._draw_notification()

    def _draw_lobby_smith(self) -> None:
        pygame.draw.rect(self.canvas, (20, 35, 42), (88, 342, 240, 82))
        pygame.draw.rect(self.canvas, (72, 119, 113), (88, 342, 240, 82), 2)
        pygame.draw.rect(self.canvas, (122, 71, 54), (142, 388, 42, 46))
        pygame.draw.rect(self.canvas, COLORS["gold"], (151, 365, 24, 24))
        text = self.small_font.render("铸刃师 · 武装谱系", True, COLORS["ice"])
        self.canvas.blit(text, (202, 365))
        self.canvas.blit(
            self.small_font.render("锻造与武器解锁", True, COLORS["muted"]),
            (202, 390),
        )

    def _draw_lobby_archive(self) -> None:
        pygame.draw.rect(self.canvas, (20, 35, 42), (920, 342, 280, 82))
        pygame.draw.rect(self.canvas, (72, 119, 113), (920, 342, 280, 82), 2)
        pygame.draw.rect(self.canvas, (44, 92, 98), (952, 366, 42, 36))
        pygame.draw.line(self.canvas, COLORS["cyan"], (958, 374), (988, 374), 2)
        pygame.draw.line(self.canvas, COLORS["cyan"], (958, 382), (988, 382), 2)
        text = self.small_font.render("远征档案 · 排行记录", True, COLORS["ice"])
        self.canvas.blit(text, (1020, 365))
        self.canvas.blit(
            self.small_font.render("查看历史战绩", True, COLORS["muted"]),
            (1020, 390),
        )

    def _menu_rect(self, index: int) -> pygame.Rect:
        return pygame.Rect(440, 315 + index * 68, 400, 58)

    def _draw_menu(self) -> None:
        for index, item in enumerate(self.items):
            rect = self._menu_rect(index)
            selected = index == self.selected and item.enabled
            pressed = index == self.pressed_item
            draw_rect = rect.move(0, 2 if pressed else 0)
            panel = pygame.transform.scale(self.assets.panel, draw_rect.size)
            panel.set_alpha(255 if selected else 190)
            self.canvas.blit(panel, draw_rect)

            if selected:
                cursor = pygame.transform.scale(self.assets.cursor, (42, 42))
                cursor.set_alpha(215 + int(40 * math.sin(self.elapsed * 4.0)))
                self.canvas.blit(
                    cursor,
                    (draw_rect.x - 54, draw_rect.centery - cursor.get_height() // 2),
                )

            color = COLORS["ice"] if selected else COLORS["muted"]
            if not item.enabled:
                color = (76, 105, 112)
            label = item.label
            if not item.enabled:
                label += "  -  暂无存档"
            text = self.menu_font.render(label, True, color)
            self.canvas.blit(text, text.get_rect(center=draw_rect.center))

    def _draw_footer(self) -> None:
        controls = self.small_font.render(
            "↑↓ 选择    Enter 确认    鼠标悬停/点击    Esc 退出",
            True,
            COLORS["muted"],
        )
        self.canvas.blit(controls, controls.get_rect(center=(640, 688)))

        version = self.small_font.render(
            "PRE-ALPHA 0.2  |  灰塔记忆核心在线",
            True,
            COLORS["muted"],
        )
        self.canvas.blit(version, (32, 680))
        self._draw_notification()

    def _overlay_rect(self) -> pygame.Rect:
        if self.overlay == "progression":
            return pygame.Rect(72, 42, 1136, 636)
        return pygame.Rect(252, 96, 776, 528)

    def _overlay_back_rect(self) -> pygame.Rect:
        rect = self._overlay_rect()
        if self.overlay == "progression":
            return pygame.Rect(rect.x + 30, rect.bottom - 60, 220, 42)
        return pygame.Rect(rect.x + 30, rect.bottom - 76, 210, 44)

    def _progression_node_rects(self) -> list[pygame.Rect]:
        rect = self._overlay_rect()
        return [
            pygame.Rect(rect.x + 28, rect.y + 86 + index * 40, 520, 34)
            for index in range(len(PROGRESSION_NODES))
        ]

    def _progression_activate_rect(self) -> pygame.Rect:
        rect = self._overlay_rect()
        return pygame.Rect(rect.right - 278, rect.bottom - 60, 248, 42)

    def _setting_rects(self) -> list[pygame.Rect]:
        rect = self._overlay_rect()
        back = self._overlay_back_rect()
        return [
            pygame.Rect(rect.x + 34, rect.y + 104, rect.width - 68, 70),
            pygame.Rect(rect.x + 34, rect.y + 184, rect.width - 68, 70),
            pygame.Rect(rect.x + 34, rect.y + 264, rect.width - 68, 70),
            pygame.Rect(rect.x + 34, rect.y + 344, rect.width - 68, 70),
            pygame.Rect(back.right + 16, back.y, 220, back.height),  # 返回主菜单
            back,  # 关闭设置
        ]

    @staticmethod
    def _keybind_actions() -> list[tuple[str, str]]:
        return [
            ("left", "向左移动"),
            ("right", "向右移动"),
            ("attack", "普通攻击"),
            ("parry", "弹刀 / 防御"),
            ("dash", "冲刺"),
            ("jump", "跳跃"),
        ]

    def _keybind_rects(self) -> list[pygame.Rect]:
        rect = self._overlay_rect()
        rows = [
            pygame.Rect(rect.x + 34, rect.y + 92 + index * 52, rect.width - 68, 44)
            for index in range(len(self._keybind_actions()))
        ]
        rows.append(self._overlay_back_rect())
        return rows

    def _draw_overlay(self) -> None:
        shade = pygame.Surface(LOGICAL_SIZE, pygame.SRCALPHA)
        shade.fill((3, 8, 18, 178))
        self.canvas.blit(shade, (0, 0))
        rect = self._overlay_rect()
        pygame.draw.rect(self.canvas, (6, 16, 28), rect)
        pygame.draw.rect(self.canvas, COLORS["cyan"], rect, 2)
        pygame.draw.line(
            self.canvas,
            COLORS["ice"],
            (rect.x + 28, rect.y + 68),
            (rect.right - 28, rect.y + 68),
            1,
        )

        title_text = {
            "leaderboard": "本地排行榜",
            "keybinds": "键位设置",
            "progression": "回响中枢 · 成长拓扑",
            "portal": "回响之门",
        }.get(self.overlay, "设置")
        title = self.overlay_title_font.render(title_text, True, COLORS["ice"])
        self.canvas.blit(title, (rect.x + 30, rect.y + 24))

        if self.overlay == "leaderboard":
            self._draw_leaderboard(rect)
        elif self.overlay == "keybinds":
            self._draw_keybinds(rect)
        elif self.overlay == "progression":
            self._draw_progression(rect)
        elif self.overlay == "portal":
            self._draw_portal_choice(rect)
        else:
            self._draw_settings(rect)

        hint_text = (
            "↑↓ 选择    Enter 设置    Esc 返回"
            if self.overlay == "keybinds"
            else "↑↓ 浏览节点    Enter 激活    Esc 返回"
            if self.overlay == "progression"
            else "←→ 选择    Enter 确认    Esc 留在房间"
            if self.overlay == "portal"
            else "↑↓ 选择    ←→ 调整    Enter 确认    Esc 返回"
        )
        hint = self.small_font.render(hint_text, True, COLORS["muted"])
        self.canvas.blit(hint, (rect.right - hint.get_width() - 28, rect.bottom - 34))

    def _draw_portal_choice(self, rect: pygame.Rect) -> None:
        """传送门选择界面：返回主菜单 / 下一关。"""
        labels = self._portal_choice_labels()
        info = self.overlay_body_font.render(
            f"本局分数 {self.run_score:05d}    完美弹刀 {self.run_parries}    "
            f"第 {self.run_floor} 层",
            True,
            COLORS["muted"],
        )
        self.canvas.blit(info, info.get_rect(center=(rect.centerx, rect.y + 132)))
        note = self.small_font.render(
            "进入后本局结算，回响遗晶自动凝结",
            True,
            COLORS["muted"],
        )
        self.canvas.blit(note, note.get_rect(center=(rect.centerx, rect.y + 168)))
        for index, (label, choice_rect) in enumerate(
            zip(labels, self._portal_choice_rects())
        ):
            selected = index == self.portal_choice_index
            if selected:
                pygame.draw.rect(self.canvas, (14, 43, 52), choice_rect)
                pygame.draw.rect(self.canvas, COLORS["gold"], choice_rect, 2)
            else:
                pygame.draw.rect(self.canvas, (6, 16, 28), choice_rect)
                pygame.draw.rect(self.canvas, COLORS["cyan"], choice_rect, 1)
            text = self.menu_font.render(
                label,
                True,
                COLORS["gold"] if selected else COLORS["ice"],
            )
            self.canvas.blit(text, text.get_rect(center=choice_rect.center))

    def _draw_progression(self, rect: pygame.Rect) -> None:
        unlocked = self._unlocked_nodes()
        node_rects = self._progression_node_rects()
        for index, (node, node_rect) in enumerate(zip(PROGRESSION_NODES, node_rects)):
            is_unlocked = node.node_id in unlocked
            is_selected = index == self.progression_selected
            available = self._node_available(node)
            if is_selected:
                pygame.draw.rect(self.canvas, (20, 61, 66), node_rect)
                pygame.draw.rect(self.canvas, COLORS["cyan"], node_rect, 2)
            elif is_unlocked:
                pygame.draw.rect(self.canvas, (15, 46, 49), node_rect)
            branch_color = {
                "锻刃谱系": COLORS["gold"],
                "共鸣谱系": COLORS["cyan"],
                "远征谱系": (166, 205, 184),
                "终局节点": COLORS["red"],
            }[node.branch]
            pygame.draw.rect(self.canvas, branch_color, (node_rect.x + 10, node_rect.y + 9, 7, 16))
            state = "已铭刻" if is_unlocked else "可激活" if available else "未解锁"
            state_color = COLORS["cyan"] if is_unlocked else COLORS["gold"] if available else COLORS["muted"]
            label = self.lobby_node_font.render(
                f"{node.title}  ·  {node.branch}", True, COLORS["ice"] if is_selected else COLORS["muted"]
            )
            self.canvas.blit(label, (node_rect.x + 30, node_rect.y + 7))
            state_text = self.small_font.render(state, True, state_color)
            self.canvas.blit(state_text, (node_rect.right - state_text.get_width() - 16, node_rect.y + 8))

        node = PROGRESSION_NODES[self.progression_selected]
        detail = pygame.Rect(rect.x + 584, rect.y + 86, 514, 430)
        pygame.draw.rect(self.canvas, (8, 25, 35), detail)
        pygame.draw.rect(self.canvas, (42, 105, 106), detail, 2)
        heading = self.overlay_body_font.render(node.title, True, COLORS["ice"])
        self.canvas.blit(heading, (detail.x + 28, detail.y + 28))
        branch = self.small_font.render(node.branch, True, COLORS["cyan"])
        self.canvas.blit(branch, (detail.x + 30, detail.y + 64))
        lines = [
            f"消耗：{node.cost} 回响遗晶",
            f"前置：{self._node_title(node.prerequisite)}",
            f"门槛：{node.requirement}",
            f"功能：{node.effect}",
        ]
        for index, line in enumerate(lines):
            color = COLORS["gold"] if index == 0 else COLORS["muted"]
            for line_index, wrapped in enumerate(self._wrap_text(line, self.small_font, detail.width - 56)):
                y = detail.y + 112 + index * 60 + line_index * 21
                self.canvas.blit(self.small_font.render(wrapped, True, color), (detail.x + 28, y))
        self._draw_ui_button(
            self._progression_activate_rect(),
            "激活节点",
            selected=True,
            enabled=self._node_available(node) and self.echo_relics >= node.cost,
        )
        self._draw_ui_button(self._overlay_back_rect(), "离开中枢")

    @staticmethod
    def _node_title(node_id: str | None) -> str:
        if node_id is None:
            return "无"
        for node in PROGRESSION_NODES:
            if node.node_id == node_id:
                return node.title
        return "未知节点"

    def _draw_leaderboard(self, rect: pygame.Rect) -> None:
        rows: list[tuple[str, str, str]] = []
        scores = self.profile.get("scores", [])
        if isinstance(scores, list):
            for score in scores[:5]:
                if isinstance(score, dict):
                    rows.append(
                        (
                            f"{int(score.get('score', 0)):05d}",
                            f"第 {int(score.get('floor', 1))} 层",
                            f"弹刀 {int(score.get('parries', 0))} 次",
                        )
                    )
        rows.extend(
            [
                ("--", "暂无成绩", "完成第一局后记录"),
                ("--", "暂无成绩", "挑战灰塔，留下你的分数"),
                ("--", "暂无成绩", "完美弹刀会带来更高倍率"),
            ]
        )
        for index, (score, name, detail) in enumerate(rows):
            y = rect.y + 110 + index * 64
            if y > rect.bottom - 105:
                break
            pygame.draw.line(
                self.canvas,
                (30, 77, 84),
                (rect.x + 30, y + 42),
                (rect.right - 30, y + 42),
                1,
            )
            rank_text = self.overlay_body_font.render(
                str(index + 1).zfill(2),
                True,
                COLORS["cyan"],
            )
            self.canvas.blit(rank_text, (rect.x + 42, y))
            name_text = self.overlay_body_font.render(name, True, COLORS["ice"])
            self.canvas.blit(name_text, (rect.x + 112, y))
            score_text = self.overlay_body_font.render(score, True, COLORS["ice"])
            self.canvas.blit(score_text, (rect.right - score_text.get_width() - 42, y))
            detail_text = self.small_font.render(detail, True, COLORS["muted"])
            self.canvas.blit(detail_text, (rect.x + 112, y + 27))
        self._draw_ui_button(
            self._overlay_back_rect(),
            "返回大厅" if self.return_page == "lobby" else "返回主菜单",
            self.overlay_selected == 0,
        )

    def _draw_settings(self, rect: pygame.Rect) -> None:
        labels = [
            ("音量", f"{self.settings['volume']}%"),
            ("辅助模式", "开启" if self.settings["assist_mode"] else "关闭"),
            ("全屏", "开启" if self.settings["fullscreen"] else "关闭"),
            ("键位设置", "进入"),
        ]
        setting_rects = self._setting_rects()
        for index, ((label, value), setting_rect) in enumerate(
            zip(labels, setting_rects[:4])
        ):
            selected = index == self.overlay_selected
            if selected:
                pygame.draw.rect(self.canvas, (14, 43, 52), setting_rect)
                pygame.draw.rect(self.canvas, COLORS["cyan"], setting_rect, 1)
            y = setting_rect.y + 22
            label_text = self.overlay_body_font.render(label, True, COLORS["ice"])
            value_text = self.overlay_body_font.render(value, True, COLORS["cyan"])
            self.canvas.blit(label_text, (rect.x + 58, y))
            self.canvas.blit(value_text, (rect.right - value_text.get_width() - 58, y))
            if index == 0:
                bar = pygame.Rect(rect.x + 250, y + 31, 270, 6)
                pygame.draw.rect(self.canvas, (24, 57, 65), bar)
                pygame.draw.rect(
                    self.canvas,
                    COLORS["cyan"],
                    (bar.x, bar.y, int(bar.width * self.settings["volume"] / 100), bar.height),
                )
                pygame.draw.rect(self.canvas, COLORS["ice"], bar, 1)
        self._draw_ui_button(
            setting_rects[4],
            "返回主菜单",
            self.overlay_selected == 4,
        )
        self._draw_ui_button(
            setting_rects[5],
            "关闭设置",
            self.overlay_selected == 5,
        )

    def _draw_keybinds(self, rect: pygame.Rect) -> None:
        for index, (action, label) in enumerate(self._keybind_actions()):
            row = self._keybind_rects()[index]
            selected = index == self.keybind_selected
            if selected:
                pygame.draw.rect(self.canvas, (14, 43, 52), row)
                pygame.draw.rect(self.canvas, COLORS["cyan"], row, 1)
            label_text = self.overlay_body_font.render(label, True, COLORS["ice"])
            value = (
                "请按下按键..."
                if self.rebinding_action == action
                else self._key_name(self.keybinds[action])
            )
            value_text = self.overlay_body_font.render(value, True, COLORS["gold"] if self.rebinding_action == action else COLORS["cyan"])
            self.canvas.blit(label_text, (row.x + 28, row.y + 12))
            self.canvas.blit(value_text, (row.right - value_text.get_width() - 28, row.y + 12))
        self._draw_ui_button(
            self._overlay_back_rect(),
            "返回设置",
            self.keybind_selected == len(self._keybind_actions()),
        )

    def _draw_ui_button(
        self,
        rect: pygame.Rect,
        label: str,
        selected: bool = False,
        enabled: bool = True,
    ) -> None:
        panel = pygame.transform.scale(self.assets.panel, rect.size)
        panel.set_alpha(255 if selected else 195 if enabled else 120)
        self.canvas.blit(panel, rect)
        if not enabled:
            color = (86, 108, 116)
        else:
            color = COLORS["ice"] if selected else COLORS["muted"]
        text = self.menu_font.render(label, True, color)
        self.canvas.blit(text, text.get_rect(center=rect.center))
        if selected and enabled:
            cursor = pygame.transform.scale(self.assets.cursor, (30, 30))
            cursor.set_alpha(215 + int(40 * math.sin(self.elapsed * 4.0)))
            self.canvas.blit(
                cursor,
                (rect.x - 38, rect.centery - cursor.get_height() // 2),
            )

    def _activate_setting(self, index: int) -> None:
        if index == 0:
            self._change_setting(index, 5)
        elif index == 1:
            self.settings["assist_mode"] = not self.settings["assist_mode"]
            self._save_profile()
            self._notify(
                "辅助模式已" + ("开启" if self.settings["assist_mode"] else "关闭")
            )
        elif index == 2:
            self.settings["fullscreen"] = not self.settings["fullscreen"]
            self._save_profile()
            self._apply_display_mode()
            self._notify("全屏已" + ("开启" if self.settings["fullscreen"] else "关闭"))
        elif index == 3:
            self._open_overlay("keybinds")
        elif index == 4:
            self._return_to_menu_from_settings()
        elif index == 5:
            self._close_overlay()

    def _return_to_menu_from_settings(self) -> None:
        """设置里的「返回主菜单」：在主菜单直接关闭，在关卡/大厅先确认。"""
        if self.return_page == "menu":
            self._close_overlay()
            return
        self.overlay = None
        self.confirm_exit = True

    def _change_setting(self, index: int, amount: int) -> None:
        if index == 0:
            self._set_volume(self.settings["volume"] + amount)
        elif index == 2:
            self._activate_setting(index)

    def _apply_display_mode(self) -> None:
        flags = pygame.FULLSCREEN if self.settings["fullscreen"] else pygame.RESIZABLE
        self.screen = pygame.display.set_mode(LOGICAL_SIZE, flags)

    def _build_tutorial_steps(self) -> list[TutorialStep]:
        """按当前键位设置生成教学步骤，让提示与实际按键保持一致。"""
        keys = {
            action: self._key_name(bound)
            for action, bound in self.keybinds.items()
        }
        return [
            TutorialStep(
                "移动训练",
                f"按 {keys['left']}/{keys['right']} 或方向键左右移动一段距离",
                "先感受加速和停下，门会在完成教学后打开。",
                "move",
            ),
            TutorialStep(
                "跳跃训练",
                f"按 {keys['jump']} 跳起",
                "跳跃会受到重力影响，可以在空中微调左右方向。",
                "jump",
            ),
            TutorialStep(
                "基础攻击",
                f"靠近训练目标，按 {keys['attack']} 或鼠标左键挥砍",
                "横向攻击会跟随角色朝向，命中后增加分数与连击。",
                "attack",
            ),
            TutorialStep(
                "上劈训练",
                f"按住 W/↑ 再按 {keys['attack']} 使用上劈",
                "上劈用于攻击头顶目标，之后会接入空中敌人。",
                "up_attack",
            ),
            TutorialStep(
                "下劈训练",
                f"跳到目标上方，按住 S/↓ 再按 {keys['attack']} 下劈命中",
                "下劈命中会把你向上弹起，连续命中可以保持滞空。",
                "down_attack",
            ),
            TutorialStep(
                "弹刀训练",
                f"按 {keys['parry']} 进行一次完美弹刀演示",
                "正式战斗里要等金色闪光亮起再按，远程子弹靠近时也能弹开。",
                "parry",
            ),
            TutorialStep(
                "教学完成",
                "走进右侧的回响之门，选择前往灰塔大厅",
                "你已经完成基础操作，进门后本局自动结算。",
                "finish",
            ),
        ]

    def _refresh_tutorial_hints(self) -> None:
        """键位设置变化后，重新生成教学关卡里的按键提示。"""
        self.tutorial_steps = self._build_tutorial_steps()

    @staticmethod
    def _build_training_room_enemies() -> list[Enemy]:
        return [
            Chaser(320, 522),
            SpearThrower(650, 522),
        ]

    def _start_run(self, floor: int, *, tutorial: bool = True) -> None:
        self.pressed_keys.clear()
        self.page = "game"
        self.overlay = None
        self.confirm_exit = False
        self.is_tutorial_run = tutorial
        self.run_floor = max(1, floor)
        self.run_score = 0
        self.run_combo = 0
        self.run_max_combo = 0
        self.run_parries = 0
        self.run_currency = 20 if "reserve_carry" in self._unlocked_nodes() else 0
        self.player = Player(230, 566)
        self._attack_hits.clear()
        self._defeated_enemies.clear()
        self.room_enemies = []
        # 进入关卡后敌人延迟登场，避免开门瞬间贴脸
        if tutorial:
            self.pending_spawn = []
            self.enemy_spawn_timer = 0.0
        else:
            self.pending_spawn = self._build_training_room_enemies()
            self.enemy_spawn_timer = ENEMY_SPAWN_DELAY
        self.pending_enemy_attacks.clear()
        self.attack_impacts.clear()
        self.reflected_projectiles.clear()
        self.dash_trails.clear()
        self._dash_trail_timer = 0.0
        self.portal_open = False
        self.portal_appear = 0.0
        self.portal_enter_timer = 0.0
        self.portal_lock_timer = 0.0
        self.portal_choice_index = 0
        self._refresh_tutorial_hints()
        self.tutorial_index = 0 if tutorial else len(self.tutorial_steps) - 1
        self.tutorial_start_x = self.player.x
        self.tutorial_move_distance = 0.0
        self._step_timer = 0.0
        if self.pending_spawn:
            self._notify("敌影正在接近…")
        else:
            self._notify("试炼房间已开启")

    def _page_buttons(self) -> dict[str, pygame.Rect]:
        if self.page == "result":
            return {
                "restart": pygame.Rect(430, 500, 200, 58),
                "menu": pygame.Rect(650, 500, 200, 58),
            }
        if self.page == "failure":
            return {"lobby": pygame.Rect(490, 512, 300, 58)}
        return {}

    def _page_button_at(self, position: tuple[int, int]) -> str | None:
        logical = self._to_logical(position)
        for name, rect in self._page_buttons().items():
            if rect.collidepoint(logical):
                return name
        return None

    def _activate_page_button(self, button: str | None) -> None:
        if button == "finish" and self.page == "game":
            if self.is_tutorial_run and self._current_tutorial_step.action != "finish":
                self._notify(f"先完成教学：{self._current_tutorial_step.title}")
                return
            self._finish_run()
        elif button == "restart" and self.page == "result":
            self._start_run(1)
        elif button == "lobby" and self.page == "failure":
            relics = self.result_relics
            self._enter_lobby()
            self._notify(f"失败勘定完成，凝结回响遗晶 +{relics}")
        elif button == "menu":
            self.page = "menu"
            self.confirm_exit = False
            self._notify("已返回主菜单")

    def _exit_buttons(self) -> dict[str, pygame.Rect]:
        return {
            "confirm": pygame.Rect(430, 390, 190, 48),
            "cancel": pygame.Rect(660, 390, 190, 48),
        }

    def _exit_button_at(self, position: tuple[int, int]) -> str | None:
        logical = self._to_logical(position)
        for name, rect in self._exit_buttons().items():
            if rect.collidepoint(logical):
                return name
        return None

    def _activate_exit_button(self, button: str | None) -> None:
        if button == "confirm":
            if self.page == "menu":
                self.running = False
            else:
                self.page = "menu"
                self.confirm_exit = False
                self._notify("已返回主菜单")
        elif button == "cancel":
            self.confirm_exit = False

    def _finish_run(self) -> None:
        relics = self._settle_run()
        self._enter_lobby()
        self._notify(f"远征已结算，凝结回响遗晶 +{relics}")

    def _settle_run(self) -> int:
        """结算本局：分数、遗晶、存档与统计，返回获得的回响遗晶。"""
        self.result_score = self.run_score + self.run_floor * 500 + self.run_parries * 100
        previous_best = int(self.profile.get("best_score", 0) or 0)
        self.result_new_record = self.result_score > previous_best
        self.profile["best_score"] = max(previous_best, self.result_score)
        self.profile["best_floor"] = max(
            int(self.profile.get("best_floor", 0) or 0),
            self.run_floor,
        )
        scores = self.profile.get("scores", [])
        if not isinstance(scores, list):
            scores = []
        scores.append(
            {
                "score": self.result_score,
                "floor": self.run_floor,
                "parries": self.run_parries,
            }
        )
        self.profile["scores"] = sorted(
            [score for score in scores if isinstance(score, dict)],
            key=lambda score: int(score.get("score", 0) or 0),
            reverse=True,
        )[:20]
        self.result_relics = 40 if self.is_tutorial_run else 30 + self.run_floor * 10 + min(
            self.run_parries * 2, 30
        )
        self.profile["echo_relics"] = self.echo_relics + self.result_relics
        self.profile["tutorial_completed"] = (
            True if self.is_tutorial_run else self.tutorial_completed
        )
        lifetime_stats = self.profile.get("lifetime_stats", {})
        if not isinstance(lifetime_stats, dict):
            lifetime_stats = {}
        lifetime_stats = lifetime_stats.copy()
        lifetime_stats["settlements"] = self._stat("settlements") + 1
        lifetime_stats["parries"] = self._stat("parries") + self.run_parries
        self.profile["lifetime_stats"] = lifetime_stats
        self._save_profile()
        self.has_save = True
        self.items = self._build_items()
        return self.result_relics

    def _fail_run(self) -> None:
        if self.page != "game":
            return

        self.result_score = self.run_score
        previous_best = int(self.profile.get("best_score", 0) or 0)
        self.result_new_record = self.result_score > previous_best
        self.profile["best_score"] = max(previous_best, self.result_score)
        self.profile["best_floor"] = max(
            int(self.profile.get("best_floor", 0) or 0),
            self.run_floor,
        )
        scores = self.profile.get("scores", [])
        if not isinstance(scores, list):
            scores = []
        scores.append(
            {
                "score": self.result_score,
                "floor": self.run_floor,
                "parries": self.run_parries,
                "outcome": "failure",
            }
        )
        self.profile["scores"] = sorted(
            [score for score in scores if isinstance(score, dict)],
            key=lambda score: int(score.get("score", 0) or 0),
            reverse=True,
        )[:20]
        self.result_relics = (
            0
            if self.is_tutorial_run
            else 15 + self.run_floor * 5 + min(self.run_parries * 2, 15)
        )
        self.profile["echo_relics"] = self.echo_relics + self.result_relics

        lifetime_stats = self.profile.get("lifetime_stats", {})
        if not isinstance(lifetime_stats, dict):
            lifetime_stats = {}
        lifetime_stats = lifetime_stats.copy()
        lifetime_stats["settlements"] = self._stat("settlements") + 1
        lifetime_stats["failures"] = self._stat("failures") + 1
        lifetime_stats["parries"] = self._stat("parries") + self.run_parries
        self.profile["lifetime_stats"] = lifetime_stats
        self._save_profile()
        self.has_save = True
        self.items = self._build_items()

        self.page = "failure"
        self.overlay = None
        self.confirm_exit = False
        self.pressed_keys.clear()
        self.pending_enemy_attacks.clear()
        self.attack_impacts.clear()
        self._notify("记忆载体崩解，远征已终止")

    def _draw_game(self) -> None:
        shade = pygame.Surface(LOGICAL_SIZE, pygame.SRCALPHA)
        shade.fill((3, 8, 18, 80))
        self.canvas.blit(shade, (0, 0))

        title = self.overlay_title_font.render("灰塔 · 序章试炼", True, COLORS["ice"])
        self.canvas.blit(title, (54, 36))
        subtitle = self.small_font.render("ROOM 01  /  回响训练场", True, COLORS["cyan"])
        self.canvas.blit(subtitle, (56, 78))

        if self.pending_spawn:
            self._draw_spawn_countdown()

        self._draw_stat_bar(
            "生命",
            100,
            104,
            240,
            14,
            self.player.hp / self.player.max_hp,
            COLORS["red"],
        )
        self._draw_stat_bar("回响能量", 100, 142, 240, 14, 0.42, COLORS["cyan"])
        score = self.overlay_body_font.render(
            f"分数  {self.run_score:05d}",
            True,
            COLORS["ice"],
        )
        floor = self.small_font.render(
            f"第 {self.run_floor} 层  ·  威胁 12%",
            True,
            COLORS["muted"],
        )
        self.canvas.blit(score, (930, 42))
        self.canvas.blit(floor, (930, 76))
        self._draw_run_currency_ui()

        # 战斗区横跨整块画面，角色与敌人都可以在左右边界之间自由移动
        pygame.draw.rect(self.canvas, (12, 37, 48), (48, 424, 1184, 142), 2)
        pygame.draw.line(self.canvas, (37, 103, 103), (60, 566), (1220, 566), 2)
        gate = pygame.transform.scale(self.assets.logo, (96, 96))
        gate.set_alpha(100)
        self.canvas.blit(gate, (592, 330))
        self._draw_portal()
        self._draw_player()
        self._draw_enemies()
        if self.is_tutorial_run:
            self._draw_tutorial_panel()

        room_title = self.overlay_body_font.render(
            "试炼房间已开启" if self.is_tutorial_run else "远征序章已开启",
            True,
            COLORS["ice"],
        )
        self.canvas.blit(room_title, room_title.get_rect(center=(640, 296)))
        if self.is_tutorial_run:
            room_hint = self.small_font.render(
                self._current_tutorial_step.objective,
                True,
                COLORS["muted"],
            )
            self.canvas.blit(room_hint, room_hint.get_rect(center=(640, 325)))
        else:
            room_hint = self.small_font.render(
                "清空房间后，右侧会开启回响之门",
                True,
                COLORS["muted"],
            )
            self.canvas.blit(room_hint, room_hint.get_rect(center=(640, 325)))

        combo = self.overlay_body_font.render(
            f"连击  x{self.run_combo}",
            True,
            COLORS["gold"],
        )
        parries = self.small_font.render(
            f"完美弹刀  {self.run_parries}",
            True,
            COLORS["cyan"],
        )
        self.canvas.blit(combo, (100, 610))
        self.canvas.blit(parries, (100, 642))

        self._draw_settings_icon()
        self._draw_portal_status()
        controls = self.small_font.render(
            (
                f"{self._key_name(self.keybinds['left'])}/{self._key_name(self.keybinds['right'])} 移动    "
                f"{self._key_name(self.keybinds['attack'])} 攻击    "
                f"{self._key_name(self.keybinds['parry'])} 弹刀    "
                f"{self._key_name(self.keybinds['dash'])} 冲刺    "
                f"{self._key_name(self.keybinds['jump'])} 跳跃    Esc 设置"
            ),
            True,
            COLORS["muted"],
        )
        self.canvas.blit(controls, controls.get_rect(center=(640, 690)))
        self._draw_notification()

    def _settings_icon_rect(self) -> pygame.Rect:
        return pygame.Rect(1224, 22, 34, 34)

    def _draw_settings_icon(self) -> None:
        """右上角小齿轮：点击或按 Esc 打开设置。"""
        rect = self._settings_icon_rect()
        hovered = rect.collidepoint(self._to_logical(pygame.mouse.get_pos()))
        color = COLORS["cyan"] if hovered else COLORS["muted"]
        pygame.draw.rect(self.canvas, (6, 16, 28), rect)
        pygame.draw.rect(self.canvas, color, rect, 1)
        center = rect.center
        for index in range(8):
            angle = math.tau * index / 8.0 + math.pi / 8.0
            pygame.draw.line(
                self.canvas,
                color,
                (
                    round(center[0] + math.cos(angle) * 8),
                    round(center[1] + math.sin(angle) * 8),
                ),
                (
                    round(center[0] + math.cos(angle) * 13),
                    round(center[1] + math.sin(angle) * 13),
                ),
                3,
            )
        pygame.draw.circle(self.canvas, color, center, 8, 2)
        pygame.draw.circle(self.canvas, color, center, 2)

    def _draw_portal(self) -> None:
        """关卡胜利后的回响之门：出现动画 + 待机循环 + 进入动画。"""
        if not self.portal_open:
            return
        rect = self._portal_rect()
        appear = max(0.0, min(1.0, self.portal_appear))

        if self.portal_enter_timer > 0.0:
            progress = 1.0 - self.portal_enter_timer / max(0.05, PORTAL_ENTER_TIME)
            frames = self.assets.portal_enter
            if frames:
                index = min(len(frames) - 1, int(progress * len(frames)))
                image = frames[index]
            else:
                image = self.assets.portal_idle[0] if self.assets.portal_idle else None
            if image is not None:
                self.canvas.blit(image, rect.topleft)
            # 白场闪光
            flash = pygame.Surface(LOGICAL_SIZE, pygame.SRCALPHA)
            alpha = round(150 * max(0.0, progress - 0.35) / 0.65)
            flash.fill((*COLORS["ice"], min(200, alpha)))
            self.canvas.blit(flash, (0, 0))
            return

        frames = self.assets.portal_idle
        image = None
        if frames:
            image = frames[int(self.elapsed * 4.0) % len(frames)]
        if image is None:
            return

        if appear < 1.0:
            # 出现动画：由小放大 + 淡入
            scale = 0.25 + 0.75 * appear
            size = (
                max(8, round(image.get_width() * scale)),
                max(8, round(image.get_height() * scale)),
            )
            scaled = pygame.transform.scale(image, size)
            scaled.set_alpha(round(255 * appear))
            self.canvas.blit(
                scaled,
                scaled.get_rect(midbottom=(rect.centerx, rect.bottom)),
            )
            ring_radius = round(20 + 70 * appear)
            surface = pygame.Surface(LOGICAL_SIZE, pygame.SRCALPHA)
            pygame.draw.circle(
                surface,
                (*COLORS["gold"], round(200 * (1.0 - appear))),
                (rect.centerx, rect.centery),
                ring_radius,
                3,
            )
            self.canvas.blit(surface, (0, 0))
            return

        self.canvas.blit(image, rect.topleft)
        glow = 0.5 + 0.5 * math.sin(self.elapsed * 3.0)
        surface = pygame.Surface(LOGICAL_SIZE, pygame.SRCALPHA)
        pygame.draw.circle(
            surface,
            (*COLORS["cyan"], round(40 + 40 * glow)),
            (rect.centerx, rect.centery),
            round(rect.width * 0.62),
            2,
        )
        self.canvas.blit(surface, (0, 0))

    def _draw_portal_status(self) -> None:
        """传送门相关提示：出现后提示走进门内。"""
        if not self.portal_open or self.portal_enter_timer > 0.0:
            return
        if self.portal_appear < 1.0:
            return
        hint = self.small_font.render("走进回响之门继续", True, COLORS["gold"])
        hint.set_alpha(180 + round(75 * (math.sin(self.elapsed * 5.0) + 1.0) * 0.5))
        rect = self._portal_rect()
        self.canvas.blit(hint, hint.get_rect(center=(rect.centerx, rect.top - 22)))

    def _draw_run_currency_ui(self) -> None:
        panel = pygame.Rect(1050, 98, 180, 42)
        shade = pygame.Surface(panel.size, pygame.SRCALPHA)
        shade.fill((6, 16, 28, 220))
        self.canvas.blit(shade, panel)
        pygame.draw.rect(self.canvas, (100, 82, 48), panel, 1)

        coin_center = (panel.x + 24, panel.centery)
        pygame.draw.circle(self.canvas, (91, 68, 37), coin_center, 12)
        pygame.draw.circle(self.canvas, COLORS["gold"], coin_center, 10, 2)
        pygame.draw.polygon(
            self.canvas,
            COLORS["gold"],
            (
                (coin_center[0], coin_center[1] - 5),
                (coin_center[0] + 5, coin_center[1]),
                (coin_center[0], coin_center[1] + 5),
                (coin_center[0] - 5, coin_center[1]),
            ),
            1,
        )
        label = self.small_font.render("战时铸币", True, COLORS["muted"])
        value = self.overlay_body_font.render(
            f"{self.run_currency:03d}", True, COLORS["gold"]
        )
        self.canvas.blit(label, (panel.x + 44, panel.y + 3))
        self.canvas.blit(value, (panel.right - value.get_width() - 12, panel.y + 17))

    def _draw_tutorial_panel(self) -> None:
        step = self._current_tutorial_step
        rect = pygame.Rect(820, 125, 380, 225)
        shade = pygame.Surface(rect.size, pygame.SRCALPHA)
        shade.fill((6, 16, 28, 226))
        self.canvas.blit(shade, rect)
        pygame.draw.rect(self.canvas, COLORS["cyan"], rect, 2)
        pygame.draw.line(
            self.canvas,
            COLORS["ice"],
            (rect.x + 22, rect.y + 58),
            (rect.right - 22, rect.y + 58),
            1,
        )

        progress = self.small_font.render(
            f"教学 {self.tutorial_index + 1}/{len(self.tutorial_steps)}",
            True,
            COLORS["gold"],
        )
        title = self.overlay_body_font.render(step.title, True, COLORS["ice"])
        self.canvas.blit(progress, (rect.x + 24, rect.y + 18))
        self.canvas.blit(title, (rect.x + 24, rect.y + 34))

        for index, line_text in enumerate(
            self._wrap_text(step.objective, self.overlay_body_font, rect.width - 48)
        ):
            line_surface = self.overlay_body_font.render(line_text, True, COLORS["ice"])
            self.canvas.blit(line_surface, (rect.x + 24, rect.y + 82 + index * 28))

        hint_lines = self._wrap_text(step.hint, self.small_font, rect.width - 48)
        hint_y = rect.bottom - 34 - (len(hint_lines) - 1) * 21
        for index, line_text in enumerate(hint_lines):
            line_surface = self.small_font.render(line_text, True, COLORS["muted"])
            self.canvas.blit(line_surface, (rect.x + 24, hint_y + index * 21))

        dot_y = rect.bottom - 18
        for index in range(len(self.tutorial_steps)):
            color = COLORS["cyan"] if index <= self.tutorial_index else (45, 88, 96)
            pygame.draw.rect(
                self.canvas,
                color,
                (rect.x + 24 + index * 18, dot_y, 10, 5),
            )

    def _wrap_text(
        self,
        text: str,
        font: pygame.font.Font,
        max_width: int,
    ) -> list[str]:
        lines: list[str] = []
        current = ""
        for char in text:
            candidate = current + char
            if current and font.size(candidate)[0] > max_width:
                lines.append(current)
                current = char
            else:
                current = candidate
        if current:
            lines.append(current)
        return lines or [""]

    def _draw_player(self) -> None:
        # 闪避残影先画在角色下方，形成拖尾
        for trail in self.dash_trails:
            ratio = max(0.0, min(1.0, trail.remaining / trail.total))
            ghost = self._dash_trail_surface(trail.sprite, trail.facing)
            ghost.set_alpha(max(0, min(255, round(165 * ratio))))
            self.canvas.blit(
                ghost,
                (round(trail.x - 48), round(trail.y - 120)),
            )

        sprite_name = self._player_sprite_name()
        image = self.assets.player_sprites.get(sprite_name) or self.assets.player
        if self.player.facing < 0:
            image = pygame.transform.flip(image, True, False)

        bob = 0
        if self.player.grounded and abs(self.player.velocity_x) > 20:
            bob = round(math.sin(self.elapsed * 18.0) * 3)

        player_image = pygame.transform.scale(image, (96, 120))
        draw_x = round(self.player.x - player_image.get_width() / 2)
        draw_y = round(self.player.y - player_image.get_height() + bob)
        self.canvas.blit(player_image, (draw_x, draw_y))
        if self.player.parry_active:
            spark = pygame.transform.scale(self.assets.spark, (112, 112))
            spark.set_alpha(230 if self.player.perfect_parry_active else 120)
            self.canvas.blit(
                spark,
                spark.get_rect(center=(round(self.player.x), round(self.player.y - 58))),
            )
        self._draw_attack_effect()

    def _draw_attack_effect(self) -> None:
        hitbox = self.player.attack_hitbox
        if hitbox is None:
            return

        sprite = self.assets.slash_sprites.get(self.player.attack_direction)
        if sprite is not None:
            effect = sprite
            if self.player.attack_direction == "side" and self.player.facing < 0:
                effect = pygame.transform.flip(effect, True, False)
            effect.set_alpha(180)
            if self.player.attack_direction == "side":
                center = (round(hitbox.left + hitbox.width / 2), round(self.player.y - 66))
            elif self.player.attack_direction == "up":
                center = (round(self.player.x), round(hitbox.top + hitbox.height / 2))
            else:
                center = (round(self.player.x), round(hitbox.top + hitbox.height / 2))
            self.canvas.blit(effect, effect.get_rect(center=center))
            return

        effect = pygame.Surface(LOGICAL_SIZE, pygame.SRCALPHA)
        if self.player.attack_direction == "up":
            start_y = self.player.y - self.player.BODY_HEIGHT + 8
            end_y = hitbox.top
            for offset, alpha, width in ((-16, 95, 3), (0, 190, 5), (16, 115, 3)):
                color = (*COLORS["ice"], alpha)
                pygame.draw.line(
                    effect,
                    color,
                    (round(self.player.x + offset), round(start_y)),
                    (round(self.player.x + offset * 0.25), round(end_y)),
                    width,
                )
        elif self.player.attack_direction == "down":
            start_y = self.player.y - 58
            end_y = hitbox.bottom
            for offset, alpha, width in ((-16, 95, 3), (0, 190, 5), (16, 115, 3)):
                color = (*COLORS["ice"], alpha)
                pygame.draw.line(
                    effect,
                    color,
                    (round(self.player.x + offset), round(start_y)),
                    (round(self.player.x + offset * 0.25), round(end_y)),
                    width,
                )
        else:
            start_x = self.player.x + self.player.facing * 18
            end_x = (
                hitbox.right + 12
                if self.player.facing > 0
                else hitbox.left - 12
            )
            center_y = self.player.y - 64
            for offset, alpha, width in ((-26, 95, 3), (0, 190, 5), (24, 115, 3)):
                color = (*COLORS["ice"], alpha)
                pygame.draw.line(
                    effect,
                    color,
                    (round(start_x), round(center_y + offset)),
                    (round(end_x), round(center_y + offset * 0.25)),
                    width,
                )
        self.canvas.blit(effect, (0, 0))

    def _draw_enemies(self) -> None:
        colors = {
            "chaser": COLORS["red"],
            "spear_thrower": COLORS["gold"],
            "shield_guard": COLORS["ice"],
            "rift_worm": (166, 99, 244),
            "resonance_mage": COLORS["cyan"],
        }
        for enemy in self.room_enemies:
            if enemy.defeated:
                continue
            x, y = int(enemy.x), int(enemy.y)
            sprite = self.assets.enemy_sprites.get(enemy.kind)
            if sprite is not None:
                draw_rect = sprite.get_rect(midbottom=(x, y))
                self.canvas.blit(sprite, draw_rect)
                hp_ratio = enemy.hp / enemy.max_hp if enemy.max_hp else 0
                hp_back = pygame.Rect(x - 26, y - 104, 52, 5)
                pygame.draw.rect(self.canvas, (24, 57, 65), hp_back)
                pygame.draw.rect(
                    self.canvas,
                    COLORS["red"],
                    (
                        hp_back.x,
                        hp_back.y,
                        int(hp_back.width * hp_ratio),
                        hp_back.height,
                    ),
                )
                label = self.small_font.render(enemy.display_name, True, COLORS["ice"])
                self.canvas.blit(label, label.get_rect(center=(x, y - 120)))
                continue

            body = pygame.Rect(x - 18, y - 44, 36, 44)
            color = colors.get(enemy.kind, COLORS["muted"])
            pygame.draw.rect(self.canvas, (9, 25, 35), body)
            pygame.draw.rect(self.canvas, color, body, 2)
            eye_x = x + (7 if enemy.facing > 0 else -12)
            pygame.draw.rect(self.canvas, color, (eye_x, y - 32, 8, 5))

            hp_ratio = enemy.hp / enemy.max_hp if enemy.max_hp else 0
            hp_back = pygame.Rect(x - 26, y - 56, 52, 5)
            pygame.draw.rect(self.canvas, (24, 57, 65), hp_back)
            pygame.draw.rect(
                self.canvas,
                COLORS["red"],
                (hp_back.x, hp_back.y, int(hp_back.width * hp_ratio), hp_back.height),
            )
            label = self.small_font.render(enemy.display_name, True, COLORS["ice"])
            self.canvas.blit(label, label.get_rect(center=(x, y - 72)))

        self._draw_enemy_attack_effects()

    def _draw_enemy_attack_effects(self) -> None:
        effect = pygame.Surface(LOGICAL_SIZE, pygame.SRCALPHA)

        for pending in self.pending_enemy_attacks:
            if pending.enemy.defeated:
                continue
            duration = max(0.001, pending.profile.telegraph_time)
            enemy_center = (
                round(pending.enemy.x),
                round(pending.enemy.y - 52),
            )
            if pending.profile.projectile_speed is not None:
                self._draw_projectile_telegraph(effect, pending)
            elif pending.profile.parryable:
                self._draw_melee_parry_flash(effect, enemy_center, pending.remaining)
            else:
                self._draw_unparryable_telegraph(effect, pending, enemy_center)

        self._draw_reflected_projectiles(effect)

        for impact in self.attack_impacts:
            progress = 1.0 - max(0.0, impact.remaining / 0.24)
            if impact.parried:
                color = COLORS["cyan"]
            elif impact.dodged:
                color = COLORS["ice"]
            elif not impact.parryable:
                color = (166, 99, 244)
            else:
                color = COLORS["red"]
            radius = round(16 + progress * 68)
            alpha = round(220 * (1.0 - progress))
            center = (round(impact.x), round(impact.y))
            pygame.draw.circle(effect, (*color, alpha), center, radius, 4)
            pygame.draw.circle(effect, (*COLORS["white"], alpha), center, 8, 2)
            for angle in range(0, 360, 45):
                radians = math.radians(angle)
                start = (
                    round(center[0] + math.cos(radians) * (radius * 0.35)),
                    round(center[1] + math.sin(radians) * (radius * 0.35)),
                )
                end = (
                    round(center[0] + math.cos(radians) * radius),
                    round(center[1] + math.sin(radians) * radius),
                )
                pygame.draw.line(effect, (*color, alpha), start, end, 2)
            if impact.dodged:
                label = self.small_font.render("闪避", True, COLORS["ice"])
                label.set_alpha(alpha)
                effect.blit(label, label.get_rect(center=(center[0], center[1] - 30)))

        self.canvas.blit(effect, (0, 0))

    def _draw_reflected_projectiles(self, effect: pygame.Surface) -> None:
        """被弹开的子弹：青色回响弹体飞回射击者。"""
        for bullet in self.reflected_projectiles:
            dx = bullet.target.x - bullet.x
            dy = (bullet.target.y - 30) - bullet.y
            distance = max(1.0, math.hypot(dx, dy))
            ux = dx / distance
            uy = dy / distance
            for step in range(1, 5):
                trail = (
                    round(bullet.x - ux * step * 9),
                    round(bullet.y - uy * step * 9),
                )
                pygame.draw.circle(
                    effect,
                    (*COLORS["cyan"], max(12, 88 - step * 18)),
                    trail,
                    max(1, 5 - step),
                )
            center = (round(bullet.x), round(bullet.y))
            pygame.draw.circle(effect, (*COLORS["cyan"], 110), center, 11)
            pygame.draw.circle(effect, (*COLORS["ice"], 235), center, 6)
            pygame.draw.circle(effect, (*COLORS["white"], 220), center, 2)

    def _draw_melee_parry_flash(
        self,
        effect: pygame.Surface,
        center: tuple[int, int],
        remaining: float,
    ) -> None:
        """近战提示：闪光亮起后的这段时间内按弹刀即可完美弹反。"""
        gold = COLORS["gold"]
        flash_age = MELEE_FLASH_LEAD - remaining
        if flash_age < 0.0:
            # 闪光尚未亮起：只留一个暗金色信号，避免和弹刀窗口混淆
            pygame.draw.circle(effect, (*gold, 55), center, 11, 2)
            pygame.draw.circle(effect, (*gold, 80), center, 3)
            return

        progress = max(0.0, min(1.0, flash_age / MELEE_FLASH_LEAD))
        burst = max(0.0, 1.0 - flash_age / 0.09)
        # 由外向内叠三层光晕，形成“亮起”的闪光
        for radius, alpha in (
            (34 + 10 * progress, 34 + 40 * burst),
            (24 + 8 * progress, 62 + 60 * burst),
            (15 + 5 * progress, 104 + 70 * burst),
        ):
            pygame.draw.circle(
                effect,
                (*gold, max(0, min(255, round(alpha)))),
                center,
                round(radius),
            )
        pygame.draw.circle(
            effect,
            (*gold, max(0, min(255, round(210 * (1.0 - 0.5 * progress))))),
            center,
            round(30 + 34 * progress + 14 * burst),
            3,
        )
        for index in range(8):
            angle = math.tau * index / 8.0 + self.elapsed * 1.4
            inner = 20 + 10 * progress
            outer = inner + 12 + 12 * burst
            pygame.draw.line(
                effect,
                (*gold, max(0, min(255, round(170 + 70 * burst)))),
                (
                    round(center[0] + math.cos(angle) * inner),
                    round(center[1] + math.sin(angle) * inner),
                ),
                (
                    round(center[0] + math.cos(angle) * outer),
                    round(center[1] + math.sin(angle) * outer),
                ),
                3,
            )
        pygame.draw.circle(
            effect,
            (*COLORS["white"], max(0, min(255, round(180 + 70 * burst)))),
            center,
            6,
        )

    def _draw_projectile_telegraph(
        self,
        effect: pygame.Surface,
        pending: PendingEnemyAttack,
    ) -> None:
        color = COLORS["ice"] if pending.profile.parryable else (166, 99, 244)
        position = self._projectile_position(pending)
        origin = pending.origin or (pending.enemy.x, pending.enemy.y - 52)
        target = pending.target or (self.player.x, self.player.y - 54)
        pygame.draw.line(effect, (*color, 40), origin, target, 2)
        duration = max(0.001, pending.profile.telegraph_time)
        progress = max(0.0, min(1.0, 1.0 - pending.remaining / duration))
        for step in range(1, 4):
            tail_progress = max(0.0, progress - 0.055 * step)
            tail = (
                round(origin[0] + (target[0] - origin[0]) * tail_progress),
                round(origin[1] + (target[1] - origin[1]) * tail_progress),
            )
            pygame.draw.circle(
                effect,
                (*color, max(24, 70 - step * 18)),
                tail,
                max(2, 7 - step),
            )
        center = (round(position[0]), round(position[1]))
        pygame.draw.circle(effect, (*color, 95), center, 12)
        pygame.draw.circle(effect, (*color, 235), center, 6)
        pygame.draw.circle(effect, (*COLORS["white"], 200), center, 2)

    def _draw_unparryable_telegraph(
        self,
        effect: pygame.Surface,
        pending: PendingEnemyAttack,
        enemy_center: tuple[int, int],
    ) -> None:
        """不可弹反的攻击：紫色扇形提示，明确告诉玩家只能闪避或走位。"""
        duration = max(0.001, pending.profile.telegraph_time)
        progress = 1.0 - max(0.0, min(1.0, pending.remaining / duration))
        color = (166, 99, 244)
        player_center = (round(self.player.x), round(self.player.y - 54))
        dx = player_center[0] - enemy_center[0]
        dy = player_center[1] - enemy_center[1]
        distance = max(1.0, math.hypot(dx, dy))
        reach = min(float(pending.profile.reach), 190.0)
        end = (
            round(enemy_center[0] + dx / distance * reach),
            round(enemy_center[1] + dy / distance * reach),
        )
        side_x = -dy / distance * (10 + 18 * progress)
        side_y = dx / distance * (10 + 18 * progress)
        pygame.draw.polygon(
            effect,
            (*color, round(28 + 62 * progress)),
            (
                enemy_center,
                (round(end[0] + side_x), round(end[1] + side_y)),
                (round(end[0] - side_x), round(end[1] - side_y)),
            ),
        )
        pygame.draw.line(
            effect,
            (*color, round(95 + 105 * progress)),
            enemy_center,
            end,
            max(2, round(2 + progress * 4)),
        )
        marker = (enemy_center[0], enemy_center[1] - 34)
        pygame.draw.line(
            effect, (*color, 245), (marker[0] - 6, marker[1] - 6),
            (marker[0] + 6, marker[1] + 6), 3,
        )
        pygame.draw.line(
            effect, (*color, 245), (marker[0] + 6, marker[1] - 6),
            (marker[0] - 6, marker[1] + 6), 3,
        )

    def _draw_stat_bar(
        self,
        label: str,
        x: int,
        y: int,
        width: int,
        height: int,
        ratio: float,
        color: tuple[int, int, int],
    ) -> None:
        label_text = self.small_font.render(label, True, COLORS["muted"])
        self.canvas.blit(label_text, (x - label_text.get_width() - 14, y - 3))
        bar = pygame.Rect(x, y, width, height)
        pygame.draw.rect(self.canvas, (19, 42, 50), bar)
        pygame.draw.rect(
            self.canvas,
            color,
            (bar.x, bar.y, int(bar.width * ratio), bar.height),
        )
        pygame.draw.rect(self.canvas, COLORS["ice"], bar, 1)

    def _draw_result(self) -> None:
        shade = pygame.Surface(LOGICAL_SIZE, pygame.SRCALPHA)
        shade.fill((3, 8, 18, 110))
        self.canvas.blit(shade, (0, 0))
        title = self.title_font.render("试炼完成", True, COLORS["ice"])
        self.canvas.blit(title, title.get_rect(center=(640, 170)))
        subtitle = self.subtitle_font.render(
            "新纪录" if self.result_new_record else "记录已更新",
            True,
            COLORS["gold"] if self.result_new_record else COLORS["cyan"],
        )
        self.canvas.blit(subtitle, subtitle.get_rect(center=(640, 220)))

        panel = pygame.Rect(390, 270, 500, 170)
        pygame.draw.rect(self.canvas, (6, 16, 28), panel)
        pygame.draw.rect(self.canvas, COLORS["cyan"], panel, 2)
        rows = [
            ("本局分数", f"{self.result_score:05d}"),
            ("抵达层数", str(self.run_floor)),
            ("完美弹刀", str(self.run_parries)),
        ]
        for index, (label, value) in enumerate(rows):
            y = panel.y + 28 + index * 42
            self.canvas.blit(
                self.small_font.render(label, True, COLORS["muted"]),
                (panel.x + 44, y),
            )
            value_text = self.overlay_body_font.render(value, True, COLORS["ice"])
            self.canvas.blit(
                value_text,
                (panel.right - value_text.get_width() - 44, y - 5),
            )
        for name, rect in self._page_buttons().items():
            self._draw_ui_button(
                rect,
                "再来一局" if name == "restart" else "返回主菜单",
            )
        hint = self.small_font.render(
            "Enter 再来一局    Esc 返回主菜单",
            True,
            COLORS["muted"],
        )
        self.canvas.blit(hint, hint.get_rect(center=(640, 610)))
        self._draw_notification()

    def _draw_failure(self) -> None:
        shade = pygame.Surface(LOGICAL_SIZE, pygame.SRCALPHA)
        shade.fill((18, 4, 12, 188))
        self.canvas.blit(shade, (0, 0))

        for radius, alpha in ((46, 32), (34, 52), (22, 82)):
            pygame.draw.circle(
                self.canvas,
                (239, 102, 105, alpha),
                (640, 104),
                radius,
                2,
            )
        pygame.draw.line(self.canvas, COLORS["red"], (622, 86), (658, 122), 4)
        pygame.draw.line(self.canvas, COLORS["red"], (658, 86), (622, 122), 4)

        title = self.title_font.render("远征失格", True, COLORS["ice"])
        self.canvas.blit(title, title.get_rect(center=(640, 198)))
        subtitle = self.subtitle_font.render(
            "记忆载体已崩解  /  回收可勘定残响",
            True,
            COLORS["red"],
        )
        self.canvas.blit(subtitle, subtitle.get_rect(center=(640, 241)))

        panel = pygame.Rect(390, 278, 500, 202)
        pygame.draw.rect(self.canvas, (10, 13, 24), panel)
        pygame.draw.rect(self.canvas, (133, 55, 66), panel, 2)
        rows = [
            ("本局分数", f"{self.result_score:05d}"),
            ("抵达层数", str(self.run_floor)),
            ("最高连击", f"x{self.run_max_combo}"),
            ("完美弹刀", str(self.run_parries)),
            ("战时铸币", f"{self.run_currency}  已消散"),
        ]
        for index, (label, value) in enumerate(rows):
            y = panel.y + 20 + index * 34
            self.canvas.blit(
                self.small_font.render(label, True, COLORS["muted"]),
                (panel.x + 38, y),
            )
            value_color = COLORS["red"] if index == 4 else COLORS["ice"]
            value_text = self.overlay_body_font.render(value, True, value_color)
            self.canvas.blit(
                value_text,
                (panel.right - value_text.get_width() - 38, y - 5),
            )

        relic_text = self.small_font.render(
            f"回响遗晶凝结  +{self.result_relics}",
            True,
            COLORS["gold"],
        )
        self.canvas.blit(relic_text, relic_text.get_rect(center=(640, 493)))
        self._draw_ui_button(self._page_buttons()["lobby"], "返回灰塔大厅")
        hint = self.small_font.render(
            "Enter / Space 返回大厅",
            True,
            COLORS["muted"],
        )
        self.canvas.blit(hint, hint.get_rect(center=(640, 600)))
        self._draw_notification()

    def _draw_spawn_countdown(self) -> None:
        """敌人登场倒计时面板：会跳动的秒数 + 进度条，最后 1 秒转红。"""
        remaining = max(0.0, self.enemy_spawn_timer)
        total = max(0.001, ENEMY_SPAWN_DELAY)
        ratio = 1.0 - max(0.0, min(1.0, remaining / total))
        panel = pygame.Rect(0, 0, 320, 96)
        panel.center = (640, 132)

        layer = pygame.Surface(panel.size, pygame.SRCALPHA)
        layer.fill((6, 16, 28, 208))
        pulse = 0.5 + 0.5 * math.sin(self.elapsed * 7.0)
        border_alpha = 150 + round(80 * pulse)
        pygame.draw.rect(
            layer,
            (*COLORS["gold"], border_alpha),
            layer.get_rect(),
            2,
        )

        title = self.small_font.render("敌影接近", True, COLORS["gold"])
        layer.blit(title, title.get_rect(center=(panel.width // 2, 20)))

        if remaining <= 1.0:
            number_color = COLORS["red"]
        elif remaining <= 2.0:
            number_color = COLORS["gold"]
        else:
            number_color = COLORS["white"]
        number = self.overlay_title_font.render(f"{remaining:0.1f}", True, number_color)
        layer.blit(number, number.get_rect(center=(panel.width // 2, 50)))

        bar = pygame.Rect(26, 76, panel.width - 52, 8)
        pygame.draw.rect(layer, (24, 57, 65), bar)
        pygame.draw.rect(
            layer,
            COLORS["gold"],
            (bar.x, bar.y, round(bar.width * ratio), bar.height),
        )
        pygame.draw.rect(layer, (*COLORS["muted"], 120), bar, 1)
        self.canvas.blit(layer, panel.topleft)

    def _draw_notification(self) -> None:
        if self.notification_timer <= 0:
            return
        toast = self.small_font.render(self.notification, True, COLORS["ice"])
        toast_rect = toast.get_rect(center=(640, 646))
        pygame.draw.rect(
            self.canvas,
            (6, 16, 28, 225),
            toast_rect.inflate(34, 16),
        )
        pygame.draw.rect(
            self.canvas,
            COLORS["cyan"],
            toast_rect.inflate(34, 16),
            1,
        )
        self.canvas.blit(toast, toast_rect)

    def _draw_exit_confirmation(self) -> None:
        shade = pygame.Surface(LOGICAL_SIZE, pygame.SRCALPHA)
        shade.fill((3, 8, 18, 190))
        self.canvas.blit(shade, (0, 0))
        rect = pygame.Rect(390, 270, 500, 180)
        pygame.draw.rect(self.canvas, (6, 16, 28), rect)
        pygame.draw.rect(self.canvas, COLORS["red"], rect, 2)
        title = self.overlay_title_font.render("离开游戏？", True, COLORS["ice"])
        body_text = (
            "按 Y 确认退出，按 N 返回菜单"
            if self.page == "menu"
            else "返回主菜单？当前试炼进度不会保存"
        )
        body = self.overlay_body_font.render(body_text, True, COLORS["muted"])
        self.canvas.blit(title, title.get_rect(center=(640, 322)))
        self.canvas.blit(body, body.get_rect(center=(640, 377)))
        for name, button_rect in self._exit_buttons().items():
            self._draw_ui_button(
                button_rect,
                "确认" if name == "confirm" else "取消",
                self.pressed_button == name,
            )

    def _notify(self, message: str) -> None:
        self.notification = message
        self.notification_timer = 2.4


def main() -> None:
    # 先给混音器一个低延迟配置，保证挥刀与弹刀音效即时响应
    pygame.mixer.pre_init(44100, -16, 2, 512)
    pygame.init()
    pygame.display.set_caption(WINDOW_TITLE)
    screen = pygame.display.set_mode(LOGICAL_SIZE, pygame.RESIZABLE)
    try:
        StartScreen(screen).run()
    finally:
        if pygame.mixer.get_init():
            pygame.mixer.stop()
        pygame.quit()


if __name__ == "__main__":
    main()
