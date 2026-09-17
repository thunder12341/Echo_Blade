from __future__ import annotations

import math
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
    DASH_DURATION = 0.2
    DASH_COOLDOWN = 0.3

    PARRY_DURATION = 0.32
    PERFECT_PARRY_WINDOW = 0.12
    # 弹刀输入缓冲：按下后这么久内命中判定都算完美弹刀，
    # 与提示闪光提前量（main.MELEE_FLASH_LEAD）保持一致。
    PARRY_INPUT_BUFFER = 0.65
    # 弹刀内置冷却：架势结束后还要等这么久才能再次弹刀
    PARRY_COOLDOWN = 0.2

    # 回响剑气：起手到剑气出手的时间，以及整段无敌时间
    SKILL_CAST_TIME = 0.18
    SKILL_DURATION = 0.66

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
        bounds: tuple[float, float] = (72.0, 1208.0),
        max_hp: int = 320,
    ) -> None:
        self.x = float(x)
        self.y = float(ground_y)
        self.ground_y = float(ground_y)
        self.bounds_left, self.bounds_right = bounds
        self.max_hp = max(1, int(max_hp))
        self.hp = self.max_hp
        # 升级带来的伤害加成，会同时作用于普通攻击与回响剑气
        self.attack_bonus = 0

        self.velocity_x = 0.0
        self.velocity_y = 0.0
        self.facing = 1
        self.grounded = True
        self.landed_this_frame = False
        self.max_air_jumps = 0
        self._air_jumps_remaining = 0
        # 闪避需要通过回响中枢解锁（教学关内始终可用）
        self.dash_unlocked = False
        # 受击闪烁：被打中后短暂泛白，提示玩家确实吃到了伤害
        self.hurt_flash = 0.0
        self.HURT_FLASH_TIME = 0.24

        self._coyote_timer = self.COYOTE_TIME
        self._jump_buffer_timer = 0.0
        self._dash_cooldown = 0.0
        self._dash_elapsed = -1.0
        self._parry_buffer = 0.0
        self._parry_cooldown = 0.0
        self._parry_elapsed = -1.0
        self._skill_elapsed = -1.0
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
    def parry_active(self) -> bool:
        return 0.0 <= self._parry_elapsed < self.PARRY_DURATION

    @property
    def parry_buffered(self) -> bool:
        """是否处于弹刀输入缓冲内（用于近战完美弹刀判定）。"""
        return self._parry_buffer > 0.0

    @property
    def parry_buffer_age(self) -> float:
        """距离上一次弹刀输入过去了多久；不在缓冲内时返回无穷大。"""
        if self._parry_buffer <= 0.0:
            return math.inf
        return self.PARRY_INPUT_BUFFER - self._parry_buffer

    @property
    def dash_active(self) -> bool:
        return 0.0 <= self._dash_elapsed < self.DASH_DURATION

    @property
    def skill_active(self) -> bool:
        return 0.0 <= self._skill_elapsed < self.SKILL_DURATION

    @property
    def skill_elapsed(self) -> float:
        return self._skill_elapsed if self._skill_elapsed >= 0.0 else 0.0

    @property
    def invulnerable(self) -> bool:
        """闪避与回响剑气期间无敌：不受任何伤害。"""
        return self.dash_active or self.skill_active

    @property
    def perfect_parry_active(self) -> bool:
        return 0.0 <= self._parry_elapsed <= self.PERFECT_PARRY_WINDOW

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
        return self.ATTACK_DAMAGE[self.attack_stage - 1] + self.attack_bonus

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
        if self.parry_active or self.skill_active:
            axis = 0.0
            self.velocity_x = 0.0
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
            self._air_jumps_remaining = self.max_air_jumps

    def request_jump(self) -> bool:
        if self.parry_active or self.skill_active:
            return False
        if self.grounded or self._coyote_timer > 0.0:
            self._jump_buffer_timer = self.JUMP_BUFFER_TIME
            return True
        if self._air_jumps_remaining <= 0:
            return False
        self._air_jumps_remaining -= 1
        self._jump_buffer_timer = 0.0
        self._coyote_timer = 0.0
        self.velocity_y = -self.JUMP_SPEED
        self.grounded = False
        return True

    def unlock_air_jump(self, count: int = 1) -> None:
        self.max_air_jumps = max(self.max_air_jumps, max(0, int(count)))
        self._air_jumps_remaining = self.max_air_jumps

    def start_attack(self, direction: str = "side") -> bool:
        if self.attack_in_progress or self.parry_active or self.skill_active:
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
        if not self.dash_unlocked:
            return False
        if self._dash_cooldown > 0.0 or self.parry_active or self.skill_active:
            return False
        self._dash_cooldown = self.DASH_COOLDOWN
        self._dash_elapsed = 0.0
        self.x = max(
            self.bounds_left,
            min(self.bounds_right, self.x + self.facing * self.DASH_DISTANCE),
        )
        self.velocity_x = self.facing * self.MOVE_SPEED * 1.35
        return True

    def start_parry(self) -> bool:
        if self.parry_active or self.skill_active or self._parry_cooldown > 0.0:
            return False
        self._attack_elapsed = -1.0
        self._parry_buffer = self.PARRY_INPUT_BUFFER
        self._parry_elapsed = 0.0
        self.velocity_x = 0.0
        return True

    def cast_skill(self) -> bool:
        """起手回响剑气：整段动作无敌，且能打断正在进行的普通攻击。"""
        if self.skill_active or self.parry_active or self.dash_active:
            return False
        self._attack_elapsed = -1.0
        self._parry_elapsed = -1.0
        self._combo_index = 0
        self._combo_timer = 0.0
        self._skill_elapsed = 0.0
        self.velocity_x = 0.0
        return True

    def gain_level(self, hp_gain: int, attack_gain: int) -> int:
        """升级把新增的生命上限同时补进当前生命：既不倒扣血，也不会回满。

        失去的生命不会因为升级而变少，但新增的上限会立刻可用；返回实际补进
        当前生命的点数，供 UI 提示使用。
        """
        hp_gain = max(0, int(hp_gain))
        self.max_hp += hp_gain
        gained_hp = 0
        if self.hp > 0:
            before = self.hp
            self.hp = min(self.max_hp, self.hp + hp_gain)
            gained_hp = self.hp - before
        self.attack_bonus += max(0, int(attack_gain))
        return gained_hp

    def take_damage(self, amount: int, *, ignore_invulnerability: bool = False) -> int:
        if self.invulnerable and not ignore_invulnerability:
            return 0
        actual_damage = max(0, int(round(amount)))
        self.hp = max(0, self.hp - actual_damage)
        if actual_damage > 0:
            self.hurt_flash = self.HURT_FLASH_TIME
        return actual_damage

    def heal(self, amount: int) -> int:
        actual_healing = min(
            max(0, int(round(amount))),
            self.max_hp - self.hp,
        )
        self.hp += actual_healing
        return actual_healing

    def _update_timers(self, dt: float) -> None:
        self._dash_cooldown = max(0.0, self._dash_cooldown - dt)
        self.hurt_flash = max(0.0, self.hurt_flash - dt)
        self._parry_buffer = max(0.0, self._parry_buffer - dt)
        self._parry_cooldown = max(0.0, self._parry_cooldown - dt)
        if self._dash_elapsed >= 0.0:
            self._dash_elapsed += dt
            if self._dash_elapsed >= self.DASH_DURATION:
                self._dash_elapsed = -1.0
        self._jump_buffer_timer = max(0.0, self._jump_buffer_timer - dt)
        if self._parry_elapsed >= 0.0:
            self._parry_elapsed += dt
            if self._parry_elapsed >= self.PARRY_DURATION:
                self._parry_elapsed = -1.0
                # 架势收招后才进入内置冷却，避免"按得快就能一直弹"
                self._parry_cooldown = max(self._parry_cooldown, self.PARRY_COOLDOWN)
        if self._skill_elapsed >= 0.0:
            self._skill_elapsed += dt
            if self._skill_elapsed >= self.SKILL_DURATION:
                self._skill_elapsed = -1.0
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
