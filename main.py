from __future__ import annotations

import json
import math
import os
import random
from dataclasses import dataclass
from pathlib import Path

import pygame

from game.audio import AudioManager
from game.entities import (
    BOSS_CLASSES,
    ENEMY_CLASSES,
    AttackProfile,
    BrokenBridgeBellKeeper,
    Chaser,
    Enemy,
    Hitbox,
    Player,
    SpearThrower,
)
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
MELEE_FLASH_LEAD = 0.65
# 远程弹道的可弹刀范围（像素）：子弹进入角色身边这个范围内按下弹刀即成功
PROJECTILE_PARRY_RANGE = 170.0
# 弹开的子弹飞回敌人的速度（像素/秒）
REFLECTED_PROJECTILE_SPEED = 900.0
# 进入关卡后敌人登场延迟（秒）
ENEMY_SPAWN_DELAY = 3.0
# 敌人登场后到第一次出手之间的缓冲（秒）：留出反应时间，避免一刷出来就挨打
ENEMY_SPAWN_ATTACK_GRACE = 1.0
# 同一层里两波敌人之间的等待时间（秒）
WAVE_SPAWN_DELAY = 2.6
# 一波敌人的横向落点范围：均匀铺开，避免叠在同一点
WAVE_SPAWN_START_X = 320.0
WAVE_SPAWN_END_X = 1180.0
WAVE_GROUND_Y = 522.0
# 闪避残影的生成间隔与存在时间
DASH_TRAIL_INTERVAL = 0.035
DASH_TRAIL_LIFE = 0.32
# 存档槽位数量
SAVE_SLOT_COUNT = 6
# 关卡胜利后出现的传送门
PORTAL_WIDTH = 96
PORTAL_HEIGHT = 160
PORTAL_CENTER_X = 1150.0
PORTAL_GROUND_Y = 566.0
PORTAL_APPEAR_TIME = 0.8
PORTAL_ENTER_TIME = 0.75
PORTAL_RETRIGGER_LOCK = 0.6

# -- 角色成长 ---------------------------------------------------------------
# 每升一级提升的生命上限与攻击力
HP_PER_LEVEL = 26
ATTACK_PER_LEVEL = 3
HEAL_TICK_INTERVAL = 10.0

# -- 回响中枢 ---------------------------------------------------------------
# 每个存档的成长拓扑不会因为战斗失败而重置，只有新建/覆盖存档才会清空
DIFFICULTY_THREAT_BONUS = 0.35
DIFFICULTY_RELIC_MULTIPLIER = 1.5

# -- 回响能量 ---------------------------------------------------------------
# 新远征开局清零，换关保留；普通攻击 < 上劈/下劈 < 击败敌人 = 完美弹刀
ECHO_ENERGY_MAX = 100
ENERGY_GAIN_ATTACK = 4
ENERGY_GAIN_HEAVY_ATTACK = 7
ENERGY_GAIN_DEFEAT = 20
ENERGY_GAIN_PARRY = 20
ENERGY_GAIN_REFLECT = 6
# 回响剑气还在场上时不再积攒能量：避免一发剑气滚出下一发
SKILL_WAVE_ENERGY_LOCK = True

# -- 回响剑气 ---------------------------------------------------------------
# 伤害为普通攻击的若干倍，命中后把敌人击飞一段距离。
SKILL_DAMAGE_MULTIPLIER = 3
# 飞行速度与寿命：寿命足够长，保证从画面任意一侧出手都能一路斩到另一侧
SKILL_WAVE_SPEED = 900.0
SKILL_WAVE_LIFE = 1.6
# 收尾淡出时长：这段时间剑气已经飞出画面，横穿全屏期间保持满亮度
SKILL_WAVE_FADE_TIME = 0.22
# 半月外形：比角色（48 x 108）略大一圈
SKILL_WAVE_HALF_HEIGHT = 74.0
SKILL_WAVE_HALF_WIDTH = 22.0
SKILL_WAVE_THICKNESS = 26.0
SKILL_KNOCKBACK_SPEED = 430.0
SKILL_KNOCKBACK_LIFT = 470.0

# -- 战斗表现 ---------------------------------------------------------------
# 敌人被击败后的倒地淡出时长
DEATH_FADE_TIME = 1.1

# -- 关卡难度 ---------------------------------------------------------------
# 每往下一层，敌人的生命与伤害同步提高
FLOOR_THREAT_BASE = 0.12
FLOOR_THREAT_STEP = 0.18

# -- 小怪成长 ---------------------------------------------------------------
# 小怪的层内成长沿用上面的威胁曲线；跨章节再乘一个明显的台阶，
# 于是第一章内部每层小幅提升，进入第二章后小怪会明显更硬、更疼。
NORMAL_ENEMY_STAGE_STEP = 0.6
# 击败敌人获得的经验（按敌人种类），并随层数放大
ENEMY_EXP = {
    "chaser": 24,
    "spear_thrower": 26,
    "shield_guard": 42,
    "rift_worm": 36,
    "resonance_mage": 40,
    "rust_crown_knight": 320,
    "broken_bridge_bell_keeper": 340,
}
FLOOR_EXP_STEP = 0.35

# -- 死亡勘定 ---------------------------------------------------------------
# 失败也会沉淀局外成长，但各表现项分别封顶，避免单一行为无限刷取。
FAILURE_RELIC_CAP = 120
FAILURE_SCORE_RELIC_CAP = 45
FAILURE_FLOOR_RELIC_CAP = 15
FAILURE_COMBO_RELIC_CAP = 20
FAILURE_PARRY_RELIC_CAP = 30

# -- 第一阶段商店与首领 -----------------------------------------------------
SHOP_FLOOR = 4
BOSS_FLOOR = 5
SECOND_STAGE_ROOM_COUNT = 7
SECOND_STAGE_SHOP_ROOM = 6
SECOND_STAGE_BOSS_ROOM = 7
BOSS_MEMORY_SEVER_DAMAGE_RATIO = 0.8

# -- 战时铸币 ---------------------------------------------------------------
# 局内铸币收益整体缩放：战斗、弹刀、事件与清房奖励统一打折结算
RUN_CURRENCY_RATE = 0.65
# 战前整备的回复货品：可以重复购买，价格固定
SHOP_HEAL_ITEM_ID = "coagulant_draught"
SHOP_HEAL_AMOUNT = 60
# 随机事件关的恢复选项：按最大生命比例结算，适配不同成长阶段
EVENT_HEAL_RATIO = 0.4

ROOM_COMBAT = "combat"
ROOM_ELITE = "elite"
ROOM_EVENT = "event"
ROOM_REWARD = "reward"
ROOM_SANCTUARY = "sanctuary"
ROOM_RIFT = "rift"
ROOM_SHOP = "shop"
ROOM_BOSS = "boss"
RANDOM_ROOM_TYPES = (
    ROOM_EVENT,
    ROOM_REWARD,
    ROOM_SANCTUARY,
    ROOM_ELITE,
    ROOM_RIFT,
)


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
class ParryShockwave:
    """弹反冲击波：从角色身上扩散，表现弹刀把首领压回去的那一下。"""

    x: float
    y: float
    remaining: float
    total: float
    radius: float = 150.0
    color: tuple[int, int, int] = (120, 240, 255)
    label: str = ""


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
class DeathFade:
    """被击败的敌人：先倒下再慢慢淡出，而不是立刻从画面消失。"""

    kind: str
    x: float
    y: float
    facing: int
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


@dataclass
class SkillWave:
    """回响剑气：向前平推的竖向半月斩，可反复命中不同敌人。"""

    x: float
    y: float
    facing: int
    damage: int
    posture_damage: int
    remaining: float
    total: float
    hits: set[int]
    speed: float = SKILL_WAVE_SPEED

    @property
    def hitbox(self) -> Hitbox:
        """半月本体的判定框：比角色略大一圈，跟着角色出手的高度走。"""
        return Hitbox(
            self.x - SKILL_WAVE_HALF_WIDTH,
            self.y - SKILL_WAVE_HALF_HEIGHT,
            SKILL_WAVE_HALF_WIDTH * 2,
            SKILL_WAVE_HALF_HEIGHT * 2,
        )

    @property
    def expired(self) -> bool:
        return self.remaining <= 0.0


@dataclass(frozen=True)
class FloorBriefing:
    """进入新一层时弹出的关卡简报。"""

    title: str
    summary: str
    entries: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ProgressionNode:
    node_id: str
    branch: str
    title: str
    prerequisite: str | None
    requirement: str
    cost: int
    effect: str


@dataclass(frozen=True)
class ShopItem:
    item_id: str
    title: str
    cost: int
    description: str
    # 可重复购买（例如战前回复）：不写入“本局已购入”名单
    repeatable: bool = False


@dataclass(frozen=True)
class ProgressionTrack:
    """成长拓扑里的一条小分支：逐级提升，每级都有独立消耗。"""

    track_id: str
    branch: str
    title: str
    effect: str
    values: tuple[float, ...]
    costs: tuple[int, ...]
    unit: str = ""


