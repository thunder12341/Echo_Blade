from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent
IMAGE_DIR = ROOT / "images"


INK = (5, 11, 22, 255)
PANEL = (6, 16, 28, 255)
CYAN = (79, 220, 214, 255)
ICE = (211, 255, 232, 255)
MUTED = (82, 130, 142, 255)
RED = (239, 102, 105, 255)
GOLD = (243, 204, 116, 255)
PURPLE = (166, 99, 244, 255)
GREEN = (92, 214, 132, 255)
TRANSPARENT = (0, 0, 0, 0)


def new_canvas(width: int, height: int) -> Image.Image:
    return Image.new("RGBA", (width, height), TRANSPARENT)


def save_scaled(image: Image.Image, filename: str, scale: int = 3) -> None:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    size = (image.width * scale, image.height * scale)
    image.resize(size, Image.Resampling.NEAREST).save(IMAGE_DIR / filename)


def rect(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], color) -> None:
    draw.rectangle(box, fill=color)


def line(draw: ImageDraw.ImageDraw, points: list[tuple[int, int]], color, width: int = 1) -> None:
    draw.line(points, fill=color, width=width)


def make_player(filename: str, pose: str) -> None:
    image = new_canvas(32, 40)
    draw = ImageDraw.Draw(image)
    leg_shift = -1 if pose == "run_a" else 1 if pose == "run_b" else 0
    body_shift = -3 if pose == "jump" else 2 if pose == "fall" else 0

    rect(draw, (12, 5 + body_shift, 21, 14 + body_shift), INK)
    rect(draw, (14, 7 + body_shift, 20, 13 + body_shift), (246, 185, 133, 255))
    rect(draw, (9, 14 + body_shift, 24, 29 + body_shift), INK)
    rect(draw, (11, 16 + body_shift, 22, 28 + body_shift), (39, 77, 94, 255))
    rect(draw, (12, 16 + body_shift, 15, 25 + body_shift), MUTED)
    rect(draw, (18, 17 + body_shift, 22, 20 + body_shift), RED)
    rect(draw, (10 + leg_shift, 29 + body_shift, 15 + leg_shift, 37 + body_shift), INK)
    rect(draw, (18 - leg_shift, 29 + body_shift, 23 - leg_shift, 37 + body_shift), INK)
    rect(draw, (11 + leg_shift, 29 + body_shift, 14 + leg_shift, 35 + body_shift), CYAN)
    rect(draw, (19 - leg_shift, 29 + body_shift, 22 - leg_shift, 35 + body_shift), MUTED)

    if pose == "attack_side":
        rect(draw, (22, 15 + body_shift, 27, 18 + body_shift), RED)
        line(draw, [(25, 15 + body_shift), (31, 10 + body_shift)], ICE, 2)
    elif pose == "attack_up":
        rect(draw, (20, 12 + body_shift, 23, 16 + body_shift), RED)
        line(draw, [(23, 13 + body_shift), (24, 0)], ICE, 2)
    elif pose == "attack_down":
        rect(draw, (20, 20 + body_shift, 23, 24 + body_shift), RED)
        line(draw, [(23, 23 + body_shift), (27, 38)], ICE, 2)
    else:
        rect(draw, (23, 15 + body_shift, 26, 28 + body_shift), INK)
        rect(draw, (25, 7 + body_shift, 27, 27 + body_shift), ICE)
        rect(draw, (24, 26 + body_shift, 28, 29 + body_shift), RED)

    save_scaled(image, filename)


