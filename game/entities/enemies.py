from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from typing import ClassVar


Position = tuple[float, float]


@dataclass(frozen=True)
class AttackProfile:
    """Data the combat and UI layers need before an enemy attack resolves."""

    name: str
    damage: int
    reach: float
    telegraph_time: float
    cooldown: float
    parryable: bool = True
    projectile_speed: float | None = None
    posture_damage: int = 0
    warning_color: str = "white"


@dataclass(frozen=True)
class EnemyIntent:
    """A compact behavior result that later room AI can translate into actions."""

    action: str
    move_x: float = 0.0
    attack: AttackProfile | None = None
    note: str = ""


class Enemy(ABC):
    """Base class shared by every normal enemy type in the design document."""

    kind: ClassVar[str] = "enemy"
    display_name: ClassVar[str] = "敌人"
    base_hp: ClassVar[int] = 1
    base_posture: ClassVar[int] = 0
    speed: ClassVar[float] = 0.0
    bounty_score: ClassVar[int] = 100
    parry_tutorial: ClassVar[str] = ""
    attack_profile: ClassVar[AttackProfile] = AttackProfile(
        name="碰撞",
        damage=1,
        reach=24,
        telegraph_time=0.2,
        cooldown=1.0,
    )

    def __init__(
        self,
        x: float,
        y: float,
        *,
        threat: float = 0.0,
        elite: bool = False,
        facing: int = -1,
    ) -> None:
        self.x = float(x)
        self.y = float(y)
        self.threat = max(0.0, float(threat))
        self.elite = elite
        self.facing = 1 if facing >= 0 else -1

        elite_hp_bonus = 1.35 if elite else 1.0
        elite_damage_bonus = 1.15 if elite else 1.0
        self.max_hp = max(1, round(self.base_hp * (1.0 + self.threat) * elite_hp_bonus))
        self.hp = self.max_hp
        self.max_posture = max(0, round(self.base_posture * elite_hp_bonus))
        self.posture = self.max_posture
        self.damage = max(
            1,
            round(
                self.attack_profile.damage
                * (1.0 + self.threat * 0.75)
                * elite_damage_bonus
            ),
        )
        self._attack_cooldown = 0.0
        self._vulnerable_timer = 0.0

    @property
    def position(self) -> Position:
        return (self.x, self.y)

    @property
    def attack_ready(self) -> bool:
        return self._attack_cooldown <= 0.0

    @property
    def vulnerable(self) -> bool:
        return self._vulnerable_timer > 0.0

    @property
    def defeated(self) -> bool:
        return self.hp <= 0

    def update(self, dt: float, player_position: Position) -> EnemyIntent:
        """Advance timers and return this frame's intended behavior."""

        elapsed = max(0.0, dt)
        self._attack_cooldown = max(0.0, self._attack_cooldown - elapsed)
        self._vulnerable_timer = max(0.0, self._vulnerable_timer - elapsed)

        if self.defeated:
            return EnemyIntent("defeated", note="已被击败")
        if self.vulnerable:
            return EnemyIntent("vulnerable", note="破绽状态")

        intent = self.choose_intent(player_position)
        self.x += intent.move_x * elapsed
        if intent.attack is not None and self.attack_ready:
            self._attack_cooldown = intent.attack.cooldown
        return intent

    @abstractmethod
    def choose_intent(self, player_position: Position) -> EnemyIntent:
        """Pick a movement or attack behavior without advancing timers."""

    def distance_to(self, player_position: Position) -> float:
        return abs(player_position[0] - self.x)

    def direction_to(self, player_position: Position) -> int:
        return 1 if player_position[0] >= self.x else -1

    def scaled_attack(self, profile: AttackProfile | None = None) -> AttackProfile:
        return replace(profile or self.attack_profile, damage=self.damage)

    def can_be_parried(self) -> bool:
        return self.attack_profile.parryable

    def on_parried(self, *, perfect: bool) -> int:
        """Apply parry consequences and return reflected damage."""

        if not self.can_be_parried():
            return 0

        self.enter_vulnerable(0.8 if perfect else 0.35)
        posture_damage = self.attack_profile.posture_damage * (2 if perfect else 1)
        self.take_posture_damage(posture_damage)
        return round(self.damage * 1.5) if perfect else 0

    def enter_vulnerable(self, seconds: float = 0.8) -> None:
        self._vulnerable_timer = max(self._vulnerable_timer, seconds)

    def take_damage(
        self,
        amount: int,
        *,
        source_x: float | None = None,
        posture_damage: int = 0,
    ) -> int:
        actual_damage = max(0, int(round(amount)))
        self.hp = max(0, self.hp - actual_damage)
        self.take_posture_damage(posture_damage)
        return actual_damage

    def take_posture_damage(self, amount: int) -> None:
        if self.max_posture <= 0 or amount <= 0:
            return
        self.posture = max(0, self.posture - amount)
        if self.posture == 0:
            self.enter_vulnerable()


class Chaser(Enemy):
    kind = "chaser"
    display_name = "追击者"
    base_hp = 72
    base_posture = 45
    speed = 105.0
    bounty_score = 120
    parry_tutorial = "学习连续弹刀与观察三连斩节奏"
    attack_profile = AttackProfile(
        name="近身三连斩",
        damage=14,
        reach=58,
        telegraph_time=0.28,
        cooldown=1.2,
        parryable=True,
        posture_damage=12,
        warning_color="white",
    )

    def choose_intent(self, player_position: Position) -> EnemyIntent:
        self.facing = self.direction_to(player_position)
        if self.distance_to(player_position) <= self.attack_profile.reach and self.attack_ready:
            return EnemyIntent(
                "triple_slash",
                attack=self.scaled_attack(),
                note="近身三连斩",
            )
        return EnemyIntent("chase", move_x=self.facing * self.speed, note="追踪玩家")