# 旧版一次性节点表：仅用于把老存档的铭刻进度迁移成新的分级分支，并在
# 旧节点已被新拓扑移除时按原价返还回响遗晶。
LEGACY_PROGRESSION_NODES = (
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
        "edge_tempering",
        "锻刃谱系",
        "锋质淬炼",
        "aftershock_calibration",
        "累计完成 2 次远征结算",
        65,
        "每局基础攻击伤害永久提高 3 点。",
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
        "execution_resonance",
        "锻刃谱系",
        "处决回流",
        "refracted_afterglow",
        "任意一局最高连击达到 12",
        100,
        "战斗房内每 10 秒恢复 8% 最大生命。",
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
        "aerial_memory",
        "共鸣谱系",
        "凌空复写",
        "white_window_record",
        "抵达第 2 层",
        80,
        "解锁二段跳；落地后恢复一次空中跳跃。",
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
        "resonant_reservoir",
        "共鸣谱系",
        "谐振储层",
        "perfect_circuit",
        "累计完成 3 次远征结算",
        100,
        "每层开局保留 20 点回响能量。",
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
        "vital_lattice",
        "远征谱系",
        "生命晶格",
        "route_cartography",
        "累计完成 2 次远征结算",
        60,
        "每局基础生命上限永久提高 40 点。",
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
        "salvage_protocol",
        "远征谱系",
        "残骸协议",
        "vital_lattice",
        "累计完成 4 次远征结算",
        90,
        "击破敌人获得的战时铸币提高 50%。",
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

LEGACY_NODE_COSTS = {node.node_id: node.cost for node in LEGACY_PROGRESSION_NODES}


PROGRESSION_BRANCHES = (
    "基元谱系",
    "机制谱系",
    "铸币谱系",
)

# 成长拓扑：三条谱系各自包含若干分级分支，每级消耗与收益都写在分支上。
PROGRESSION_TRACKS = (
    # -- 基元谱系：直接提升基础数值 ---------------------------------------
    ProgressionTrack(
        "vital_lattice",
        "基元谱系",
        "生命晶格",
        "每局生命上限提高 {value} 点。",
        (100, 200, 300, 400, 500),
        (20, 40, 80, 160, 320),
        "点生命",
    ),
    ProgressionTrack(
        "edge_tempering",
        "基元谱系",
        "锋刃淬炼",
        "每局攻击力提高 {value} 点。",
        (5, 10, 15, 20, 25),
        (30, 60, 120, 240, 480),
        "点攻击",
    ),
    ProgressionTrack(
        "resonance_amplifier",
        "基元谱系",
        "谐振增幅",
        "回响剑气伤害提高 {value}%。",
        (10, 20, 30, 40, 50),
        (30, 60, 120, 240, 480),
        "% 剑气伤害",
    ),
    # -- 机制谱系：解锁动作与自动恢复 -------------------------------------
    ProgressionTrack(
        "shadow_dash",
        "机制谱系",
        "疾影闪避",
        "解锁闪避冲刺：瞬间位移并获得短暂无敌。",
        (1,),
        (60,),
    ),
    ProgressionTrack(
        "aerial_memory",
        "机制谱系",
        "凌空复写",
        "解锁二段跳：滞空时可以再跳一次。",
        (1,),
        (80,),
    ),
    ProgressionTrack(
        "vital_regeneration",
        "机制谱系",
        "生命自愈",
        "战斗房内每 10 秒恢复 {value} 点生命。",
        (3, 6, 9, 12, 15),
        (50, 90, 150, 230, 340),
        "点/10秒",
    ),
    ProgressionTrack(
        "resonance_reflux",
        "机制谱系",
        "谐振回流",
        "战斗中每秒恢复 {value} 点回响能量。",
        (1, 2, 3, 4, 5),
        (60, 110, 180, 260, 360),
        "点/秒",
    ),
    # -- 铸币谱系：战时铸币与难度抉择 -------------------------------------
    ProgressionTrack(
        "reserve_carry",
        "铸币谱系",
        "开局行囊",
        "每局开局获得 {value} 枚战时铸币。",
        (5, 10, 15, 20, 25),
        (30, 60, 110, 180, 260),
        "枚铸币",
    ),
    ProgressionTrack(
        "salvage_protocol",
        "铸币谱系",
        "战利议价",
        "击败敌人获得的战时铸币提高 {value}%。",
        (5, 10, 15, 20, 25),
        (30, 60, 110, 180, 260),
        "% 铸币",
    ),
    ProgressionTrack(
        "risk_covenant",
        "铸币谱系",
        "风险契约",
        "开局前可选择「高压远征」：敌人更强，但回响遗晶收益更高。",
        (1,),
        (120,),
    ),
)

# 旧节点 → 新分支的对应关系；不在表里的旧节点会被移除并返还遗晶。
LEGACY_NODE_TRACKS = {
    "vital_lattice": "vital_lattice",
    "edge_tempering": "edge_tempering",
    "aerial_memory": "aerial_memory",
    "reserve_carry": "reserve_carry",
    "salvage_protocol": "salvage_protocol",
    "risk_covenant": "risk_covenant",
}


# 第一阶段前三层为三波常规战，第五层为区域首领战。
FLOOR_WAVE_PLANS: dict[int, tuple[tuple[str, ...], ...]] = {
    1: (
        ("chaser", "spear_thrower"),
        ("chaser", "spear_thrower", "spear_thrower"),
        ("chaser", "chaser", "spear_thrower", "spear_thrower"),
    ),
    2: (
        ("shield_guard", "spear_thrower"),
        ("shield_guard", "chaser", "spear_thrower"),
        (
            "shield_guard",
            "chaser",
            "chaser",
            "spear_thrower",
            "spear_thrower",
        ),
    ),
    3: (
        ("shield_guard", "rift_worm"),
        ("rift_worm", "rift_worm", "chaser"),
        ("shield_guard", "rift_worm", "resonance_mage"),
    ),
    5: (("rust_crown_knight",),),
}

# 第二阶段共七关；第二关的实际类型由路线种子决定，六、七关固定为商店和首领。
SECOND_STAGE_WAVE_PLANS: dict[int, tuple[tuple[str, ...], ...]] = {
    1: (
        ("shield_guard", "rift_worm", "spear_thrower", "chaser"),
        ("chaser", "resonance_mage", "rift_worm", "spear_thrower", "chaser"),
        ("shield_guard", "rift_worm", "resonance_mage", "chaser", "spear_thrower"),
    ),
    3: (
        ("shield_guard", "shield_guard", "resonance_mage", "spear_thrower"),
        ("rift_worm", "chaser", "chaser", "spear_thrower", "resonance_mage"),
        ("shield_guard", "rift_worm", "resonance_mage", "chaser", "spear_thrower"),
    ),
    4: (
        ("shield_guard", "resonance_mage", "resonance_mage", "spear_thrower"),
        ("rift_worm", "rift_worm", "shield_guard", "chaser", "resonance_mage"),
        ("shield_guard", "rift_worm", "resonance_mage", "chaser", "spear_thrower"),
    ),
    7: (("broken_bridge_bell_keeper",),),
}

SHOP_ITEMS = (
    ShopItem("repair_infusion", "晶格护层", 16, "本次远征最大生命提高 25，不恢复生命。"),
    ShopItem("edge_plating", "锋刃镀层", 28, "本次远征攻击力永久提高 4 点。"),
    ShopItem("vital_expansion", "晶格扩容", 34, "本次远征最大生命提高 45，不恢复生命。"),
    ShopItem("resonance_cell", "谐振电池", 20, "立即补充 45 点回响能量。"),
    ShopItem(
        SHOP_HEAL_ITEM_ID,
        "凝血汤剂",
        18,
        "立即恢复 60 点生命，可重复购买。",
        repeatable=True,
    ),
)

# 每层的关卡简报：介绍本层首次登场的敌人及其攻击特点
FLOOR_BRIEFINGS: dict[int, FloorBriefing] = {
    1: FloorBriefing(
        "锈蚀中庭",
        "灰塔外围的巡逻残响，攻击节奏直来直去，适合熟悉弹刀。",
        (
            (
                "追击者",
                "近身三连斩：贴身挥出三段连斩，起手只有 0.28 秒。"
                "等待金色闪光亮起再弹刀，可以完美反震。",
            ),
            (
                "投矛手",
                "可反射长矛：与你拉开距离后投出长矛，出手前摇 0.42 秒。"
                "长矛属于可弹反的飞行物，弹回去会直接打在它自己身上。",
            ),
        ),
    ),
    2: FloorBriefing(
        "镜面回廊",
        "重甲与长矛开始协同推进，正面硬顶会吃亏。",
        (
            (
                "盾卫",
                "盾击：血厚韧高，正面来袭的伤害会被盾牌削减到 35%，"
                "但会额外承受削韧。绕到背后攻击，或先打空韧性制造破绽。",
            ),
            (
                "组合压力",
                "盾卫负责正面顶住，追击者贴身压制，投矛手在远处消耗。"
                "优先弹反长矛清掉后排，再处理盾卫的正面推进。",
            ),
        ),
    ),
    3: FloorBriefing(
        "裂隙深庭",
        "裂隙能量渗入回廊，出现无法弹反的突进。",
        (
            (
                "裂隙虫",
                "裂隙突进：唯一不可弹反的攻击，紫色扇形提示，"
                "冲刺速度是平时的 1.65 倍。只能闪避或用走位躲开。",
            ),
            (
                "共鸣法师",
                "延迟能量球：预警长达 0.65 秒，弹道很慢但射程极远，"
                "离得远会主动贴近，把你逼到墙角则就地施法。"
                "看准弹道靠近后弹刀，可以把能量球原路打回去。",
            ),
        ),
    ),
    4: FloorBriefing(
        "余烬行商驿站",
        "战时铸币在此获得用途；整备完成后可直接前往区域执政者所在层。",
        (
            (
                "灰烬行商",
                "可购买锋刃强化、生命扩容、能量补给与凝血汤剂。强化类货品每次远征限购一次，"
                "凝血汤剂可以重复购买，也可以不消费直接离开。",
            ),
            (
                "战前整备",
                "购买的攻击与生命强化会保留至第五层首领战；离开柜台后回响之门开启。",
            ),
        ),
    ),
    5: FloorBriefing(
        "锈冠王庭",
        "第一阶段终点：锈冠骑士全阶段减免 80% 伤害，破防窗口才是真正的输出期。",
        (
            (
                "第一阶段 · 王庭残仪",
                "骑士连续挥出三段冠冕三裁：每段弹刀窗口 0.4 秒，落点间隔 0.3 / 0.4 秒。"
                "三段全部弹开才会被击退破防，漏掉的每一段会造成 120 点伤害。",
            ),
            (
                "破防 · 核心暴露",
                "破防瞬间骑士承受最大生命 10% 的伤害，并在 5 秒内失去全部减伤；"
                "这段时间结束后抗性回归，骑士会立刻重新起手。",
            ),
            (
                "第二阶段 · 熔锈誓约",
                "生命低于 50% 后骑士约每 7 秒瞬移至远端发动断忆敕令：弹刀窗口更短，"
                "未完美弹刀会失去 80% 当前生命；成功则以弹反冲击波令其瘫痪 5 秒并失去减伤。",
            ),
        ),
    ),
}

ROOM_TYPE_BRIEFINGS: dict[str, FloorBriefing] = {
    ROOM_ELITE: FloorBriefing(
        "赤印精英庭",
        "高威胁敌群获得额外生命与攻击修正，击破后可取得更多战时铸币。",
        (
            ("精英契印", "敌群威胁额外提高 20%，编成会混合前后排与不可弹反攻击。"),
            ("讨伐酬赏", "清空全部波次后额外获得一批战时铸币。"),
        ),
    ),
    ROOM_EVENT: FloorBriefing(
        "失真记忆事件",
        "本关没有强制战斗；读取残留记忆，并在四项不可撤销的结果中选择其一。",
        (
            (
                "记忆抉择",
                "选择铸币、回响能量、恢复生命，或以生命换取本局攻击强化。",
            ),
            ("一次勘定", "结果确认后立即写入暂存，重新进入关卡不能重复领取。"),
        ),
    ),
    ROOM_REWARD: FloorBriefing(
        "遗珍回廊",
        "稳定的回响遗珍悬浮于回廊中，可从三种本局强化中选择一种。",
        (
            ("锋刃遗珍", "本次远征攻击力提高 3 点。"),
            ("生命遗珍", "最大生命提高 35 点，但不恢复当前生命。"),
        ),
    ),
    ROOM_SANCTUARY: FloorBriefing(
        "静滞庇护所",
        "安全区室允许进行一次整备，不会生成敌人。",
        (
            ("静滞扩容", "最大生命提高 25 点，但不恢复当前生命。"),
            ("谐振整备", "补满回响能量，或放弃整备换取战时铸币。"),
        ),
    ),
    ROOM_RIFT: FloorBriefing(
        "紊乱裂隙",
        "裂隙会随机拼接高压敌群，威胁更高，但清理后获得额外铸币。",
        (
            ("未知编成", "敌群从第二阶段战斗池中重组，威胁额外提高 30%。"),
            ("裂隙溢价", "清空房间后额外获得一批战时铸币。"),
        ),
    ),
    ROOM_SHOP: FloorBriefing(
        "余烬行商驿站",
        "第二阶段第六关固定为整备商店，可为最终首领战补充资源。",
        (
            (
                "区域行商",
                "生命上限、攻击与能量货品每件限购一次；凝血汤剂可重复购买，用于战前回复。",
            ),
            ("最终整备", "不消费也可离开；离店后直接开启第七关入口。"),
        ),
    ),
    ROOM_BOSS: FloorBriefing(
        "断桥钟楼",
        "第二阶段第七关：断桥司钟以时钉散射压制，核心未暴露时不受任何伤害。",
        (
            (
                "时钉散射",
                "钟体一次连续射出三枚时钉，可逐发弹刀反弹；玩家贴身时改用刻度横扫。",
            ),
            (
                "核心暴露",
                "只有削空韧性才能打伤钟体：核心暴露 4 秒且钟体停火，窗口结束后韧性回满。",
            ),
        ),
    ),
}


class AssetStore:
    def __init__(self) -> None:
        self.background = self._load("title_background.png", alpha=False)
        self.logo = self._load("logo_emblem.png")
        self.player = self._load("player_idle.png")
        self.panel = self._load("menu_panel.png")
        self.cursor = self._load("menu_cursor.png")
        self.spark = self._load("parry_spark.png")
        # 大厅三个入口各用一张独立图标：中枢、城门与排行不再共用同一张图
        self.room_gate = self._load_optional("room_gate.png")
        self.echo_shard = self._load_optional("echo_shard.png")
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
        self.expedition_choice_selected = 0
        self.keybind_selected = 0
        self.rebinding_action: str | None = None
        self.confirm_exit = False
        self.pressed_item: int | None = None
        self.pressed_button: str | None = None
        self.pressed_keys: set[int] = set()
        self.tutorial_steps: list[TutorialStep] = []
        self.tutorial_index = 0
        self.lobby_selected = 0
        self.progression_selected = 0
        self.progression_collapsed = {
            branch: branch != PROGRESSION_BRANCHES[0]
            for branch in PROGRESSION_BRANCHES
        }
        self.is_tutorial_run = False

        # 存档：设置全局共享，六个槽位各自保存一份独立的远征档案
        self.save_store = self._load_store()
        self.save_slots = self._load_slots()
        self.active_slot: int | None = None
        self.profile: dict = {}
        self.slot_mode = "new"
        self.slot_selected = 0
        self.slot_confirm_index: int | None = None
        self.has_save = any(slot is not None for slot in self.save_slots)

        saved_settings = self.save_store.get("settings", {})
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
        self.items = self._build_items()
        self.selected = next(
            (index for index, item in enumerate(self.items) if item.enabled),
            0,
        )

        self.run_floor = 1
        self.run_stage = 1
        self.run_route_seed = 0
        self.room_type = ROOM_COMBAT
        self.room_resolved = False
        self.room_choice_selected = 0
        self.run_score = 0
        self.run_combo = 0
        self.run_max_combo = 0
        self.run_parries = 0
        self.run_kills = 0
        self.run_currency = 0
        # 铸币缩放产生的零头：攒够 1 枚再结算，避免每次收益都被向下取整吃掉
        self._currency_pool = 0.0
        self.run_shop_attack_bonus = 0
        self.run_shop_hp_bonus = 0
        self.shop_selected = 0
        self.shop_purchased: set[str] = set()
        self.shop_closed = True
        self.player = Player(230, 566)
        self._attack_hits: set[tuple[int, int]] = set()
        self._defeated_enemies: set[int] = set()
        self.death_fades: list[DeathFade] = []
        self._death_fade_ids: set[int] = set()
        self._flash_cache: dict[tuple[str, int], pygame.Surface] = {}
        self.room_enemies: list[Enemy] = []
        self.pending_enemy_attacks: list[PendingEnemyAttack] = []
        self.attack_impacts: list[AttackImpact] = []
        self.shockwaves: list[ParryShockwave] = []
        self.dash_trails: list[DashTrail] = []
        self._dash_trail_timer = 0.0
        self._dash_was_active = False
        self._trail_surface_cache: dict[tuple[str, int], pygame.Surface] = {}
        self.reflected_projectiles: list[ReflectedProjectile] = []
        self.pending_spawn: list[Enemy] = []
        self.enemy_spawn_timer = 0.0
        # 波次：本层完整的刷怪编成、已经排到第几波、倒计时面板用的总量与文案
        self.wave_plan: list[list[Enemy]] = []
        self.wave_index = 0
        self.spawn_countdown_total = ENEMY_SPAWN_DELAY
        self.spawn_countdown_label = "敌影接近"
        self.run_threat = FLOOR_THREAT_BASE
        # 成长与回响能量
        self.player_level = 1
        self.player_exp = 0
        self.echo_energy = 0
        self.skill_waves: list[SkillWave] = []
        self._skill_wave_spawned = False
        self.portal_open = False
        self.portal_appear = 0.0
        self.portal_enter_timer = 0.0
        self.portal_lock_timer = 0.0
        self.portal_choice_index = 0
        # 进入关卡的过场动画：漩涡 → 黑屏 → 圆形展开
        self.transition: dict | None = None
        # 风险契约：本局是否选择了「高压远征」
        self.run_difficulty_hard = False
        self.difficulty_selected = 0
        # 本局成长数值：技能树提供的开局加成与自动恢复
        self.skill_damage_scale = 1.0
        self.auto_heal_per_second = 0.0
        self.auto_energy_per_second = 0.0
        self._auto_heal_pool = 0.0
        self._auto_energy_pool = 0.0
        self.run_kills = 0
        self.result_score = 0
        self.result_new_record = False
        self.result_cleared = False
        self.result_relics = 0
        self.result_relic_breakdown: list[tuple[str, int]] = []

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

    @staticmethod
    def _new_profile() -> dict:
        """一份全新的档案：等级、成长树与关卡进度都从头开始。"""
        return {
            "version": 2,
            "best_score": 0,
            "best_stage": 0,
            "best_floor": 0,
            "scores": [],
            "tutorial_completed": False,
            "echo_relics": 0,
            "progression": {
                "version": 2,
                "levels": {},
                "equipped_start_module": None,
            },
            "lifetime_stats": {},
            "active_run": None,
        }

    @staticmethod
    def _normalise_run_checkpoint(data: object) -> dict | None:
        """Validate a temporary expedition checkpoint from disk."""
        if not isinstance(data, dict) or data.get("status") != "active":
            return None

        def number(name: str, default: int, lower: int, upper: int) -> int:
            try:
                value = int(data.get(name, default) or 0)
            except (TypeError, ValueError):
                value = default
            return max(lower, min(upper, value))

        stage = number("stage", 1, 1, 99)
        max_room = BOSS_FLOOR if stage == 1 else SECOND_STAGE_ROOM_COUNT
        floor = number("floor", 1, 1, max_room)
        route_seed = number("route_seed", 0, 0, 2147483647)
        room_type = StartScreen._room_type_for(
            stage,
            floor,
            route_seed,
            data.get("room_type"),
        )
        player_hp = number("player_hp", 1, 0, 999999)
        if player_hp <= 0:
            return None
        purchased = data.get("shop_purchased", [])
        valid_shop_items = {item.item_id for item in SHOP_ITEMS}
        if not isinstance(purchased, list):
            purchased = []
        return {
            "version": 2,
            "status": "active",
            "stage": stage,
            "floor": floor,
            "route_seed": route_seed,
            "room_type": room_type,
            "room_resolved": bool(data.get("room_resolved", False)),
            "run_score": number("run_score", 0, 0, 999999999),
            "run_combo": number("run_combo", 0, 0, 999999),
            "run_max_combo": number("run_max_combo", 0, 0, 999999),
            "run_parries": number("run_parries", 0, 0, 999999),
            "run_kills": number("run_kills", 0, 0, 999999),
            "run_currency": number("run_currency", 0, 0, 999999),
            "player_level": number("player_level", 1, 1, 999),
            "player_exp": number("player_exp", 0, 0, 999999),
            "player_hp": player_hp,
            "echo_energy": number("echo_energy", 0, 0, ECHO_ENERGY_MAX),
            "shop_attack_bonus": number("shop_attack_bonus", 0, 0, 9999),
            "shop_hp_bonus": number("shop_hp_bonus", 0, 0, 99999),
            "shop_purchased": sorted(
                {
                    item_id
                    for item_id in purchased
                    if isinstance(item_id, str) and item_id in valid_shop_items
                }
            ),
            "shop_closed": bool(
                data.get(
                    "shop_closed",
                    room_type != ROOM_SHOP,
                )
            ),
            "hard_mode": bool(data.get("hard_mode", False)),
        }

    @staticmethod
    def _normalise_profile(data: dict) -> dict:
        """补全缺失字段，保证旧档案也能直接读。"""
        profile = dict(data)
        profile.pop("settings", None)
        raw_echoes = profile.get(
            "echo_relics",
            profile.get("echo_tokens", profile.get("permanent_memory", 0)),
        )
        try:
            echoes = int(raw_echoes or 0)
        except (TypeError, ValueError):
            echoes = 0
        profile["echo_relics"] = max(0, echoes)
        if not isinstance(profile.get("progression"), dict):
            profile["progression"] = {
                "version": 2,
                "levels": {},
                "equipped_start_module": None,
            }
        if not isinstance(profile.get("lifetime_stats"), dict):
            profile["lifetime_stats"] = {}
        if not isinstance(profile.get("scores"), list):
            profile["scores"] = []
        try:
            profile["best_stage"] = max(0, int(profile.get("best_stage", 0) or 0))
        except (TypeError, ValueError):
            profile["best_stage"] = 0
        if profile["best_stage"] == 0 and int(profile.get("best_floor", 0) or 0) > 0:
            profile["best_stage"] = 1
        profile["active_run"] = StartScreen._normalise_run_checkpoint(
            profile.get("active_run")
        )
        profile["progression"] = StartScreen._migrate_progression(profile)
        return profile

    def _load_store(self) -> dict:
        if not SAVE_FILE.exists():
            return {}
        try:
            data = json.loads(SAVE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _migrate_legacy_profile(self) -> dict | None:
        """把旧版单档案格式迁移到 1 号槽，避免玩家进度凭空消失。"""
        legacy_keys = (
            "best_score",
            "best_stage",
            "best_floor",
            "tutorial_completed",
            "echo_relics",
            "progression",
        )
        if not any(key in self.save_store for key in legacy_keys):
            return None
        profile = self._new_profile()
        for key in (
            "best_score",
            "best_stage",
            "best_floor",
            "scores",
            "tutorial_completed",
            "echo_relics",
            "progression",
            "lifetime_stats",
            "active_run",
        ):
            if key in self.save_store:
                profile[key] = self.save_store[key]
        return self._normalise_profile(profile)

    def _load_slots(self) -> list[dict | None]:
        raw = self.save_store.get("slots")
        if not isinstance(raw, list):
            legacy = self._migrate_legacy_profile()
            return (
                [legacy] + [None] * (SAVE_SLOT_COUNT - 1)
                if legacy
                else [None] * SAVE_SLOT_COUNT
            )
        slots: list[dict | None] = []
        for index in range(SAVE_SLOT_COUNT):
            entry = raw[index] if index < len(raw) else None
            slots.append(
                self._normalise_profile(entry) if isinstance(entry, dict) else None
            )
        return slots

    @property
    def tutorial_completed(self) -> bool:
        return bool(self.profile.get("tutorial_completed", False))

    @property
    def echo_relics(self) -> int:
        return max(0, int(self.profile.get("echo_relics", 0) or 0))

    def _progression(self) -> dict:
        progression = self.profile.get("progression", {})
        return progression if isinstance(progression, dict) else {}

    @staticmethod
    def _migrate_progression(profile: dict) -> dict:
        """把旧版一次性节点折叠成新拓扑的分级进度。"""
        raw = profile.get("progression")
        progression = raw if isinstance(raw, dict) else {}
        legacy_version = int(progression.get("version", 1) or 1)

        levels: dict[str, int] = {}
        stored = progression.get("levels")
        for track in PROGRESSION_TRACKS:
            value = 0
            if isinstance(stored, dict):
                try:
                    value = int(stored.get(track.track_id, 0) or 0)
                except (TypeError, ValueError):
                    value = 0
            levels[track.track_id] = max(0, min(len(track.values), value))

        refund = 0
        legacy_nodes = progression.get("unlocked_nodes")
        if legacy_version < 2 and isinstance(legacy_nodes, list):
            for node_id in legacy_nodes:
                if not isinstance(node_id, str):
                    continue
                track_id = LEGACY_NODE_TRACKS.get(node_id)
                if track_id is None:
                    refund += LEGACY_NODE_COSTS.get(node_id, 0)
                    continue
                levels[track_id] = max(1, levels.get(track_id, 0))
            if refund:
                # 被移除的旧节点按原价返还，避免玩家的遗晶凭空消失
                current = int(profile.get("echo_relics", 0) or 0)
                profile["echo_relics"] = max(0, current) + refund

        return {
            "version": 2,
            "levels": levels,
            "equipped_start_module": progression.get("equipped_start_module"),
            "migration_refund": refund,
        }

    def _track_levels(self) -> dict[str, int]:
        levels = self._progression().get("levels")
        if not isinstance(levels, dict):
            return {}
        result: dict[str, int] = {}
        for track in PROGRESSION_TRACKS:
            try:
                result[track.track_id] = int(levels.get(track.track_id, 0) or 0)
            except (TypeError, ValueError):
                result[track.track_id] = 0
        return result

    def _track_level(self, track_id: str) -> int:
        return self._track_levels().get(track_id, 0)

    def _track_value(self, track_id: str, level: int | None = None) -> float:
        """分支在当前等级下的数值；没点过就是 0。"""
        for track in PROGRESSION_TRACKS:
            if track.track_id != track_id:
                continue
            current = self._track_level(track_id) if level is None else level
            if current <= 0:
                return 0.0
            return float(track.values[min(current, len(track.values)) - 1])
        return 0.0

    def _track_unlocked(self, track_id: str) -> bool:
        return self._track_level(track_id) > 0

    def _stat(self, name: str) -> int:
        stats = self.profile.get("lifetime_stats", {})
        if not isinstance(stats, dict):
            return 0
        return max(0, int(stats.get(name, 0) or 0))

    def _active_run_checkpoint(self) -> dict | None:
        return self._normalise_run_checkpoint(self.profile.get("active_run"))

    def _build_run_checkpoint(self) -> dict:
        return {
            "version": 2,
            "status": "active",
            "stage": self.run_stage,
            "floor": self.run_floor,
            "route_seed": self.run_route_seed,
            "room_type": self.room_type,
            "room_resolved": self.room_resolved,
            "run_score": self.run_score,
            "run_combo": self.run_combo,
            "run_max_combo": self.run_max_combo,
            "run_parries": self.run_parries,
            "run_kills": self.run_kills,
            "run_currency": self.run_currency,
            "player_level": self.player_level,
            "player_exp": self.player_exp,
            "player_hp": max(0, self.player.hp),
            "echo_energy": self.echo_energy,
            "shop_attack_bonus": self.run_shop_attack_bonus,
            "shop_hp_bonus": self.run_shop_hp_bonus,
            "shop_purchased": sorted(self.shop_purchased),
            "shop_closed": self.shop_closed,
            "hard_mode": self.run_difficulty_hard,
        }

    def _save_run_checkpoint(self) -> None:
        """Persist the current floor checkpoint for the active save slot."""
        if self.is_tutorial_run:
            return
        self.profile["active_run"] = self._build_run_checkpoint()
        self._save_profile()

    def _clear_run_checkpoint(self) -> None:
        self.profile["active_run"] = None

    def _resume_run_checkpoint(self, checkpoint: object) -> bool:
        saved = self._normalise_run_checkpoint(checkpoint)
        if saved is None:
            return False

        self._start_run(
            saved["floor"],
            tutorial=False,
            stage=saved["stage"],
            room_type=saved["room_type"],
            route_seed=saved["route_seed"],
        )
        self.run_score = saved["run_score"]
        self.run_combo = saved["run_combo"]
        self.run_max_combo = max(saved["run_max_combo"], self.run_combo)
        self.run_parries = saved["run_parries"]
        self.run_kills = saved["run_kills"]
        self.run_currency = saved["run_currency"]
        self._currency_pool = 0.0
        self.player_level = saved["player_level"]
        self.player_exp = min(saved["player_exp"], self.exp_to_next - 1)
        self.run_shop_attack_bonus = saved["shop_attack_bonus"]
        self.run_shop_hp_bonus = saved["shop_hp_bonus"]
        self.shop_purchased = set(saved["shop_purchased"])
        self.shop_closed = saved["shop_closed"] if self._is_shop_room() else True
        self.room_resolved = saved["room_resolved"]
        self.run_difficulty_hard = saved["hard_mode"]
        self.run_threat = self._floor_threat(self.run_floor, self.run_stage) + (
            DIFFICULTY_THREAT_BONUS if self.run_difficulty_hard else 0.0
        )
        if self.room_type == ROOM_ELITE:
            self.run_threat += 0.2
        elif self.room_type == ROOM_RIFT:
            self.run_threat += 0.3

        gained_levels = max(0, self.player_level - 1)
        self.player.max_hp += self.run_shop_hp_bonus + gained_levels * HP_PER_LEVEL
        self.player.attack_bonus += (
            self.run_shop_attack_bonus + gained_levels * ATTACK_PER_LEVEL
        )
        self.player.hp = min(saved["player_hp"], self.player.max_hp)
        self.echo_energy = saved["echo_energy"]
        self._save_run_checkpoint()
        return True

    def _start_or_resume_expedition(self) -> None:
        checkpoint = self._active_run_checkpoint()
        if checkpoint is not None and self._resume_run_checkpoint(checkpoint):
            self._notify(
                f"已读取暂存进度：从第 {self.run_stage} 阶段"
                f"第 {self.run_floor} 关继续远征"
            )
            return
        # 一局 = 从第一层打到失败或通关，所以新远征永远从第一层开始
        self._clear_run_checkpoint()
        self._start_run(1, tutorial=False)
        self._save_run_checkpoint()
        self._notify("未发现暂存进度：从第一层第一关开始新远征")

    @staticmethod
    def _default_keybinds() -> dict[str, int]:
        return {
            "left": pygame.K_a,
            "right": pygame.K_d,
            "attack": pygame.K_j,
            "parry": pygame.K_k,
            "dash": pygame.K_l,
            "jump": pygame.K_SPACE,
            "skill": pygame.K_u,
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

    def _profile_snapshot(self) -> dict:
        """把当前档案整理成可写入存档文件的结构（设置单独存放）。"""
        return {
            "version": 2,
            "best_score": int(self.profile.get("best_score", 0) or 0),
            "best_stage": int(self.profile.get("best_stage", 0) or 0),
            "best_floor": int(self.profile.get("best_floor", 0) or 0),
            "scores": self.profile.get("scores", []),
            "tutorial_completed": bool(
                self.profile.get("tutorial_completed", False)
            ),
            "echo_relics": self.echo_relics,
            "progression": self._progression(),
            "lifetime_stats": self.profile.get("lifetime_stats", {}),
            "active_run": self._normalise_run_checkpoint(
                self.profile.get("active_run")
            ),
        }

    def _write_store(self) -> None:
        data = {
            "version": 3,
            "active_slot": self.active_slot,
            "settings": {**self.settings, "keybinds": self.keybinds.copy()},
            "slots": self.save_slots,
        }
        try:
            SAVE_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self.save_store = data
        except OSError:
            self._notify("设置无法保存，请检查文件权限")

    def _save_settings(self) -> None:
        """设置是全局的：还没选槽位时也能保存。"""
        self._write_store()

    def _save_profile(self) -> None:
        """把当前档案写回槽位。未选槽位时回落到 1 号槽，避免进度静默丢失。"""
        slot = self.active_slot if self.active_slot is not None else 0
        self.profile = self._profile_snapshot()
        self.save_slots[slot] = self.profile
        self.active_slot = slot
        self.has_save = True
        self.items = self._build_items()
        self._write_store()

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
        self._save_settings()
        self._notify(f"音量 {self.settings['volume']}%")

    def _handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                if self.page == "game" and not self.is_tutorial_run:
                    self._save_run_checkpoint()
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
                    self._save_settings()
                    self._notify(f"{action_name} 已绑定为 {self._key_name(key)}")
                return
            if key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                self._close_overlay()
            elif key in (pygame.K_UP, pygame.K_w):
                self.keybind_selected = (
                    self.keybind_selected - 1
                ) % (len(self._keybind_actions()) + 1)
            elif key in (pygame.K_DOWN, pygame.K_s):
                self.keybind_selected = (
                    self.keybind_selected + 1
                ) % (len(self._keybind_actions()) + 1)
            elif key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_j):
                if self.keybind_selected >= len(self._keybind_actions()):
                    self._close_overlay()
                else:
                    self.rebinding_action = self._keybind_actions()[self.keybind_selected][0]
                    self._notify("请按下新的键位，Esc 取消")
            return

        if self.overlay == "settings":
            if key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                self._close_overlay()
            elif key in (pygame.K_UP, pygame.K_w):
                self.overlay_selected = (self.overlay_selected - 1) % 7
            elif key in (pygame.K_DOWN, pygame.K_s):
                self.overlay_selected = (self.overlay_selected + 1) % 7
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

        if self.overlay == "expedition_choice":
            if key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                self._close_overlay()
            elif key in (
                pygame.K_LEFT,
                pygame.K_a,
                pygame.K_UP,
                pygame.K_w,
                pygame.K_RIGHT,
                pygame.K_d,
                pygame.K_DOWN,
                pygame.K_s,
            ):
                self.expedition_choice_selected = 1 - self.expedition_choice_selected
            elif key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_j):
                self._activate_expedition_choice(self.expedition_choice_selected)
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
                self._move_progression_selection(-1)
            elif key in (pygame.K_DOWN, pygame.K_s):
                self._move_progression_selection(1)
            elif key in (pygame.K_LEFT, pygame.K_a):
                self._switch_progression_branch(-1)
            elif key in (pygame.K_RIGHT, pygame.K_d):
                self._switch_progression_branch(1)
            elif key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_j):
                self._upgrade_track(self.progression_selected)
            return

        if self.overlay == "difficulty":
            if key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                self._close_overlay()
            elif key in (pygame.K_LEFT, pygame.K_a, pygame.K_RIGHT, pygame.K_d):
                self.difficulty_selected = 1 - self.difficulty_selected
            elif key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_j):
                self._confirm_difficulty(self.difficulty_selected)
            return

        if self.overlay == "room_event":
            choice_count = len(self._room_event_choices())
            if key in (pygame.K_UP, pygame.K_w):
                self.room_choice_selected = (self.room_choice_selected - 1) % choice_count
            elif key in (pygame.K_DOWN, pygame.K_s):
                self.room_choice_selected = (self.room_choice_selected + 1) % choice_count
            elif key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_j):
                self._resolve_room_event(self.room_choice_selected)
            return

        if self.overlay == "shop":
            if key in (pygame.K_UP, pygame.K_w):
                self.shop_selected = (self.shop_selected - 1) % (len(SHOP_ITEMS) + 1)
            elif key in (pygame.K_DOWN, pygame.K_s):
                self.shop_selected = (self.shop_selected + 1) % (len(SHOP_ITEMS) + 1)
            elif key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_j):
                if self.shop_selected == len(SHOP_ITEMS):
                    self._leave_shop()
                else:
                    self._purchase_shop_item(self.shop_selected)
            elif key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                self._leave_shop()
            return

        if self.overlay == "floor_intro":
            if key in (
                pygame.K_RETURN,
                pygame.K_SPACE,
                pygame.K_ESCAPE,
                pygame.K_j,
                pygame.K_KP_ENTER,
            ):
                self._dismiss_floor_intro()
            return

        if self.overlay == "slots":
            if key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                self.slot_confirm_index = None
                self._close_overlay()
            elif key in (pygame.K_UP, pygame.K_w):
                self.slot_selected = (self.slot_selected - 1) % SAVE_SLOT_COUNT
                self.slot_confirm_index = None
            elif key in (pygame.K_DOWN, pygame.K_s):
                self.slot_selected = (self.slot_selected + 1) % SAVE_SLOT_COUNT
                self.slot_confirm_index = None
            elif key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_j):
                self._activate_slot(self.slot_selected)
            return

        if self.page == "game":
            if key in (
                pygame.K_LEFT,
                pygame.K_a,
                self.keybinds["left"],
                pygame.K_RIGHT,
                pygame.K_d,
                self.keybinds["right"],
            ):
                self._complete_tutorial_action("move")
            if key == self.keybinds["attack"]:
                self._start_player_attack(self._attack_direction_from_input())
            elif key == self.keybinds["parry"]:
                if self.player.start_parry():
                    self.audio.play("parry_ready")
                    self._try_projectile_parry()
                    self._notify("弹刀架势")
                    self._complete_tutorial_action("parry")
            elif key == self.keybinds["skill"]:
                self._try_cast_skill()
            elif key in (pygame.K_LSHIFT, self.keybinds["dash"]):
                if self.player.dash():
                    self.audio.play("dash")
                    self._dash_trail_timer = 0.0
                    self._notify("闪避")
            elif key == self.keybinds["jump"]:
                if self.player.request_jump():
                    self.audio.play("jump")
                    self._notify("跳跃")
                    self._complete_tutorial_action("jump")
            elif key == pygame.K_ESCAPE:
                self._open_overlay("settings", return_page="game")
            return

        if self.page == "result":
            if key in (
                pygame.K_RETURN,
                pygame.K_SPACE,
                pygame.K_j,
                pygame.K_ESCAPE,
            ):
                self._activate_page_button("lobby")
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
        if self.overlay == "expedition_choice":
            logical = self._to_logical(position)
            for index, rect in enumerate(self._expedition_choice_rects()):
                if rect.collidepoint(logical):
                    self.expedition_choice_selected = index
                    return
        if self.overlay == "progression":
            logical = self._to_logical(position)
            for index, rect in self._progression_visible_node_rects().items():
                if rect.collidepoint(logical):
                    self.progression_selected = index
                    return
        if self.overlay == "difficulty":
            logical = self._to_logical(position)
            for index, rect in enumerate(self._difficulty_rects()):
                if rect.collidepoint(logical):
                    self.difficulty_selected = index
                    return
        if self.overlay == "room_event":
            logical = self._to_logical(position)
            for index, row in enumerate(self._room_event_rects()):
                if row.collidepoint(logical):
                    self.room_choice_selected = index
                    return
        if self.overlay == "shop":
            logical = self._to_logical(position)
            for index, row in enumerate(self._shop_item_rects()):
                if row.collidepoint(logical):
                    self.shop_selected = index
                    return
        if self.overlay == "slots":
            logical = self._to_logical(position)
            for index, rect in enumerate(self._slot_row_rects()):
                if rect.collidepoint(logical):
                    self.slot_selected = index
                    return
        if self.overlay is None and self.page == "menu":
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
            self._open_slot_select("new")
        elif action == "continue":
            self._open_slot_select("continue")
        elif action == "leaderboard":
            self._open_overlay("leaderboard")
        elif action == "settings":
            self._open_overlay("settings")

    def _lobby_actions(self) -> list[tuple[str, str, pygame.Rect]]:
        checkpoint = self._active_run_checkpoint()
        gate_label = (
            f"继续远征 · {checkpoint['stage']}-{checkpoint['floor']}"
            if checkpoint is not None
            else "开启新远征"
        )
        # 中间是远征城门，左侧回响中枢，右侧远征排行
        return [
            ("gate", gate_label, pygame.Rect(500, 250, 280, 330)),
            ("nexus", "回响中枢", pygame.Rect(150, 320, 240, 260)),
            ("records", "远征排行", pygame.Rect(890, 320, 240, 260)),
        ]

    def _enter_lobby(self) -> None:
        self.page = "lobby"
        self.overlay = None
        self.confirm_exit = False
        self.lobby_selected = 0
        self.transition = None
        self.run_currency = 0
        self._notify("灰塔大厅已就绪")

    # -- 存档槽位 -----------------------------------------------------------

    def _open_slot_select(self, mode: str) -> None:
        """打开六格存档选择：new 用于新建/覆盖，continue 用于载入。"""
        self.slot_mode = mode
        self.slot_selected = 0
        self.slot_confirm_index = None
        self._open_overlay("slots", return_page="menu")

    def _slot_row_rects(self) -> list[pygame.Rect]:
        rect = self._overlay_rect()
        return [
            pygame.Rect(rect.x + 30, rect.y + 84 + index * 68, rect.width - 60, 62)
            for index in range(SAVE_SLOT_COUNT)
        ]

    @staticmethod
    def _slot_summary(profile: dict) -> str:
        progression = profile.get("progression", {})
        levels = progression.get("levels", {}) if isinstance(progression, dict) else {}
        unlocked = (
            sum(int(value or 0) for value in levels.values())
            if isinstance(levels, dict)
            else 0
        )
        tutorial = "已完成教学" if profile.get("tutorial_completed") else "未完成教学"
        checkpoint = StartScreen._normalise_run_checkpoint(profile.get("active_run"))
        run_state = (
            f"暂存阶段 {checkpoint['stage']}-{checkpoint['floor']}"
            if checkpoint is not None
            else "无暂存远征"
        )
        return (
            f"最高进度 {int(profile.get('best_stage', 1) or 1)}-"
            f"{int(profile.get('best_floor', 0) or 0)}   "
            f"最高分 {int(profile.get('best_score', 0) or 0):05d}   "
            f"遗晶 {max(0, int(profile.get('echo_relics', 0) or 0))}   "
            f"共鸣节点 {unlocked}   {run_state}   {tutorial}"
        )

    def _bind_slot(self, index: int, *, fresh: bool = False) -> None:
        """把某个槽位设为当前档案；fresh=True 时先清空该槽位。"""
        if fresh or self.save_slots[index] is None:
            self.save_slots[index] = self._new_profile()
        self.active_slot = index
        self.profile = self.save_slots[index]
        self.has_save = any(slot is not None for slot in self.save_slots)
        self.items = self._build_items()

    def _start_new_save(self, index: int) -> None:
        """新建档案：等级、成长树与关卡进度全部重置，并重新走一遍新手教程。"""
        self._bind_slot(index, fresh=True)
        self.result_relics = 0
        self._save_profile()
        self._start_run(1, tutorial=True)
        self._notify(f"存档 {index + 1}：新档案已建立，开始新手教程")

    def _load_slot(self, index: int) -> None:
        self._bind_slot(index)
        if not self.tutorial_completed:
            # 这份档案还没走完新手教程：继续游戏就直接接着教学
            self._start_run(1, tutorial=True)
            self._notify(f"已载入存档 {index + 1}：继续新手教程")
            return
        self._enter_lobby()
        self._notify(f"已载入存档 {index + 1}")

    def _activate_slot(self, index: int) -> None:
        """在存档选择界面确认某个槽位。"""
        if index < 0 or index >= SAVE_SLOT_COUNT:
            return
        occupied = self.save_slots[index] is not None
        if self.slot_mode == "continue":
            if not occupied:
                self._notify(f"存档 {index + 1} 是空的")
                return
            self._close_overlay()
            self._load_slot(index)
            return
        if occupied and self.slot_confirm_index != index:
            # 覆盖会清掉已有进度，所以要求再确认一次
            self.slot_confirm_index = index
            self._notify(f"再确认一次：覆盖存档 {index + 1} 的进度")
            return
        self.slot_confirm_index = None
        self._close_overlay()
        self._start_new_save(index)

    def _activate_lobby_action(self, index: int) -> None:
        actions = self._lobby_actions()
        if index < 0 or index >= len(actions):
            return
        action = actions[index][0]
        if action == "gate":
            checkpoint = self._active_run_checkpoint()
            if checkpoint is not None:
                self.expedition_choice_selected = 0
                self._open_overlay("expedition_choice", return_page="lobby")
            else:
                self._start_new_expedition_flow()
        elif action == "nexus":
            self._open_overlay("progression", return_page="lobby")
        elif action == "records":
            self._open_overlay("leaderboard", return_page="lobby")

    def _start_new_expedition_flow(self) -> None:
        """Start a fresh run, including the optional risk-contract choice."""
        self.run_difficulty_hard = False
        if self._track_unlocked("risk_covenant"):
            self.difficulty_selected = 0
            self._open_overlay("difficulty", return_page="lobby")
        else:
            self._begin_expedition_transition()

    def _activate_expedition_choice(self, index: int) -> None:
        """Continue the checkpoint or discard only that run and start anew."""
        if self.overlay != "expedition_choice" or index not in (0, 1):
            return
        if index == 0:
            if self._active_run_checkpoint() is None:
                self._close_overlay()
                self._notify("暂存进度已失效，将开始新远征")
                self._start_new_expedition_flow()
                return
            self.overlay = None
            self.page = "lobby"
            self._begin_expedition_transition()
            return

        self._clear_run_checkpoint()
        self._save_profile()
        self.overlay = None
        self.page = "lobby"
        self._notify("已放弃暂存远征；永久成长与回响遗晶不受影响")
        self._start_new_expedition_flow()

    @staticmethod
    def _format_track_value(value: float) -> str:
        return str(int(value)) if float(value).is_integer() else f"{value:g}"

    def _track_max_level(self, track: ProgressionTrack) -> int:
        return len(track.values)

    def _track_next_cost(self, track: ProgressionTrack) -> int | None:
        """下一级需要的回响遗晶；已经满级时返回 None。"""
        level = self._track_level(track.track_id)
        if level >= self._track_max_level(track):
            return None
        return int(track.costs[level])

    def _track_effect_text(self, track: ProgressionTrack, level: int) -> str:
        if level <= 0:
            return "尚未点亮。"
        value = track.values[min(level, len(track.values)) - 1]
        return f"Lv.{level}：{track.effect.format(value=self._format_track_value(value))}"

    def _upgrade_track(self, index: int) -> None:
        """把选中的分支提升一级，并扣除对应的回响遗晶。"""
        if index < 0 or index >= len(PROGRESSION_TRACKS):
            return
        track = PROGRESSION_TRACKS[index]
        cost = self._track_next_cost(track)
        if cost is None:
            self._notify(f"{track.title} 已经满级")
            return
        if self.echo_relics < cost:
            self._notify(f"回响遗晶不足，还需 {cost - self.echo_relics}")
            return
        levels = self._track_levels()
        levels[track.track_id] = levels.get(track.track_id, 0) + 1
        progression = self._progression().copy()
        progression["version"] = 2
        progression["levels"] = levels
        progression.setdefault("equipped_start_module", None)
        self.profile["progression"] = progression
        self.profile["echo_relics"] = self.echo_relics - cost
        self._save_profile()
        self._notify(
            f"{track.title} 提升至 Lv.{levels[track.track_id]}"
            f"  ·  {self._format_track_value(track.values[levels[track.track_id] - 1])}"
        )

    def _open_overlay(self, overlay: str, return_page: str | None = None) -> None:
        self.overlay = overlay
        self.return_page = return_page or self.page
        self.overlay_selected = 0
        self.keybind_selected = 0
        self.rebinding_action = None

    def _close_overlay(self) -> None:
        self.overlay = None
        self.page = self.return_page

    @staticmethod
    def _room_type_for(
        stage: int,
        floor: int,
        route_seed: int,
        requested: object = None,
    ) -> str:
        """Resolve a room type without rerolling an already persisted route."""
        valid = {
            ROOM_COMBAT,
            ROOM_ELITE,
            ROOM_EVENT,
            ROOM_REWARD,
            ROOM_SANCTUARY,
            ROOM_RIFT,
            ROOM_SHOP,
            ROOM_BOSS,
        }
        if isinstance(requested, str) and requested in valid:
            return requested
        if stage == 1:
            if floor == SHOP_FLOOR:
                return ROOM_SHOP
            if floor == BOSS_FLOOR:
                return ROOM_BOSS
            return ROOM_COMBAT
        if floor == SECOND_STAGE_SHOP_ROOM:
            return ROOM_SHOP
        if floor == SECOND_STAGE_BOSS_ROOM:
            return ROOM_BOSS
        if floor == 2:
            index = (route_seed + stage * 97 + floor * 31) % len(RANDOM_ROOM_TYPES)
            return RANDOM_ROOM_TYPES[index]
        return {
            1: ROOM_COMBAT,
            3: ROOM_COMBAT,
            4: ROOM_ELITE,
            5: ROOM_EVENT,
        }.get(floor, ROOM_COMBAT)

    def _is_shop_room(self) -> bool:
        return self.room_type == ROOM_SHOP

    def _is_boss_room(self) -> bool:
        return self.room_type == ROOM_BOSS

    def _floor_briefing(self, floor: int) -> FloorBriefing:
        if self.run_stage >= 2:
            return ROOM_TYPE_BRIEFINGS.get(
                self.room_type,
                FLOOR_BRIEFINGS[3],
            )
        return FLOOR_BRIEFINGS.get(floor, FLOOR_BRIEFINGS[3])

    def _open_floor_briefing(self) -> None:
        """进入新一层时弹出简报，介绍本层敌人的攻击方式。"""
        self._open_overlay("floor_intro", return_page="game")

    def _dismiss_floor_intro(self) -> None:
        if self.overlay == "floor_intro":
            self._close_overlay()
            if self._is_shop_room() and not self.shop_closed:
                self._open_shop()
            elif self.room_type in {ROOM_EVENT, ROOM_REWARD, ROOM_SANCTUARY}:
                if not self.room_resolved:
                    self._open_room_event()

    def _open_shop(self) -> None:
        self.shop_selected = 0
        self._open_overlay("shop", return_page="game")
        self._notify("灰烬行商已展开战前整备目录")

    def _open_room_event(self) -> None:
        self.room_choice_selected = 0
        self._open_overlay("room_event", return_page="game")
        self._notify("选择一项结果；确认后将立即写入暂存")

    def _room_event_choices(self) -> tuple[tuple[str, str], ...]:
        if self.room_type == ROOM_REWARD:
            return (
                ("锋刃遗珍", "攻击力 +3"),
                ("生命遗珍", "最大生命 +35，不恢复当前生命"),
                ("谐振遗珍", "回响能量 +60"),
            )
        if self.room_type == ROOM_SANCTUARY:
            return (
                ("静滞扩容", "最大生命 +25，不恢复当前生命"),
                ("谐振整备", "回响能量补满"),
                (
                    "拆解装置",
                    f"获得 {self._currency_reward(18)} 枚战时铸币",
                ),
            )
        return (
            ("回收记忆", f"获得 {self._currency_reward(24)} 枚战时铸币"),
            ("汲取谐振", "回响能量 +40"),
            (
                "回溯愈合",
                f"恢复 {self.event_heal_amount} 点生命"
                f"（最大生命的 {round(EVENT_HEAL_RATIO * 100)}%）",
            ),
            ("承受烙印", "失去 15% 当前生命，攻击力 +4"),
        )

    @property
    def event_heal_amount(self) -> int:
        """事件关的回血量：按最大生命比例，随本局成长自动放大。"""
        return max(1, round(self.player.max_hp * EVENT_HEAL_RATIO))

    def _room_event_rects(self) -> list[pygame.Rect]:
        rect = self._overlay_rect()
        choices = self._room_event_choices()
        height = 82
        spacing = 108
        bottom_margin = 28
        # 选项超过三行时压缩行距，保证仍然落在面板内
        needed = rect.y + 112 + spacing * (len(choices) - 1) + height + bottom_margin
        if needed > rect.bottom:
            spacing = max(
                height + 8,
                (rect.height - 112 - height - bottom_margin) // max(1, len(choices) - 1),
            )
        return [
            pygame.Rect(rect.x + 42, rect.y + 112 + index * spacing, rect.width - 84, height)
            for index in range(len(choices))
        ]

    def _resolve_room_event(self, index: int) -> bool:
        if self.room_resolved or index < 0 or index >= len(self._room_event_choices()):
            return False
        title = self._room_event_choices()[index][0]
        message = f"{title} 已完成，回响之门正在开启"
        if self.room_type == ROOM_REWARD:
            if index == 0:
                self.run_shop_attack_bonus += 3
                self.player.attack_bonus += 3
            elif index == 1:
                self.run_shop_hp_bonus += 35
                self.player.max_hp += 35
            else:
                self.echo_energy = min(ECHO_ENERGY_MAX, self.echo_energy + 60)
        elif self.room_type == ROOM_SANCTUARY:
            if index == 0:
                self.run_shop_hp_bonus += 25
                self.player.max_hp += 25
            elif index == 1:
                self.echo_energy = ECHO_ENERGY_MAX
            else:
                self._grant_fixed_currency(18)
        else:
            if index == 0:
                self._grant_fixed_currency(24)
            elif index == 1:
                self.echo_energy = min(ECHO_ENERGY_MAX, self.echo_energy + 40)
            elif index == 2:
                if self.player.hp >= self.player.max_hp:
                    self._notify("生命值已满，不需要回溯愈合")
                    return False
                healed = self.player.heal(self.event_heal_amount)
                message = f"{title}  生命 +{healed}，回响之门正在开启"
            else:
                self.player.hp = max(1, self.player.hp - max(1, round(self.player.hp * 0.15)))
                self.run_shop_attack_bonus += 4
                self.player.attack_bonus += 4
        self.room_resolved = True
        self.overlay = None
        self.page = "game"
        self._save_run_checkpoint()
        self.audio.play("hit", 0.45)
        self._notify(message)
        return True

    def _leave_shop(self) -> None:
        if self.overlay != "shop":
            return
        self.shop_closed = True
        self.overlay = None
        self.page = "game"
        self._save_run_checkpoint()
        self._notify("整备结束，通往锈冠王庭的回响之门正在开启")

    def _shop_item_rects(self) -> list[pygame.Rect]:
        rect = self._overlay_rect()
        rows = [
            pygame.Rect(rect.x + 42, rect.y + 104 + index * 72, rect.width - 84, 60)
            for index in range(len(SHOP_ITEMS))
        ]
        rows.append(pygame.Rect(rect.centerx - 150, rect.bottom - 104, 300, 44))
        return rows

    def _purchase_shop_item(self, index: int) -> bool:
        if index < 0 or index >= len(SHOP_ITEMS):
            return False
        item = SHOP_ITEMS[index]
        if item.item_id in self.shop_purchased and not item.repeatable:
            self._notify("该货品本次远征已经购入")
            return False
        if self.run_currency < item.cost:
            self._notify(f"战时铸币不足，还需 {item.cost - self.run_currency}")
            return False
        if item.item_id == SHOP_HEAL_ITEM_ID and self.player.hp >= self.player.max_hp:
            self._notify("生命值已满，不需要回复")
            return False
        self.run_currency -= item.cost
        message = f"购入 {item.title}  铸币 -{item.cost}"
        if item.item_id == "repair_infusion":
            self.run_shop_hp_bonus += 25
            self.player.max_hp += 25
        elif item.item_id == "edge_plating":
            self.run_shop_attack_bonus += 4
            self.player.attack_bonus += 4
        elif item.item_id == "vital_expansion":
            self.run_shop_hp_bonus += 45
            self.player.max_hp += 45
        elif item.item_id == "resonance_cell":
            self.echo_energy = min(ECHO_ENERGY_MAX, self.echo_energy + 45)
        elif item.item_id == SHOP_HEAL_ITEM_ID:
            healed = self.player.heal(SHOP_HEAL_AMOUNT)
            message = (
                f"购入 {item.title}  铸币 -{item.cost}  生命 +{healed}"
            )
        if not item.repeatable:
            self.shop_purchased.add(item.item_id)
        lifetime_stats = self.profile.get("lifetime_stats", {})
        if not isinstance(lifetime_stats, dict):
            lifetime_stats = {}
        lifetime_stats = lifetime_stats.copy()
        lifetime_stats["shop_purchases"] = self._stat("shop_purchases") + 1
        self.profile["lifetime_stats"] = lifetime_stats
        self.audio.play("hit", 0.5)
        self._notify(message)
        self._save_run_checkpoint()
        return True

    def _handle_overlay_click(self, position: tuple[int, int]) -> None:
        if self.overlay == "floor_intro":
            # 关卡简报不设按钮：点一下任意位置就开打
            self._dismiss_floor_intro()
            return
        logical = self._to_logical(position)
        if self.overlay == "room_event":
            for index, row in enumerate(self._room_event_rects()):
                if row.collidepoint(logical):
                    self.room_choice_selected = index
                    self._resolve_room_event(index)
                    return
            return
        if self.overlay == "shop":
            for index, row in enumerate(self._shop_item_rects()):
                if row.collidepoint(logical):
                    self.shop_selected = index
                    if index == len(SHOP_ITEMS):
                        self._leave_shop()
                    else:
                        self._purchase_shop_item(index)
                    return
            return
        if self.overlay == "slots":
            for index, row in enumerate(self._slot_row_rects()):
                if row.collidepoint(logical):
                    self.slot_selected = index
                    self._activate_slot(index)
                    return
            if not self._overlay_rect().collidepoint(logical):
                self._close_overlay()
            return
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
            for index, rect in enumerate(rects[4:], start=4):
                if rect.collidepoint(logical):
                    self.overlay_selected = index
                    self._activate_setting(index)
                    return
            if not self._overlay_rect().collidepoint(logical):
                self._close_overlay()
        elif self.overlay == "expedition_choice":
            for index, choice_rect in enumerate(self._expedition_choice_rects()):
                if choice_rect.collidepoint(logical):
                    self.expedition_choice_selected = index
                    self._activate_expedition_choice(index)
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
                self._upgrade_track(self.progression_selected)
            else:
                for branch, branch_rect in self._progression_branch_rects().items():
                    if branch_rect.collidepoint(logical):
                        self._toggle_progression_branch(branch)
                        return
                for index, node_rect in self._progression_visible_node_rects().items():
                    if node_rect.collidepoint(logical):
                        self.progression_selected = index
                        return
                if not self._overlay_rect().collidepoint(logical):
                    self._close_overlay()
        elif self.overlay == "difficulty":
            for index, choice_rect in enumerate(self._difficulty_rects()):
                if choice_rect.collidepoint(logical):
                    self._confirm_difficulty(index)
                    return
            if not self._overlay_rect().collidepoint(logical):
                self._close_overlay()

    def _update(self, dt: float) -> None:
        if self.notification_timer > 0:
            self.notification_timer = max(0.0, self.notification_timer - dt)

        if self.transition is not None:
            # 过场期间暂停世界，只推进动画本身
            self._update_transition(dt)
            return

        if self.page != "game" or self.overlay is not None or self.confirm_exit:
            return

        fixed_dt = min(max(0.0, dt), 1.0 / 30.0)
        # 进入传送门时锁住操作，由动画把角色吸向门心
        move_axis = 0.0 if self.portal_enter_timer > 0.0 else self._move_axis()
        self.player.update(fixed_dt, move_axis)
        self._update_passive_recovery(fixed_dt)
        self._update_death_fades(fixed_dt)
        self._update_attack_impacts(fixed_dt)
        self._update_dash_trails(fixed_dt)
        self._update_enemy_spawn(fixed_dt)
        self._update_skill_waves(fixed_dt)
        self._update_reflected_projectiles(fixed_dt)
        self._update_portal(fixed_dt)
        self._update_movement_audio(fixed_dt)
        self._resolve_player_attack()
        if not self.is_tutorial_run or self._current_tutorial_step.action == "parry":
            self._update_enemy_attacks(fixed_dt)

    VORTEX_TIME = 0.65
    BLACK_TIME = 0.26
    IRIS_TIME = 0.5

    def _difficulty_rects(self) -> list[pygame.Rect]:
        rect = self._overlay_rect()
        return [
            pygame.Rect(rect.x + 60, rect.y + 150, 300, 220),
            pygame.Rect(rect.right - 360, rect.y + 150, 300, 220),
        ]

    def _difficulty_labels(self) -> list[tuple[str, str, str]]:
        return [
            ("标准远征", "按常规威胁值推进，回响遗晶收益不变。", "威胁 +0%"),
            (
                "高压远征",
                "敌人生命与攻击同步提高，结束后获得更多回响遗晶。",
                f"威胁 +{round(DIFFICULTY_THREAT_BONUS * 100)}%  ·  "
                f"遗晶 x{DIFFICULTY_RELIC_MULTIPLIER:g}",
            ),
        ]

    def _confirm_difficulty(self, index: int) -> None:
        """确认本局难度，随后照常播放进城过场。"""
        self.run_difficulty_hard = index == 1
        self.overlay = None
        self._notify(
            "高压远征已确认：敌人更强，遗晶收益提高"
            if self.run_difficulty_hard
            else "标准远征已确认"
        )
        self._begin_expedition_transition()

    def _draw_difficulty(self, rect: pygame.Rect) -> None:
        note = self.small_font.render(
            "风险契约已点亮：本局开始前可以决定是否加压。",
            True,
            COLORS["muted"],
        )
        self.canvas.blit(note, (rect.x + 34, rect.y + 78))
        for index, ((title, detail, tag), choice_rect) in enumerate(
            zip(self._difficulty_labels(), self._difficulty_rects())
        ):
            selected = index == self.difficulty_selected
            pygame.draw.rect(
                self.canvas,
                (20, 61, 66) if selected else (10, 31, 41),
                choice_rect,
            )
            if selected:
                pygame.draw.rect(self.canvas, COLORS["cyan"], choice_rect, 2)
            color = COLORS["gold"] if index == 1 else COLORS["ice"]
            heading = self.overlay_body_font.render(title, True, color)
            self.canvas.blit(
                heading,
                heading.get_rect(center=(choice_rect.centerx, choice_rect.y + 56)),
            )
            for line_index, line in enumerate(
                self._wrap_text(detail, self.small_font, choice_rect.width - 48)
            ):
                self.canvas.blit(
                    self.small_font.render(line, True, COLORS["muted"]),
                    (choice_rect.x + 24, choice_rect.y + 96 + line_index * 22),
                )
            tag_text = self.small_font.render(tag, True, COLORS["cyan"])
            self.canvas.blit(
                tag_text,
                tag_text.get_rect(center=(choice_rect.centerx, choice_rect.bottom - 34)),
            )

    def _begin_expedition_transition(self) -> None:
        """点下远征城门：先播漩涡过场，再真正进入关卡。"""
        if self.transition is not None:
            return
        self.transition = {"phase": "vortex", "t": 0.0}
        self.audio.play("portal_enter")

    def _update_transition(self, dt: float) -> None:
        if self.transition is None:
            return
        self.transition["t"] += dt
        phase = self.transition["phase"]
        if phase == "vortex" and self.transition["t"] >= self.VORTEX_TIME:
            # 等画面被漩涡吞掉之后再换场景，避免看到画面突变
            self.transition = {"phase": "black", "t": 0.0}
            self._start_or_resume_expedition()
        elif phase == "black" and self.transition["t"] >= self.BLACK_TIME:
            self.transition = {"phase": "iris", "t": 0.0}
        elif phase == "iris" and self.transition["t"] >= self.IRIS_TIME:
            self.transition = None

    def _draw_transition(self) -> None:
        if self.transition is None:
            return
        phase = self.transition["phase"]
        timer = self.transition["t"]
        center = (LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] // 2)
        reach = int(math.hypot(*center)) + 40
        layer = pygame.Surface(LOGICAL_SIZE, pygame.SRCALPHA)

        if phase == "vortex":
            progress = max(0.0, min(1.0, timer / self.VORTEX_TIME))
            for index in range(5):
                angle = self.elapsed * 5.5 + index * math.tau / 5.0
                points = []
                for step in range(26):
                    spiral_angle = angle + step * 0.34
                    radius = (70 + progress * 520) * (step / 25.0) ** 0.9
                    points.append(
                        (
                            center[0] + math.cos(spiral_angle) * radius,
                            center[1] + math.sin(spiral_angle) * radius * 0.72,
                        )
                    )
                pygame.draw.lines(
                    layer,
                    (*COLORS["cyan"], int(210 * (1.0 - progress * 0.35))),
                    False,
                    points,
                    3,
                )
            pygame.draw.circle(
                layer,
                (4, 10, 20, int(235 * progress)),
                center,
                int(reach * progress),
            )
            pygame.draw.circle(
                layer,
                (*COLORS["white"], int(200 * progress)),
                center,
                18 + int(70 * progress),
                3,
            )
        elif phase == "black":
            layer.fill((3, 8, 18, 255))
        else:
            progress = max(0.0, min(1.0, timer / self.IRIS_TIME))
            layer.fill((3, 8, 18, 255))
            pygame.draw.circle(layer, (0, 0, 0, 0), center, int(reach * progress))

        self.canvas.blit(layer, (0, 0))

    def _update_passive_recovery(self, dt: float) -> None:
        """生命恢复每十秒结算一次；商店和事件类房间禁用恢复。"""
        healing_blocked = self.room_type in {
            ROOM_SHOP,
            ROOM_EVENT,
            ROOM_REWARD,
            ROOM_SANCTUARY,
        }
        if self.auto_heal_per_second > 0.0 and not healing_blocked:
            self._auto_heal_pool += dt
            ticks = int(self._auto_heal_pool / HEAL_TICK_INTERVAL)
            if ticks > 0:
                self._auto_heal_pool -= ticks * HEAL_TICK_INTERVAL
                self.player.heal(round(self.auto_heal_per_second) * ticks)
        if self.auto_energy_per_second > 0.0:
            self._auto_energy_pool += self.auto_energy_per_second * dt
            whole = int(self._auto_energy_pool)
            if whole > 0:
                self._auto_energy_pool -= whole
                self._gain_energy(whole)

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
        if self.player.skill_active:
            return "attack_side"
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
        """立刻让待登场的敌人出现，并留出一小段不出手的反应时间。"""
        if not self.pending_spawn:
            return
        for enemy in self.pending_spawn:
            enemy.begin_spawn_grace(ENEMY_SPAWN_ATTACK_GRACE)
        self.room_enemies.extend(self.pending_spawn)
        self.pending_spawn.clear()
        self.enemy_spawn_timer = 0.0

    def _queue_next_wave(self) -> bool:
        """把下一波敌人放进待登场队列，并重置倒计时。"""
        if self.wave_index >= len(self.wave_plan):
            return False
        self.pending_spawn = list(self.wave_plan[self.wave_index])
        self.wave_index += 1
        opening_wave = self.wave_index == 1
        self.enemy_spawn_timer = (
            ENEMY_SPAWN_DELAY if opening_wave else WAVE_SPAWN_DELAY
        )
        self.spawn_countdown_total = self.enemy_spawn_timer
        self.spawn_countdown_label = (
            "敌影接近" if opening_wave else f"第 {self.wave_index} 波敌影"
        )
        return True

    # -- 关卡胜利与传送门 -------------------------------------------------

    def _portal_rect(self) -> pygame.Rect:
        return pygame.Rect(
            round(PORTAL_CENTER_X - PORTAL_WIDTH / 2),
            round(PORTAL_GROUND_Y - PORTAL_HEIGHT),
            PORTAL_WIDTH,
            PORTAL_HEIGHT,
        )

    def _room_cleared(self) -> bool:
        """本层所有波次都清空（教学关还要等教学步骤走完）才算房间胜利。"""
        if self._is_shop_room() and not self.shop_closed:
            return False
        if self.room_type in {ROOM_EVENT, ROOM_REWARD, ROOM_SANCTUARY} and not self.room_resolved:
            return False
        if self.pending_spawn or self.room_enemies:
            return False
        if self.wave_index < len(self.wave_plan):
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
                if self.room_type in {ROOM_ELITE, ROOM_RIFT} and not self.room_resolved:
                    bonus = self._grant_fixed_currency(
                        24 if self.room_type == ROOM_ELITE else 32
                    )
                    self.room_resolved = True
                    self._save_run_checkpoint()
                    self._notify(f"额外勘定完成  战时铸币 +{bonus}")
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
        if self.run_stage >= 2 and self.run_floor >= SECOND_STAGE_BOSS_ROOM:
            return ("返回主菜单", "完成第二阶段并返回大厅")
        if self.run_stage == 1 and self.run_floor >= BOSS_FLOOR:
            return ("返回主菜单", "进入第二阶段 · 第 1 关")
        return (
            "返回主菜单",
            f"进入第 {self.run_stage} 阶段 · 第 {self.run_floor + 1} 关",
        )

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
        if self.run_stage >= 2 and self.run_floor >= SECOND_STAGE_BOSS_ROOM:
            self.result_cleared = True
            self.result_relics = relics
            self.page = "result"
            self.confirm_exit = False
            self._notify(f"第二阶段完成，凝结回响遗晶 +{relics}")
            return
        if self.run_stage == 1 and self.run_floor >= BOSS_FLOOR:
            next_stage, next_floor = 2, 1
        else:
            next_stage, next_floor = self.run_stage, self.run_floor + 1
        self._start_run(
            next_floor,
            tutorial=False,
            keep_progress=True,
            stage=next_stage,
            route_seed=self.run_route_seed,
        )
        self._save_run_checkpoint()
        self._notify(
            f"进入第 {next_stage} 阶段 · 第 {next_floor} 关  遗晶 +{relics}"
        )

    def _update_enemy_spawn(self, dt: float) -> None:
        """按波次刷怪：每波之间留出倒计时间隔，清空后自动排下一波。"""
        if not self.pending_spawn:
            # 当前波已经被清空，看看本层还有没有排队的波次
            if self.room_enemies or not self._queue_next_wave():
                return
        self.enemy_spawn_timer = max(0.0, self.enemy_spawn_timer - dt)
        if self.enemy_spawn_timer > 0.0:
            return
        self._spawn_pending_enemies()
        self.audio.play("spawn")
        if self.wave_index >= len(self.wave_plan):
            self._notify("最终波敌人出现")
        else:
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
        self._grant_currency(2)
        self._gain_energy(ENERGY_GAIN_REFLECT)
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
        profile = pending.profile
        reflected_damage = enemy.on_attack_parried(profile, perfect=True)
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
            # 近战弹刀把敌人向后震开一段，形成"弹开"的手感；
            # 首领连段的前两段不产生击退，只有三段全弹开才会被震开
            if enemy.allows_parry_knockback(profile):
                enemy.apply_knockback(
                    self.player.facing,
                    enemy.PARRY_KNOCKBACK_SPEED,
                    enemy.PARRY_KNOCKBACK_LIFT,
                )
        self.audio.play("parry")
        self.audio.duck(0.5, 0.45)
        self.run_score += 260
        self.run_combo += 2
        self.run_max_combo = max(self.run_max_combo, self.run_combo)
        self.run_parries += 1
        self._grant_currency(5)
        self._gain_energy(ENERGY_GAIN_PARRY)
        self.attack_impacts.append(
            AttackImpact(self.player.x, self.player.y - 58, True, True)
        )
        if profile.tag == "boss_memory_sever":
            self._spawn_parry_shockwave(
                radius=190.0,
                color=(190, 240, 255),
                label="弹反冲击波",
            )
            self._notify(
                f"敕令逆断  弹反冲击波令 {enemy.display_name} 瘫痪 5 秒且减伤失效"
            )
        elif profile.tag.startswith("boss_combo_") and enemy.allows_parry_knockback(
            profile
        ):
            self._spawn_parry_shockwave(
                radius=130.0,
                color=COLORS["gold"],
                label="破防",
            )
            self._notify(f"冠冕三裁 三段全弹开  {enemy.display_name} 被击退破防")
        elif reflect:
            self._notify(f"PERFECT  弹开子弹  反弹 {reflected_damage}")
        else:
            self._notify(f"PERFECT  弹刀成功  反震 {reflected_damage}")
        self._complete_tutorial_action("parry")
        enemy.on_attack_resolved(profile, parried=True)
        if enemy.defeated:
            self._award_enemy_defeat(enemy)

    def _spawn_parry_shockwave(
        self,
        *,
        radius: float,
        color: tuple[int, int, int],
        label: str = "",
    ) -> None:
        """弹刀成功的冲击波：从角色身上向外扩散。"""
        self.shockwaves.append(
            ParryShockwave(
                x=self.player.x,
                y=self.player.y - 54,
                remaining=0.5,
                total=0.5,
                radius=radius,
                color=color,
                label=label,
            )
        )

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
            if self._current_tutorial_step.action == "energy":
                self._complete_tutorial_action("energy")
            elif direction == "side":
                self._complete_tutorial_action("attack")
            elif direction == "up":
                self._complete_tutorial_action("up_attack")
            elif direction == "down":
                self._complete_tutorial_action("down_attack")

    def _resolve_player_attack(self) -> None:
        attack_hitbox = self.player.attack_hitbox
        if attack_hitbox is None:
            return

        for enemy in list(self.room_enemies):
            enemy_id = id(enemy)
            if enemy.defeated or (self.player.attack_id, enemy_id) in self._attack_hits:
                continue
            enemy_hitbox = Hitbox(
                enemy.x - enemy.body_width / 2,
                enemy.y - enemy.body_height,
                enemy.body_width,
                enemy.body_height,
            )
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
            self.run_score += 120
            self.run_combo += 1
            self.run_max_combo = max(self.run_max_combo, self.run_combo)
            self._grant_currency(2)
            self._gain_energy(
                ENERGY_GAIN_HEAVY_ATTACK
                if self.player.attack_direction in ("up", "down")
                else ENERGY_GAIN_ATTACK
            )
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

    def _update_death_fades(self, dt: float) -> None:
        """倒地动画推进：时间走完就把剪影移除。"""
        for fade in self.death_fades:
            fade.remaining -= dt
        self.death_fades = [fade for fade in self.death_fades if fade.remaining > 0.0]

    def _update_attack_impacts(self, dt: float) -> None:
        for impact in self.attack_impacts:
            impact.remaining -= dt
        self.attack_impacts = [
            impact for impact in self.attack_impacts if impact.remaining > 0.0
        ]
        for wave in self.shockwaves:
            wave.remaining -= dt
        self.shockwaves = [wave for wave in self.shockwaves if wave.remaining > 0.0]

    def _parry_window_open(self, profile: AttackProfile) -> bool:
        """当前是否处在这次攻击的弹刀窗口内。

        多数招式沿用全局弹刀缓冲；首领连段与断忆敕令通过
        `AttackProfile.parry_window` 指定更短、更严格的窗口。
        """
        if not self.player.parry_buffered:
            return False
        window = profile.parry_window
        if window is None:
            return True
        return self.player.parry_buffer_age <= window

    def _resolve_enemy_attack(self, pending: PendingEnemyAttack) -> None:
        enemy = pending.enemy
        profile = pending.profile
        is_projectile = profile.projectile_speed is not None

        # 近战：金色闪光亮起后的窗口内按下弹刀即为完美弹刀。
        # 远程弹刀在按下瞬间按“贴身范围”判定（见 _try_projectile_parry），
        # 因此这里不再用时间缓冲补判，避免离得很远也能弹。
        if profile.parryable and not is_projectile and self._parry_window_open(profile):
            self._perfect_parry(pending)
            return

        # 断忆敕令是首领二阶段的强制弹刀检定：冲刺与剑气无敌不能替代弹刀，
        # 失误按“当前生命”结算，未受伤时不会直接被满血秒杀。
        if profile.tag == "boss_memory_sever":
            damage = self.player.take_damage(
                max(1, round(self.player.hp * BOSS_MEMORY_SEVER_DAMAGE_RATIO)),
                ignore_invulnerability=True,
            )
            self.audio.play("hurt")
            self.audio.duck(0.7, 0.55)
            self.run_combo = 0
            self.attack_impacts.append(
                AttackImpact(
                    self.player.x,
                    self.player.y - 54,
                    False,
                    True,
                )
            )
            self._notify(f"断忆敕令贯穿防护  失去 {damage} 点生命")
            enemy.on_attack_resolved(profile, parried=False)
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
            enemy.on_attack_resolved(profile, parried=False)
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
        enemy.on_attack_resolved(profile, parried=False)
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
        currency_gain = max(4, enemy.bounty_score // 20)
        salvage_rate = self._track_value("salvage_protocol")
        if salvage_rate > 0:
            currency_gain = math.ceil(currency_gain * (1.0 + salvage_rate / 100.0))
        currency_gain = self._grant_currency(currency_gain)
        self.run_kills += 1
        self.audio.play("defeat")
        message = (
            f"击败 {enemy.display_name}  铸币 +{currency_gain}"
            if currency_gain > 0
            else f"击败 {enemy.display_name}"
        )
        self._notify(message)
        self._gain_energy(ENERGY_GAIN_DEFEAT)
        self._gain_exp(self._enemy_exp(enemy))
        if enemy.kind in BOSS_CLASSES:
            lifetime_stats = self.profile.get("lifetime_stats", {})
            if not isinstance(lifetime_stats, dict):
                lifetime_stats = {}
            lifetime_stats = lifetime_stats.copy()
            lifetime_stats["boss_kills"] = self._stat("boss_kills") + 1
            self.profile["lifetime_stats"] = lifetime_stats

    def _remove_defeated_enemies(self) -> None:
        for enemy in self.room_enemies:
            if not enemy.defeated or id(enemy) in self._death_fade_ids:
                continue
            # 倒地动画：先记下倒下的剪影，再把它从战斗序列里移除
            self._death_fade_ids.add(id(enemy))
            self.death_fades.append(
                DeathFade(
                    kind=enemy.kind,
                    x=enemy.x,
                    y=enemy.y,
                    facing=enemy.facing,
                    remaining=DEATH_FADE_TIME,
                    total=DEATH_FADE_TIME,
                )
            )
        self.room_enemies = [enemy for enemy in self.room_enemies if not enemy.defeated]
        self.pending_enemy_attacks = [
            pending
            for pending in self.pending_enemy_attacks
            if not pending.enemy.defeated and pending.enemy in self.room_enemies
        ]

    # -- 等级与经验 -------------------------------------------------------

    @staticmethod
    def _exp_needed(level: int) -> int:
        """升到下一级所需的经验：逐级提高。"""
        step = max(0, level - 1)
        return 60 + 45 * step + 6 * step * step

    def _enemy_exp(self, enemy: Enemy) -> int:
        """击败敌人获得的经验：按种类与所在层数计价。"""
        base = ENEMY_EXP.get(enemy.kind, 30)
        floor_scale = 1.0 + FLOOR_EXP_STEP * (self.run_floor - 1)
        return max(1, round(base * floor_scale))

    @property
    def exp_to_next(self) -> int:
        return self._exp_needed(self.player_level)

    def _gain_exp(self, amount: int) -> None:
        if amount <= 0:
            return
        self.player_exp += amount
        while self.player_exp >= self.exp_to_next:
            self.player_exp -= self.exp_to_next
            self._level_up()

    def _level_up(self) -> None:
        self.player_level += 1
        self.player.gain_level(HP_PER_LEVEL, ATTACK_PER_LEVEL)
        self.audio.play("parry_ready")
        self._notify(
            f"等级提升 Lv.{self.player_level}  "
            f"生命上限 +{HP_PER_LEVEL}  攻击 +{ATTACK_PER_LEVEL}"
        )

    # -- 回响能量与回响剑气 -----------------------------------------------

    def _currency_reward(self, base: int) -> int:
        """固定铸币奖励的折算值：UI 文案与实际发放共用同一个数字。"""
        return max(1, round(base * RUN_CURRENCY_RATE))

    def _grant_currency(self, amount: int) -> int:
        """战斗收益入账：整体按 RUN_CURRENCY_RATE 缩放，零头攒到下一次。"""
        if amount <= 0:
            return 0
        self._currency_pool += amount * RUN_CURRENCY_RATE
        whole = int(self._currency_pool)
        if whole <= 0:
            return 0
        self._currency_pool -= whole
        self.run_currency += whole
        return whole

    def _grant_fixed_currency(self, base: int) -> int:
        """固定奖励（事件、清房）：按折算值一次性发放，避免与提示文案不符。"""
        reward = self._currency_reward(base)
        self.run_currency += reward
        return reward

    @property
    def energy_ready(self) -> bool:
        return self.echo_energy >= ECHO_ENERGY_MAX

    @property
    def skill_energy_locked(self) -> bool:
        """回响剑气还在出手或仍在场上时，战斗收益不再积攒能量。"""
        if not SKILL_WAVE_ENERGY_LOCK:
            return False
        return bool(self.skill_waves) or self.player.skill_active

    def _gain_energy(self, amount: int) -> None:
        """普通攻击 / 上劈下劈 / 击败敌人 / 完美弹刀都会积攒回响能量。"""
        if amount <= 0 or self.energy_ready or self.skill_energy_locked:
            return
        self.echo_energy = min(ECHO_ENERGY_MAX, self.echo_energy + amount)
        if self.energy_ready:
            self.audio.play("parry_ready")
            self._notify(
                "回响能量已满  "
                f"按 {self._key_name(self.keybinds['skill'])} 释放回响剑气"
            )

    def _try_cast_skill(self) -> None:
        if self.page != "game" or self.overlay is not None or self.confirm_exit:
            return
        if not self.energy_ready:
            self.audio.play("parry_ready", 0.4)
            self._notify(f"回响能量不足  {self.echo_energy}/{ECHO_ENERGY_MAX}")
            return
        if not self.player.cast_skill():
            return
        self.echo_energy = 0
        self._skill_wave_spawned = False
        self.audio.play("parry")
        self.audio.duck(0.6, 0.5)
        self._notify("回响剑气")
        self._complete_tutorial_action("skill")

    def _spawn_skill_wave(self) -> None:
        player = self.player
        self.skill_waves.append(
            SkillWave(
                x=player.x + player.facing * 46.0,
                y=player.y - player.BODY_HEIGHT / 2,
                facing=player.facing,
                damage=round(
                    player.attack_damage * SKILL_DAMAGE_MULTIPLIER * self.skill_damage_scale
                ),
                posture_damage=player.posture_damage * 2,
                remaining=SKILL_WAVE_LIFE,
                total=SKILL_WAVE_LIFE,
                hits=set(),
            )
        )
        self.audio.play("swing_3")

    def _update_skill_waves(self, dt: float) -> None:
        if self.player.skill_active and not self._skill_wave_spawned:
            if self.player.skill_elapsed >= Player.SKILL_CAST_TIME:
                self._skill_wave_spawned = True
                self._spawn_skill_wave()
        if not self.skill_waves:
            return

        active: list[SkillWave] = []
        for wave in self.skill_waves:
            wave.remaining -= dt
            wave.x += wave.facing * wave.speed * dt
            if wave.expired or wave.x < -180.0 or wave.x > LOGICAL_SIZE[0] + 180.0:
                continue
            self._resolve_skill_wave(wave)
            active.append(wave)
        self.skill_waves = active
        self._remove_defeated_enemies()

    def _resolve_skill_wave(self, wave: SkillWave) -> None:
        """剑气命中：造成大量伤害、把敌人击飞，并斩灭沿途的敌方子弹。"""
        hitbox = wave.hitbox
        for enemy in list(self.room_enemies):
            if enemy.defeated or id(enemy) in wave.hits:
                continue
            enemy_hitbox = Hitbox(
                enemy.x - enemy.body_width / 2,
                enemy.y - enemy.body_height,
                enemy.body_width,
                enemy.body_height,
            )
            if not hitbox.overlaps(enemy_hitbox):
                continue
            wave.hits.add(id(enemy))
            # 剑气是范围冲击：不吃盾卫的正面减伤，直接打满
            damage = enemy.take_damage(wave.damage, posture_damage=wave.posture_damage)
            enemy.apply_knockback(
                wave.facing,
                SKILL_KNOCKBACK_SPEED,
                SKILL_KNOCKBACK_LIFT,
            )
            self.pending_enemy_attacks = [
                pending
                for pending in self.pending_enemy_attacks
                if pending.enemy is not enemy
            ]
            self.audio.play("hit")
            self.audio.duck(0.32, 0.26)
            self.attack_impacts.append(
                AttackImpact(enemy.x, enemy.y - 62, True, True)
            )
            if damage <= 0:
                continue
            self.run_score += 200
            self.run_combo += 1
            self.run_max_combo = max(self.run_max_combo, self.run_combo)
            self._grant_currency(3)
            if enemy.defeated:
                self._award_enemy_defeat(enemy)
            else:
                self._notify(f"剑气命中 {enemy.display_name}  -{damage}")

        for pending in list(self.pending_enemy_attacks):
            if pending.profile.projectile_speed is None:
                continue
            position = self._projectile_position(pending)
            projectile_box = Hitbox(position[0] - 14, position[1] - 14, 28, 28)
            if not hitbox.overlaps(projectile_box):
                continue
            self.pending_enemy_attacks.remove(pending)
            self.attack_impacts.append(
                AttackImpact(position[0], position[1], True, True)
            )
            self.audio.play("hit", 0.5)

    @property
    def _current_tutorial_step(self) -> TutorialStep:
        return self.tutorial_steps[self.tutorial_index]

    def _complete_tutorial_action(self, action: str) -> None:
        if self.page != "game" or self.tutorial_index >= len(self.tutorial_steps) - 1:
            return
        if self._current_tutorial_step.action != action:
            return
        self.tutorial_index += 1
        next_action = self._current_tutorial_step.action
        if next_action == "attack" and not self.room_enemies:
            self.room_enemies = self._build_training_room_enemies()
            self._notify("战斗训练目标已投放")
            return
        if next_action == "parry":
            self._prepare_tutorial_parry_target()
        elif next_action == "energy":
            self._notify("再挥砍一次，观察回响能量的积蓄")
            return
        elif next_action == "skill":
            self.echo_energy = ECHO_ENERGY_MAX
            self._notify(
                f"能量已满  按 {self._key_name(self.keybinds['skill'])} 释放回响剑气"
            )
            return
        if next_action == "finish":
            # 训练目标只用于动作展示，不应成为完成教学后的额外清敌门槛。
            self.room_enemies.clear()
            self.pending_enemy_attacks.clear()
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
        if self.transition is not None:
            self._draw_transition()

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
        checkpoint = self._active_run_checkpoint()
        if checkpoint is not None:
            run_state = (
                f"暂存远征  阶段 {checkpoint['stage']}-{checkpoint['floor']}  ·  "
                f"Lv.{checkpoint['player_level']}"
            )
        else:
            run_state = "本局从第一层开始"
        suspended = self.small_font.render(run_state, True, COLORS["cyan"])
        self.canvas.blit(suspended, (930, 104))
        if self.result_relics:
            settlement = self.small_font.render(
                f"本次远征凝结 +{self.result_relics} 遗晶",
                True,
                COLORS["gold"],
            )
            self.canvas.blit(settlement, (930, 128))

        # 三个入口：左侧回响中枢、中间远征城门、右侧远征排行
        mouse = self._to_logical(pygame.mouse.get_pos())
        actions = self._lobby_actions()
        for index, (action, label, rect) in enumerate(actions):
            selected = index == self.lobby_selected
            hovered = rect.collidepoint(mouse)
            if hovered and not selected:
                # 鼠标悬停：把选中的入口切过去，图标稍后放大
                self.lobby_selected = index
                selected = True
            scale = 1.14 if (hovered or selected) else 1.0
            icon = self._lobby_icon(action)
            if icon is not None:
                base = 190 if action == "gate" else 140
                size = round(base * scale)
                image = pygame.transform.smoothscale(icon, (size, size))
                if selected:
                    image = image.copy()
                    image.set_alpha(255)
                else:
                    image = image.copy()
                    image.set_alpha(215)
                self.canvas.blit(
                    image,
                    image.get_rect(center=(rect.centerx, rect.centery - 26)),
                )
            if selected:
                glow = pygame.Surface(LOGICAL_SIZE, pygame.SRCALPHA)
                pygame.draw.circle(
                    glow,
                    (*COLORS["cyan"], 60),
                    (rect.centerx, rect.centery - 26),
                    round(78 * scale),
                    3,
                )
                self.canvas.blit(glow, (0, 0))
            name = self.overlay_body_font.render(
                label, True, COLORS["gold"] if selected else COLORS["ice"]
            )
            self.canvas.blit(name, name.get_rect(center=(rect.centerx, rect.bottom - 34)))

        gate_hint = self.small_font.render(
            actions[0][1], True, COLORS["muted"]
        )
        self.canvas.blit(gate_hint, gate_hint.get_rect(center=(actions[0][2].centerx, actions[0][2].bottom + 4)))

        hint = self.small_font.render(
            "方向键 / WASD 或鼠标选择交互点    Enter 进入    Esc 返回主菜单",
            True,
            COLORS["muted"],
        )
        self.canvas.blit(hint, hint.get_rect(center=(640, 688)))
        self._draw_notification()

    def _lobby_icon(self, action: str) -> pygame.Surface | None:
        if action == "gate":
            return self.assets.room_gate or self.assets.logo
        if action == "nexus":
            return self.assets.logo
        return self.assets.echo_shard

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
        if self.overlay in {"floor_intro", "shop"}:
            return pygame.Rect(180, 62, 920, 596)
        if self.overlay == "slots":
            return pygame.Rect(240, 72, 800, 576)
        return pygame.Rect(252, 96, 776, 528)

    def _overlay_back_rect(self) -> pygame.Rect:
        rect = self._overlay_rect()
        if self.overlay == "progression":
            return pygame.Rect(rect.x + 30, rect.bottom - 60, 220, 42)
        return pygame.Rect(rect.x + 30, rect.bottom - 76, 210, 44)

    def _progression_layout(
        self,
    ) -> tuple[dict[str, pygame.Rect], dict[int, pygame.Rect]]:
        rect = self._overlay_rect()
        branch_rects: dict[str, pygame.Rect] = {}
        node_rects: dict[int, pygame.Rect] = {}
        cursor_y = rect.y + 74
        left_x = rect.x + 28
        left_width = 520

        for branch in PROGRESSION_BRANCHES:
            branch_rects[branch] = pygame.Rect(left_x, cursor_y, left_width, 34)
            cursor_y += 40
            if self.progression_collapsed.get(branch, False):
                continue
            for index, track in enumerate(PROGRESSION_TRACKS):
                if track.branch != branch:
                    continue
                node_rects[index] = pygame.Rect(
                    left_x + 18,
                    cursor_y,
                    left_width - 18,
                    34,
                )
                cursor_y += 40

        return branch_rects, node_rects

    def _progression_branch_rects(self) -> dict[str, pygame.Rect]:
        return self._progression_layout()[0]

    def _progression_visible_node_rects(self) -> dict[int, pygame.Rect]:
        return self._progression_layout()[1]

    def _progression_node_rects(self) -> list[pygame.Rect]:
        """兼容旧接口：返回当前可见的分支行。"""
        return list(self._progression_visible_node_rects().values())

    def _visible_progression_indices(self) -> list[int]:
        return list(self._progression_visible_node_rects())

    def _move_progression_selection(self, direction: int) -> None:
        visible = self._visible_progression_indices()
        if not visible:
            return
        if self.progression_selected not in visible:
            self.progression_selected = visible[0]
            return
        position = visible.index(self.progression_selected)
        self.progression_selected = visible[(position + direction) % len(visible)]

    def _toggle_progression_branch(self, branch: str) -> None:
        if branch not in self.progression_collapsed:
            return
        will_expand = self.progression_collapsed[branch]
        if will_expand:
            for name in self.progression_collapsed:
                self.progression_collapsed[name] = True
            self.progression_collapsed[branch] = False
            self.progression_selected = next(
                index
                for index, track in enumerate(PROGRESSION_TRACKS)
                if track.branch == branch
            )
        else:
            self.progression_collapsed[branch] = True

    def _switch_progression_branch(self, direction: int) -> None:
        current = PROGRESSION_TRACKS[self.progression_selected].branch
        branch_index = PROGRESSION_BRANCHES.index(current)
        branch = PROGRESSION_BRANCHES[
            (branch_index + direction) % len(PROGRESSION_BRANCHES)
        ]
        for name in self.progression_collapsed:
            self.progression_collapsed[name] = name != branch
        self.progression_selected = next(
            index
            for index, track in enumerate(PROGRESSION_TRACKS)
            if track.branch == branch
        )

    def _progression_activate_rect(self) -> pygame.Rect:
        rect = self._overlay_rect()
        return pygame.Rect(rect.right - 278, rect.bottom - 60, 248, 42)

    def _setting_rects(self) -> list[pygame.Rect]:
        rect = self._overlay_rect()
        button_y = rect.bottom - 76
        button_width = 230
        button_gap = 12
        return [
            pygame.Rect(rect.x + 34, rect.y + 104, rect.width - 68, 70),
            pygame.Rect(rect.x + 34, rect.y + 184, rect.width - 68, 70),
            pygame.Rect(rect.x + 34, rect.y + 264, rect.width - 68, 70),
            pygame.Rect(rect.x + 34, rect.y + 344, rect.width - 68, 70),
            pygame.Rect(rect.x + 30, button_y, button_width, 44),  # 暂返大厅
            pygame.Rect(
                rect.x + 30 + button_width + button_gap,
                button_y,
                button_width,
                44,
            ),  # 返回主菜单
            pygame.Rect(
                rect.x + 30 + (button_width + button_gap) * 2,
                button_y,
                button_width,
                44,
            ),  # 关闭设置
        ]

    def _expedition_choice_rects(self) -> list[pygame.Rect]:
        rect = self._overlay_rect()
        return [
            pygame.Rect(rect.x + 50, rect.y + 210, 316, 170),
            pygame.Rect(rect.right - 366, rect.y + 210, 316, 170),
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
            ("skill", "回响剑气"),
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

        if self.overlay == "floor_intro":
            briefing = self._floor_briefing(self.run_floor)
            title_text = (
                f"第 {self.run_stage} 阶段 · 第 {self.run_floor} 关 · "
                f"{briefing.title}"
            )
        elif self.overlay == "slots":
            title_text = (
                "开始游戏 · 选择存档位"
                if self.slot_mode == "new"
                else "继续游戏 · 选择存档位"
            )
        else:
            title_text = {
                "leaderboard": "本地排行榜",
                "keybinds": "键位设置",
                "progression": "回响中枢 · 成长拓扑",
                "portal": "回响之门",
                "expedition_choice": "远征城门 · 暂存进度",
                "shop": "余烬行商 · 战前整备",
                "room_event": self._floor_briefing(self.run_floor).title,
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
        elif self.overlay == "shop":
            self._draw_shop(rect)
        elif self.overlay == "room_event":
            self._draw_room_event(rect)
        elif self.overlay == "floor_intro":
            self._draw_floor_briefing(rect)
        elif self.overlay == "slots":
            self._draw_slot_select(rect)
        elif self.overlay == "difficulty":
            self._draw_difficulty(rect)
        elif self.overlay == "expedition_choice":
            self._draw_expedition_choice(rect)
        else:
            self._draw_settings(rect)

        hint_text = (
            "Enter / 空格 / 点击 开始战斗"
            if self.overlay == "floor_intro"
            else "←→ 选择难度    Enter 确认出征    Esc 返回"
            if self.overlay == "difficulty"
            else "←→ 选择    Enter 确认    Esc 返回大厅"
            if self.overlay == "expedition_choice"
            else "↑↓ 选择货品    Enter 购买    Esc 结束整备"
            if self.overlay == "shop"
            else "↑↓ 选择结果    Enter 确认"
            if self.overlay == "room_event"
            else "↑↓ 选择    Enter 确认    Esc 返回"
            if self.overlay == "slots"
            else "↑↓ 选择    Enter 设置    Esc 返回"
            if self.overlay == "keybinds"
            else "↑↓ 浏览节点    ←→ 切换谱系    Enter 激活    Esc 返回"
            if self.overlay == "progression"
            else "←→ 选择    Enter 确认    Esc 留在房间"
            if self.overlay == "portal"
            else "↑↓ 选择    ←→ 调整    Enter 确认    Esc 返回"
        )
        hint = self.small_font.render(hint_text, True, COLORS["muted"])
        if self.overlay == "progression":
            self.canvas.blit(hint, (rect.x + 584, rect.bottom - 96))
        elif self.overlay == "settings":
            self.canvas.blit(
                hint,
                (rect.right - hint.get_width() - 28, rect.bottom - 104),
            )
        else:
            self.canvas.blit(
                hint,
                (rect.right - hint.get_width() - 28, rect.bottom - 34),
            )

    def _draw_slot_select(self, rect: pygame.Rect) -> None:
        """六格存档列表：显示每格摘要，并标明本次点击会做什么。"""
        for index, row in enumerate(self._slot_row_rects()):
            profile = self.save_slots[index]
            occupied = profile is not None
            selected = index == self.slot_selected
            armed = self.slot_confirm_index == index
            if armed:
                pygame.draw.rect(self.canvas, (40, 14, 20), row)
                pygame.draw.rect(self.canvas, COLORS["red"], row, 2)
            elif selected:
                pygame.draw.rect(self.canvas, (14, 43, 52), row)
                pygame.draw.rect(self.canvas, COLORS["cyan"], row, 2)
            else:
                pygame.draw.rect(self.canvas, (8, 25, 35), row)
                pygame.draw.rect(self.canvas, (42, 105, 106), row, 1)

            badge = pygame.Rect(row.x + 12, row.y + 11, 76, 38)
            badge_color = COLORS["gold"] if occupied else COLORS["muted"]
            pygame.draw.rect(self.canvas, (6, 16, 28), badge)
            pygame.draw.rect(self.canvas, badge_color, badge, 1)
            number = self.lobby_node_font.render(
                f"{index + 1:02d}", True, badge_color
            )
            self.canvas.blit(number, number.get_rect(center=badge.center))

            if occupied:
                label = self.overlay_body_font.render(
                    f"存档 {index + 1}", True, COLORS["ice"]
                )
                self.canvas.blit(label, (row.x + 104, row.y + 6))
                detail = self.small_font.render(
                    self._slot_summary(profile), True, COLORS["muted"]
                )
                self.canvas.blit(detail, (row.x + 104, row.y + 33))
            else:
                label = self.overlay_body_font.render(
                    "空存档位", True, COLORS["muted"]
                )
                self.canvas.blit(
                    label, label.get_rect(midleft=(row.x + 104, row.centery))
                )

            if armed:
                state, color = "确认覆盖", COLORS["red"]
            elif self.slot_mode == "continue":
                state, color = (
                    ("载入", COLORS["cyan"]) if occupied else ("空", COLORS["muted"])
                )
            elif occupied:
                state, color = "覆盖", COLORS["gold"]
            else:
                state, color = "新建", COLORS["cyan"]
            state_text = self.small_font.render(state, True, color)
            self.canvas.blit(
                state_text,
                state_text.get_rect(midright=(row.right - 18, row.centery)),
            )

        if self.slot_confirm_index is not None:
            warning = self.small_font.render(
                f"存档 {self.slot_confirm_index + 1} 已有进度，"
                "再确认一次将清空它并重新开始教学",
                True,
                COLORS["red"],
            )
        else:
            warning = self.small_font.render(
                "开始游戏会建立全新档案：等级、成长树与关卡进度全部重置，"
                "并重新走一遍新手教程"
                if self.slot_mode == "new"
                else "继续游戏会载入所选档案，进入灰塔大厅",
                True,
                COLORS["muted"],
            )
        self.canvas.blit(warning, (rect.x + 32, rect.y + 500))

    def _draw_floor_briefing(self, rect: pygame.Rect) -> None:
        """关卡简报：本层敌人的攻击方式与应对提示。"""
        briefing = self._floor_briefing(self.run_floor)
        summary = self.overlay_body_font.render(
            briefing.summary, True, COLORS["muted"]
        )
        self.canvas.blit(summary, (rect.x + 34, rect.y + 76))

        if self._is_shop_room():
            room_status = "非战斗层    使用战时铸币整备    可不消费直接离开"
        elif self._is_boss_room():
            room_status = (
                f"区域执政者    两个阶段    威胁 {round(self.run_threat * 100)}%"
            )
        elif self.room_type in {ROOM_EVENT, ROOM_REWARD, ROOM_SANCTUARY}:
            room_status = "非战斗关    三选一结果    确认后立即暂存"
        else:
            room_status = (
                f"本关共 {len(self._floor_wave_plan(self.run_floor, self.run_stage, self.room_type))} 波敌人    "
                f"威胁 {round(self.run_threat * 100)}%    敌人生命与伤害同步提升"
            )
        wave_text = self.small_font.render(
            room_status,
            True,
            COLORS["gold"],
        )
        self.canvas.blit(wave_text, (rect.x + 34, rect.y + 110))

        y = rect.y + 150
        for name, description in briefing.entries:
            panel = pygame.Rect(rect.x + 30, y, rect.width - 60, 118)
            pygame.draw.rect(self.canvas, (8, 25, 35), panel)
            pygame.draw.rect(self.canvas, (42, 105, 106), panel, 1)
            pygame.draw.rect(self.canvas, COLORS["cyan"], (panel.x, panel.y, 6, 118))
            title = self.overlay_body_font.render(name, True, COLORS["ice"])
            self.canvas.blit(title, (panel.x + 24, panel.y + 14))
            for index, line in enumerate(
                self._wrap_text(description, self.small_font, panel.width - 56)
            ):
                self.canvas.blit(
                    self.small_font.render(line, True, COLORS["muted"]),
                    (panel.x + 24, panel.y + 48 + index * 22),
                )
            y += 130

        hint_text = (
            "按 Enter / 空格 / 鼠标左键 进入交易"
            if self._is_shop_room()
            else "按 Enter / 空格 / 鼠标左键 查看选项"
            if self.room_type in {ROOM_EVENT, ROOM_REWARD, ROOM_SANCTUARY}
            else "按 Enter / 空格 / 鼠标左键 开始战斗"
        )
        hint = self.small_font.render(
            hint_text,
            True,
            COLORS["cyan"],
        )
        self.canvas.blit(hint, (rect.x + 34, rect.bottom - 70))

    def _draw_room_event(self, rect: pygame.Rect) -> None:
        intro = self.small_font.render(
            "选择一项结果；本关只能勘定一次，并会立即写入当前远征暂存。",
            True,
            COLORS["muted"],
        )
        self.canvas.blit(intro, (rect.x + 42, rect.y + 80))
        for index, ((title, description), row) in enumerate(
            zip(self._room_event_choices(), self._room_event_rects())
        ):
            selected = index == self.room_choice_selected
            pygame.draw.rect(
                self.canvas,
                (18, 48, 50) if selected else (8, 25, 35),
                row,
            )
            pygame.draw.rect(
                self.canvas,
                COLORS["gold"] if selected else (42, 105, 106),
                row,
                2 if selected else 1,
            )
            self.canvas.blit(
                self.overlay_body_font.render(title, True, COLORS["ice"]),
                (row.x + 22, row.y + 12),
            )
            self.canvas.blit(
                self.small_font.render(description, True, COLORS["muted"]),
                (row.x + 22, row.y + 48),
            )

    def _draw_shop(self, rect: pygame.Rect) -> None:
        intro = self.small_font.render(
            f"持有战时铸币 {self.run_currency}    强化限购一次 · 凝血汤剂可重复购买",
            True,
            COLORS["gold"],
        )
        self.canvas.blit(intro, (rect.x + 42, rect.y + 78))
        rows = self._shop_item_rects()
        for index, item in enumerate(SHOP_ITEMS):
            row = rows[index]
            selected = index == self.shop_selected
            purchased = item.item_id in self.shop_purchased and not item.repeatable
            affordable = self.run_currency >= item.cost and not purchased
            pygame.draw.rect(
                self.canvas,
                (18, 48, 50) if selected else (8, 25, 35),
                row,
            )
            pygame.draw.rect(
                self.canvas,
                COLORS["gold"] if selected else (42, 105, 106),
                row,
                2 if selected else 1,
            )
            title = self.overlay_body_font.render(item.title, True, COLORS["ice"])
            self.canvas.blit(title, (row.x + 22, row.y + 5))
            detail = self.small_font.render(item.description, True, COLORS["muted"])
            self.canvas.blit(detail, (row.x + 22, row.y + 33))
            if purchased:
                state, color = "已购入", COLORS["cyan"]
            elif affordable:
                state, color = f"{item.cost} 铸币", COLORS["gold"]
            else:
                state, color = f"{item.cost} 铸币", COLORS["red"]
            price = self.lobby_node_font.render(state, True, color)
            self.canvas.blit(price, price.get_rect(midright=(row.right - 20, row.centery)))

        self._draw_ui_button(
            rows[-1],
            "结束整备并开启王庭入口",
            selected=self.shop_selected == len(SHOP_ITEMS),
        )

    def _draw_portal_choice(self, rect: pygame.Rect) -> None:
        """传送门选择界面：返回主菜单 / 下一关。"""
        labels = self._portal_choice_labels()
        info = self.overlay_body_font.render(
            f"本局分数 {self.run_score:05d}    完美弹刀 {self.run_parries}    "
            f"第 {self.run_stage} 阶段 · 第 {self.run_floor} 关",
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
        levels = self._track_levels()
        branch_rects, track_rects = self._progression_layout()
        branch_colors = {
            "基元谱系": COLORS["gold"],
            "机制谱系": COLORS["cyan"],
            "铸币谱系": (166, 205, 184),
        }

        for branch, branch_rect in branch_rects.items():
            branch_color = branch_colors[branch]
            collapsed = self.progression_collapsed.get(branch, False)
            branch_tracks = [
                track for track in PROGRESSION_TRACKS if track.branch == branch
            ]
            point_count = sum(levels.get(track.track_id, 0) for track in branch_tracks)
            point_total = sum(len(track.values) for track in branch_tracks)
            pygame.draw.rect(self.canvas, (10, 31, 41), branch_rect)
            pygame.draw.rect(self.canvas, branch_color, branch_rect, 1)
            pygame.draw.rect(
                self.canvas,
                branch_color,
                (branch_rect.x, branch_rect.y, 5, branch_rect.height),
            )
            arrow_x = branch_rect.x + 20
            arrow_y = branch_rect.centery
            arrow = (
                (
                    (arrow_x - 4, arrow_y - 6),
                    (arrow_x + 5, arrow_y),
                    (arrow_x - 4, arrow_y + 6),
                )
                if collapsed
                else (
                    (arrow_x - 6, arrow_y - 3),
                    (arrow_x + 6, arrow_y - 3),
                    (arrow_x, arrow_y + 5),
                )
            )
            pygame.draw.polygon(self.canvas, branch_color, arrow)
            label = self.lobby_node_font.render(branch, True, COLORS["ice"])
            self.canvas.blit(label, (branch_rect.x + 38, branch_rect.y + 7))
            count = self.small_font.render(
                f"已点亮 {point_count}/{point_total}",
                True,
                branch_color,
            )
            self.canvas.blit(
                count,
                (branch_rect.right - count.get_width() - 14, branch_rect.y + 8),
            )

        for index, track_rect in track_rects.items():
            track = PROGRESSION_TRACKS[index]
            level = levels.get(track.track_id, 0)
            max_level = len(track.values)
            is_selected = index == self.progression_selected
            branch_color = branch_colors[track.branch]
            if is_selected:
                pygame.draw.rect(self.canvas, (20, 61, 66), track_rect)
                pygame.draw.rect(self.canvas, COLORS["cyan"], track_rect, 2)
            elif level:
                pygame.draw.rect(self.canvas, (15, 46, 49), track_rect)
            pygame.draw.line(
                self.canvas,
                branch_color,
                (track_rect.x + 10, track_rect.y),
                (track_rect.x + 10, track_rect.bottom),
                2,
            )
            pygame.draw.circle(
                self.canvas,
                branch_color,
                (track_rect.x + 10, track_rect.centery),
                4,
            )
            label = self.lobby_node_font.render(
                track.title,
                True,
                COLORS["ice"] if is_selected else COLORS["muted"],
            )
            self.canvas.blit(label, (track_rect.x + 25, track_rect.y + 7))

            # 等级圆点：已点亮的格子按谱系配色，未点亮留空
            pip_x = track_rect.x + 150
            for pip in range(max_level):
                color = branch_color if pip < level else (32, 62, 70)
                pygame.draw.circle(
                    self.canvas,
                    color,
                    (pip_x + pip * 15, track_rect.centery),
                    5,
                )

            cost = self._track_next_cost(track)
            if cost is None:
                state, state_color = "已满级", COLORS["gold"]
            elif self.echo_relics >= cost:
                state, state_color = f"升级 {cost} 遗晶", COLORS["cyan"]
            else:
                state, state_color = f"{cost} 遗晶", COLORS["muted"]
            state_text = self.small_font.render(state, True, state_color)
            self.canvas.blit(
                state_text,
                (
                    track_rect.right - state_text.get_width() - 14,
                    track_rect.y + 8,
                ),
            )

        track = PROGRESSION_TRACKS[self.progression_selected]
        level = levels.get(track.track_id, 0)
        max_level = len(track.values)
        cost = self._track_next_cost(track)
        branch_color = branch_colors[track.branch]
        detail = pygame.Rect(rect.x + 584, rect.y + 86, 514, 430)
        pygame.draw.rect(self.canvas, (8, 25, 35), detail)
        pygame.draw.rect(self.canvas, (42, 105, 106), detail, 2)
        heading = self.overlay_body_font.render(track.title, True, COLORS["ice"])
        self.canvas.blit(heading, (detail.x + 28, detail.y + 28))
        level_text = self.lobby_node_font.render(
            f"{track.branch}   Lv.{level} / {max_level}",
            True,
            branch_color,
        )
        self.canvas.blit(level_text, (detail.x + 30, detail.y + 64))

        lines = [
            (
                f"下一级消耗：{cost} 回响遗晶" if cost is not None else "该分支已经满级",
                COLORS["gold"],
            ),
            (f"当前效果：{self._track_effect_text(track, level)}", COLORS["muted"]),
            (
                "升级效果："
                + (
                    self._track_effect_text(track, level + 1)
                    if cost is not None
                    else "无"
                ),
                COLORS["cyan"],
            ),
        ]
        cursor = detail.y + 108
        for text, color in lines:
            for wrapped in self._wrap_text(text, self.small_font, detail.width - 56):
                self.canvas.blit(
                    self.small_font.render(wrapped, True, color),
                    (detail.x + 28, cursor),
                )
                cursor += 22
            cursor += 14

        balance = self.small_font.render(
            f"回响遗晶余额  {self.echo_relics}",
            True,
            COLORS["gold"],
        )
        self.canvas.blit(balance, (detail.x + 28, detail.bottom - 40))
        if cost is None:
            button_label = "已满级"
        elif self.echo_relics >= cost:
            button_label = f"升级  -{cost}"
        else:
            button_label = f"遗晶不足  -{cost}"
        self._draw_ui_button(
            self._progression_activate_rect(),
            button_label,
            selected=True,
            enabled=cost is not None and self.echo_relics >= cost,
        )
        self._draw_ui_button(self._overlay_back_rect(), "离开中枢")

    def _draw_leaderboard(self, rect: pygame.Rect) -> None:
        """排行记录：按本局闯到的最高层数排序。"""
        entries = self._leaderboard_entries()
        summary = self.small_font.render(
            f"用时最深的远征前 {len(entries)} 名  ·  按抵达层数排序",
            True,
            COLORS["muted"],
        )
        self.canvas.blit(summary, (rect.x + 34, rect.y + 76))

        header_y = rect.y + 108
        for text, x in (
            ("名次", rect.x + 42),
            ("抵达关卡", rect.x + 112),
            ("击败", rect.x + 330),
            ("弹刀", rect.x + 430),
            ("分数", rect.right - 160),
        ):
            self.canvas.blit(
                self.small_font.render(text, True, COLORS["cyan"]),
                (x, header_y),
            )

        if not entries:
            empty = self.small_font.render(
                "还没有远征记录：完成一局之后就会出现在这里。",
                True,
                COLORS["muted"],
            )
            self.canvas.blit(empty, (rect.x + 42, header_y + 46))

        for index, entry in enumerate(entries):
            y = header_y + 40 + index * 46
            if y > rect.bottom - 110:
                break
            pygame.draw.line(
                self.canvas,
                (30, 77, 84),
                (rect.x + 30, y + 36),
                (rect.right - 30, y + 36),
                1,
            )
            rank_text = self.overlay_body_font.render(
                str(index + 1).zfill(2),
                True,
                COLORS["gold"] if index == 0 else COLORS["cyan"],
            )
            self.canvas.blit(rank_text, (rect.x + 42, y))
            floor_text = self.overlay_body_font.render(
                f"阶段 {entry['stage']}-{entry['floor']}",
                True,
                COLORS["ice"],
            )
            self.canvas.blit(floor_text, (rect.x + 112, y))
            detail = self.small_font.render(
                ("通关" if entry.get("cleared") else "失败")
                + f"  ·  连击 x{entry['max_combo']}",
                True,
                COLORS["muted"],
            )
            self.canvas.blit(detail, (rect.x + 112, y + 22))
            kills = self.small_font.render(str(entry["kills"]), True, COLORS["muted"])
            self.canvas.blit(kills, (rect.x + 330, y + 6))
            parries = self.small_font.render(
                str(entry["parries"]), True, COLORS["muted"]
            )
            self.canvas.blit(parries, (rect.x + 430, y + 6))
            score_text = self.overlay_body_font.render(
                entry["score"], True, COLORS["ice"]
            )
            self.canvas.blit(
                score_text, (rect.right - score_text.get_width() - 42, y)
            )
        self._draw_ui_button(
            self._overlay_back_rect(),
            "返回大厅" if self.return_page == "lobby" else "返回主菜单",
            self.overlay_selected == 0,
        )

    def _leaderboard_entries(self, limit: int = 10) -> list[dict]:
        """把存档里的战绩整理成排行条目：层数优先，其次分数。"""
        scores = self.profile.get("scores", [])
        if not isinstance(scores, list):
            return []
        rows = [score for score in scores if isinstance(score, dict)]
        rows.sort(
            key=lambda score: (
                int(score.get("stage", 1) or 1),
                int(score.get("floor", 0) or 0),
                int(score.get("score", 0) or 0),
            ),
            reverse=True,
        )
        return [
            {
                "stage": max(1, int(row.get("stage", 1) or 1)),
                "floor": max(1, int(row.get("floor", 1) or 1)),
                "score": f"{int(row.get('score', 0) or 0):05d}",
                "kills": int(row.get("kills", 0) or 0),
                "parries": int(row.get("parries", 0) or 0),
                "max_combo": int(row.get("max_combo", 0) or 0),
                "cleared": row.get("outcome") == "clear",
            }
            for row in rows[:limit]
        ]

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
            "暂返大厅",
            self.overlay_selected == 4,
            enabled=self.return_page == "game" and not self.is_tutorial_run,
        )
        self._draw_ui_button(
            setting_rects[5],
            "返回主菜单",
            self.overlay_selected == 5,
        )
        self._draw_ui_button(
            setting_rects[6],
            "关闭设置",
            self.overlay_selected == 6,
        )

    def _draw_expedition_choice(self, rect: pygame.Rect) -> None:
        checkpoint = self._active_run_checkpoint()
        if checkpoint is None:
            summary = "暂存进度已失效，请返回大厅重新进入城门。"
        else:
            summary = (
                f"阶段 {checkpoint['stage']}-{checkpoint['floor']}  ·  "
                f"Lv.{checkpoint['player_level']}  ·  "
                f"生命 {checkpoint['player_hp']}  ·  "
                f"回响能量 {checkpoint['echo_energy']}"
            )
        note = self.small_font.render(summary, True, COLORS["cyan"])
        self.canvas.blit(note, note.get_rect(center=(rect.centerx, rect.y + 108)))
        warning = self.small_font.render(
            "重新开始会删除当前远征暂存，但不会影响回响遗晶、成长节点与历史战绩。",
            True,
            COLORS["muted"],
        )
        self.canvas.blit(warning, warning.get_rect(center=(rect.centerx, rect.y + 142)))

        labels = (
            ("继续当前远征", "恢复已保存的关卡、生命与局内资源"),
            ("放弃暂存并重新开始", "从第一阶段第一关建立一局新远征"),
        )
        for index, ((title, detail), choice_rect) in enumerate(
            zip(labels, self._expedition_choice_rects())
        ):
            selected = index == self.expedition_choice_selected
            pygame.draw.rect(
                self.canvas,
                (20, 61, 66) if selected else (10, 31, 41),
                choice_rect,
            )
            pygame.draw.rect(
                self.canvas,
                COLORS["cyan"] if selected else (30, 72, 78),
                choice_rect,
                2 if selected else 1,
            )
            color = COLORS["gold"] if index == 1 else COLORS["ice"]
            heading = self.overlay_body_font.render(title, True, color)
            self.canvas.blit(
                heading,
                heading.get_rect(center=(choice_rect.centerx, choice_rect.y + 56)),
            )
            detail_text = self.small_font.render(detail, True, COLORS["muted"])
            self.canvas.blit(
                detail_text,
                detail_text.get_rect(center=(choice_rect.centerx, choice_rect.y + 108)),
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
            self._save_settings()
            self._notify(
                "辅助模式已" + ("开启" if self.settings["assist_mode"] else "关闭")
            )
        elif index == 2:
            self.settings["fullscreen"] = not self.settings["fullscreen"]
            self._save_settings()
            self._apply_display_mode()
            self._notify("全屏已" + ("开启" if self.settings["fullscreen"] else "关闭"))
        elif index == 3:
            self._open_overlay("keybinds")
        elif index == 4:
            self._suspend_run_to_lobby()
        elif index == 5:
            self._return_to_menu_from_settings()
        elif index == 6:
            self._close_overlay()

    def _suspend_run_to_lobby(self) -> None:
        """Checkpoint a live expedition and return to the lobby without settling it."""
        if self.return_page != "game" or self.page != "game" or self.is_tutorial_run:
            self._notify("只有正式远征中可以暂返大厅")
            return
        self._save_run_checkpoint()
        self._enter_lobby()
        self._notify("远征已暂存，可从城门继续或重新开始")

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
                f"按 {keys['left']}/{keys['right']} 或方向键进行一次左右移动",
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
                f"按 {keys['attack']} 或鼠标左键挥砍一次",
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
                f"按住 S/↓ 再按 {keys['attack']} 使用一次下劈",
                "下劈命中会把你向上弹起，连续命中可以保持滞空。",
                "down_attack",
            ),
            TutorialStep(
                "弹刀训练",
                f"按 {keys['parry']} 进入一次弹刀架势",
                "正式战斗里要等金色闪光亮起再按，远程子弹靠近时也能弹开。",
                "parry",
            ),
            TutorialStep(
                "回响能量",
                f"再按一次 {keys['attack']}，为回响能量充能",
                "普通攻击 +4、上劈下劈 +7、击败敌人与完美弹刀各 +20；"
                "跳跃、冲刺与移动不产生能量。",
                "energy",
            ),
            TutorialStep(
                "回响剑气",
                f"按 {keys['skill']} 释放回响剑气，一路斩到画面另一侧",
                "剑气向前斩出，期间角色无敌，会把命中的敌人击飞，"
                "并斩灭沿途碰到的敌方子弹。",
                "skill",
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

    @staticmethod
    def _floor_threat(floor: int, stage: int = 1) -> float:
        """层数越深，敌人生命与伤害同步提高。"""
        stage_bonus = max(0, stage - 1) * 0.45
        return FLOOR_THREAT_BASE + stage_bonus + FLOOR_THREAT_STEP * (max(1, floor) - 1)

    def _progress_depth(self) -> int:
        return self.run_floor if self.run_stage <= 1 else BOSS_FLOOR + self.run_floor

    @staticmethod
    def _floor_wave_plan(
        floor: int,
        stage: int = 1,
        room_type: str | None = None,
    ) -> tuple[tuple[str, ...], ...]:
        """Return the combat plan for a stage room; non-combat rooms are empty."""
        resolved_type = room_type or StartScreen._room_type_for(stage, floor, 0)
        if resolved_type in {ROOM_SHOP, ROOM_EVENT, ROOM_REWARD, ROOM_SANCTUARY}:
            return ()
        if stage == 1:
            return FLOOR_WAVE_PLANS.get(floor, FLOOR_WAVE_PLANS[3])
        if resolved_type == ROOM_RIFT:
            return (
                ("rift_worm", "resonance_mage", "spear_thrower", "chaser"),
                ("shield_guard", "chaser", "rift_worm", "resonance_mage", "spear_thrower"),
                ("rift_worm", "rift_worm", "shield_guard", "chaser", "resonance_mage"),
            )
        if resolved_type == ROOM_ELITE and floor != 4:
            return SECOND_STAGE_WAVE_PLANS[4]
        return SECOND_STAGE_WAVE_PLANS.get(floor, SECOND_STAGE_WAVE_PLANS[3])

    @staticmethod
    def _wave_positions(count: int) -> list[float]:
        """把一波敌人均匀铺在战斗区，避免全部叠在同一个落点。"""
        if count <= 0:
            return []
        if count == 1:
            return [WAVE_SPAWN_START_X]
        step = (WAVE_SPAWN_END_X - WAVE_SPAWN_START_X) / (count - 1)
        return [WAVE_SPAWN_START_X + step * index for index in range(count)]

    def _build_wave(self, kinds: tuple[str, ...], threat: float) -> list[Enemy]:
        enemies: list[Enemy] = []
        for kind, x in zip(kinds, self._wave_positions(len(kinds))):
            enemy_class = ENEMY_CLASSES.get(kind) or BOSS_CLASSES[kind]
            spawn_x = 980.0 if kind in BOSS_CLASSES else x
            # 章节成长只作用于小怪：首领会按自己的阶段强化
            scale = self._normal_enemy_scale() if kind in ENEMY_CLASSES else 1.0
            enemies.append(
                enemy_class(
                    spawn_x,
                    WAVE_GROUND_Y,
                    threat=threat,
                    scale=scale,
                )
            )
        return enemies

    def _normal_enemy_scale(self) -> float:
        """小怪的跨章节成长倍率：第一章为 1.0，第二章整体上一个台阶。"""
        stage_steps = max(0, self.run_stage - 1)
        return 1.0 + NORMAL_ENEMY_STAGE_STEP * stage_steps

    def _start_run(
        self,
        floor: int,
        *,
        tutorial: bool = True,
        keep_progress: bool = False,
        stage: int = 1,
        room_type: str | None = None,
        route_seed: int | None = None,
    ) -> None:
        carried_currency = self.run_currency if keep_progress else None
        carried_hp = self.player.hp if keep_progress else None
        carried_energy = self.echo_energy if keep_progress else None
        entering_new_stage = keep_progress and max(1, int(stage)) != self.run_stage
        self.pressed_keys.clear()
        self.page = "game"
        self.overlay = None
        self.confirm_exit = False
        self.is_tutorial_run = tutorial
        self.run_stage = max(1, int(stage))
        max_room = BOSS_FLOOR if self.run_stage == 1 else SECOND_STAGE_ROOM_COUNT
        self.run_floor = max(1, min(max_room, int(floor)))
        if route_seed is not None:
            self.run_route_seed = max(0, int(route_seed))
        elif not keep_progress or self.run_route_seed <= 0:
            self.run_route_seed = random.SystemRandom().randrange(1, 2147483647)
        self.room_type = self._room_type_for(
            self.run_stage,
            self.run_floor,
            self.run_route_seed,
            room_type,
        )
        self.room_resolved = False
        self.room_choice_selected = 0
        self.run_threat = self._floor_threat(self.run_floor, self.run_stage) + (
            DIFFICULTY_THREAT_BONUS if self.run_difficulty_hard else 0.0
        )
        if self.room_type == ROOM_ELITE:
            self.run_threat += 0.2
        elif self.room_type == ROOM_RIFT:
            self.run_threat += 0.3
        self.run_score = 0
        self.run_combo = 0
        self.run_max_combo = 0
        self.run_parries = 0
        if not keep_progress:
            self.run_shop_attack_bonus = 0
            self.run_shop_hp_bonus = 0
            self.shop_purchased.clear()
        elif entering_new_stage:
            # 每个阶段的行商库存独立，跨阶段保留强化但允许再次购买。
            self.shop_purchased.clear()
        carry_currency = int(self._track_value("reserve_carry"))
        self.run_currency = (
            carried_currency if carried_currency is not None else carry_currency
        )
        self._currency_pool = 0.0
        self.result_relic_breakdown = []
        self.player = Player(230, 566)
        nexus_hp = int(self._track_value("vital_lattice"))
        nexus_attack = int(self._track_value("edge_tempering"))
        if nexus_hp:
            self.player.max_hp += nexus_hp
        if nexus_attack:
            self.player.attack_bonus += nexus_attack
        self.player.max_hp += self.run_shop_hp_bonus
        self.player.attack_bonus += self.run_shop_attack_bonus
        self.player.hp = self.player.max_hp
        if self._track_unlocked("aerial_memory"):
            self.player.unlock_air_jump()
        self.player.dash_unlocked = (
            tutorial or self._track_unlocked("shadow_dash")
        )
        self.skill_damage_scale = 1.0 + self._track_value("resonance_amplifier") / 100.0
        self.auto_heal_per_second = self._track_value("vital_regeneration")
        self.auto_energy_per_second = self._track_value("resonance_reflux")
        self._auto_heal_pool = 0.0
        self._auto_energy_pool = 0.0
        self.run_kills = 0
        if keep_progress:
            # 换关保留当前生命与等级收益，不再借由场景重建自动补满生命。
            gained_levels = max(0, self.player_level - 1)
            self.player.max_hp += gained_levels * HP_PER_LEVEL
            self.player.attack_bonus += gained_levels * ATTACK_PER_LEVEL
            self.player.hp = min(
                self.player.max_hp,
                max(1, int(carried_hp if carried_hp is not None else 1)),
            )
        else:
            self.player_level = 1
            self.player_exp = 0
        # 同一局换关保留回响能量；只有新远征开局才归零。
        self.echo_energy = (
            min(ECHO_ENERGY_MAX, max(0, int(carried_energy)))
            if carried_energy is not None
            else 0
        )
        self.skill_waves.clear()
        self._skill_wave_spawned = False
        self._attack_hits.clear()
        self._defeated_enemies.clear()
        self.room_enemies = []
        self.wave_index = 0
        self.pending_spawn = []
        self.enemy_spawn_timer = 0.0
        self.spawn_countdown_total = ENEMY_SPAWN_DELAY
        self.spawn_countdown_label = "敌影接近"
        self.shop_selected = 0
        self.shop_closed = not self._is_shop_room()
        if tutorial:
            self.wave_plan = []
        else:
            self.wave_plan = [
                self._build_wave(kinds, self.run_threat)
                for kinds in self._floor_wave_plan(
                    self.run_floor,
                    self.run_stage,
                    self.room_type,
                )
            ]
            # 进入关卡后敌人延迟登场，避免开门瞬间贴脸
            self._queue_next_wave()
        self.pending_enemy_attacks.clear()
        self.attack_impacts.clear()
        self.shockwaves.clear()
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
        self._step_timer = 0.0
        if self.pending_spawn:
            self._notify("敌影正在接近…")
        elif self._is_shop_room():
            self._notify("余烬行商驿站已接入")
        else:
            self._notify("试炼房间已开启")
        if not tutorial:
            self._open_floor_briefing()

    def _page_buttons(self) -> dict[str, pygame.Rect]:
        if self.page == "result":
            return {"lobby": pygame.Rect(490, 566, 300, 58)}
        if self.page == "failure":
            return {"lobby": pygame.Rect(490, 566, 300, 58)}
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
        elif button == "lobby" and self.page == "failure":
            relics = self.result_relics
            self._enter_lobby()
            self._notify(f"失败勘定完成，凝结回响遗晶 +{relics}")
        elif button == "lobby" and self.page == "result":
            relics = self.result_relics
            self._enter_lobby()
            self._notify(f"第二阶段通关，凝结回响遗晶 +{relics}")
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
                if self.page == "game" and not self.is_tutorial_run:
                    self._save_run_checkpoint()
                self.page = "menu"
                self.confirm_exit = False
                self._notify(
                    "远征已暂存并返回主菜单"
                    if self._active_run_checkpoint() is not None
                    else "已返回主菜单"
                )
        elif button == "cancel":
            self.confirm_exit = False

    def _finish_run(self) -> None:
        relics = self._settle_run()
        self._enter_lobby()
        self._notify(f"远征已结算，凝结回响遗晶 +{relics}")

    def _settle_run(self) -> int:
        """结算本局：分数、遗晶、存档与统计，返回获得的回响遗晶。"""
        depth = self._progress_depth()
        self.result_score = self.run_score + depth * 500 + self.run_parries * 100
        previous_best = int(self.profile.get("best_score", 0) or 0)
        self.result_new_record = self.result_score > previous_best
        self.profile["best_score"] = max(previous_best, self.result_score)
        best_stage = int(self.profile.get("best_stage", 0) or 0)
        best_floor = int(self.profile.get("best_floor", 0) or 0)
        if (self.run_stage, self.run_floor) > (best_stage, best_floor):
            self.profile["best_stage"] = self.run_stage
            self.profile["best_floor"] = self.run_floor
        scores = self.profile.get("scores", [])
        if not isinstance(scores, list):
            scores = []
        scores.append(
            {
                "score": self.result_score,
                "stage": self.run_stage,
                "floor": self.run_floor,
                "parries": self.run_parries,
                "kills": self.run_kills,
                "max_combo": self.run_max_combo,
                "outcome": "clear",
            }
        )
        self.profile["scores"] = sorted(
            [score for score in scores if isinstance(score, dict)],
            key=lambda score: (
                int(score.get("stage", 1) or 1),
                int(score.get("floor", 0) or 0),
                int(score.get("score", 0) or 0),
            ),
            reverse=True,
        )[:20]
        self.result_relics = 40 if self.is_tutorial_run else 30 + depth * 10 + min(
            self.run_parries * 2, 30
        )
        if self.run_difficulty_hard and not self.is_tutorial_run:
            # 高压远征：结算时按倍率发放额外回响遗晶
            self.result_relics = round(self.result_relics * DIFFICULTY_RELIC_MULTIPLIER)
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
        lifetime_stats["best_combo"] = max(
            self._stat("best_combo"), self.run_max_combo
        )
        self.profile["lifetime_stats"] = lifetime_stats
        self._clear_run_checkpoint()
        self._save_profile()
        self.has_save = True
        self.items = self._build_items()
        return self.result_relics

    def _calculate_failure_relics(self) -> tuple[list[tuple[str, int]], int]:
        if self.is_tutorial_run:
            return [], 0

        breakdown = [
            ("残响底蕴", 10),
            (
                "分数折算",
                min(FAILURE_SCORE_RELIC_CAP, max(0, self.result_score) // 250),
            ),
            (
                "层级进度",
                min(FAILURE_FLOOR_RELIC_CAP, max(1, self._progress_depth()) * 5),
            ),
            (
                "连击技艺",
                min(FAILURE_COMBO_RELIC_CAP, (max(0, self.run_max_combo) // 4) * 2),
            ),
            (
                "弹刀技艺",
                min(FAILURE_PARRY_RELIC_CAP, max(0, self.run_parries) * 3),
            ),
        ]
        return breakdown, min(FAILURE_RELIC_CAP, sum(value for _, value in breakdown))

    def _fail_run(self) -> None:
        if self.page != "game":
            return

        self.result_score = self.run_score
        previous_best = int(self.profile.get("best_score", 0) or 0)
        self.result_new_record = self.result_score > previous_best
        self.profile["best_score"] = max(previous_best, self.result_score)
        best_stage = int(self.profile.get("best_stage", 0) or 0)
        best_floor = int(self.profile.get("best_floor", 0) or 0)
        if (self.run_stage, self.run_floor) > (best_stage, best_floor):
            self.profile["best_stage"] = self.run_stage
            self.profile["best_floor"] = self.run_floor
        self.result_relic_breakdown, self.result_relics = (
            self._calculate_failure_relics()
        )
        if self.run_difficulty_hard:
            # 高压远征：死亡勘定同样按倍率结算
            boosted = round(self.result_relics * DIFFICULTY_RELIC_MULTIPLIER)
            self.result_relic_breakdown = self.result_relic_breakdown + [
                ("高压远征", boosted - self.result_relics)
            ]
            self.result_relics = boosted
        scores = self.profile.get("scores", [])
        if not isinstance(scores, list):
            scores = []
        scores.append(
            {
                "score": self.result_score,
                "stage": self.run_stage,
                "floor": self.run_floor,
                "parries": self.run_parries,
                "kills": self.run_kills,
                "max_combo": self.run_max_combo,
                "relics": self.result_relics,
                "outcome": "failure",
            }
        )
        self.profile["scores"] = sorted(
            [score for score in scores if isinstance(score, dict)],
            key=lambda score: (
                int(score.get("stage", 1) or 1),
                int(score.get("floor", 0) or 0),
                int(score.get("score", 0) or 0),
            ),
            reverse=True,
        )[:20]
        self.profile["echo_relics"] = self.echo_relics + self.result_relics

        lifetime_stats = self.profile.get("lifetime_stats", {})
        if not isinstance(lifetime_stats, dict):
            lifetime_stats = {}
        lifetime_stats = lifetime_stats.copy()
        lifetime_stats["settlements"] = self._stat("settlements") + 1
        lifetime_stats["failures"] = self._stat("failures") + 1
        lifetime_stats["parries"] = self._stat("parries") + self.run_parries
        lifetime_stats["best_combo"] = max(
            self._stat("best_combo"), self.run_max_combo
        )
        self.profile["lifetime_stats"] = lifetime_stats
        self._clear_run_checkpoint()
        self._save_profile()
        self.has_save = True
        self.items = self._build_items()

        self.page = "failure"
        self.overlay = None
        self.confirm_exit = False
        self.pressed_keys.clear()
        self.pending_enemy_attacks.clear()
        self.attack_impacts.clear()
        self.shockwaves.clear()
        self._notify("记忆载体崩解，远征已终止")

    def _draw_game(self) -> None:
        shade = pygame.Surface(LOGICAL_SIZE, pygame.SRCALPHA)
        shade.fill((3, 8, 18, 80))
        self.canvas.blit(shade, (0, 0))

        briefing = self._floor_briefing(self.run_floor)
        title = self.overlay_title_font.render(
            "灰塔 · 序章试炼"
            if self.is_tutorial_run
            else f"灰塔 · 第 {self.run_stage} 阶段 · 第 {self.run_floor} 关",
            True,
            COLORS["ice"],
        )
        self.canvas.blit(title, (54, 36))
        subtitle = self.small_font.render(
            "ROOM 01  /  回响训练场"
            if self.is_tutorial_run
            else f"STAGE {self.run_stage:02d} · ROOM {self.run_floor:02d}  /  {briefing.title}",
            True,
            COLORS["cyan"],
        )
        self.canvas.blit(subtitle, (56, 78))

        if self.pending_spawn:
            self._draw_spawn_countdown()

        self._draw_vitals()
        score = self.overlay_body_font.render(
            f"分数  {self.run_score:05d}",
            True,
            COLORS["ice"],
        )
        floor = self.small_font.render(
            f"第 {self.run_stage} 阶段 · 第 {self.run_floor} 关  ·  "
            f"威胁 {round(self.run_threat * 100)}%",
            True,
            COLORS["muted"],
        )
        self.canvas.blit(score, (930, 42))
        self.canvas.blit(floor, (930, 76))
        self._draw_run_currency_ui()
        self._draw_boss_hud()

        pygame.draw.line(self.canvas, (37, 103, 103), (60, 566), (1220, 566), 2)
        gate = pygame.transform.scale(self.assets.logo, (96, 96))
        gate.set_alpha(100)
        self.canvas.blit(gate, (592, 330))
        self._draw_portal()
        self._draw_death_fades()
        self._draw_enemies()
        # 角色永远画在最上层：不会被敌人或特效盖住
        self._draw_player()
        self._draw_skill_waves()
        if self.is_tutorial_run:
            self._draw_tutorial_panel()

        room_title = self.overlay_body_font.render(
            "试炼房间已开启"
            if self.is_tutorial_run
            else f"{briefing.title}  ·  第 {self.run_stage} 阶段第 {self.run_floor} 关",
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
        elif self._is_shop_room():
            room_hint = self.small_font.render(
                "整备已经完成  ·  进入右侧回响之门继续远征",
                True,
                COLORS["muted"],
            )
        elif self._is_boss_room():
            boss = next(
                (enemy for enemy in self.room_enemies if enemy.kind in BOSS_CLASSES),
                None,
            )
            phase = getattr(boss, "phase", 1)
            room_hint = self.small_font.render(
                f"首领阶段 {phase} / 2  ·  击破区域执政者后完成当前阶段",
                True,
                COLORS["muted"],
            )
        elif self.room_type in {ROOM_EVENT, ROOM_REWARD, ROOM_SANCTUARY}:
            room_hint = self.small_font.render(
                "本关勘定完成  ·  进入右侧回响之门继续远征",
                True,
                COLORS["muted"],
            )
        else:
            wave_now = min(self.wave_index, len(self.wave_plan))
            room_hint = self.small_font.render(
                f"第 {wave_now} / {len(self.wave_plan)} 波  ·  "
                "清空全部波次后开启回响之门",
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
                f"{self._key_name(self.keybinds['skill'])} 剑气    "
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

    def _draw_boss_hud(self) -> None:
        boss = next(
            (enemy for enemy in self.room_enemies if enemy.kind in BOSS_CLASSES),
            None,
        )
        if boss is None or boss.defeated:
            return
        phase = int(getattr(boss, "phase", 1))
        bar = pygame.Rect(330, 184, 620, 18)
        pygame.draw.rect(self.canvas, (30, 13, 18), bar)
        pygame.draw.rect(
            self.canvas,
            COLORS["red"],
            (bar.x, bar.y, round(bar.width * boss.hp / max(1, boss.max_hp)), bar.height),
        )
        if hasattr(boss, "phase"):
            title_text = f"区域执政者 · {boss.display_name}    阶段 {phase}/2"
        else:
            title_text = f"区域执政者 · {boss.display_name}"
        title = self.small_font.render(
            title_text,
            True,
            COLORS["gold"] if phase == 2 else COLORS["ice"],
        )
        self.canvas.blit(title, title.get_rect(center=(bar.centerx, bar.y - 14)))
        state_text, state_color = self._boss_state_text(boss)
        if state_text:
            state = self.small_font.render(state_text, True, state_color)
            self.canvas.blit(state, state.get_rect(center=(bar.centerx, bar.bottom + 14)))

    @staticmethod
    def _boss_state_text(boss: Enemy) -> tuple[str, tuple[int, int, int]]:
        """首领血条下方的状态说明：破防 / 核心暴露等关键输出窗口。"""
        if getattr(boss, "core_exposed", False):
            remaining = float(getattr(boss, "core_exposure_remaining", 0.0))
            return f"核心暴露 · 可以造成伤害 {remaining:.1f} 秒", COLORS["cyan"]
        if getattr(boss, "defense_broken", False):
            return "破防 · 减伤失效", COLORS["cyan"]
        if boss.kind == "rust_crown_knight":
            return "全阶段减伤 80% · 三连弹刀破防", COLORS["muted"]
        if boss.kind == "broken_bridge_bell_keeper":
            return "核心未暴露 · 攻击只削韧", COLORS["muted"]
        return "", COLORS["muted"]

    def _draw_tutorial_panel(self) -> None:
        step = self._current_tutorial_step
        rect = pygame.Rect(820, 125, 380, 225)
        shade = pygame.Surface(rect.size, pygame.SRCALPHA)
        shade.fill((6, 16, 28, 226))
        self.canvas.blit(shade, rect)
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
        center = (round(self.player.x), round(self.player.y - 56))
        if self.player.skill_active:
            # 释放剑气期间：白色爆发光环提示这段时间无敌
            progress = min(
                1.0, self.player.skill_elapsed / max(0.01, Player.SKILL_CAST_TIME)
            )
            aura = pygame.Surface(LOGICAL_SIZE, pygame.SRCALPHA)
            for radius, alpha in (
                (round(72 + 26 * progress), round(120 * (1.0 - progress) + 30)),
                (round(46 + 14 * progress), round(170 * (1.0 - progress) + 50)),
            ):
                pygame.draw.circle(
                    aura,
                    (*COLORS["white"], max(0, min(255, alpha))),
                    center,
                    radius,
                    3,
                )
            self.canvas.blit(aura, (0, 0))
        elif self.energy_ready:
            # 回响能量满：身上不停闪白光，提示技能可用
            pulse = 0.5 + 0.5 * math.sin(self.elapsed * 6.5)
            aura = pygame.Surface(LOGICAL_SIZE, pygame.SRCALPHA)
            pygame.draw.circle(
                aura,
                (*COLORS["white"], round(40 + 55 * pulse)),
                center,
                round(54 + 8 * pulse),
                3,
            )
            pygame.draw.circle(
                aura,
                (*COLORS["white"], round(22 + 34 * pulse)),
                center,
                round(70 + 12 * pulse),
                1,
            )
            self.canvas.blit(aura, (0, 0))
        self.canvas.blit(player_image, (draw_x, draw_y))
        if self.player.hurt_flash > 0.0:
            # 受击闪烁：角色整体泛白，明确反馈“这一下确实吃到了”
            step = 1 + int(
                3.0 * min(1.0, self.player.hurt_flash / self.player.HURT_FLASH_TIME)
            )
            self.canvas.blit(
                self._flash_overlay(
                    f"player:{sprite_name}:{self.player.facing}",
                    player_image,
                    step,
                ),
                (draw_x, draw_y),
            )
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

    def _draw_skill_waves(self) -> None:
        """回响剑气：竖着的白色半月斩，带残留辉光向前平推。"""
        if not self.skill_waves:
            return
        layer = pygame.Surface(LOGICAL_SIZE, pygame.SRCALPHA)
        for wave in self.skill_waves:
            self._draw_skill_wave(layer, wave)
        self.canvas.blit(layer, (0, 0))

    def _draw_skill_wave(self, layer: pygame.Surface, wave: SkillWave) -> None:
        # 亮度只看「还剩多少秒」：剑气横穿整屏期间保持满亮度，
        # 只有在飞出画面之后才淡出，避免看起来像走到一半就消失了。
        fade = min(1.0, max(0.0, wave.remaining / SKILL_WAVE_FADE_TIME))

        def crescent(
            radius: float,
            thickness: float,
            alpha: int,
            offset: float = 0.0,
        ) -> None:
            """画一段半月：外弧向前凸，内弧按 cos 收窄，两端自然收尖。"""
            if alpha <= 0 or thickness <= 0.0:
                return
            outer_points: list[tuple[int, int]] = []
            inner_points: list[tuple[int, int]] = []
            for step in range(29):
                angle = -math.pi / 2 + math.pi * step / 28
                taper = math.cos(angle) ** 0.72
                for target, current in (
                    (outer_points, radius),
                    (inner_points, max(2.0, radius - thickness * taper)),
                ):
                    x = current * math.cos(angle) + offset
                    y = current * math.sin(angle)
                    target.append(
                        (
                            round(wave.x + x * wave.facing),
                            round(wave.y + y),
                        )
                    )
            pygame.draw.polygon(
                layer,
                (*COLORS["white"], alpha),
                outer_points + inner_points[::-1],
            )

        # 后方残留的弧影，强调向前推进的速度感
        for step in range(3, 0, -1):
            crescent(
                SKILL_WAVE_HALF_HEIGHT * 0.92,
                SKILL_WAVE_THICKNESS * 0.4,
                round(46 * fade / step),
                offset=-42.0 * step,
            )
        crescent(
            SKILL_WAVE_HALF_HEIGHT * 1.08,
            SKILL_WAVE_THICKNESS * 1.35,
            round(64 * fade),
        )
        crescent(
            SKILL_WAVE_HALF_HEIGHT,
            SKILL_WAVE_THICKNESS * 0.66,
            round(150 * fade),
        )
        crescent(
            SKILL_WAVE_HALF_HEIGHT * 0.94,
            SKILL_WAVE_THICKNESS * 0.3,
            round(238 * fade),
        )

        # 半月最前缘的高光
        tip = (
            round(wave.x + SKILL_WAVE_HALF_HEIGHT * 0.96 * wave.facing),
            round(wave.y),
        )
        pygame.draw.circle(layer, (*COLORS["white"], round(220 * fade)), tip, 5)
        pygame.draw.circle(layer, (*COLORS["white"], round(120 * fade)), tip, 13, 2)

    def _flash_overlay(
        self,
        name: str,
        image: pygame.Surface,
        step: int,
    ) -> pygame.Surface:
        """生成/复用精灵的白色剪影，用于受击与弹刀闪烁。"""
        cache_key = (name, step)
        cached = self._flash_cache.get(cache_key)
        if cached is None:
            alpha = 60 + step * 40
            mask = pygame.mask.from_surface(image)
            cached = mask.to_surface(
                setcolor=(255, 255, 255, min(255, alpha)),
                unsetcolor=(0, 0, 0, 0),
            )
            self._flash_cache[cache_key] = cached
        return cached

    def _draw_death_fades(self) -> None:
        """倒地淡出：敌人先向一侧倒下，再逐渐变透明消失。"""
        for fade in self.death_fades:
            ratio = max(0.0, min(1.0, fade.remaining / max(0.01, fade.total)))
            sprite = self.assets.enemy_sprites.get(fade.kind)
            fall = 1.0 - ratio
            angle = -min(78.0, 92.0 * fall) * fade.facing
            if sprite is None:
                size = (56, 56)
                body = pygame.Surface(size, pygame.SRCALPHA)
                pygame.draw.rect(body, (60, 74, 82), body.get_rect(), 3)
                image = body
            else:
                image = pygame.transform.scale(sprite, (96, 120))
                if fade.facing < 0:
                    image = pygame.transform.flip(image, True, False)
            rotated = pygame.transform.rotate(image, angle)
            if fall > 0.35:
                # 后半段贴在“地面”上，看起来是倒下而不是悬空旋转
                rotated = pygame.transform.smoothscale(
                    rotated, (rotated.get_width(), max(8, rotated.get_height() // 2))
                )
            rotated.set_alpha(round(255 * (ratio**1.4)))
            self.canvas.blit(
                rotated,
                rotated.get_rect(midbottom=(round(fade.x), round(fade.y))),
            )

    def _draw_enemies(self) -> None:
        colors = {
            "chaser": COLORS["red"],
            "spear_thrower": COLORS["gold"],
            "shield_guard": COLORS["ice"],
            "rift_worm": (166, 99, 244),
            "resonance_mage": COLORS["cyan"],
            "rust_crown_knight": COLORS["gold"],
            "broken_bridge_bell_keeper": (122, 214, 226),
        }
        for enemy in self.room_enemies:
            if enemy.defeated:
                continue
            x, y = int(enemy.x), int(enemy.y)
            sprite = self.assets.enemy_sprites.get(enemy.kind)
            if sprite is not None:
                draw_rect = sprite.get_rect(midbottom=(x, y))
                self.canvas.blit(sprite, draw_rect)
                if enemy.hurt_flash > 0.0:
                    step = 1 + int(
                        3.0 * min(1.0, enemy.hurt_flash / enemy.HURT_FLASH_TIME)
                    )
                    self.canvas.blit(
                        self._flash_overlay(f"enemy:{enemy.kind}", sprite, step),
                        draw_rect,
                    )
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

            body = pygame.Rect(
                round(x - enemy.body_width / 2),
                round(y - enemy.body_height),
                round(enemy.body_width),
                round(enemy.body_height),
            )
            color = (
                COLORS["white"]
                if enemy.hurt_flash > 0.0
                else colors.get(enemy.kind, COLORS["muted"])
            )
            pygame.draw.rect(self.canvas, (9, 25, 35), body)
            is_boss = enemy.kind in BOSS_CLASSES
            pygame.draw.rect(self.canvas, color, body, 3 if is_boss else 2)
            if enemy.kind == "rust_crown_knight":
                crown_y = body.y - 18
                pygame.draw.polygon(
                    self.canvas,
                    COLORS["gold"],
                    (
                        (body.x + 10, crown_y + 18),
                        (body.x + 18, crown_y),
                        (body.centerx, crown_y + 13),
                        (body.right - 18, crown_y),
                        (body.right - 10, crown_y + 18),
                    ),
                    3,
                )
                blade_x = body.right + 12 if enemy.facing > 0 else body.x - 12
                pygame.draw.line(
                    self.canvas,
                    COLORS["ice"],
                    (blade_x, body.y + 22),
                    (blade_x + enemy.facing * 18, body.bottom - 8),
                    6,
                )
                if getattr(enemy, "defense_broken", False):
                    pygame.draw.circle(self.canvas, COLORS["cyan"], body.center, 68, 3)
            elif enemy.kind == "broken_bridge_bell_keeper":
                # 钟体：外圈刻度环 + 中央钟摆，核心暴露时额外套一层青色光环
                pygame.draw.circle(self.canvas, color, body.center, 30, 3)
                pygame.draw.circle(self.canvas, COLORS["gold"], body.center, 6)
                pygame.draw.line(
                    self.canvas,
                    COLORS["gold"],
                    (body.centerx, body.y + 14),
                    (body.centerx + enemy.facing * 26, body.centery + 20),
                    5,
                )
                if getattr(enemy, "core_exposed", False):
                    pygame.draw.circle(self.canvas, COLORS["cyan"], body.center, 46, 3)
            else:
                eye_x = x + (7 if enemy.facing > 0 else -12)
                pygame.draw.rect(self.canvas, color, (eye_x, y - 32, 8, 5))

            if is_boss:
                continue
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
            if pending.profile.tag == "boss_memory_sever":
                self._draw_boss_decree_telegraph(effect, pending, enemy_center)
            elif pending.profile.projectile_speed is not None:
                self._draw_projectile_telegraph(effect, pending)
            elif pending.profile.parryable:
                self._draw_melee_parry_flash(
                    effect,
                    enemy_center,
                    pending.remaining,
                    pending.profile.parry_window,
                )
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

        for wave in self.shockwaves:
            progress = 1.0 - max(
                0.0,
                min(1.0, wave.remaining / max(0.001, wave.total)),
            )
            radius = round(wave.radius * (0.35 + 0.65 * progress))
            alpha = round(230 * (1.0 - progress) ** 1.2)
            center = (round(wave.x), round(wave.y))
            pygame.draw.circle(
                effect,
                (*wave.color, alpha),
                center,
                radius,
                max(2, round(8 * (1.0 - progress) + 2)),
            )
            pygame.draw.circle(
                effect,
                (*COLORS["white"], max(0, alpha - 60)),
                center,
                max(6, round(radius * 0.45)),
                3,
            )
            for angle in range(0, 360, 30):
                radians = math.radians(angle)
                inner = radius * 0.55
                outer = radius * 0.92
                start = (
                    round(center[0] + math.cos(radians) * inner),
                    round(center[1] + math.sin(radians) * inner),
                )
                end = (
                    round(center[0] + math.cos(radians) * outer),
                    round(center[1] + math.sin(radians) * outer),
                )
                pygame.draw.line(effect, (*wave.color, alpha), start, end, 3)
            if wave.label:
                label = self.small_font.render(wave.label, True, COLORS["ice"])
                label.set_alpha(alpha)
                effect.blit(
                    label,
                    label.get_rect(center=(center[0], center[1] - radius - 12)),
                )

        self.canvas.blit(effect, (0, 0))

    def _draw_boss_decree_telegraph(
        self,
        effect: pygame.Surface,
        pending: PendingEnemyAttack,
        enemy_center: tuple[int, int],
    ) -> None:
        """A full-field gold/crimson warning reserved for the lethal boss decree."""
        duration = max(0.001, pending.profile.telegraph_time)
        progress = 1.0 - max(0.0, min(1.0, pending.remaining / duration))
        pulse = 0.5 + 0.5 * math.sin(self.elapsed * 18.0)
        alpha = round(45 + progress * 70 + pulse * 35)
        pygame.draw.rect(effect, (190, 42, 48, alpha), (0, 0, *LOGICAL_SIZE), 12)
        center = (round(self.player.x), round(self.player.y - 54))
        radius = round(170 - 125 * progress)
        # 敕令的弹刀窗口比普通近战更短：提示光也要跟着收紧
        window = pending.profile.parry_window or MELEE_FLASH_LEAD
        window_open = pending.remaining <= window
        signal_color = COLORS["gold"] if window_open else COLORS["red"]
        pygame.draw.circle(effect, (*signal_color, 190), center, max(28, radius), 6)
        pygame.draw.line(
            effect,
            (*signal_color, 210),
            enemy_center,
            center,
            max(3, round(3 + progress * 7)),
        )
        marker = self.overlay_body_font.render(
            "断忆敕令 · 弹刀" if window_open else "断忆敕令 · 即将发动",
            True,
            signal_color,
        )
        marker.set_alpha(min(255, round(150 + pulse * 105)))
        effect.blit(marker, marker.get_rect(center=(640, 370)))

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
        window: float | None = None,
    ) -> None:
        """近战提示：闪光亮起后的这段时间内按弹刀即可完美弹反。"""
        gold = COLORS["gold"]
        # 首领连段之类可以指定更短的弹刀窗口，提示闪光必须与之一致
        lead = MELEE_FLASH_LEAD if window is None else window
        flash_age = lead - remaining
        if flash_age < 0.0:
            # 闪光尚未亮起：只留一个暗金色信号，避免和弹刀窗口混淆
            pygame.draw.circle(effect, (*gold, 55), center, 11, 2)
            pygame.draw.circle(effect, (*gold, 80), center, 3)
            return

        progress = max(0.0, min(1.0, flash_age / max(0.001, lead)))
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
        text: str = "",
        highlight: bool = False,
    ) -> None:
        label_text = self.small_font.render(label, True, COLORS["muted"])
        self.canvas.blit(label_text, (x - label_text.get_width() - 14, y - 3))
        bar = pygame.Rect(x, y, width, height)
        pygame.draw.rect(self.canvas, (19, 42, 50), bar)
        clamped = max(0.0, min(1.0, ratio))
        pygame.draw.rect(
            self.canvas,
            color,
            (bar.x, bar.y, round(bar.width * clamped), bar.height),
        )
        if highlight:
            glow = pygame.Surface(bar.size, pygame.SRCALPHA)
            glow.fill((*COLORS["white"], 40))
            self.canvas.blit(glow, bar)
        if text and height >= 14:
            value = self.small_font.render(text, True, COLORS["white"])
            self.canvas.blit(value, value.get_rect(center=bar.center))

    def _draw_vitals(self) -> None:
        """左上角状态区：生命值、等级经验与回响能量都带具体数值。"""
        player = self.player
        hp_ratio = player.hp / player.max_hp if player.max_hp else 0.0
        self._draw_stat_bar(
            "生命",
            104,
            102,
            238,
            18,
            hp_ratio,
            COLORS["red"],
            text=f"{player.hp} / {player.max_hp}",
            highlight=hp_ratio <= 0.3,
        )
        self._draw_stat_bar(
            "经验",
            104,
            128,
            238,
            10,
            self.player_exp / max(1, self.exp_to_next),
            COLORS["gold"],
        )
        self.canvas.blit(
            self.small_font.render(f"Lv.{self.player_level}", True, COLORS["gold"]),
            (350, 120),
        )
        self.canvas.blit(
            self.small_font.render(
                f"{self.player_exp} / {self.exp_to_next}", True, COLORS["muted"]
            ),
            (404, 120),
        )
        # 能量满时整条转白并闪光，提示技能已就绪
        ready = self.energy_ready
        self._draw_stat_bar(
            "回响能量",
            104,
            150,
            238,
            18,
            self.echo_energy / ECHO_ENERGY_MAX,
            COLORS["white"] if ready else COLORS["cyan"],
            text=(
                f"{self.echo_energy} / {ECHO_ENERGY_MAX}   剑气就绪"
                if ready
                else f"{self.echo_energy} / {ECHO_ENERGY_MAX}"
            ),
            highlight=ready,
        )

    def _draw_result(self) -> None:
        """通关结算：一局结束后的成果清单。"""
        shade = pygame.Surface(LOGICAL_SIZE, pygame.SRCALPHA)
        shade.fill((3, 8, 18, 170))
        self.canvas.blit(shade, (0, 0))
        title = self.title_font.render("第二阶段 · 通关", True, COLORS["ice"])
        self.canvas.blit(title, title.get_rect(center=(640, 150)))
        subtitle = self.subtitle_font.render(
            "灰塔第二阶段七关已贯通  /  记忆重构完成",
            True,
            COLORS["gold"],
        )
        self.canvas.blit(subtitle, subtitle.get_rect(center=(640, 196)))

        panel = pygame.Rect(330, 236, 620, 300)
        pygame.draw.rect(self.canvas, (6, 16, 28), panel)
        pygame.draw.rect(self.canvas, (42, 105, 106), panel, 2)
        heading = self.small_font.render("本局结算", True, COLORS["cyan"])
        self.canvas.blit(heading, (panel.x + 30, panel.y + 18))
        for index, (label, value) in enumerate(self._settlement_rows()):
            y = panel.y + 58 + index * 38
            self.canvas.blit(
                self.overlay_body_font.render(label, True, COLORS["muted"]),
                (panel.x + 40, y),
            )
            value_color = COLORS["gold"] if label == "获得技能点" else COLORS["ice"]
            value_text = self.overlay_body_font.render(value, True, value_color)
            self.canvas.blit(
                value_text,
                (panel.right - value_text.get_width() - 40, y),
            )

        self._draw_ui_button(self._page_buttons()["lobby"], "返回灰塔大厅")
        hint = self.small_font.render(
            "Enter / Space 返回大厅  ·  下一局从第一层重新开始",
            True,
            COLORS["muted"],
        )
        self.canvas.blit(hint, hint.get_rect(center=(640, 656)))
        self._draw_notification()

    def _settlement_rows(self) -> list[tuple[str, str]]:
        """结算清单：本局走到哪、拿到多少、打得怎么样。"""
        return [
            ("抵达关卡", f"第 {self.run_stage} 阶段 · 第 {self.run_floor} 关"),
            ("获得技能点", f"+{self.result_relics} 回响遗晶"),
            ("击败敌人", f"{self.run_kills}"),
            ("完美弹刀", f"{self.run_parries}"),
            ("最高连击", f"x{self.run_max_combo}"),
            ("本局分数", f"{self.result_score:05d}"),
        ]

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

        panel = pygame.Rect(300, 278, 680, 230)
        pygame.draw.rect(self.canvas, (10, 13, 24), panel)
        pygame.draw.rect(self.canvas, (133, 55, 66), panel, 2)
        pygame.draw.line(
            self.canvas,
            (68, 56, 70),
            (panel.centerx, panel.y + 22),
            (panel.centerx, panel.bottom - 22),
            1,
        )

        performance_title = self.small_font.render(
            "本局表现", True, COLORS["red"]
        )
        reward_title = self.small_font.render(
            "遗晶勘定", True, COLORS["gold"]
        )
        self.canvas.blit(performance_title, (panel.x + 30, panel.y + 18))
        self.canvas.blit(reward_title, (panel.centerx + 28, panel.y + 18))

        performance_rows = [
            ("本局分数", f"{self.result_score:05d}"),
            ("抵达层数", str(self.run_floor)),
            ("最高连击", f"x{self.run_max_combo}"),
            ("完美弹刀", str(self.run_parries)),
            ("击败敌人", str(self.run_kills)),
        ]
        for index, (label, value) in enumerate(performance_rows):
            y = panel.y + 52 + index * 31
            self.canvas.blit(
                self.small_font.render(label, True, COLORS["muted"]),
                (panel.x + 30, y),
            )
            value_color = COLORS["ice"]
            value_text = self.overlay_body_font.render(value, True, value_color)
            self.canvas.blit(
                value_text,
                (panel.centerx - value_text.get_width() - 28, y - 5),
            )

        if self.result_relic_breakdown:
            for index, (label, value) in enumerate(self.result_relic_breakdown):
                y = panel.y + 52 + index * 27
                self.canvas.blit(
                    self.small_font.render(label, True, COLORS["muted"]),
                    (panel.centerx + 28, y),
                )
                amount = self.small_font.render(f"+{value}", True, COLORS["gold"])
                self.canvas.blit(
                    amount,
                    (panel.right - amount.get_width() - 30, y),
                )
        else:
            note = self.small_font.render(
                "教学失败不凝结遗晶", True, COLORS["muted"]
            )
            self.canvas.blit(note, (panel.centerx + 28, panel.y + 60))

        pygame.draw.line(
            self.canvas,
            (100, 82, 48),
            (panel.centerx + 28, panel.bottom - 48),
            (panel.right - 30, panel.bottom - 48),
            1,
        )
        relic_label = self.overlay_body_font.render(
            "本次凝结", True, COLORS["ice"]
        )
        relic_value = self.overlay_body_font.render(
            f"+{self.result_relics}", True, COLORS["gold"]
        )
        self.canvas.blit(relic_label, (panel.centerx + 28, panel.bottom - 38))
        self.canvas.blit(
            relic_value,
            (panel.right - relic_value.get_width() - 30, panel.bottom - 38),
        )
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
        total = max(0.001, self.spawn_countdown_total)
        ratio = 1.0 - max(0.0, min(1.0, remaining / total))
        panel = pygame.Rect(0, 0, 320, 96)
        panel.center = (640, 132)

        layer = pygame.Surface(panel.size, pygame.SRCALPHA)
        layer.fill((6, 16, 28, 208))
        pulse = 0.5 + 0.5 * math.sin(self.elapsed * 7.0)

        title = self.small_font.render(
            self.spawn_countdown_label, True, COLORS["gold"]
        )
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
