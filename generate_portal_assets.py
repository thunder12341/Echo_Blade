"""生成关卡右侧「回响之门」传送门素材。

按 images/ 现有像素风格生成：先在 24x40 的小画布上绘制，再用最近邻放大 4 倍输出
96x160，保证硬边像素观感。产出：

* portal_idle_0.png / portal_idle_1.png   —— 待机循环两帧（内部旋涡缓慢旋转）
* portal_enter_0..3.png                   —— 进入动画四帧（旋涡收紧 → 强闪光 → 白场）

用法：
    .\\.venv\\Scripts\\python.exe generate_portal_assets.py

如果之后手绘了新的传送门，直接覆盖同名文件即可，代码无需改动。
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent
IMAGE_DIR = PROJECT_ROOT / "images"

PIXEL_SIZE = 4
GRID_WIDTH = 24
GRID_HEIGHT = 40
OUTPUT_SIZE = (GRID_WIDTH * PIXEL_SIZE, GRID_HEIGHT * PIXEL_SIZE)

VOID = (7, 12, 25)
DEEP = (16, 30, 54)
CYAN = (79, 220, 214)
ICE = (211, 255, 232)
GOLD = (243, 204, 116)
VIOLET = (166, 99, 244)


def _mix(first: tuple[int, int, int], second: tuple[int, int, int], ratio: float) -> tuple[int, int, int]:
    ratio = max(0.0, min(1.0, ratio))
    return tuple(
        round(first[index] + (second[index] - first[index]) * ratio) for index in range(3)
    )


def _smoothstep(edge0: float, edge1: float, value: float) -> float:
    if edge1 <= edge0:
        return 0.0
    ratio = max(0.0, min(1.0, (value - edge0) / (edge1 - edge0)))
    return ratio * ratio * (3.0 - 2.0 * ratio)


def render_portal(
    *,
    phase: float = 0.0,
    intensity: float = 0.0,
    collapse: float = 0.0,
) -> Image.Image:
    """绘制一帧传送门。

    phase:     旋涡旋转相位（0~1）
    intensity: 0 为常态，1 为进入动画的高亮峰值
    collapse:  0 为完整门形，1 为收缩成白场
    """
    image = Image.new("RGBA", (GRID_WIDTH, GRID_HEIGHT), (0, 0, 0, 0))
    pixels = image.load()
    center_x = (GRID_WIDTH - 1) / 2.0
    center_y = (GRID_HEIGHT - 1) / 2.0
    radius_x = GRID_WIDTH * 0.40
    radius_y = GRID_HEIGHT * 0.43
    shrink = 1.0 - 0.55 * collapse

    for y in range(GRID_HEIGHT):
        for x in range(GRID_WIDTH):
            nx = (x - center_x) / radius_x
            ny = (y - center_y) / radius_y
            distance = math.hypot(nx, ny) / max(0.25, shrink)
            if distance > 1.32:
                continue
            angle = math.atan2(ny, nx)

            # 内部旋涡：随相位旋转，越靠中心越亮
            swirl = 0.5 + 0.5 * math.sin(angle * 2.0 - distance * 9.0 + phase * math.tau)
            inner = 1.0 - _smoothstep(0.12, 0.62, distance)
            body = _mix(DEEP, VOID, inner)
            swirl_color = _mix(CYAN, ICE, swirl)
            body = _mix(body, swirl_color, inner * (0.35 + 0.55 * swirl))

            # 门框：环状高亮
            ring = math.exp(-((distance - 0.8) ** 2) / (2 * 0.075**2))
            ring_color = _mix(ICE, GOLD, 0.25 * intensity)
            body = _mix(body, ring_color, min(1.0, ring * (0.85 + 0.35 * intensity)))

            # 金色符文：沿门框均匀分布，进入动画时更亮
            rune_phase = (angle + math.pi) / (math.tau / 8.0)
            rune = max(0.0, 1.0 - abs(rune_phase - round(rune_phase)) * 4.0)
            rune *= math.exp(-((distance - 0.8) ** 2) / (2 * 0.1**2))
            if rune > 0.02:
                body = _mix(body, GOLD, min(1.0, rune * (0.8 + 0.6 * intensity)))

            # 外发光
            glow = max(0.0, (distance - 0.88) / 0.44)
            glow_colour = _mix(CYAN, VIOLET, 0.45 * collapse)

            alpha = 255.0
            if distance > 1.0:
                alpha = 255.0 * (1.0 - _smoothstep(1.0, 1.32, distance))
            if glow > 0.0:
                body = _mix(body, glow_colour, glow * (0.55 + 0.35 * intensity))
                alpha = max(alpha, 210.0 * (1.0 - glow))

            # 进入动画：扩张的冲击环与最终白场
            if intensity > 0.0:
                shock_radius = 0.95 + 0.5 * intensity
                shock = math.exp(-((distance - shock_radius) ** 2) / (2 * 0.05**2))
                if shock > 0.05:
                    body = _mix(body, ICE, min(1.0, shock * intensity))
                    alpha = max(alpha, 255.0 * min(1.0, shock * intensity))
                core = 1.0 - _smoothstep(0.0, 0.7, distance)
                if core > 0.05 and intensity > 0.5:
                    body = _mix(body, ICE, core * (intensity - 0.5) * 1.6)
                    alpha = max(alpha, 255.0 * core)

            pixels[x, y] = (*body, round(max(0.0, min(255.0, alpha))))

    return image.resize(OUTPUT_SIZE, Image.NEAREST)


def main() -> None:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    outputs: list[tuple[str, Image.Image]] = [
        ("portal_idle_0.png", render_portal(phase=0.0)),
        ("portal_idle_1.png", render_portal(phase=0.5)),
        ("portal_enter_0.png", render_portal(phase=0.75, intensity=0.25, collapse=0.05)),
        ("portal_enter_1.png", render_portal(phase=0.0, intensity=0.55, collapse=0.2)),
        ("portal_enter_2.png", render_portal(phase=0.25, intensity=0.85, collapse=0.5)),
        ("portal_enter_3.png", render_portal(phase=0.5, intensity=1.0, collapse=0.85)),
    ]
    for name, image in outputs:
        path = IMAGE_DIR / name
        image.save(path)
        print(f"  生成 {name:<20} {OUTPUT_SIZE[0]}x{OUTPUT_SIZE[1]}")
    print(f"素材目录：{IMAGE_DIR}")


if __name__ == "__main__":
    main()