def make_enemy(filename: str, main_color, accent, shape: str) -> None:
    image = new_canvas(32, 32)
    draw = ImageDraw.Draw(image)
    if shape == "worm":
        rect(draw, (5, 18, 27, 24), INK)
        rect(draw, (7, 16, 25, 22), main_color)
        rect(draw, (21, 14, 28, 21), accent)
        rect(draw, (9, 23, 12, 26), INK)
        rect(draw, (18, 23, 21, 26), INK)
    elif shape == "shield":
        rect(draw, (8, 6, 21, 27), INK)
        rect(draw, (10, 8, 19, 26), main_color)
        rect(draw, (18, 10, 27, 26), accent)
        rect(draw, (21, 14, 25, 17), ICE)
    elif shape == "mage":
        rect(draw, (10, 5, 21, 14), INK)
        rect(draw, (12, 7, 19, 13), accent)
        rect(draw, (8, 14, 24, 29), INK)
        rect(draw, (10, 16, 22, 28), main_color)
        rect(draw, (14, 18, 18, 22), CYAN)
        line(draw, [(24, 10), (27, 25)], ICE, 1)
    elif shape == "boss":
        rect(draw, (7, 3, 24, 29), INK)
        rect(draw, (9, 7, 22, 28), main_color)
        rect(draw, (11, 4, 20, 8), GOLD)
        rect(draw, (12, 14, 19, 18), accent)
        line(draw, [(24, 8), (29, 27)], ICE, 2)
    else:
        rect(draw, (11, 5, 20, 13), INK)
        rect(draw, (13, 7, 19, 12), accent)
        rect(draw, (8, 13, 24, 28), INK)
        rect(draw, (10, 15, 22, 27), main_color)
        rect(draw, (22, 15, 26, 19), RED)
        rect(draw, (11, 27, 15, 30), INK)
        rect(draw, (18, 27, 22, 30), INK)
    save_scaled(image, filename)


def make_slash(filename: str, direction: str) -> None:
    image = new_canvas(48, 48)
    draw = ImageDraw.Draw(image)
    if direction == "up":
        points = [(24, 42), (20, 28), (23, 8), (28, 3), (31, 28)]
    elif direction == "down":
        points = [(24, 6), (20, 20), (23, 40), (28, 45), (31, 20)]
    else:
        points = [(5, 27), (18, 20), (34, 18), (44, 22), (32, 29), (15, 31)]
    draw.polygon(points, fill=(211, 255, 232, 128))
    line(draw, points, ICE, 1)
    save_scaled(image, filename, scale=2)


def make_projectile(filename: str, kind: str) -> None:
    image = new_canvas(32, 16)
    draw = ImageDraw.Draw(image)
    if kind == "orb":
        rect(draw, (11, 4, 20, 11), CYAN)
        rect(draw, (13, 2, 18, 13), (139, 245, 236, 180))
        rect(draw, (15, 6, 17, 8), ICE)
    else:
        line(draw, [(3, 8), (26, 8)], ICE, 2)
        draw.polygon([(26, 4), (31, 8), (26, 12)], fill=GOLD)
        rect(draw, (8, 6, 12, 10), RED)
    save_scaled(image, filename, scale=2)


def make_icon(filename: str, kind: str) -> None:
    image = new_canvas(24, 24)
    draw = ImageDraw.Draw(image)
    if kind == "heart":
        rect(draw, (6, 7, 10, 11), RED)
        rect(draw, (14, 7, 18, 11), RED)
        rect(draw, (5, 10, 19, 15), RED)
        rect(draw, (8, 15, 16, 19), RED)
    elif kind == "echo":
        rect(draw, (10, 3, 13, 20), CYAN)
        rect(draw, (5, 9, 18, 12), (139, 245, 236, 190))
    elif kind == "combo":
        line(draw, [(5, 16), (12, 8), (19, 16)], GOLD, 3)
    elif kind == "parry":
        line(draw, [(5, 18), (18, 5)], ICE, 2)
        rect(draw, (9, 9, 15, 15), CYAN)
    elif kind == "dash":
        line(draw, [(4, 8), (18, 8)], CYAN, 2)
        line(draw, [(7, 14), (21, 14)], ICE, 2)
    elif kind == "warning":
        draw.polygon([(12, 3), (21, 20), (3, 20)], fill=PURPLE)
        rect(draw, (11, 8, 13, 14), ICE)
        rect(draw, (11, 17, 13, 19), ICE)
    elif kind == "coin":
        rect(draw, (6, 6, 18, 18), GOLD)
        rect(draw, (9, 8, 15, 16), (162, 112, 48, 255))
    elif kind == "skull":
        rect(draw, (7, 5, 17, 15), ICE)
        rect(draw, (9, 16, 15, 20), ICE)
        rect(draw, (9, 9, 11, 11), INK)
        rect(draw, (14, 9, 16, 11), INK)
    save_scaled(image, filename, scale=3)


