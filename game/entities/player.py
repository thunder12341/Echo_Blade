from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Hitbox:
    left: float
    top: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.left + self.width

    @property
    def bottom(self) -> float:
        return self.top + self.height

    def overlaps(self, other: Hitbox) -> bool:
        return (
            self.left < other.right
            and self.right > other.left
            and self.top < other.bottom
            and self.bottom > other.top
        )


class Player:
    """Time-based player controller for movement, jumping and three-hit attacks."""

    MOVE_SPEED = 250.0
    GROUND_ACCELERATION = 1900.0
    AIR_ACCELERATION = 1050.0
    GROUND_FRICTION = 2300.0
    AIR_DRAG = 420.0
    JUMP_SPEED = 620.0
    GRAVITY = 1850.0
    MAX_FALL_SPEED = 900.0
    COYOTE_TIME = 0.11
    JUMP_BUFFER_TIME = 0.12
    DASH_DISTANCE = 72.0
    DASH_COOLDOWN = 0.32

    ATTACK_DURATION = 0.34
    ATTACK_ACTIVE_START = 0.06
    ATTACK_ACTIVE_END = 0.2
    COMBO_WINDOW = 0.55
    ATTACK_DAMAGE = (18, 20, 26)
    ATTACK_REACH = {
        "side": (76.0, 82.0, 94.0),
        "up": (78.0, 84.0, 92.0),
        "down": (80.0, 86.0, 96.0),
    }
    ATTACK_POSTURE_DAMAGE = (8, 10, 14)
    DOWN_ATTACK_BOUNCE_SPEED = 390.0

    BODY_WIDTH = 48.0
    BODY_HEIGHT = 108.0

    def __init__(
        self,
        x: float,
        ground_y: float,
        *,
        bounds: tuple[float, float] = (110.0, 690.0),
        max_hp: int = 100,
    ) -> None:
        self.x = float(x)
        self.y = float(ground_y)
        self.ground_y = float(ground_y)
        self.bounds_left, self.bounds_right = bounds
        self.max_hp = max(1, int(max_hp))
        self.hp = self.max_hp

        self.velocity_x = 0.0
        self.velocity_y = 0.0
        self.facing = 1
        self.grounded = True
        self.landed_this_frame = False

        self._coyote_timer = self.COYOTE_TIME
        self._jump_buffer_timer = 0.0
        self._dash_cooldown = 0.0
        self._attack_elapsed = -1.0
        self._attack_direction = "side"
        self._combo_index = 0
        self._combo_timer = 0.0
        self.attack_id = 0

    @property
    def position(self) -> tuple[float, float]:
        return (self.x, self.y)

    @property
    def body_hitbox(self) -> Hitbox:
        return Hitbox(
            self.x - self.BODY_WIDTH / 2,
            self.y - self.BODY_HEIGHT,
            self.BODY_WIDTH,
            self.BODY_HEIGHT,
        )

    @property
    def attack_in_progress(self) -> bool:
        return 0.0 <= self._attack_elapsed < self.ATTACK_DURATION

    @property
    def attack_active(self) -> bool:
        return self.attack_in_progress and (
            self.ATTACK_ACTIVE_START <= self._attack_elapsed <= self.ATTACK_ACTIVE_END
        )

    @property
    def attack_stage(self) -> int:
        return self._combo_index or 1

    @property
    def attack_direction(self) -> str:
        return self._attack_direction

    @property
    def attack_damage(self) -> int:
        return self.ATTACK_DAMAGE[self.attack_stage - 1]

    @property
    def posture_damage(self) -> int:
        return self.ATTACK_POSTURE_DAMAGE[self.attack_stage - 1]

    @property
    def attack_hitbox(self) -> Hitbox | None:
        if not self.attack_active:
            return None
        reach = self.ATTACK_REACH[self.attack_direction][self.attack_stage - 1]
        if self.attack_direction == "up":
            width = max(42.0, self.BODY_WIDTH + 16.0)
            return Hitbox(
                self.x - width / 2,
                self.y - self.BODY_HEIGHT - reach,
                width,
                reach,
            )
        if self.attack_direction == "down":
            width = max(72.0, self.BODY_WIDTH + 32.0)
            return Hitbox(self.x - width / 2, self.y, width, reach)

        width = max(24.0, reach - 12.0)
        left = self.x + 12.0 if self.facing > 0 else self.x - reach
        return Hitbox(left, self.y - self.BODY_HEIGHT, width, self.BODY_HEIGHT - 12.0)

    def update(self, dt: float, move_axis: float) -> None:
        elapsed = max(0.0, dt)
        self.landed_this_frame = False
        self._update_timers(elapsed)

        axis = max(-1.0, min(1.0, float(move_axis)))
        if abs(axis) > 0.01:
            self.facing = 1 if axis > 0 else -1
            target_speed = axis * self.MOVE_SPEED
            if self.attack_active:
                target_speed *= 0.45
            acceleration = (
                self.GROUND_ACCELERATION if self.grounded else self.AIR_ACCELERATION
            )
            self.velocity_x = self._move_towards(
                self.velocity_x,
                target_speed,
                acceleration * elapsed,
            )
        else:
            friction = self.GROUND_FRICTION if self.grounded else self.AIR_DRAG
            self.velocity_x = self._move_towards(
                self.velocity_x,
                0.0,
                friction * elapsed,
            )

        self.x += self.velocity_x * elapsed
        if self.x <= self.bounds_left:
            self.x = self.bounds_left
            self.velocity_x = max(0.0, self.velocity_x)
        elif self.x >= self.bounds_right:
            self.x = self.bounds_right
            self.velocity_x = min(0.0, self.velocity_x)

        if self.grounded:
            self._coyote_timer = self.COYOTE_TIME
        else:
            self._coyote_timer = max(0.0, self._coyote_timer - elapsed)

        if self._jump_buffer_timer > 0.0 and self._coyote_timer > 0.0:
            self.velocity_y = -self.JUMP_SPEED
            self.grounded = False
            self._jump_buffer_timer = 0.0
            self._coyote_timer = 0.0

        if not self.grounded:
            self.velocity_y = min(
                self.MAX_FALL_SPEED,
                self.velocity_y + self.GRAVITY * elapsed,
            )
            self.y += self.velocity_y * elapsed

        if self.y >= self.ground_y:
            if not self.grounded:
                self.landed_this_frame = True
            self.y = self.ground_y
            self.velocity_y = 0.0
            self.grounded = True

    def request_jump(self) -> bool:
        self._jump_buffer_timer = self.JUMP_BUFFER_TIME
        return self.grounded or self._coyote_timer > 0.0

    def start_attack(self, direction: str = "side") -> bool:
        if self.attack_in_progress:
            return False
        if direction not in self.ATTACK_REACH:
            raise ValueError(f"不支持的攻击方向: {direction}")
        self._attack_direction = direction
        if direction == "down":
            self.velocity_x *= 0.25
        if self._combo_timer > 0.0:
            self._combo_index = self._combo_index % len(self.ATTACK_DAMAGE) + 1
        else:
            self._combo_index = 1
        self._combo_timer = self.COMBO_WINDOW
        self._attack_elapsed = 0.0
        self.attack_id += 1
        return True

    def bounce_from_down_attack(self) -> bool:
        if self.attack_direction != "down":
            return False
        self.velocity_y = -self.DOWN_ATTACK_BOUNCE_SPEED
        self.grounded = False
        self.y = min(self.y, self.ground_y)
        return True

    def dash(self) -> bool:
        if self._dash_cooldown > 0.0:
            return False
        self._dash_cooldown = self.DASH_COOLDOWN
        self.x = max(
            self.bounds_left,
            min(self.bounds_right, self.x + self.facing * self.DASH_DISTANCE),
        )
        self.velocity_x = self.facing * self.MOVE_SPEED * 1.35
        return True

    def _update_timers(self, dt: float) -> None:
        self._dash_cooldown = max(0.0, self._dash_cooldown - dt)
        self._jump_buffer_timer = max(0.0, self._jump_buffer_timer - dt)
        if self._combo_timer > 0.0:
            self._combo_timer = max(0.0, self._combo_timer - dt)
            if self._combo_timer == 0.0 and not self.attack_in_progress:
                self._combo_index = 0

        if self._attack_elapsed >= 0.0:
            self._attack_elapsed += dt
            if self._attack_elapsed >= self.ATTACK_DURATION:
                self._attack_elapsed = -1.0

    @staticmethod
    def _move_towards(value: float, target: float, max_delta: float) -> float:
        if value < target:
            return min(value + max_delta, target)
        if value > target:
            return max(value - max_delta, target)
        return target
