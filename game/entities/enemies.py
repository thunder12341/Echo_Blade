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
    tag: str = ""
    # 该招式专属的弹刀窗口（秒）。留空则沿用全局的弹刀输入缓冲。
    parry_window: float | None = None


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
    body_width: ClassVar[float] = 36.0
    body_height: ClassVar[float] = 44.0
    attack_profile: ClassVar[AttackProfile] = AttackProfile(
        name="碰撞",
        damage=1,
        reach=24,
        telegraph_time=0.2,
        cooldown=1.0,
    )
    # 被回响剑气击飞时的重力与水平摩擦
    KNOCKBACK_GRAVITY: ClassVar[float] = 1750.0
    KNOCKBACK_FRICTION: ClassVar[float] = 900.0
    # 韧性归零后的破绽窗口：窗口结束韧性回满，敌人重新投入战斗
    BREAK_WINDOW: ClassVar[float] = 0.8
    # 被近战弹刀击退：横向速度与腾空高度
    PARRY_KNOCKBACK_SPEED: ClassVar[float] = 330.0
    PARRY_KNOCKBACK_LIFT: ClassVar[float] = 200.0
    # 受击闪烁时长
    HURT_FLASH_TIME: ClassVar[float] = 0.22
    # 与角色之间必须保留的最小间距（在双方半身宽度之外再加一段）
    MIN_BODY_GAP: ClassVar[float] = 22.0

    def __init__(
        self,
        x: float,
        y: float,
        *,
        threat: float = 0.0,
        scale: float = 1.0,
        elite: bool = False,
        facing: int = -1,
        bounds: tuple[float, float] = (40.0, 1240.0),
    ) -> None:
        self.x = float(x)
        self.y = float(y)
        self.bounds_left, self.bounds_right = bounds
        self.threat = max(0.0, float(threat))
        # 章节成长倍率：同时放大生命与伤害，首领保持 1.0
        self.scale = max(0.05, float(scale))
        self.elite = elite
        self.facing = 1 if facing >= 0 else -1
        self.ground_y = float(y)
        self.velocity_x = 0.0
        self.velocity_y = 0.0

        elite_hp_bonus = 1.35 if elite else 1.0
        elite_damage_bonus = 1.15 if elite else 1.0
        self.max_hp = max(
            1,
            round(self.base_hp * (1.0 + self.threat) * elite_hp_bonus * self.scale),
        )
        self.hp = self.max_hp
        self.max_posture = max(0, round(self.base_posture * elite_hp_bonus))
        self.posture = self.max_posture
        self.damage = max(
            1,
            round(
                self.attack_profile.damage
                * (1.0 + self.threat * 0.75)
                * elite_damage_bonus
                * self.scale
            ),
        )
        self._attack_cooldown = 0.0
        self._vulnerable_timer = 0.0
        self._posture_broken = False
        self.hurt_flash = 0.0

    @property
    def position(self) -> Position:
        return (self.x, self.y)

    @property
    def attack_ready(self) -> bool:
        return self._attack_cooldown <= 0.0

    def begin_spawn_grace(self, seconds: float) -> None:
        """刚踏入战场：先把首次出手推迟一段时间，留给玩家反应余地。"""
        self._attack_cooldown = max(self._attack_cooldown, max(0.0, float(seconds)))

    @property
    def vulnerable(self) -> bool:
        return self._vulnerable_timer > 0.0

    @property
    def defeated(self) -> bool:
        return self.hp <= 0

    @property
    def airborne(self) -> bool:
        """是否处在滞空阶段（含刚被击飞、还没离开地面的那一帧）。"""
        return self.y < self.ground_y - 0.01 or self.velocity_y < -0.01

    @property
    def being_knocked_back(self) -> bool:
        """是否正处于被击飞的滑行/滞空阶段。"""
        return self.airborne or abs(self.velocity_x) > 1.0

    def update(self, dt: float, player_position: Position) -> EnemyIntent:
        """Advance timers and return this frame's intended behavior."""

        elapsed = max(0.0, dt)
        self._attack_cooldown = max(0.0, self._attack_cooldown - elapsed)
        self._vulnerable_timer = max(0.0, self._vulnerable_timer - elapsed)
        self.hurt_flash = max(0.0, self.hurt_flash - elapsed)
        # 破绽结束：韧性回满，否则一次破韧后敌人会永远站不起来
        if self._posture_broken and self._vulnerable_timer <= 0.0:
            self._posture_broken = False
            self.posture = self.max_posture

        if self.defeated:
            return EnemyIntent("defeated", note="已被击败")
        if self.being_knocked_back:
            # 被剑气击飞期间脱离 AI：先横向滑出，再受重力落回地面
            self._advance_knockback(elapsed)
            return EnemyIntent("knocked_back", note="被击飞")
        if self.vulnerable:
            return EnemyIntent("vulnerable", note="破绽状态")

        intent = self.choose_intent(player_position)
        self.x += intent.move_x * elapsed
        self._keep_distance_from(player_position)
        # 只被场地左右边界挡住，避免走出画面或被卡在半途
        self.x = min(max(self.x, self.bounds_left), self.bounds_right)
        if intent.attack is not None and self.attack_ready:
            self._attack_cooldown = intent.attack.cooldown
        return intent

    @abstractmethod
    def choose_intent(self, player_position: Position) -> EnemyIntent:
        """Pick a movement or attack behavior without advancing timers."""

    def distance_to(self, player_position: Position) -> float:
        return abs(player_position[0] - self.x)

    def _keep_distance_from(self, player_position: Position) -> None:
        """贴身停下就好：不让近战敌人和角色重叠在一起。"""
        gap = self.body_width / 2 + self.MIN_BODY_GAP
        delta = self.x - float(player_position[0])
        if abs(delta) >= gap:
            return
        direction = 1.0 if delta >= 0 else -1.0
        self.x = float(player_position[0]) + direction * gap

    def direction_to(self, player_position: Position) -> int:
        return 1 if player_position[0] >= self.x else -1

    def can_step(self, direction: int, margin: float = 60.0) -> bool:
        """朝某个方向还能不能继续走：用于判断后撤是不是已经贴到画面边缘。"""
        if direction > 0:
            return self.x < self.bounds_right - margin
        return self.x > self.bounds_left + margin

    def scaled_attack(self, profile: AttackProfile | None = None) -> AttackProfile:
        return replace(profile or self.attack_profile, damage=self.damage)

    def can_be_parried(self) -> bool:
        return self.attack_profile.parryable

    def on_parried(self, *, perfect: bool) -> int:
        """Apply parry consequences and return reflected damage."""

        if not self.can_be_parried():
            return 0

        # 弹刀特效：比普通受击更亮的闪烁
        self.hurt_flash = self.HURT_FLASH_TIME * 1.8
        self.enter_vulnerable(0.8 if perfect else 0.35)
        posture_damage = self.attack_profile.posture_damage * (2 if perfect else 1)
        self.take_posture_damage(posture_damage)
        return round(self.damage * 1.5) if perfect else 0

    def on_attack_parried(self, profile: AttackProfile, *, perfect: bool) -> int:
        """Resolve an individual attack's parry consequence."""
        return self.on_parried(perfect=perfect)

    def on_attack_resolved(
        self,
        profile: AttackProfile,
        *,
        parried: bool,
    ) -> None:
        """攻击结算回调：供首领连段之类需要按段推进的机制使用。"""
        return None

    def allows_parry_knockback(self, profile: AttackProfile) -> bool:
        """弹刀是否会把该敌人震开。首领连段的前段不产生击退。"""
        return True

    def enter_vulnerable(self, seconds: float = 0.8) -> None:
        self._vulnerable_timer = max(self._vulnerable_timer, seconds)

    def break_posture(self) -> None:
        """韧性归零：进入破绽窗口，窗口结束后韧性回满。"""
        self._posture_broken = True
        self.enter_vulnerable(self.BREAK_WINDOW)

    def apply_knockback(self, direction: int, speed: float, lift: float) -> None:
        """被回响剑气击飞：横向推开并腾空，之后自然落下。"""
        self.velocity_x = (1.0 if direction >= 0 else -1.0) * abs(float(speed))
        self.velocity_y = -abs(float(lift))
        self.enter_vulnerable(0.9)

    def _advance_knockback(self, elapsed: float) -> None:
        self.x += self.velocity_x * elapsed
        self.x = min(max(self.x, self.bounds_left), self.bounds_right)

        self.velocity_y += self.KNOCKBACK_GRAVITY * elapsed
        self.y += self.velocity_y * elapsed
        if self.y >= self.ground_y:
            self.y = self.ground_y
            self.velocity_y = 0.0

        speed = abs(self.velocity_x)
        if speed > 0.0:
            speed = max(0.0, speed - self.KNOCKBACK_FRICTION * elapsed)
            self.velocity_x = math.copysign(speed, self.velocity_x)

    def take_damage(
        self,
        amount: int,
        *,
        source_x: float | None = None,
        posture_damage: int = 0,
    ) -> int:
        actual_damage = max(0, int(round(amount)))
        self.hp = max(0, self.hp - actual_damage)
        if actual_damage > 0:
            self.hurt_flash = max(self.hurt_flash, self.HURT_FLASH_TIME)
        self.take_posture_damage(posture_damage)
        return actual_damage

    def take_posture_damage(self, amount: int) -> None:
        if self.max_posture <= 0 or amount <= 0:
            return
        if self._posture_broken:
            # 破绽窗口内不再累计：否则连续命中会把破绽无限延长成永久僵直
            return
        self.posture = max(0, self.posture - amount)
        if self.posture == 0:
            self.break_posture()