def make_tile(filename: str, kind: str) -> None:
    image = new_canvas(32, 32)
    draw = ImageDraw.Draw(image)
    rect(draw, (0, 0, 31, 31), PANEL)
    if kind == "floor":
        rect(draw, (0, 0, 31, 4), MUTED)
        rect(draw, (4, 12, 13, 13), (32, 82, 88, 255))
        rect(draw, (20, 22, 29, 23), (32, 82, 88, 255))
    elif kind == "gate":
        rect(draw, (6, 3, 25, 31), INK)
        rect(draw, (9, 7, 22, 31), MUTED)
        rect(draw, (12, 12, 19, 31), PANEL)
        rect(draw, (10, 7, 21, 9), CYAN)
    elif kind == "shard":
        draw.polygon([(15, 3), (24, 17), (16, 29), (7, 17)], fill=CYAN)
        draw.polygon([(15, 6), (18, 17), (14, 24), (11, 15)], fill=ICE)
    save_scaled(image, filename, scale=3)


def make_reward(filename: str, color) -> None:
    image = new_canvas(32, 32)
    draw = ImageDraw.Draw(image)
    rect(draw, (7, 8, 24, 25), INK)
    rect(draw, (9, 10, 22, 23), color)
    rect(draw, (13, 5, 18, 26), ICE)
    rect(draw, (5, 13, 26, 18), ICE)
    save_scaled(image, filename, scale=3)


def main() -> None:
    for filename, pose in (
        ("player_idle_v2.png", "idle"),
        ("player_run_0.png", "run_a"),
        ("player_run_1.png", "run_b"),
        ("player_jump.png", "jump"),
        ("player_fall.png", "fall"),
        ("player_attack_side.png", "attack_side"),
        ("player_attack_up.png", "attack_up"),
        ("player_attack_down.png", "attack_down"),
    ):
        make_player(filename, pose)

    make_enemy("enemy_chaser.png", (78, 133, 142, 255), RED, "chaser")
    make_enemy("enemy_spear_thrower.png", (88, 96, 112, 255), GOLD, "chaser")
    make_enemy("enemy_shield_guard.png", (96, 125, 140, 255), CYAN, "shield")
    make_enemy("enemy_rift_worm.png", PURPLE, RED, "worm")
    make_enemy("enemy_resonance_mage.png", (64, 92, 126, 255), CYAN, "mage")
    make_enemy("boss_rust_crown_knight.png", (84, 104, 120, 255), RED, "boss")
    make_enemy("boss_broadcast_ghost.png", (72, 78, 126, 255), CYAN, "mage")
    make_enemy("boss_city_heart.png", (68, 118, 114, 255), RED, "boss")

    make_slash("slash_side.png", "side")
    make_slash("slash_up.png", "up")
    make_slash("slash_down.png", "down")
    make_projectile("projectile_spear.png", "spear")
    make_projectile("projectile_orb.png", "orb")

    for filename, kind in (
        ("icon_heart.png", "heart"),
        ("icon_echo.png", "echo"),
        ("icon_combo.png", "combo"),
        ("icon_parry.png", "parry"),
        ("icon_dash.png", "dash"),
        ("icon_warning.png", "warning"),
        ("icon_coin.png", "coin"),
        ("icon_skull.png", "skull"),
    ):
        make_icon(filename, kind)

    make_tile("tile_floor.png", "floor")
    make_tile("room_gate.png", "gate")
    make_tile("echo_shard.png", "shard")
    make_reward("reward_common.png", MUTED)
    make_reward("reward_rare.png", CYAN)
    make_reward("reward_epic.png", PURPLE)


if __name__ == "__main__":
    main()
