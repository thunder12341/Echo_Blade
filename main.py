from __future__ import annotations

import json
import math
from dataclasses import dataclass

import pygame

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
    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self.canvas = pygame.Surface(LOGICAL_SIZE)
        self.assets = AssetStore()
        self.running = True
        self.clock = pygame.time.Clock()
        self.elapsed = 0.0
        self.notification = ""
        self.notification_timer = 0.0
        self.overlay: str | None = None
        self.confirm_exit = False
        self.settings = {
            "window_scale": 1,
            "assist_mode": False,
            "volume": 80,
        }
        self.has_save = self._load_save()
        self.items = self._build_items()
        self.selected = next(
            (index for index, item in enumerate(self.items) if item.enabled),
            0,
        )
        self.pressed_item: int | None = None

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

    def _load_save(self) -> bool:
        if not SAVE_FILE.exists():
            return False
        try:
            data = json.loads(SAVE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return bool(data.get("best_score") or data.get("best_floor"))

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
            elif event.type == pygame.MOUSEMOTION and self.overlay is None:
                self._select_from_mouse(event.pos)
            elif event.type == pygame.VIDEORESIZE:
                self.screen = pygame.display.set_mode(event.size, pygame.RESIZABLE)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.overlay is not None:
                    self._handle_overlay_click(event.pos)
                else:
                    self.pressed_item = self._item_at(event.pos)
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                if self.overlay is None:
                    index = self._item_at(event.pos)
                    if self.pressed_item is not None and index == self.pressed_item:
                        self._activate(index)
                    self.pressed_item = None

    def _handle_key(self, key: int) -> None:
        if self.overlay == "settings":
            if key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                self.overlay = None
            elif key in (pygame.K_LEFT, pygame.K_RIGHT):
                self.settings["volume"] = max(
                    0, min(100, self.settings["volume"] + (5 if key == pygame.K_RIGHT else -5))
                )
                self._notify(f"音量 {self.settings['volume']}%")
            elif key in (pygame.K_a, pygame.K_RETURN, pygame.K_SPACE):
                self.settings["assist_mode"] = not self.settings["assist_mode"]
                self._notify("辅助模式已" + ("开启" if self.settings["assist_mode"] else "关闭"))
            return

        if self.confirm_exit:
            if key in (pygame.K_y, pygame.K_RETURN):
                self.running = False
            elif key in (pygame.K_n, pygame.K_ESCAPE):
                self.confirm_exit = False
            return

        if self.overlay == "leaderboard":
            if key in (pygame.K_ESCAPE, pygame.K_BACKSPACE, pygame.K_RETURN, pygame.K_SPACE):
                self.overlay = None
            return

        if key in (pygame.K_UP, pygame.K_w):
            self._move_selection(-1)
        elif key in (pygame.K_DOWN, pygame.K_s):
            self._move_selection(1)
        elif key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_j):
            self._activate(self.selected)
        elif key == pygame.K_ESCAPE:
            self.confirm_exit = True

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
            rect = self._menu_rect(index)
            if rect.collidepoint(x, y):
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
            self._notify("新一局即将开始……")
        elif action == "continue":
            self._notify("继续游戏功能已准备好，战斗场景将在下一步接入。")
        elif action == "leaderboard":
            self.overlay = "leaderboard"
        elif action == "settings":
            self.overlay = "settings"

    def _handle_overlay_click(self, position: tuple[int, int]) -> None:
        logical = self._to_logical(position)
        if self.overlay in ("settings", "leaderboard"):
            if not self._overlay_rect().collidepoint(logical):
                self.overlay = None

    def _update(self, dt: float) -> None:
        if self.notification_timer > 0:
            self.notification_timer = max(0.0, self.notification_timer - dt)

    def _draw(self) -> None:
        self.canvas.blit(self.assets.background, (0, 0))
        self._draw_atmosphere()
        self._draw_branding()
        self._draw_menu()
        self._draw_footer()
        if self.overlay is not None:
            self._draw_overlay()
        if self.confirm_exit:
            self._draw_exit_confirmation()

        self.screen.fill(COLORS["ink"])
        width, height = self.screen.get_size()
        scale = min(width / LOGICAL_SIZE[0], height / LOGICAL_SIZE[1])
        scaled_size = (int(LOGICAL_SIZE[0] * scale), int(LOGICAL_SIZE[1] * scale))
        scaled = pygame.transform.scale(self.canvas, scaled_size)
        self.screen.blit(scaled, ((width - scaled_size[0]) // 2, (height - scaled_size[1]) // 2))

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
        title_rect = title.get_rect(center=(640, 218))
        self.canvas.blit(title, title_rect)

        subtitle = self.subtitle_font.render("E C H O   B L A D E", True, COLORS["cyan"])
        subtitle_rect = subtitle.get_rect(center=(640, 254))
        self.canvas.blit(subtitle, subtitle_rect)

        line = pygame.Rect(522, 275, 236, 2)
        pygame.draw.rect(self.canvas, COLORS["cyan"], line)
        pygame.draw.rect(self.canvas, COLORS["ice"], (line.x + 72, line.y, 92, 2))

    def _menu_rect(self, index: int) -> pygame.Rect:
        return pygame.Rect(440, 315 + index * 68, 400, 58)

    def _draw_menu(self) -> None:
        for index, item in enumerate(self.items):
            rect = self._menu_rect(index)
            selected = index == self.selected and item.enabled
            panel = pygame.transform.scale(self.assets.panel, rect.size)
            panel.set_alpha(255 if selected else 190)
            self.canvas.blit(panel, rect)

            if selected:
                cursor = pygame.transform.scale(self.assets.cursor, (42, 42))
                cursor.set_alpha(215 + int(40 * math.sin(self.elapsed * 4.0)))
                self.canvas.blit(cursor, (rect.x - 54, rect.centery - cursor.get_height() // 2))

            color = COLORS["ice"] if selected else COLORS["muted"]
            if not item.enabled:
                color = (76, 105, 112)
            label = item.label
            if not item.enabled:
                label += "  -  暂无存档"
            text = self.menu_font.render(label, True, color)
            self.canvas.blit(text, text.get_rect(center=rect.center))

    def _draw_footer(self) -> None:
        controls = self.small_font.render("↑↓ 选择    Enter 确认    Esc 退出", True, COLORS["muted"])
        self.canvas.blit(controls, controls.get_rect(center=(640, 688)))

        version = self.small_font.render("PRE-ALPHA 0.1  |  灰塔记忆核心在线", True, COLORS["muted"])
        self.canvas.blit(version, (32, 680))

        if self.notification_timer > 0:
            toast = self.small_font.render(self.notification, True, COLORS["ice"])
            toast_rect = toast.get_rect(center=(640, 646))
            pygame.draw.rect(self.canvas, (6, 16, 28, 225), toast_rect.inflate(34, 16))
            pygame.draw.rect(self.canvas, COLORS["cyan"], toast_rect.inflate(34, 16), 1)
            self.canvas.blit(toast, toast_rect)

    def _overlay_rect(self) -> pygame.Rect:
        return pygame.Rect(304, 150, 672, 420)

    def _draw_overlay(self) -> None:
        shade = pygame.Surface(LOGICAL_SIZE, pygame.SRCALPHA)
        shade.fill((3, 8, 18, 178))
        self.canvas.blit(shade, (0, 0))
        rect = self._overlay_rect()
        pygame.draw.rect(self.canvas, (6, 16, 28), rect)
        pygame.draw.rect(self.canvas, COLORS["cyan"], rect, 2)
        pygame.draw.line(self.canvas, COLORS["ice"], (rect.x + 28, rect.y + 68), (rect.right - 28, rect.y + 68), 1)

        title_text = "本地排行榜" if self.overlay == "leaderboard" else "设置"
        title = self.overlay_title_font.render(title_text, True, COLORS["ice"])
        self.canvas.blit(title, (rect.x + 30, rect.y + 24))

        if self.overlay == "leaderboard":
            self._draw_leaderboard(rect)
        else:
            self._draw_settings(rect)

        hint = self.small_font.render("Enter / Esc 关闭", True, COLORS["muted"])
        self.canvas.blit(hint, (rect.right - hint.get_width() - 28, rect.bottom - 34))

    def _draw_leaderboard(self, rect: pygame.Rect) -> None:
        rows = [
            ("--", "暂无成绩", "完成第一局后记录"),
            ("--", "暂无成绩", "挑战灰塔，留下你的分数"),
            ("--", "暂无成绩", "完美弹刀会带来更高倍率"),
        ]
        for index, (rank, name, detail) in enumerate(rows):
            y = rect.y + 110 + index * 64
            pygame.draw.line(self.canvas, (30, 77, 84), (rect.x + 30, y + 42), (rect.right - 30, y + 42), 1)
            rank_text = self.overlay_body_font.render(str(index + 1).zfill(2), True, COLORS["cyan"])
            self.canvas.blit(rank_text, (rect.x + 42, y))
            name_text = self.overlay_body_font.render(name, True, COLORS["ice"])
            self.canvas.blit(name_text, (rect.x + 112, y))
            detail_text = self.small_font.render(detail, True, COLORS["muted"])
            self.canvas.blit(detail_text, (rect.x + 112, y + 27))

    def _draw_settings(self, rect: pygame.Rect) -> None:
        labels = [
            ("音量", f"{self.settings['volume']}%"),
            ("辅助模式", "开启" if self.settings["assist_mode"] else "关闭"),
            ("窗口缩放", "自适应"),
        ]
        for index, (label, value) in enumerate(labels):
            y = rect.y + 112 + index * 66
            label_text = self.overlay_body_font.render(label, True, COLORS["ice"])
            value_text = self.overlay_body_font.render(value, True, COLORS["cyan"])
            self.canvas.blit(label_text, (rect.x + 46, y))
            self.canvas.blit(value_text, (rect.right - value_text.get_width() - 46, y))
            if index == 0:
                bar = pygame.Rect(rect.x + 184, y + 10, 250, 5)
                pygame.draw.rect(self.canvas, (24, 57, 65), bar)
                pygame.draw.rect(self.canvas, COLORS["cyan"], (bar.x, bar.y, bar.width * self.settings["volume"] / 100, bar.height))

    def _draw_exit_confirmation(self) -> None:
        shade = pygame.Surface(LOGICAL_SIZE, pygame.SRCALPHA)
        shade.fill((3, 8, 18, 190))
        self.canvas.blit(shade, (0, 0))
        rect = pygame.Rect(390, 270, 500, 180)
        pygame.draw.rect(self.canvas, (6, 16, 28), rect)
        pygame.draw.rect(self.canvas, COLORS["red"], rect, 2)
        title = self.overlay_title_font.render("离开游戏？", True, COLORS["ice"])
        body = self.overlay_body_font.render("按 Y 确认退出，按 N 返回菜单", True, COLORS["muted"])
        self.canvas.blit(title, title.get_rect(center=(640, 322)))
        self.canvas.blit(body, body.get_rect(center=(640, 377)))

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