class Chaser(Enemy):
    kind = "chaser"
    display_name = "追击者"
    base_hp = 88
    base_posture = 50
    speed = 105.0
    bounty_score = 120
    parry_tutorial = "学习连续弹刀与观察三连斩节奏"
    attack_profile = AttackProfile(
        name="近身三连斩",
        damage=16,
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
    base_hp = 68
    base_posture = 34
    speed = 68.0
    bounty_score = 140
    parry_tutorial = "学习反射远程长矛"
    preferred_distance = 260.0
    attack_profile = AttackProfile(
        name="可反射长矛",
        damage=20,
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
        # 贴边时不再徒劳后撤，否则会被逼到画面边缘后彻底卡住
        if distance < 150 and self.can_step(-self.facing):
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
    base_hp = 135
    base_posture = 88
    speed = 46.0
    bounty_score = 180
    parry_tutorial = "学习绕后攻击与破韧"
    attack_profile = AttackProfile(
        name="盾击",
        damage=21,
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
    base_hp = 56
    base_posture = 0
    speed = 170.0
    bounty_score = 150
    parry_tutorial = "学习识别紫色不可弹反突进"
    attack_profile = AttackProfile(
        name="裂隙突进",
        damage=25,
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
    base_hp = 78
    base_posture = 40
    speed = 42.0
    bounty_score = 170
    parry_tutorial = "学习延迟能量球和二次弹反站位"
    safe_distance = 220.0
    # 离画面边缘这么近时不再后撤：否则会被逼到边缘后永远卡在原地
    wall_margin = 60.0
    attack_profile = AttackProfile(
        name="延迟能量球",
        damage=19,
        # 射程覆盖大半个战场：站在很远的地方也能继续施压
        reach=900,
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
        # 只有身后还有余地时才后撤；贴边就地施法，避免卡死在画面边缘
        if distance < self.safe_distance and self.can_step(
            -self.facing, self.wall_margin
        ):
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
        if distance > self.attack_profile.reach:
            # 距离太远时主动靠近，而不是站在原地什么都不做
            return EnemyIntent(
                "advance",
                move_x=self.facing * self.speed,
                note="缩短施法距离",
            )
        return EnemyIntent("channel", note="蓄积共鸣能量")


class RustCrownKnight(Enemy):
    """王庭首领：三连弹刀破防与断忆敕令构成全部攻防节奏。"""

    kind = "rust_crown_knight"
    display_name = "锈冠骑士"
    base_hp = 760
    base_posture = 180
    speed = 72.0
    bounty_score = 1800
    parry_tutorial = "连续弹开三段冠冕三裁才能击退破防；二阶段的断忆敕令必须完美弹刀"
    body_width = 88.0
    body_height = 126.0
    PHASE_TWO_THRESHOLD = 0.5
    SPECIAL_INTERVAL = 7.0
    # 初始冷却只在一阶段期间消耗；二阶段的入场敕令由 _check_phase_two 直接放开
    SPECIAL_FIRST_DELAY = 3.2
    # 全阶段抗性：常规状态减少 80% 伤害，弹反伤害同样被减免
    DAMAGE_RESISTANCE = 0.8
    BROKEN_DAMAGE_TAKEN = 1.0
    # 破防 / 瘫痪：五秒内不再减伤，开场先吃一记最大生命 10% 的破防伤害
    DEFENSE_BREAK_DURATION = 5.0
    BREAK_DAMAGE_RATIO = 0.1
    # 首领韧性归零只中断当前行动，暴露 1.2 秒核心后重新起身
    BREAK_WINDOW = 1.2
    # 一阶段冠冕三裁：三段各自 0.4 秒弹刀窗口，落点间隔 0.3 / 0.4 秒
    COMBO_SIZE = 3
    COMBO_DAMAGE = 120
    COMBO_PARRY_WINDOW = 0.4
    COMBO_TELEGRAPH = 0.3
    # 落点间隔：第一段→第二段 0.3 秒，第二段→第三段 0.4 秒
    COMBO_IMPACT_GAPS = (0.3, 0.4)
    COMBO_RECOVERY = 1.2
    COMBO_REACH = 122.0
    # 二阶段断忆敕令：弹刀窗口收紧，失误按当前生命结算
    DECREE_PARRY_WINDOW = 0.35
    # 重甲首领不会被弹刀远远震开，只后退一小步
    PARRY_KNOCKBACK_SPEED = 200.0
    PARRY_KNOCKBACK_LIFT = 0.0

    # attack_profile 保留为基类与伤害结算用的基准招式：两个阶段的常规攻击
    # 都走下面的 combo_profiles，骑士不会再打出单发横斩。
    attack_profile = AttackProfile(
        name="王庭横斩",
        damage=28,
        reach=92,
        telegraph_time=0.52,
        cooldown=1.55,
        parryable=True,
        posture_damage=24,
        warning_color="gold",
        tag="boss_slash",
    )
    execution_profile = AttackProfile(
        name="断忆敕令",
        damage=1,
        reach=2000,
        telegraph_time=1.2,
        cooldown=2.2,
        parryable=True,
        posture_damage=0,
        warning_color="crimson",
        tag="boss_memory_sever",
        parry_window=DECREE_PARRY_WINDOW,
    )
    combo_profiles = (
        AttackProfile(
            name="冠冕三裁 · 一",
            damage=COMBO_DAMAGE,
            reach=COMBO_REACH,
            telegraph_time=COMBO_TELEGRAPH,
            cooldown=0.0,
            parryable=True,
            posture_damage=0,
            warning_color="gold",
            tag="boss_combo_1",
            parry_window=COMBO_PARRY_WINDOW,
        ),
        AttackProfile(
            name="冠冕三裁 · 二",
            damage=COMBO_DAMAGE,
            reach=COMBO_REACH,
            telegraph_time=COMBO_TELEGRAPH,
            cooldown=0.0,
            parryable=True,
            posture_damage=0,
            warning_color="gold",
            tag="boss_combo_2",
            parry_window=COMBO_PARRY_WINDOW,
        ),
        AttackProfile(
            name="冠冕三裁 · 三",
            damage=COMBO_DAMAGE,
            reach=COMBO_REACH,
            telegraph_time=COMBO_TELEGRAPH,
            cooldown=0.0,
            parryable=True,
            posture_damage=0,
            warning_color="gold",
            tag="boss_combo_3",
            parry_window=COMBO_PARRY_WINDOW,
        ),
    )

    def __init__(self, x: float, y: float, **kwargs) -> None:
        super().__init__(x, y, **kwargs)
        self.phase = 1
        self._special_cooldown = self.SPECIAL_FIRST_DELAY
        self._defense_break_timer = 0.0
        self._combo_active = False
        self._combo_step = 0
        self._combo_parries = 0
        self._combo_delay = 0.0
        self._combo_recovery = 0.0
        # 距离上一次断忆敕令之后打完了几套连段：二阶段用它保证"连段 ↔ 敕令"的穿插
        self._comboes_since_decree = 0

    @property
    def defense_broken(self) -> bool:
        return self._defense_break_timer > 0.0

    @property
    def in_crown_combo(self) -> bool:
        return self._combo_active

    @property
    def _advance_speed(self) -> float:
        """追击速度：二阶段骑士会把自己拽回玩家身边，避免放完敕令要走上十几秒。"""
        return self.speed * (2.6 if self.phase == 2 else 1.0)

    def scaled_attack(self, profile: AttackProfile | None = None) -> AttackProfile:
        source = profile or self.attack_profile
        damage = max(1, round(source.damage * (1.0 + self.threat * 0.75)))
        return replace(source, damage=damage)

    def update(self, dt: float, player_position: Position) -> EnemyIntent:
        elapsed = max(0.0, dt)
        was_broken = self.defense_broken
        self._defense_break_timer = max(0.0, self._defense_break_timer - elapsed)
        self._combo_delay = max(0.0, self._combo_delay - elapsed)
        self._combo_recovery = max(0.0, self._combo_recovery - elapsed)
        if was_broken and not self.defense_broken:
            # 破防结束：抗性回归，骑士立刻重新起手
            self._attack_cooldown = 0.0
            self._reset_combo()
        if self.phase == 2:
            self._special_cooldown = max(0.0, self._special_cooldown - elapsed)
        return super().update(dt, player_position)

    def choose_intent(self, player_position: Position) -> EnemyIntent:
        self.facing = self.direction_to(player_position)
        distance = self.distance_to(player_position)
        if self.defense_broken:
            return EnemyIntent("defense_broken", note="破防：核心暴露")
        # 断忆敕令只在连段收招之后插入，避免把三段弹刀检定从中间打断
        if (
            self.phase == 2
            and not self._combo_active
            and self._special_cooldown <= 0.0
            and self._comboes_since_decree > 0
            and self.attack_ready
        ):
            left_anchor = self.bounds_left + self.body_width / 2
            right_anchor = self.bounds_right - self.body_width / 2
            self.x = max(
                (left_anchor, right_anchor),
                key=lambda anchor: abs(anchor - float(player_position[0])),
            )
            self.velocity_x = 0.0
            self.velocity_y = 0.0
            self.y = self.ground_y
            self.facing = self.direction_to(player_position)
            return EnemyIntent(
                "memory_sever",
                attack=self.scaled_attack(self.execution_profile),
                note="远距瞬移 · 断忆敕令：必须完美弹刀",
            )
        # 两个阶段的常规攻击都是冠冕三裁：破防恢复后不会退回单发横斩
        return self._phase_one_intent(distance)

    def _phase_one_intent(self, distance: float) -> EnemyIntent:
        """常规攻击只有一套冠冕三裁：逼近后连续三次弹刀检定（两个阶段通用）。"""
        if self._combo_active:
            index = min(self._combo_step, self.COMBO_SIZE - 1)
            profile = self.combo_profiles[index]
            if self.attack_ready and self._combo_delay <= 0.0 and distance <= profile.reach:
                return EnemyIntent(
                    "crown_combo",
                    attack=profile,
                    note=f"冠冕三裁 {index + 1}/{self.COMBO_SIZE}",
                )
            return EnemyIntent(
                "royal_advance",
                move_x=self.facing * self._advance_speed,
                note="追击重新起手",
            )
        if (
            self.attack_ready
            and self._combo_recovery <= 0.0
            and distance <= self.COMBO_REACH
        ):
            self._combo_active = True
            self._combo_step = 0
            self._combo_parries = 0
            self._combo_delay = 0.0
            return EnemyIntent(
                "crown_combo",
                attack=self.combo_profiles[0],
                note=f"冠冕三裁 1/{self.COMBO_SIZE}",
            )
        return EnemyIntent(
            "royal_advance",
            move_x=self.facing * self._advance_speed,
            note="持刃迫近",
        )

    def take_damage(
        self,
        amount: int,
        *,
        source_x: float | None = None,
        posture_damage: int = 0,
    ) -> int:
        multiplier = (
            self.BROKEN_DAMAGE_TAKEN
            if self.defense_broken
            else 1.0 - self.DAMAGE_RESISTANCE
        )
        dealt = super().take_damage(
            round(amount * multiplier),
            source_x=source_x,
            posture_damage=posture_damage,
        )
        self._check_phase_two()
        return dealt

    def on_attack_parried(self, profile: AttackProfile, *, perfect: bool) -> int:
        if profile.tag.startswith("boss_combo_"):
            # 连段弹刀不直接掉血：三段全部弹开的回报是击退与破防
            if perfect:
                self._combo_parries += 1
                self.hurt_flash = max(self.hurt_flash, self.HURT_FLASH_TIME * 1.8)
            return 0
        if profile.tag == "boss_memory_sever" and perfect:
            # 弹反冲击波让骑士瘫痪：五秒内减伤失效
            self._reset_combo()
            self._start_defense_break()
            return 0
        return super().on_attack_parried(profile, perfect=perfect)

    def on_attack_resolved(
        self,
        profile: AttackProfile,
        *,
        parried: bool,
    ) -> None:
        if profile.tag == "boss_memory_sever":
            # 处决技的冷却从“结算那一刻”开始算：即使意图被主循环丢弃也不会空转 7 秒
            self._special_cooldown = self.SPECIAL_INTERVAL
            # 放完敕令必须再打完一套连段，才会允许下一次敕令
            self._comboes_since_decree = 0
            return
        if not profile.tag.startswith("boss_combo_") or not self._combo_active:
            return
        self._combo_step += 1
        if self._combo_step < self.COMBO_SIZE:
            # 落点间隔从命中那一刻开始算，保证 0.3 / 0.4 秒的连段节奏
            gap = self.COMBO_IMPACT_GAPS[self._combo_step - 1]
            self._combo_delay = max(0.0, gap - profile.telegraph_time)
            return
        full_parry = self._combo_parries >= self.COMBO_SIZE
        self._reset_combo()
        self._comboes_since_decree += 1
        self._combo_recovery = self.COMBO_RECOVERY
        if full_parry:
            self._enter_defense_break()

    def allows_parry_knockback(self, profile: AttackProfile) -> bool:
        """前两段弹刀不产生击退，只有三段全部弹开时才被震开。"""
        if not profile.tag.startswith("boss_combo_"):
            return True
        return self._combo_parries >= self.COMBO_SIZE

    def _reset_combo(self) -> None:
        self._combo_active = False
        self._combo_step = 0
        self._combo_parries = 0
        self._combo_delay = 0.0

    def _start_defense_break(self) -> None:
        # 破防结束的第一时间就重新起手连段，不额外吃连段恢复时间
        self._combo_recovery = 0.0
        self._defense_break_timer = self.DEFENSE_BREAK_DURATION
        self.enter_vulnerable(self.DEFENSE_BREAK_DURATION)
        self.velocity_y = 0.0
        self.y = self.ground_y

    def _enter_defense_break(self) -> None:
        """三段全弹开：击退后进入破防，并按最大生命结算一次真实伤害。"""
        self._reset_combo()
        self._start_defense_break()
        self.hurt_flash = max(self.hurt_flash, self.HURT_FLASH_TIME * 1.8)
        self.hp = max(
            0,
            self.hp - max(1, round(self.max_hp * self.BREAK_DAMAGE_RATIO)),
        )

    def _check_phase_two(self) -> None:
        if self.phase != 1 or self.hp > self.max_hp * self.PHASE_TWO_THRESHOLD:
            return
        self.phase = 2
        # 一进二阶段立刻放断忆敕令：清掉连段状态并让处决技马上可用
        self._special_cooldown = 0.0
        self._reset_combo()
        self._comboes_since_decree = 1
        self._combo_recovery = 0.0
        if self.defense_broken:
            # 破防期间被打进二阶段：提前结束破防，敕令直接接上
            self._defense_break_timer = 0.0
            self._vulnerable_timer = 0.0


class BrokenBridgeBellKeeper(Enemy):
    """断桥司钟：第二阶段首领。远程散射压制，只有核心暴露时才会受伤。"""

    kind = "broken_bridge_bell_keeper"
    display_name = "断桥司钟"
    base_hp = 520
    base_posture = 140
    speed = 58.0
    bounty_score = 2200
    parry_tutorial = "弹反时钉削减韧性；只有核心暴露时才能造成伤害"
    body_width = 92.0
    body_height = 132.0
    safe_distance = 240.0
    wall_margin = 90.0
    # 核心暴露窗口：韧性归零后才能被打伤，窗口结束韧性回满
    CORE_EXPOSURE_TIME = 4.0
    BURST_SIZE = 3
    # 时钉落点之间的间隔；弹道飞行时间与它相同，因此连发节奏稳定
    BURST_INTERVAL = 0.55
    VOLLEY_COOLDOWN = 1.6
    BREAK_WINDOW = CORE_EXPOSURE_TIME
    # 重装钟体不会被击飞，也不会被剑气推着走
    PARRY_KNOCKBACK_SPEED = 0.0
    PARRY_KNOCKBACK_LIFT = 0.0
    attack_profile = AttackProfile(
        name="时钉散射",
        damage=16,
        reach=1000,
        telegraph_time=BURST_INTERVAL,
        cooldown=0.0,
        parryable=True,
        projectile_speed=780.0,
        posture_damage=18,
        warning_color="ice",
        tag="bell_bullet",
    )
    sweep_profile = AttackProfile(
        name="刻度横扫",
        damage=24,
        reach=96,
        telegraph_time=0.5,
        cooldown=1.7,
        parryable=True,
        posture_damage=24,
        warning_color="ice",
        tag="bell_sweep",
    )

    def __init__(self, x: float, y: float, **kwargs) -> None:
        super().__init__(x, y, **kwargs)
        self._burst_left = 0
        self._burst_delay = 0.0
        # 时钉还在飞的时候不再出手，同时兼作“弹道被剑气斩灭”时的保险丝
        self._bullet_in_flight = 0.0
        self._volley_cooldown = 1.2
        self._core_timer = 0.0

    @property
    def core_exposed(self) -> bool:
        return self._core_timer > 0.0

    @property
    def core_exposure_remaining(self) -> float:
        return self._core_timer

    def update(self, dt: float, player_position: Position) -> EnemyIntent:
        elapsed = max(0.0, dt)
        self._core_timer = max(0.0, self._core_timer - elapsed)
        self._volley_cooldown = max(0.0, self._volley_cooldown - elapsed)
        self._burst_delay = max(0.0, self._burst_delay - elapsed)
        self._bullet_in_flight = max(0.0, self._bullet_in_flight - elapsed)
        if self.core_exposed:
            # 核心暴露期间停火：把输出窗口完整交给玩家
            self._burst_left = 0
            self._volley_cooldown = self.VOLLEY_COOLDOWN
        return super().update(dt, player_position)

    def break_posture(self) -> None:
        """韧性归零：核心暴露，只有这段时间里钟体才会受伤。"""
        self._posture_broken = True
        self.posture = 0
        self._core_timer = self.CORE_EXPOSURE_TIME
        self.enter_vulnerable(self.CORE_EXPOSURE_TIME)

    def apply_knockback(self, direction: int, speed: float, lift: float) -> None:
        """重装钟体：不吃击退与击飞。"""
        return None

    def take_damage(
        self,
        amount: int,
        *,
        source_x: float | None = None,
        posture_damage: int = 0,
    ) -> int:
        if not self.core_exposed:
            # 核心未暴露：攻击只削韧，不掉血
            self.take_posture_damage(posture_damage)
            return 0
        return super().take_damage(
            amount,
            source_x=source_x,
            posture_damage=posture_damage,
        )

    def choose_intent(self, player_position: Position) -> EnemyIntent:
        self.facing = self.direction_to(player_position)
        distance = self.distance_to(player_position)
        if self.core_exposed:
            return EnemyIntent("core_exposed", note="核心暴露")
        if distance < self.safe_distance and self.can_step(-self.facing, self.wall_margin):
            return EnemyIntent(
                "blink_back",
                move_x=-self.facing * self.speed,
                note="维持钟摆节拍距离",
            )
        if self._bullet_in_flight > 0.0:
            return EnemyIntent("channel", note="时钉在飞")
        if distance <= self.sweep_profile.reach and self.attack_ready:
            return EnemyIntent(
                "bell_sweep",
                attack=self.scaled_attack(self.sweep_profile),
                note="刻度横扫",
            )
        if self.attack_ready and distance <= self.attack_profile.reach:
            if self._burst_left <= 0 and self._volley_cooldown <= 0.0:
                self._burst_left = self.BURST_SIZE
            if self._burst_left > 0 and self._burst_delay <= 0.0:
                self._burst_left -= 1
                self._bullet_in_flight = self.attack_profile.telegraph_time + 0.25
                return EnemyIntent(
                    "bell_volley",
                    attack=self.scaled_attack(self.attack_profile),
                    note=(
                        f"时钉散射 "
                        f"{self.BURST_SIZE - self._burst_left}/{self.BURST_SIZE}"
                    ),
                )
        if distance > self.attack_profile.reach:
            return EnemyIntent("advance", move_x=self.facing * self.speed, note="进入射程")
        return EnemyIntent("channel", note="校准钟摆")

    def on_attack_resolved(
        self,
        profile: AttackProfile,
        *,
        parried: bool,
    ) -> None:
        if profile.tag != "bell_bullet":
            return
        self._bullet_in_flight = 0.0
        if self._burst_left > 0:
            # 连发间隔从落点开始算，避免主循环丢帧吃掉一颗时钉
            self._burst_delay = max(0.0, self.BURST_INTERVAL - profile.telegraph_time)
            return
        self._volley_cooldown = self.VOLLEY_COOLDOWN


ENEMY_CLASSES: dict[str, type[Enemy]] = {
    Chaser.kind: Chaser,
    SpearThrower.kind: SpearThrower,
    ShieldGuard.kind: ShieldGuard,
    RiftWorm.kind: RiftWorm,
    ResonanceMage.kind: ResonanceMage,
}

BOSS_CLASSES: dict[str, type[Enemy]] = {
    RustCrownKnight.kind: RustCrownKnight,
    BrokenBridgeBellKeeper.kind: BrokenBridgeBellKeeper,
}