class SpearThrower(Enemy):
    kind = "spear_thrower"
    display_name = "投矛手"
    base_hp = 54
    base_posture = 30
    speed = 68.0
    bounty_score = 140
    parry_tutorial = "学习反射远程长矛"
    preferred_distance = 260.0
    attack_profile = AttackProfile(
        name="可反射长矛",
        damage=17,
        reach=560,
        telegraph_time=0.42,
        cooldown=1.7,
        parryable=True,
        projectile_speed=320,
        posture_damage=10,
        warning_color="white",
    )

    def choose_intent(self, player_position: Position) -> EnemyIntent:
        self.facing = self.direction_to(player_position)
        distance = self.distance_to(player_position)
        if distance < 150:
            return EnemyIntent(
                "backstep",
                move_x=-self.facing * self.speed,
                note="拉开投掷距离",
            )
        if distance <= self.attack_profile.reach and self.attack_ready:
            return EnemyIntent(
                "throw_spear",
                attack=self.scaled_attack(),
                note="后排投掷可反射长矛",
            )
        return EnemyIntent(
            "reposition",
            move_x=self.facing * (self.speed * 0.55),
            note="寻找投矛角度",
        )


class ShieldGuard(Enemy):
    kind = "shield_guard"
    display_name = "盾卫"
    base_hp = 110
    base_posture = 80
    speed = 46.0
    bounty_score = 180
    parry_tutorial = "学习绕后攻击与破韧"
    attack_profile = AttackProfile(
        name="盾击",
        damage=18,
        reach=50,
        telegraph_time=0.34,
        cooldown=1.45,
        parryable=True,
        posture_damage=18,
        warning_color="white",
    )

    def choose_intent(self, player_position: Position) -> EnemyIntent:
        self.facing = self.direction_to(player_position)
        if self.distance_to(player_position) <= self.attack_profile.reach and self.attack_ready:
            return EnemyIntent("shield_bash", attack=self.scaled_attack(), note="盾击压制")
        return EnemyIntent("guard_advance", move_x=self.facing * self.speed, note="正面格挡推进")

    def take_damage(
        self,
        amount: int,
        *,
        source_x: float | None = None,
        posture_damage: int = 0,
    ) -> int:
        if source_x is not None and self.is_blocking_source(source_x) and not self.vulnerable:
            posture_damage += 8
            amount = math.ceil(amount * 0.35)
        return super().take_damage(
            amount,
            source_x=source_x,
            posture_damage=posture_damage,
        )

    def is_blocking_source(self, source_x: float) -> bool:
        return (source_x - self.x) * self.facing >= 0


class RiftWorm(Enemy):
    kind = "rift_worm"
    display_name = "裂隙虫"
    base_hp = 46
    base_posture = 0
    speed = 170.0
    bounty_score = 150
    parry_tutorial = "学习识别紫色不可弹反突进"
    attack_profile = AttackProfile(
        name="裂隙突进",
        damage=22,
        reach=220,
        telegraph_time=0.22,
        cooldown=1.45,
        parryable=False,
        posture_damage=0,
        warning_color="purple",
    )

    def choose_intent(self, player_position: Position) -> EnemyIntent:
        self.facing = self.direction_to(player_position)
        if self.distance_to(player_position) <= self.attack_profile.reach and self.attack_ready:
            return EnemyIntent(
                "rift_charge",
                move_x=self.facing * (self.speed * 1.65),
                attack=self.scaled_attack(),
                note="快速突进，不可弹反",
            )
        return EnemyIntent(
            "skitter",
            move_x=self.facing * self.speed,
            note="高速贴近玩家",
        )


class ResonanceMage(Enemy):
    kind = "resonance_mage"
    display_name = "共鸣法师"
    base_hp = 62
    base_posture = 35
    speed = 42.0
    bounty_score = 170
    parry_tutorial = "学习延迟能量球和二次弹反站位"
    safe_distance = 220.0
    attack_profile = AttackProfile(
        name="延迟能量球",
        damage=16,
        reach=620,
        telegraph_time=0.65,
        cooldown=2.1,
        parryable=True,
        projectile_speed=165,
        posture_damage=14,
        warning_color="white",
    )

    def choose_intent(self, player_position: Position) -> EnemyIntent:
        self.facing = self.direction_to(player_position)
        distance = self.distance_to(player_position)
        if distance < self.safe_distance:
            return EnemyIntent(
                "blink_back",
                move_x=-self.facing * self.speed,
                note="保持施法距离",
            )
        if distance <= self.attack_profile.reach and self.attack_ready:
            return EnemyIntent(
                "cast_delayed_orb",
                attack=self.scaled_attack(),
                note="释放延迟能量球",
            )
        return EnemyIntent("channel", note="蓄积共鸣能量")


ENEMY_CLASSES: dict[str, type[Enemy]] = {
    Chaser.kind: Chaser,
    SpearThrower.kind: SpearThrower,
    ShieldGuard.kind: ShieldGuard,
    RiftWorm.kind: RiftWorm,
    ResonanceMage.kind: ResonanceMage,
}
