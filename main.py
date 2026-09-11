from __future__ import annotations

import json
import math
from dataclasses import dataclass

import pygame

from game.entities import Chaser, Enemy, SpearThrower
from settings import COLORS, FPS, IMAGE_DIR, LOGICAL_SIZE, SAVE_FILE, WINDOW_TITLE


@dataclass(frozen=True)
class MenuItem:
    label: str
    action: str
    enabled: bool = True


class AssetStore:
    def __init__(self) -> None:
        self.background = self._load("title_background.png", alpha=False)
        self.logo = self._load("logo_emblem.png")
        self.player = self._load("player_idle.png")
        self.panel = self._load("menu_panel.png")
        self.cursor = self._load("menu_cursor.png")
        self.spark = self._load("parry_spark.png")

    @staticmethod
    def _load(filename: str, alpha: bool = True) -> pygame.Surface:
        path = IMAGE_DIR / filename
        if not path.exists():
            raise FileNotFoundError(f"找不到界面素材: {path}")
        image = pygame.image.load(path)
        return image.convert_alpha() if alpha else image.convert()


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
        self.run_parries = 0
        self.player_x = 230
        self.room_enemies: list[Enemy] = []
        self.result_score = 0
        self.result_new_record = False

        self.title_font = self._font(56, bold=True)
        self.subtitle_font = self._font(18, bold=True)
        self.menu_font = self._font(25, bold=True)
        self.small_font = self._font(16)
        self.overlay_title_font = self._font(30, bold=True)
        self.overlay_body_font = self._font(19)

    @staticmethod
    def _font(size: int, bold: bool = False) -> pygame.font.Font:
        for name in ("microsoftyahei", "simhei", "noto sans cjk sc", "arial"):
            return pygame.font.SysFont(name, size, bold=bold)
        return pygame.font.Font(None, size)

    def _load_profile(self) -> dict:
        if not SAVE_FILE.exists():
            return {}
        try:
            data = json.loads(SAVE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _load_save(self) -> bool:
        return bool(
            self.profile.get("best_score")
            or self.profile.get("best_floor")
            or self.profile.get("scores")
        )

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
            "version": 1,
            "best_score": int(self.profile.get("best_score", 0) or 0),
            "best_floor": int(self.profile.get("best_floor", 0) or 0),
            "scores": self.profile.get("scores", []),
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
            self._draw()
            pygame.display.flip()

    def _handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                self._handle_key(event.key)
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
                self.overlay_selected = (self.overlay_selected - 1) % 5
            elif key in (pygame.K_DOWN, pygame.K_s):
                self.overlay_selected = (self.overlay_selected + 1) % 5
            elif key in (pygame.K_LEFT, pygame.K_RIGHT):
                self._change_setting(
                    self.overlay_selected,
                    5 if key == pygame.K_RIGHT else -5,
                )
            elif key == pygame.K_a:
                self._activate_setting(1)
            elif key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_j):
                if self.overlay_selected == 3:
                    self._open_overlay("keybinds")
                elif self.overlay_selected == 4:
                    self._close_overlay()
                else:
                    self._activate_setting(self.overlay_selected)
            return

        if self.overlay == "leaderboard":
            if key in (pygame.K_ESCAPE, pygame.K_BACKSPACE, pygame.K_RETURN, pygame.K_SPACE):
                self._close_overlay()
            return

        if self.page == "game":
            if key in (pygame.K_LEFT, self.keybinds["left"]):
                self.player_x = max(110, self.player_x - 18)
            elif key in (pygame.K_RIGHT, self.keybinds["right"]):
                self.player_x = min(690, self.player_x + 18)
            elif key == self.keybinds["attack"]:
                self.run_score += 120
                self.run_combo += 1
                self._notify("折光长刃：连击 +1")
            elif key == self.keybinds["parry"]:
                self.run_score += 260
                self.run_combo += 2
                self.run_parries += 1
                self._notify("PERFECT  弹刀成功")
            elif key in (pygame.K_LSHIFT, self.keybinds["dash"]):
                self.player_x = min(690, self.player_x + 70)
                self._notify("冲刺")
            elif key == self.keybinds["jump"]:
                self._notify("跳跃")
            elif key == pygame.K_ESCAPE:
                self.confirm_exit = True
            return

        if self.page == "result":
            if key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_j):
                self._activate_page_button("restart")
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
        elif self.overlay is None and self.page == "menu":
            self._select_from_mouse(position)

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
            self._start_run(1)
        elif action == "continue":
            self._start_run(int(self.profile.get("best_floor", 1) or 1))
        elif action == "leaderboard":
            self._open_overlay("leaderboard")
        elif action == "settings":
            self._open_overlay("settings")

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
            if self._overlay_back_rect().collidepoint(logical):
                self._close_overlay()
                return
            for index, rect in enumerate(rects[:4]):
                if rect.collidepoint(logical):
                    self.overlay_selected = index
                    if index == 0:
                        ratio = (logical[0] - (rect.x + 190)) / 270
                        self.settings["volume"] = max(
                            0,
                            min(100, int(round(ratio * 20) * 5)),
                        )
                        self._save_profile()
                        self._notify(f"音量 {self.settings['volume']}%")
                    else:
                        self._activate_setting(index)
                    return
            if not self._overlay_rect().collidepoint(logical):
                self._close_overlay()
        elif self.overlay == "leaderboard":
            if (
                self._overlay_back_rect().collidepoint(logical)
                or not self._overlay_rect().collidepoint(logical)
            ):
                self._close_overlay()

    def _update(self, dt: float) -> None:
        if self.notification_timer > 0:
            self.notification_timer = max(0.0, self.notification_timer - dt)

    def _draw(self) -> None:
        self.canvas.blit(self.assets.background, (0, 0))
        self._draw_atmosphere()
        if self.page == "menu":
            self._draw_branding()
            self._draw_menu()
            self._draw_footer()
        elif self.page == "game":
            self._draw_game()
        elif self.page == "result":
            self._draw_result()
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
        return pygame.Rect(252, 96, 776, 528)

    def _overlay_back_rect(self) -> pygame.Rect:
        rect = self._overlay_rect()
        return pygame.Rect(rect.x + 30, rect.bottom - 76, 210, 44)

    def _setting_rects(self) -> list[pygame.Rect]:
        rect = self._overlay_rect()
        return [
            pygame.Rect(rect.x + 34, rect.y + 104, rect.width - 68, 70),
            pygame.Rect(rect.x + 34, rect.y + 184, rect.width - 68, 70),
            pygame.Rect(rect.x + 34, rect.y + 264, rect.width - 68, 70),
            pygame.Rect(rect.x + 34, rect.y + 344, rect.width - 68, 70),
            self._overlay_back_rect(),
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
        }.get(self.overlay, "设置")
        title = self.overlay_title_font.render(title_text, True, COLORS["ice"])
        self.canvas.blit(title, (rect.x + 30, rect.y + 24))

        if self.overlay == "leaderboard":
            self._draw_leaderboard(rect)
        elif self.overlay == "keybinds":
            self._draw_keybinds(rect)
        else:
            self._draw_settings(rect)

        hint_text = (
            "↑↓ 选择    Enter 设置    Esc 返回"
            if self.overlay == "keybinds"
            else "↑↓ 选择    ←→ 调整    Enter 确认    Esc 返回"
        )
        hint = self.small_font.render(hint_text, True, COLORS["muted"])
        self.canvas.blit(hint, (rect.right - hint.get_width() - 28, rect.bottom - 34))

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
            "返回主菜单",
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
            zip(labels, setting_rects)
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
            self._overlay_back_rect(),
            "返回主菜单",
            self.overlay_selected == 4,
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
    ) -> None:
        panel = pygame.transform.scale(self.assets.panel, rect.size)
        panel.set_alpha(255 if selected else 195)
        self.canvas.blit(panel, rect)
        color = COLORS["ice"] if selected else COLORS["muted"]
        text = self.menu_font.render(label, True, color)
        self.canvas.blit(text, text.get_rect(center=rect.center))
        if selected:
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

    def _change_setting(self, index: int, amount: int) -> None:
        if index == 0:
            self.settings["volume"] = max(0, min(100, self.settings["volume"] + amount))
            self._save_profile()
            self._notify(f"音量 {self.settings['volume']}%")
        elif index == 2:
            self._activate_setting(index)

    def _apply_display_mode(self) -> None:
        flags = pygame.FULLSCREEN if self.settings["fullscreen"] else pygame.RESIZABLE
        self.screen = pygame.display.set_mode(LOGICAL_SIZE, flags)

    @staticmethod
    def _build_training_room_enemies() -> list[Enemy]:
        return [
            Chaser(560, 522),
            SpearThrower(660, 522),
        ]

    def _start_run(self, floor: int) -> None:
        self.page = "game"
        self.overlay = None
        self.confirm_exit = False
        self.run_floor = max(1, floor)
        self.run_score = 0
        self.run_combo = 0
        self.run_parries = 0
        self.player_x = 230
        self.room_enemies = self._build_training_room_enemies()
        self._notify("试炼房间已开启")

    def _page_buttons(self) -> dict[str, pygame.Rect]:
        if self.page == "game":
            return {
                "finish": pygame.Rect(860, 500, 320, 58),
                "menu": pygame.Rect(860, 574, 320, 58),
            }
        if self.page == "result":
            return {
                "restart": pygame.Rect(430, 500, 200, 58),
                "menu": pygame.Rect(650, 500, 200, 58),
            }
        return {}

    def _page_button_at(self, position: tuple[int, int]) -> str | None:
        logical = self._to_logical(position)
        for name, rect in self._page_buttons().items():
            if rect.collidepoint(logical):
                return name
        return None

    def _activate_page_button(self, button: str | None) -> None:
        if button == "finish" and self.page == "game":
            self._finish_run()
        elif button == "restart" and self.page == "result":
            self._start_run(1)
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
        self._save_profile()
        self.has_save = True
        self.items = self._build_items()
        self.page = "result"
        self._notify("本局记录已保存")

    def _draw_game(self) -> None:
        shade = pygame.Surface(LOGICAL_SIZE, pygame.SRCALPHA)
        shade.fill((3, 8, 18, 80))
        self.canvas.blit(shade, (0, 0))

        title = self.overlay_title_font.render("灰塔 · 序章试炼", True, COLORS["ice"])
        self.canvas.blit(title, (54, 36))
        subtitle = self.small_font.render("ROOM 01  /  回响训练场", True, COLORS["cyan"])
        self.canvas.blit(subtitle, (56, 78))

        self._draw_stat_bar("生命", 100, 104, 240, 14, 0.84, COLORS["red"])
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

        pygame.draw.line(self.canvas, (37, 103, 103), (120, 566), (760, 566), 2)
        pygame.draw.rect(self.canvas, (12, 37, 48), (165, 428, 500, 138), 2)
        gate = pygame.transform.scale(self.assets.logo, (96, 96))
        gate.set_alpha(100)
        self.canvas.blit(gate, (520, 340))
        player = pygame.transform.scale(self.assets.player, (96, 120))
        self.canvas.blit(player, (self.player_x, 446))
        self._draw_enemies()

        room_title = self.overlay_body_font.render("试炼房间已开启", True, COLORS["ice"])
        room_hint = self.small_font.render(
            "用移动观察空间，尝试攻击与弹刀。完成房间后进入结算。",
            True,
            COLORS["muted"],
        )
        self.canvas.blit(room_title, room_title.get_rect(center=(410, 296)))
        self.canvas.blit(room_hint, room_hint.get_rect(center=(410, 325)))

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

        for name, rect in self._page_buttons().items():
            label = "完成当前房间" if name == "finish" else "返回主菜单"
            self._draw_ui_button(rect, label)
        controls = self.small_font.render(
            (
                f"{self._key_name(self.keybinds['left'])}/{self._key_name(self.keybinds['right'])} 移动    "
                f"{self._key_name(self.keybinds['attack'])} 攻击    "
                f"{self._key_name(self.keybinds['parry'])} 弹刀    "
                f"{self._key_name(self.keybinds['dash'])} 冲刺    "
                f"{self._key_name(self.keybinds['jump'])} 跳跃    Esc 返回"
            ),
            True,
            COLORS["muted"],
        )
        self.canvas.blit(controls, controls.get_rect(center=(640, 690)))
        self._draw_notification()

    def _draw_enemies(self) -> None:
        colors = {
            "chaser": COLORS["red"],
            "spear_thrower": COLORS["gold"],
            "shield_guard": COLORS["ice"],
            "rift_worm": (166, 99, 244),
            "resonance_mage": COLORS["cyan"],
        }
        for enemy in self.room_enemies:
            x, y = int(enemy.x), int(enemy.y)
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
    pygame.init()
    pygame.display.set_caption(WINDOW_TITLE)
    screen = pygame.display.set_mode(LOGICAL_SIZE, pygame.RESIZABLE)
    try:
        StartScreen(screen).run()
    finally:
        pygame.quit()


if __name__ == "__main__":
    main()
