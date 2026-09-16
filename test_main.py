import json
import os
import hashlib

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

import main
from game.entities import (
    ENEMY_CLASSES,
    Chaser,
    Enemy,
    Player,
    ResonanceMage,
    RiftWorm,
    RustCrownKnight,
    ShieldGuard,
    SpearThrower,
)
from main import PendingEnemyAttack, StartScreen


class _RecordingAudio:
    """测试替身：记录游戏请求播放的音乐与音效。"""

    def __init__(self) -> None:
        self.played: list[str] = []
        self.music: list[str] = []
        self.volume: int | None = None
        self.duck_count = 0

    def play(self, name: str, volume: float = 1.0) -> None:
        self.played.append(name)

    def play_swing(self, stage: int) -> None:
        self.played.append(f"swing_{max(1, min(3, int(stage)))}")

    def play_music(self, track: str | None, fade: float = 1.0) -> None:
        self.music.append(track or "none")

    def set_volume(self, percent: int) -> None:
        self.volume = percent

    def duck(self, amount: float = 0.45, duration: float = 0.28) -> None:
        self.duck_count += 1

    def update(self, dt: float) -> None:
        return None

    def shutdown(self) -> None:
        return None


def _app_with_recording_audio(monkeypatch, tmp_path):
    """创建 StartScreen 并把音频替换成记录器，返回 (app, recorder)。"""
    monkeypatch.setattr(main, "SAVE_FILE", tmp_path / "save.json")
    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)
    recorder = _RecordingAudio()
    app.audio = recorder
    return app, recorder


def _enter_level(app, floor: int = 1, *, tutorial: bool = False):
    """进入关卡并跳过刷怪等待，便于测试战斗逻辑本身。"""
    app._start_run(floor, tutorial=tutorial)
    app._dismiss_floor_intro()
    app._spawn_pending_enemies()
    return app


def _start_expedition(app, seconds: float = 2.0):
    """从大厅点城门出发，并把漩涡过场动画走完。"""
    app._activate_lobby_action(0)
    _advance(app, seconds)
    return app


def _grant_tracks(app, **levels) -> None:
    """直接点亮技能树分支，省去逐级升级的操作。"""
    progression = app.profile.setdefault("progression", {})
    progression["version"] = 2
    stored = progression.setdefault("levels", {})
    stored.update(levels)
    app.profile["echo_relics"] = max(0, app.echo_relics)
    app._save_profile()


def _clear_room(app) -> None:
    """清空整层：敌人、待登场的一波以及后面还没排到的波次。"""
    app.room_enemies.clear()
    app.pending_spawn.clear()
    app.wave_plan = []
    app.wave_index = 0


def _advance(app, seconds: float, step: float = 1.0 / 60.0) -> None:
    for _ in range(max(1, int(round(seconds / step)))):
        app._update(step)


def _saved_slot(save_file) -> dict:
    """读回存档文件里的当前槽位：设置是全局的，进度按槽位分开保存。"""
    data = json.loads(save_file.read_text(encoding="utf-8"))
    return data["slots"][data["active_slot"]]


def _countdown_panel_digest(app) -> str:
    """把倒计时面板区域画一遍并取指纹，用来验证它确实在随时间变化。"""
    app._draw()
    region = pygame.Rect(480, 84, 320, 96)
    raw = pygame.image.tobytes(app.canvas.subsurface(region), "RGB")
    return hashlib.sha1(raw).hexdigest()


def test_font_loader_survives_broken_windows_font_registry(monkeypatch, tmp_path):
    monkeypatch.setenv("WINDIR", str(tmp_path))

    def broken_sysfont(*args, **kwargs):
        raise TypeError("expected str, bytes or os.PathLike object, not int")

    monkeypatch.setattr(pygame.font, "SysFont", broken_sysfont)
    pygame.init()

    font = StartScreen._font(18, bold=True)

    assert isinstance(font, pygame.font.Font)
    assert font.render("fallback", True, (255, 255, 255)).get_width() > 0
    pygame.quit()


def test_start_screen_menu_states(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "SAVE_FILE", tmp_path / "save.json")

    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)

    assert len(app.items) == 5
    first_enabled = next(index for index, item in enumerate(app.items) if item.enabled)
    assert app.selected == first_enabled

    app._handle_key(pygame.K_DOWN)
    expected_after_down = 1 if first_enabled == 0 else 2
    assert app.selected == expected_after_down
    app._handle_key(pygame.K_UP)
    assert app.selected == first_enabled

    app._handle_key(pygame.K_RIGHT)
    assert app.overlay is None
    app._activate(3)
    assert app.overlay == "settings"
    app._handle_key(pygame.K_a)
    assert app.settings["assist_mode"] is True
    app._handle_key(pygame.K_ESCAPE)
    assert app.overlay is None

    app._activate(4)
    assert app.confirm_exit is True
    app._handle_key(pygame.K_n)
    assert app.confirm_exit is False

    pygame.quit()


def test_design_enemy_types_are_directly_instantiable():
    assert set(ENEMY_CLASSES) == {
        "chaser",
        "spear_thrower",
        "shield_guard",
        "rift_worm",
        "resonance_mage",
    }

    for enemy_class in ENEMY_CLASSES.values():
        enemy = enemy_class(100, 220, threat=0.25)

        assert isinstance(enemy, Enemy)
        assert enemy.position == (100.0, 220.0)
        assert enemy.hp == enemy.max_hp
        assert enemy.damage >= enemy.attack_profile.damage
        assert enemy.display_name
        assert enemy.parry_tutorial


def test_enemy_intents_match_game_design_roles():
    assert Chaser(100, 0).update(0.016, (130, 0)).action == "triple_slash"

    spear_intent = SpearThrower(100, 0).update(0.016, (360, 0))
    assert spear_intent.action == "throw_spear"
    assert spear_intent.attack is not None
    assert spear_intent.attack.projectile_speed is not None
    assert spear_intent.attack.parryable is True

    assert ShieldGuard(100, 0).update(0.016, (135, 0)).action == "shield_bash"

    worm_intent = RiftWorm(100, 0).update(0.016, (260, 0))
    assert worm_intent.action == "rift_charge"
    assert worm_intent.attack is not None
    assert worm_intent.attack.parryable is False
    assert worm_intent.attack.warning_color == "purple"

    mage_intent = ResonanceMage(100, 0).update(0.016, (360, 0))
    assert mage_intent.action == "cast_delayed_orb"
    assert mage_intent.attack is not None
    assert mage_intent.attack.name == "延迟能量球"


def test_resonance_mage_keeps_fighting_at_any_distance():
    """共鸣法师不会因为离得太远就发呆，也不会被逼到画面边缘后卡死。"""
    # 远距离：主动靠近缩短施法距离，而不是站着不动
    far = ResonanceMage(1180, 522)
    far_intent = far.update(0.016, (80.0, 522.0))
    assert far_intent.action == "advance"
    assert far_intent.move_x < 0

    # 中距离：正常施法
    mid = ResonanceMage(600, 522)
    assert mid.update(0.016, (900.0, 522.0)).action == "cast_delayed_orb"

    # 贴脸且身后有余地：后撤保持施法距离
    backoff = ResonanceMage(600, 522)
    assert backoff.update(0.016, (700.0, 522.0)).action == "blink_back"

    # 贴脸且已经贴到画面边缘：就地施法，不再徒劳后撤
    cornered = ResonanceMage(45, 522)
    cornered_intent = cornered.update(0.016, (200.0, 522.0))
    assert cornered_intent.action == "cast_delayed_orb"
    assert cornered_intent.attack is not None

    right_corner = ResonanceMage(1235, 522)
    right_intent = right_corner.update(0.016, (1080.0, 522.0))
    assert right_intent.action == "cast_delayed_orb"


def test_resonance_mage_walks_into_range_instead_of_standing_still():
    mage = ResonanceMage(1180, 522)
    player_position = (80.0, 522.0)
    start_x = mage.x

    for _ in range(900):
        mage.update(1.0 / 60.0, player_position)

    assert mage.x < start_x - 150.0
    assert mage.distance_to(player_position) <= mage.attack_profile.reach


def test_cornered_enemies_do_not_freeze_at_the_wall():
    """贴到画面边缘的远程敌人要就地反击，不能永远重复后撤动作。"""
    thrower = SpearThrower(45, 522)
    intent = thrower.update(0.016, (100.0, 522.0))

    assert intent.action == "throw_spear"
    assert intent.attack is not None


def test_shield_guard_blocks_front_damage_only():
    guard = ShieldGuard(100, 0, facing=1)

    front_damage = guard.take_damage(30, source_x=140)
    back_damage = guard.take_damage(30, source_x=60)

    assert front_damage < 30
    assert back_damage == 30


def test_perfect_parry_opens_vulnerability_and_reflects_damage():
    enemy = Chaser(100, 0)

    reflected_damage = enemy.on_parried(perfect=True)

    assert reflected_damage == round(enemy.damage * 1.5)
    assert enemy.vulnerable is True
    assert enemy.update(0.1, (120, 0)).action == "vulnerable"


def test_player_moves_accelerates_faces_and_stops_at_bounds():
    player = Player(300, 566)

    player.update(0.1, 1)
    assert player.x > 300
    assert player.velocity_x > 0
    assert player.facing == 1

    for _ in range(360):
        player.update(1.0 / 60.0, 1)
    assert player.x == player.bounds_right
    # 战斗区横跨整块画面：左右只被屏幕边界挡住
    assert player.bounds_right >= 1200.0
    assert player.bounds_left <= 80.0

    player.update(0.1, -1)
    assert player.facing == -1


def test_player_jump_uses_gravity_and_lands():
    player = Player(300, 566)

    assert player.request_jump() is True
    player.update(0.016, 0)
    assert player.grounded is False
    assert player.y < player.ground_y

    for _ in range(120):
        player.update(0.016, 0)
        if player.grounded:
            break

    assert player.grounded is True
    assert player.y == player.ground_y
    assert player.velocity_y == 0


def test_air_jump_is_locked_by_default_and_refreshes_after_landing():
    player = Player(300, 566)
    player.request_jump()
    player.update(0.016, 0)

    assert player.request_jump() is False

    player.unlock_air_jump()
    player.update(0.05, 0)
    assert player.request_jump() is True
    assert player.velocity_y == -player.JUMP_SPEED
    player.update(0.05, 0)
    assert player.request_jump() is False

    for _ in range(180):
        player.update(1.0 / 60.0, 0)
        if player.grounded:
            break
    player.request_jump()
    player.update(0.016, 0)
    assert player.request_jump() is True


def test_player_parry_locks_movement_and_other_actions():
    player = Player(300, 566)
    player.velocity_x = 180

    assert player.start_parry() is True
    player.update(0.05, 1)

    assert player.x == 300
    assert player.velocity_x == 0
    assert player.request_jump() is False
    assert player.dash() is False
    assert player.start_attack() is False

    player.update(player.PARRY_DURATION, 0)
    assert player.parry_active is False


def test_parry_without_incoming_hit_does_not_count(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "SAVE_FILE", tmp_path / "save.json")
    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)
    app._start_run(1)

    app._handle_key(app.keybinds["parry"])

    assert app.player.parry_active is True
    assert app.run_parries == 0
    pygame.quit()


def test_perfect_parry_negates_hit_and_reflects_damage(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "SAVE_FILE", tmp_path / "save.json")
    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)
    app._start_run(1, tutorial=False)
    enemy = Chaser(app.player.x + 40, 522)
    app.room_enemies = [enemy]
    starting_player_hp = app.player.hp
    starting_enemy_hp = enemy.hp

    app.player.start_parry()
    app.player.update(app.player.PERFECT_PARRY_WINDOW * 0.75, 1)
    app._resolve_enemy_attack(
        PendingEnemyAttack(enemy, enemy.scaled_attack(), 0.0)
    )

    assert app.player.hp == starting_player_hp
    assert enemy.hp < starting_enemy_hp
    assert app.run_parries == 1
    assert app.run_combo == 2
    pygame.quit()


def test_parry_pressed_before_the_window_does_not_negate_hit(monkeypatch, tmp_path):
    """弹刀窗口是“闪光亮起后的一段时间”，太早按不再算完美弹刀。"""
    monkeypatch.setattr(main, "SAVE_FILE", tmp_path / "save.json")
    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)
    app._start_run(1, tutorial=False)
    enemy = Chaser(app.player.x + 40, 522)
    app.room_enemies = [enemy]

    app.player.start_parry()
    app.player.update(app.player.PARRY_INPUT_BUFFER + 0.05, 0)
    app._resolve_enemy_attack(
        PendingEnemyAttack(enemy, enemy.scaled_attack(), 0.0)
    )

    assert app.player.hp == app.player.max_hp - enemy.damage
    assert enemy.hp == enemy.max_hp
    assert app.run_parries == 0
    pygame.quit()


def test_non_parryable_attack_hits_during_perfect_window(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "SAVE_FILE", tmp_path / "save.json")
    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)
    app._start_run(1, tutorial=False)
    enemy = RiftWorm(app.player.x + 40, 522)
    app.room_enemies = [enemy]

    app.player.start_parry()
    app._resolve_enemy_attack(
        PendingEnemyAttack(enemy, enemy.scaled_attack(), 0.0)
    )

    assert app.player.hp == app.player.max_hp - enemy.damage
    assert enemy.hp == enemy.max_hp
    assert app.run_parries == 0
    pygame.quit()


def test_player_three_hit_attack_has_active_hitbox():
    player = Player(300, 566)

    assert player.start_attack() is True
    player.update(0.1, 0)
    assert player.attack_stage == 1
    assert player.attack_active is True
    assert player.attack_hitbox is not None

    player.update(0.4, 0)
    assert player.attack_in_progress is False
    assert player.start_attack() is True
    assert player.attack_stage == 2

    player.update(0.4, 0)
    assert player.start_attack() is True
    assert player.attack_stage == 3


def test_player_up_and_down_attack_hitboxes_follow_direction():
    player = Player(300, 566)

    player.facing = -1
    player.start_attack("side")
    player.update(0.1, 0)
    side_hitbox = player.attack_hitbox
    assert side_hitbox is not None
    assert side_hitbox.right <= player.x

    player.update(0.4, 0)
    player.start_attack("up")
    player.update(0.1, 0)
    up_hitbox = player.attack_hitbox
    assert up_hitbox is not None
    assert up_hitbox.bottom <= player.y - player.BODY_HEIGHT
    assert up_hitbox.top < up_hitbox.bottom

    player.update(0.4, 0)
    player.start_attack("down")
    player.update(0.1, 0)
    down_hitbox = player.attack_hitbox
    assert down_hitbox is not None
    assert down_hitbox.top == player.y
    assert down_hitbox.bottom > player.y


def test_game_attack_damages_enemy(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "SAVE_FILE", tmp_path / "save.json")

    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)
    _enter_level(app)
    enemy = app.room_enemies[0]
    starting_hp = enemy.hp

    app._start_player_attack()
    app.player.update(0.1, 0)
    app._resolve_player_attack()

    assert enemy.hp < starting_hp
    assert app.run_score > 0
    assert app.run_currency >= 2
    pygame.quit()


def test_enemy_attack_telegraph_draws_visible_timing_effect(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "SAVE_FILE", tmp_path / "save.json")
    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)
    app._start_run(1, tutorial=False)
    enemy = Chaser(app.player.x + 40, 522)
    app.room_enemies = [enemy]
    app.pending_enemy_attacks = [
        PendingEnemyAttack(
            enemy,
            enemy.scaled_attack(),
            app.player.PERFECT_PARRY_WINDOW * 0.5,
        )
    ]
    app.canvas.fill((0, 0, 0))

    app._draw_enemy_attack_effects()

    assert pygame.mask.from_threshold(
        app.canvas,
        (0, 0, 0),
        threshold=(1, 1, 1, 255),
    ).count() < app.canvas.get_width() * app.canvas.get_height()
    pygame.quit()


def test_unlocked_reserve_carry_grants_starting_run_currency(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "SAVE_FILE", tmp_path / "save.json")
    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)
    app.profile = app._new_profile()
    app.profile["progression"]["levels"] = {"reserve_carry": 3}

    app._start_run(1, tutorial=False)

    assert app.run_currency == 15
    pygame.quit()


def test_defeated_enemy_is_removed_from_active_room(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "SAVE_FILE", tmp_path / "save.json")

    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)
    _enter_level(app)
    enemy = app.room_enemies[0]
    enemy.hp = 1

    app._start_player_attack()
    app.player.update(0.1, 0)
    app._resolve_player_attack()
    score_after_defeat = app.run_score

    assert enemy.hp == 0
    assert enemy not in app.room_enemies

    app._resolve_player_attack()
    assert app.run_score == score_after_defeat
    pygame.quit()


def test_lethal_enemy_attack_opens_failure_settlement_and_returns_lobby(
    monkeypatch, tmp_path
):
    save_file = tmp_path / "save.json"
    monkeypatch.setattr(main, "SAVE_FILE", save_file)
    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)
    app._start_run(2, tutorial=False)
    app._dismiss_floor_intro()
    enemy = Chaser(app.player.x + 40, 522)
    app.room_enemies = [enemy]
    app.player.hp = enemy.damage
    app.run_score = 420
    app.run_currency = 17
    app._save_run_checkpoint()
    app.pending_enemy_attacks = [
        PendingEnemyAttack(enemy, enemy.scaled_attack(), 0.001)
    ]

    app._update(1.0 / 60.0)

    assert app.player.hp == 0
    assert app.page == "failure"
    assert app.result_score == 420
    assert app.result_relics == 21
    assert dict(app.result_relic_breakdown) == {
        "残响底蕴": 10,
        "分数折算": 1,
        "层级进度": 10,
        "连击技艺": 0,
        "弹刀技艺": 0,
    }
    assert app.pending_enemy_attacks == []
    assert app._stat("failures") == 1
    assert app._active_run_checkpoint() is None
    assert _saved_slot(save_file)["echo_relics"] == 21
    assert _saved_slot(save_file)["active_run"] is None

    app._handle_key(pygame.K_RETURN)
    assert app.page == "lobby"
    assert app.run_currency == 0
    pygame.quit()


def test_tutorial_failure_does_not_grant_relics(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "SAVE_FILE", tmp_path / "save.json")
    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)
    app._start_run(1, tutorial=True)

    app.player.hp = 0
    app._fail_run()

    assert app.page == "failure"
    assert app.result_relics == 0
    assert app.echo_relics == 0
    assert app.tutorial_completed is False
    pygame.quit()


def test_successful_settlement_clears_active_expedition_checkpoint(
    monkeypatch, tmp_path
):
    save_file = tmp_path / "save.json"
    monkeypatch.setattr(main, "SAVE_FILE", save_file)
    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)
    app.profile = app._new_profile()
    app._start_run(2, tutorial=False)
    app._save_run_checkpoint()

    app._settle_run()

    assert app._active_run_checkpoint() is None
    assert _saved_slot(save_file)["active_run"] is None
    pygame.quit()


def test_initial_room_move_and_jump_use_game_loop_input(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "SAVE_FILE", tmp_path / "save.json")

    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)
    app._start_run(1)
    starting_x = app.player.x

    assert app.room_enemies == []

    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_d))
    app._handle_events()

    for _ in range(60):
        app._update(1.0 / 60.0)

    assert app.page == "game"
    assert app.player.x > starting_x + 100

    pygame.event.post(pygame.event.Event(pygame.KEYUP, key=pygame.K_d))
    pygame.event.post(
        pygame.event.Event(pygame.KEYDOWN, key=app.keybinds["jump"])
    )
    app._handle_events()
    for _ in range(6):
        app._update(1.0 / 60.0)

    assert app.player.grounded is False
    assert app.player.y < app.player.ground_y
    pygame.quit()


def test_tutorial_keeps_a_d_as_fallback_after_rebinding(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "SAVE_FILE", tmp_path / "save.json")

    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)
    app.keybinds["left"] = pygame.K_q
    app.keybinds["right"] = pygame.K_e
    app._start_run(1)
    starting_x = app.player.x

    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_d))
    app._handle_events()
    for _ in range(20):
        app._update(1.0 / 60.0)

    assert app.player.x > starting_x
    pygame.quit()


def test_down_attack_hit_bounces_player_up(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "SAVE_FILE", tmp_path / "save.json")

    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)
    _enter_level(app)
    app.player.x = app.room_enemies[0].x
    app.player.y = 500
    app.player.grounded = False
    app.player.velocity_x = -120
    enemy = app.room_enemies[0]
    app.pressed_keys.add(pygame.K_s)

    for _ in range(3):
        hp_before = enemy.hp
        pygame.event.post(
            pygame.event.Event(pygame.KEYDOWN, key=app.keybinds["attack"])
        )
        app._handle_events()
        assert app.player.attack_direction == "down"

        for _ in range(20):
            app._update(1.0 / 60.0)
            if enemy.hp < hp_before and app.player.velocity_y < 0:
                break

        assert enemy.hp < hp_before
        assert app.player.velocity_y < 0
        assert app.player.grounded is False
        while app.player.attack_in_progress:
            app._update(1.0 / 60.0)
            assert app.player.y < app.player.ground_y
    pygame.quit()


def test_mouse_attack_uses_directional_input(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "SAVE_FILE", tmp_path / "save.json")

    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)
    app._start_run(1)

    app.pressed_keys.add(pygame.K_s)
    pygame.event.post(
        pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            button=1,
            pos=(400, 400),
        )
    )
    app._handle_events()

    assert app.player.attack_direction == "down"
    pygame.quit()


def test_initial_room_tutorial_progresses_in_order(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "SAVE_FILE", tmp_path / "save.json")

    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)
    app._start_run(1)

    assert app._current_tutorial_step.action == "move"
    app._activate_page_button("finish")
    assert app.page == "game"

    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_d))
    app._handle_events()
    for _ in range(30):
        app._update(1.0 / 60.0)
    assert app._current_tutorial_step.action == "jump"

    pygame.event.post(pygame.event.Event(pygame.KEYUP, key=pygame.K_d))
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=app.keybinds["jump"]))
    app._handle_events()
    app._update(1.0 / 60.0)
    assert app._current_tutorial_step.action == "attack"
    assert len(app.room_enemies) == 2

    app._handle_key(app.keybinds["attack"])
    assert app._current_tutorial_step.action == "up_attack"

    app.player.update(0.4, 0)
    app.pressed_keys.add(pygame.K_w)
    app._handle_key(app.keybinds["attack"])
    assert app._current_tutorial_step.action == "down_attack"

    app.player.update(0.4, 0)
    app.pressed_keys.discard(pygame.K_w)
    app.pressed_keys.add(pygame.K_s)
    app.player.x = app.room_enemies[0].x
    app.player.y = 500
    app.player.grounded = False
    app._handle_key(app.keybinds["attack"])
    for _ in range(20):
        app._update(1.0 / 60.0)
        if app._current_tutorial_step.action == "parry":
            break
    assert app._current_tutorial_step.action == "parry"

    for _ in range(30):
        app._update(1.0 / 60.0)
        if (
            app.pending_enemy_attacks
            and app.pending_enemy_attacks[0].remaining
            <= app.player.PERFECT_PARRY_WINDOW * 0.75
        ):
            break
    assert app.pending_enemy_attacks

    app._handle_key(app.keybinds["parry"])
    for _ in range(10):
        app._update(1.0 / 60.0)
        if app._current_tutorial_step.action == "energy":
            break
    assert app._current_tutorial_step.action == "energy"

    # 回响能量步骤：教学关把能量推到只差一次行动，攒满才能进入剑气步骤
    assert app.echo_energy == main.ECHO_ENERGY_MAX - main.ENERGY_GAIN_PARRY
    target = app.room_enemies[0]
    app.player.start_parry()
    app.player.update(app.player.PERFECT_PARRY_WINDOW * 0.75, 1)
    app._resolve_enemy_attack(
        PendingEnemyAttack(target, target.scaled_attack(), 0.0)
    )
    assert app.echo_energy == main.ECHO_ENERGY_MAX
    for _ in range(10):
        app._update(1.0 / 60.0)
        if app._current_tutorial_step.action == "skill":
            break
    assert app._current_tutorial_step.action == "skill"

    # 回响剑气步骤：能量满时按下技能键即可斩出剑气（弹刀收招后才能出招）
    app.player.update(app.player.PARRY_DURATION, 0)
    app._handle_key(app.keybinds["skill"])
    assert app._current_tutorial_step.action == "finish"

    app._activate_page_button("finish")
    assert app.page == "lobby"
    assert app.tutorial_completed is True
    assert app.echo_relics == 40
    pygame.quit()


def test_tutorial_completion_enters_lobby_and_lobby_starts_new_run(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "SAVE_FILE", tmp_path / "save.json")

    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)
    app._start_run(1, tutorial=True)
    app.tutorial_index = len(app.tutorial_steps) - 1
    app._activate_page_button("finish")

    assert app.page == "lobby"
    assert app.is_tutorial_run is True
    assert app.echo_relics == 40

    _start_expedition(app)
    assert app.page == "game"
    assert app.is_tutorial_run is False
    assert app.run_floor == 1
    assert app.tutorial_index == len(app.tutorial_steps) - 1
    assert app._active_run_checkpoint()["floor"] == 1
    pygame.quit()


def test_lobby_without_checkpoint_ignores_historical_best_floor(
    monkeypatch, tmp_path
):
    """历史最高层只是纪录，不能把远征起点顶上去；起点由 progress_floor 决定。"""
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    app.profile = app._new_profile()
    app.profile["tutorial_completed"] = True
    app.profile["best_floor"] = 5
    app._enter_lobby()

    _start_expedition(app)

    assert app.page == "game"
    assert app.run_floor == 1
    assert app._active_run_checkpoint()["floor"] == 1
    assert "第一层第一关" in app.notification
    pygame.quit()


def test_lobby_gate_plays_the_vortex_before_entering_the_level(monkeypatch, tmp_path):
    """点城门先播漩涡过场：动画期间还在大厅，走完才真正进入关卡。"""
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    app.profile = app._new_profile()
    app.profile["tutorial_completed"] = True
    app._enter_lobby()

    app._activate_lobby_action(0)
    assert app.transition is not None
    assert app.page == "lobby"
    app._draw()

    _advance(app, 1.6)

    assert app.transition is None
    assert app.page == "game"
    assert app.run_floor == 1
    pygame.quit()


def test_failure_sends_the_next_expedition_back_to_the_first_floor(
    monkeypatch, tmp_path
):
    """一局=从第一层打到失败或通关：死亡结算之后，下一局重新从第一层开始。"""
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    app.profile = app._new_profile()
    app.profile["tutorial_completed"] = True
    _enter_level(app, floor=3)
    app.player.hp = 0
    app._fail_run()

    assert app.page == "failure"
    assert app._active_run_checkpoint() is None

    app._enter_lobby()
    assert app._lobby_actions()[0][1] == "开启新远征"
    _start_expedition(app)

    assert app.page == "game"
    assert app.run_floor == 1
    assert app._active_run_checkpoint()["floor"] == 1
    pygame.quit()


def test_clearing_the_final_floor_opens_the_clear_settlement(monkeypatch, tmp_path):
    """闯过第五层算通关：一局结束并弹出结算界面，下一局再从第一层开始。"""
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    app.profile = app._new_profile()
    app.profile["tutorial_completed"] = True
    _enter_level(app, floor=5)
    boss = app.room_enemies[0]
    boss.hp = 0
    app._award_enemy_defeat(boss)
    app.room_enemies.clear()
    app.pending_spawn.clear()
    app.wave_plan = []
    app.wave_index = 0

    app._open_portal_choice()
    app._activate_portal_choice(1)

    assert app.page == "result"
    assert app.result_cleared is True
    assert app._active_run_checkpoint() is None
    rows = dict(app._settlement_rows())
    assert rows["抵达关卡"] == "第 5 层"
    assert rows["击败敌人"] == "1"
    app._draw()

    app._handle_key(pygame.K_RETURN)
    assert app.page == "lobby"

    _start_expedition(app)
    assert app.run_floor == 1
    pygame.quit()


def test_lobby_resumes_persisted_expedition_checkpoint_after_restart(
    monkeypatch, tmp_path
):
    save_file = tmp_path / "save.json"
    monkeypatch.setattr(main, "SAVE_FILE", save_file)
    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)
    app._bind_slot(0, fresh=True)
    app.profile["tutorial_completed"] = True
    app._start_run(3, tutorial=False)
    app.run_score = 1234
    app.run_combo = 6
    app.run_max_combo = 11
    app.run_parries = 4
    app.run_currency = 77
    app.player_level = 4
    app.player_exp = 20
    app.run_shop_attack_bonus = 4
    app.run_shop_hp_bonus = 45
    app.player.hp = 211
    app.echo_energy = 60
    app._save_run_checkpoint()

    again = StartScreen(screen)
    again._load_slot(0)
    assert again.page == "lobby"
    assert "继续远征" in again._lobby_actions()[0][1]
    _start_expedition(again)

    assert again.page == "game"
    assert again.run_floor == 3
    assert again.run_score == 1234
    assert again.run_combo == 6
    assert again.run_max_combo == 11
    assert again.run_parries == 4
    assert again.run_currency == 77
    assert again.player_level == 4
    assert again.player_exp == 20
    assert again.player.hp == 211
    assert again.echo_energy == 60
    assert again.player.max_hp == 320 + 45 + 3 * main.HP_PER_LEVEL
    assert again.player.attack_damage == 18 + 4 + 3 * main.ATTACK_PER_LEVEL
    assert "第 3 层" in again.notification
    pygame.quit()


def test_invalid_or_lethal_checkpoint_is_ignored_by_lobby(monkeypatch, tmp_path):
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    app.profile = app._new_profile()
    app.profile["tutorial_completed"] = True
    app.profile["active_run"] = {
        "status": "active",
        "floor": 999,
        "player_hp": 0,
    }
    app._enter_lobby()

    _start_expedition(app)

    assert app.run_floor == 1
    assert app.player.hp > 0
    assert app._active_run_checkpoint()["floor"] == 1
    pygame.quit()


def test_lobby_nexus_upgrades_a_track_and_persists(monkeypatch, tmp_path):
    save_file = tmp_path / "save.json"
    monkeypatch.setattr(main, "SAVE_FILE", save_file)

    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)
    app.profile = app._new_profile()
    app.profile["echo_relics"] = 40
    app._enter_lobby()
    app._activate_lobby_action(1)

    assert app.overlay == "progression"
    index = next(
        position
        for position, track in enumerate(main.PROGRESSION_TRACKS)
        if track.track_id == "vital_lattice"
    )
    app.progression_selected = index
    app._upgrade_track(index)

    assert app._track_level("vital_lattice") == 1
    assert app.echo_relics == 20
    saved = _saved_slot(save_file)
    assert saved["progression"]["levels"]["vital_lattice"] == 1
    assert saved["echo_relics"] == 20
    pygame.quit()


def test_nexus_tracks_keep_previous_levels_without_being_overwritten(
    monkeypatch, tmp_path
):
    save_file = tmp_path / "save.json"
    monkeypatch.setattr(main, "SAVE_FILE", save_file)
    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)
    app.profile = app._new_profile()
    app.profile["echo_relics"] = 200

    vital = next(
        position
        for position, track in enumerate(main.PROGRESSION_TRACKS)
        if track.track_id == "vital_lattice"
    )
    attack = next(
        position
        for position, track in enumerate(main.PROGRESSION_TRACKS)
        if track.track_id == "edge_tempering"
    )
    app._upgrade_track(vital)
    app._upgrade_track(vital)
    app._upgrade_track(attack)

    levels = app._track_levels()
    assert levels["vital_lattice"] == 2
    assert levels["edge_tempering"] == 1
    assert app.echo_relics == 200 - 20 - 40 - 30
    saved = _saved_slot(save_file)
    assert saved["progression"]["levels"]["vital_lattice"] == 2
    assert saved["progression"]["levels"]["edge_tempering"] == 1
    pygame.quit()


def test_progression_branches_are_grouped_collapsible_and_directly_clickable(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(main, "SAVE_FILE", tmp_path / "save.json")
    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)
    app.profile = app._new_profile()
    app.profile["tutorial_completed"] = True
    app.profile["echo_relics"] = 200
    app._open_overlay("progression", return_page="lobby")

    assert set(app._progression_branch_rects()) == set(main.PROGRESSION_BRANCHES)
    visible = app._progression_visible_node_rects()
    assert visible
    assert all(
        main.PROGRESSION_TRACKS[index].branch == "基元谱系" for index in visible
    )

    branch_rect = app._progression_branch_rects()["基元谱系"]
    app._handle_overlay_click(branch_rect.center)
    assert app.progression_collapsed["基元谱系"] is True
    assert app._progression_visible_node_rects() == {}

    mechanism_rect = app._progression_branch_rects()["机制谱系"]
    app._handle_overlay_click(mechanism_rect.center)
    dash_index = next(
        position
        for position, track in enumerate(main.PROGRESSION_TRACKS)
        if track.track_id == "shadow_dash"
    )
    dash_rect = app._progression_visible_node_rects()[dash_index]
    app._handle_overlay_click(dash_rect.center)
    assert app.progression_selected == dash_index
    app._handle_overlay_click(app._progression_activate_rect().center)
    assert app._track_level("shadow_dash") == 1
    pygame.quit()


def test_new_nexus_tracks_apply_attributes_and_mechanics(monkeypatch, tmp_path):
    """技能树分支要真正作用到本局：数值、动作解锁、自动恢复与铸币。"""
    monkeypatch.setattr(main, "SAVE_FILE", tmp_path / "save.json")
    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)
    app.profile = app._new_profile()
    app.profile["progression"]["levels"] = {
        "vital_lattice": 1,
        "edge_tempering": 2,
        "resonance_amplifier": 5,
        "aerial_memory": 1,
        "shadow_dash": 1,
        "reserve_carry": 2,
        "salvage_protocol": 1,
        "vital_regeneration": 2,
        "resonance_reflux": 1,
    }

    app._start_run(1, tutorial=False)

    assert app.player.max_hp == 320 + 100
    assert app.player.attack_bonus == 10
    assert app.player.max_air_jumps == 1
    assert app.player.dash_unlocked is True
    assert app.run_currency == 10
    assert app.skill_damage_scale == 1.5
    assert app.auto_heal_per_second == 6
    assert app.auto_energy_per_second == 1

    # 战利议价 +5%：追击者基础 6 铸币 → 7
    app._award_enemy_defeat(Chaser(300, 522))
    assert app.run_currency == 17
    assert app.run_kills == 1

    # 自动回复：每秒 6 点生命与 1 点回响能量
    app._dismiss_floor_intro()
    app.player.hp = 100
    app.echo_energy = 0
    _advance(app, 1.02)
    assert app.player.hp == 106
    assert app.echo_energy == 1
    pygame.quit()


def test_failure_relics_scale_with_score_combo_and_parries(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "SAVE_FILE", tmp_path / "save.json")
    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)
    app.profile = app._new_profile()
    app._start_run(3, tutorial=False)
    app.run_score = 5000
    app.run_max_combo = 20
    app.run_parries = 5
    app._save_run_checkpoint()

    app.player.hp = 0
    app._fail_run()

    assert app.result_relics == 70
    assert app.echo_relics == 70
    assert app.page == "failure"
    assert app._active_run_checkpoint() is None
    app._fail_run()
    assert app.echo_relics == 70
    pygame.quit()


def test_tutorial_hints_follow_custom_keybinds(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "SAVE_FILE", tmp_path / "save.json")

    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)
    app._start_run(1)

    jump_step = next(step for step in app.tutorial_steps if step.action == "jump")
    parry_step = next(step for step in app.tutorial_steps if step.action == "parry")
    assert jump_step.objective == "按 SPACE 跳起"
    assert parry_step.objective == "按 K 进行一次完美弹刀演示"

    # 先把弹刀从 K 挪到 P，腾出 K 再绑定给跳跃，模拟玩家在设置里换键。
    app.overlay = "keybinds"
    app.rebinding_action = "parry"
    app._handle_key(pygame.K_p)
    app.rebinding_action = "jump"
    app._handle_key(pygame.K_k)

    assert app.keybinds["parry"] == pygame.K_p
    assert app.keybinds["jump"] == pygame.K_k

    jump_step = next(step for step in app.tutorial_steps if step.action == "jump")
    parry_step = next(step for step in app.tutorial_steps if step.action == "parry")
    attack_step = next(step for step in app.tutorial_steps if step.action == "up_attack")
    assert jump_step.objective == "按 K 跳起"
    assert parry_step.objective == "按 P 进行一次完美弹刀演示"
    assert attack_step.objective == "按住 W/↑ 再按 J 使用上劈"

    # 重新开一局也要保留玩家自定义的键位提示。
    app._start_run(1)
    jump_step = next(step for step in app.tutorial_steps if step.action == "jump")
    assert jump_step.objective == "按 K 跳起"
    pygame.quit()


def test_audio_manager_degrades_gracefully_without_assets(tmp_path):
    """缺少音频素材（或没有音频设备）时不能抛异常，游戏要能静音运行。"""
    from game.audio import AudioManager

    pygame.init()
    manager = AudioManager(tmp_path, volume=50)

    manager.play("parry")
    manager.play("step")
    manager.play_swing(3)
    manager.play_music("battle")
    manager.update(0.016)
    manager.set_volume(30)
    manager.duck()
    manager.update(0.5)
    manager.stop_music()
    manager.shutdown()
    manager.play("hit")

    assert manager.volume == 30
    pygame.quit()


def test_music_switches_between_lobby_and_level(monkeypatch, tmp_path):
    app, recorder = _app_with_recording_audio(monkeypatch, tmp_path)

    app._sync_music()
    assert recorder.music[-1] == "lobby"

    # 新手教程关卡也算进入关卡，必须切换到战斗音乐
    app._start_run(1, tutorial=True)
    app._sync_music()
    assert recorder.music[-1] == "battle"

    app._start_run(3, tutorial=False)
    app._sync_music()
    assert recorder.music[-1] == "battle"

    # 结算/失败界面回到大厅音乐
    app._enter_lobby()
    app._sync_music()
    assert recorder.music[-1] == "lobby"

    app.page = "result"
    app._sync_music()
    assert recorder.music[-1] == "lobby"
    pygame.quit()


def test_combat_actions_emit_expected_sfx(monkeypatch, tmp_path):
    app, recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    _grant_tracks(app, shadow_dash=1)
    app._start_run(1, tutorial=False)
    app._dismiss_floor_intro()

    # 角色动作：攻击（未命中也要有声）、冲刺、跳跃、弹刀架势
    app._handle_key(app.keybinds["attack"])
    assert recorder.played[-1] == "swing_1"
    app.player.update(app.player.ATTACK_DURATION, 0)
    app._handle_key(app.keybinds["dash"])
    assert recorder.played[-1] == "dash"
    app._handle_key(app.keybinds["jump"])
    assert recorder.played[-1] == "jump"
    app._handle_key(app.keybinds["parry"])
    assert recorder.played[-1] == "parry_ready"
    app.player.update(app.player.PARRY_DURATION, 0)

    enemy = Chaser(app.player.x + 40, 522)
    app.room_enemies = [enemy]
    app.pending_enemy_attacks.clear()

    # 敌人发动攻击：起手即有提示音
    app._update_enemy_attacks(0.016)
    assert "enemy_attack" in recorder.played

    # 玩家命中敌人：额外命中确认音
    recorder.played.clear()
    app.player.start_attack("side")
    app.player.update(0.1, 0)
    app._resolve_player_attack()
    assert "hit" in recorder.played
    assert recorder.duck_count > 0

    # 完美弹刀：最响的确认音 + 压低音乐
    recorder.played.clear()
    app.player.start_parry()
    app.player.update(app.player.PERFECT_PARRY_WINDOW * 0.75, 1)
    app._resolve_enemy_attack(PendingEnemyAttack(enemy, enemy.scaled_attack(), 0.0))
    assert "parry" in recorder.played

    # 玩家被打中：额外受击确认音（先结束架势，避免再次触发弹刀）
    recorder.played.clear()
    app.player.update(app.player.PARRY_INPUT_BUFFER + 0.05, 0)
    app._resolve_enemy_attack(PendingEnemyAttack(enemy, enemy.scaled_attack(), 0.0))
    assert "hurt" in recorder.played
    pygame.quit()


def test_running_emits_footsteps_and_idle_does_not(monkeypatch, tmp_path):
    app, recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    app._start_run(1, tutorial=False)

    app.player.grounded = True
    for _ in range(20):
        app.player.velocity_x = Player.MOVE_SPEED
        app._update_movement_audio(1.0 / 30.0)
    assert recorder.played.count("step") >= 1

    recorder.played.clear()
    app.player.velocity_x = 0.0
    app._update_movement_audio(1.0)
    assert "step" not in recorder.played

    # 落地时补一次落地音
    app.player.landed_this_frame = True
    app._update_movement_audio(1.0 / 60.0)
    assert "land" in recorder.played
    pygame.quit()


def test_volume_setting_updates_audio_and_profile(monkeypatch, tmp_path):
    app, recorder = _app_with_recording_audio(monkeypatch, tmp_path)

    app._set_volume(35)
    assert app.settings["volume"] == 35
    assert recorder.volume == 35
    # 设置是全局的：还没选存档位也要能写进存档文件
    saved = json.loads(main.SAVE_FILE.read_text(encoding="utf-8"))
    assert saved["settings"]["volume"] == 35

    app._change_setting(0, 5)
    assert app.settings["volume"] == 40
    assert recorder.volume == 40
    pygame.quit()


def test_level_escape_opens_settings_and_has_no_finish_button(monkeypatch, tmp_path):
    """关卡里不再有「完成关卡/返回主菜单」按钮，Esc 直接开设置。"""
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    app._start_run(1, tutorial=False)
    app._dismiss_floor_intro()

    assert app._page_buttons() == {}
    app._handle_key(pygame.K_ESCAPE)
    assert app.overlay == "settings"
    assert app.confirm_exit is False
    assert app.return_page == "game"
    pygame.quit()


def test_settings_icon_click_opens_settings(monkeypatch, tmp_path):
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    app._start_run(1, tutorial=False)
    app._dismiss_floor_intro()

    pygame.event.post(
        pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            button=1,
            pos=app._settings_icon_rect().center,
        )
    )
    app._handle_events()

    assert app.overlay == "settings"
    # 点图标不应该同时触发一次攻击
    assert app.player.attack_in_progress is False
    pygame.quit()


def test_settings_can_return_to_menu_from_level(monkeypatch, tmp_path):
    """设置里的「返回主菜单」：关卡中先确认，再回到主菜单。"""
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    app._start_run(1, tutorial=False)
    app._handle_key(pygame.K_ESCAPE)

    app._activate_setting(4)
    assert app.overlay is None
    assert app.confirm_exit is True

    app._activate_exit_button("confirm")
    assert app.page == "menu"
    assert app.confirm_exit is False
    pygame.quit()


def test_settings_from_main_menu_closes_without_confirmation(monkeypatch, tmp_path):
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    app._open_overlay("settings")

    app._activate_setting(4)
    assert app.overlay is None
    assert app.confirm_exit is False
    assert app.page == "menu"
    pygame.quit()


def test_settings_overlay_has_six_rows(monkeypatch, tmp_path):
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    app._open_overlay("settings")
    assert len(app._setting_rects()) == 6

    app._handle_key(pygame.K_DOWN)
    assert app.overlay_selected == 1
    for _ in range(5):
        app._handle_key(pygame.K_DOWN)
    assert app.overlay_selected == 0  # 6 项循环

    app._activate_setting(5)
    assert app.overlay is None
    pygame.quit()


def test_room_clear_opens_portal_and_assets_are_loaded(monkeypatch, tmp_path):
    app, recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    _enter_level(app)
    _clear_room(app)

    assert app.assets.portal_idle, "传送门待机素材应当存在"
    assert len(app.assets.portal_enter) == 4, "传送门进入动画应当有 4 帧"

    _advance(app, 0.2)
    assert app.portal_open is True
    assert "portal_open" in recorder.played

    _advance(app, main.PORTAL_APPEAR_TIME)
    assert app.portal_appear == 1.0
    app._draw()  # 传送门绘制路径不应抛异常
    pygame.quit()


def test_walking_into_portal_plays_enter_animation_then_shows_choice(
    monkeypatch, tmp_path
):
    app, recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    _enter_level(app)
    _clear_room(app)
    _advance(app, main.PORTAL_APPEAR_TIME + 0.2)
    assert app.portal_appear == 1.0

    app.player.x = main.PORTAL_CENTER_X
    app.player.y = main.PORTAL_GROUND_Y
    _advance(app, 0.05)
    assert app.portal_enter_timer > 0.0
    assert "portal_enter" in recorder.played

    _advance(app, main.PORTAL_ENTER_TIME + 0.1)
    assert app.overlay == "portal"
    pygame.quit()


def test_portal_choice_next_level_and_menu(monkeypatch, tmp_path):
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    _enter_level(app, floor=3)
    app.room_enemies.clear()
    app.pending_spawn.clear()
    app.portal_open = True
    app.portal_appear = 1.0
    app.portal_enter_timer = 0.0
    app._open_portal_choice()

    assert app._portal_choice_labels()[1] == "进入第 4 层"
    app._activate_portal_choice(1)
    assert app.page == "game"
    assert app.run_floor == 4
    assert app.is_tutorial_run is False
    assert app.portal_open is False
    assert app.has_save is True

    app.room_enemies.clear()
    app.pending_spawn.clear()
    app.portal_open = True
    app.portal_appear = 1.0
    app._open_portal_choice()
    app._activate_portal_choice(0)
    assert app.page == "menu"
    pygame.quit()


def test_tutorial_portal_leads_to_lobby(monkeypatch, tmp_path):
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    app._start_run(1, tutorial=True)
    app.tutorial_index = len(app.tutorial_steps) - 1
    app.room_enemies.clear()
    app.pending_spawn.clear()
    _advance(app, 0.2)
    assert app.portal_open is True

    assert app._portal_choice_labels()[1] == "进入灰塔大厅"
    app._open_portal_choice()
    app._activate_portal_choice(1)
    assert app.page == "lobby"
    assert app.tutorial_completed is True
    pygame.quit()


def test_portal_choice_cancel_keeps_player_in_room(monkeypatch, tmp_path):
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    _enter_level(app)
    app.portal_open = True
    app.portal_appear = 1.0
    app._open_portal_choice()

    app._leave_portal_choice()
    assert app.overlay is None
    assert app.page == "game"
    assert app.player.x < main.PORTAL_CENTER_X - 100
    assert app.portal_lock_timer > 0.0
    pygame.quit()


def test_player_and_enemies_move_across_the_whole_screen(monkeypatch, tmp_path):
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    _enter_level(app)

    # 玩家可以一路走到原来会被卡住的中段之后
    app.player.x = 900
    app.player.update(1.0 / 60.0, 1)
    assert app.player.x > 900

    # 追击者会从屏幕右侧一路向左追，且不会越过左侧边界
    chaser = Chaser(1200, 522)
    app.room_enemies = [chaser]
    app.player.x = 100
    for _ in range(600):
        chaser.update(1.0 / 60.0, app.player.position)
    assert chaser.x >= chaser.bounds_left
    assert chaser.x < 400

    # 反向：玩家在右侧时敌人向右移动也不会越过右侧边界
    chaser.x = 1200
    app.player.x = 1260
    for _ in range(600):
        chaser.update(1.0 / 60.0, app.player.position)
    assert chaser.x <= chaser.bounds_right
    pygame.quit()


def test_dash_has_cooldown_and_grants_invulnerability(monkeypatch, tmp_path):
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    _grant_tracks(app, shadow_dash=1)
    app._start_run(1, tutorial=False)
    player = app.player
    enemy = Chaser(player.x + 40, 522)
    app.room_enemies = [enemy]
    starting_hp = player.hp

    assert player.dash() is True
    assert player.invulnerable is True
    # 内置 CD：0.3 秒内不能再次闪避
    assert player.dash() is False
    assert player.DASH_COOLDOWN == 0.3

    # 闪避期间无敌，攻击命中也不掉血、不打断连击
    app.run_combo = 3
    app._resolve_enemy_attack(
        PendingEnemyAttack(enemy, enemy.scaled_attack(), 0.0)
    )
    assert player.hp == starting_hp
    assert app.run_combo == 3

    # 冲刺结束时无敌解除
    player.update(player.DASH_DURATION, 0)
    assert player.invulnerable is False

    # CD 结束后可以再次闪避；无敌结束后会正常受伤
    player.update(player.DASH_COOLDOWN, 0)
    assert player.dash() is True
    player.update(player.DASH_DURATION + 0.05, 0)
    app._resolve_enemy_attack(
        PendingEnemyAttack(enemy, enemy.scaled_attack(), 0.0)
    )
    assert player.hp == starting_hp - enemy.damage
    pygame.quit()


def test_dash_leaves_afterimages_that_fade(monkeypatch, tmp_path):
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    _grant_tracks(app, shadow_dash=1)
    app._start_run(1, tutorial=False)
    player = app.player

    player.grounded = True
    assert player.dash() is True
    app._update_dash_trails(1.0 / 60.0)
    assert len(app.dash_trails) == 1  # 冲刺起手立刻留下一格残影

    for _ in range(19):
        player.velocity_x = player.MOVE_SPEED
        player.update(1.0 / 60.0, 1)
        app._update_dash_trails(1.0 / 60.0)
    assert len(app.dash_trails) >= 2
    app._draw()  # 残影绘制路径不应抛异常

    for _ in range(60):
        player.update(1.0 / 60.0, 0)
        app._update_dash_trails(1.0 / 60.0)
    assert app.dash_trails == []
    pygame.quit()


def test_parry_window_matches_flash_lead():
    """金色闪光提前量必须与弹刀输入缓冲一致，否则窗口提示会骗人。"""
    assert main.MELEE_FLASH_LEAD == Player.PARRY_INPUT_BUFFER


def test_melee_parry_accepts_press_inside_flash_window(monkeypatch, tmp_path):
    app, recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    app._start_run(1, tutorial=False)
    app._dismiss_floor_intro()
    enemy = Chaser(app.player.x + 40, 522)
    app.room_enemies = [enemy]
    starting_hp = app.player.hp

    # 闪光亮起后按下弹刀（0.2 秒后命中），仍在窗口内
    app._handle_key(app.keybinds["parry"])
    app.player.update(0.2, 0)
    app._resolve_enemy_attack(
        PendingEnemyAttack(enemy, enemy.scaled_attack(), 0.0)
    )

    assert app.player.hp == starting_hp
    assert app.run_parries == 1
    assert enemy.hp < enemy.max_hp
    assert "parry" in recorder.played
    pygame.quit()


def test_projectile_parry_requires_close_range(monkeypatch, tmp_path):
    app, recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    app._start_run(1, tutorial=False)
    app._dismiss_floor_intro()
    thrower = SpearThrower(1000, 522)
    app.room_enemies = [thrower]
    profile = thrower.scaled_attack()
    player_center = (app.player.x, app.player.y - 54)

    # 子弹刚出膛，离角色很远：按下弹刀不生效
    far = PendingEnemyAttack(
        thrower,
        profile,
        profile.telegraph_time,
        origin=(thrower.x, thrower.y - 52),
        target=player_center,
    )
    app.pending_enemy_attacks = [far]
    app._handle_key(app.keybinds["parry"])
    assert app.pending_enemy_attacks == [far]
    assert app.run_parries == 0

    # 子弹飞到角色身边：按下弹刀立即弹开并反震
    app.player.update(app.player.PARRY_DURATION, 0)
    near = PendingEnemyAttack(
        thrower,
        profile,
        profile.telegraph_time * 0.02,
        origin=(thrower.x, thrower.y - 52),
        target=player_center,
    )
    app.pending_enemy_attacks = [near]
    app._handle_key(app.keybinds["parry"])
    assert app.pending_enemy_attacks == []
    assert app.run_parries == 1
    assert "parry" in recorder.played
    pygame.quit()


def test_unparried_projectile_still_damages_player(monkeypatch, tmp_path):
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    app._start_run(1, tutorial=False)
    thrower = SpearThrower(1000, 522)
    app.room_enemies = [thrower]
    profile = thrower.scaled_attack()
    starting_hp = app.player.hp

    # 没有按弹刀：弹道命中时正常结算伤害
    app._resolve_enemy_attack(
        PendingEnemyAttack(
            thrower,
            profile,
            0.0,
            origin=(thrower.x, thrower.y - 52),
            target=(app.player.x, app.player.y - 54),
        )
    )
    assert app.player.hp == starting_hp - thrower.damage
    pygame.quit()


def test_level_spawns_enemies_after_delay(monkeypatch, tmp_path):
    """进入新关卡不能秒刷怪：先等待，再让敌人登场。"""
    app, recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    app._start_run(1, tutorial=False)
    assert app.room_enemies == []
    assert len(app.pending_spawn) == 2
    assert app.enemy_spawn_timer == main.ENEMY_SPAWN_DELAY
    app._dismiss_floor_intro()

    _advance(app, main.ENEMY_SPAWN_DELAY - 0.2)
    assert app.room_enemies == []

    _advance(app, 0.3)
    assert len(app.room_enemies) == 2
    assert app.pending_spawn == []
    assert "spawn" in recorder.played
    pygame.quit()


def test_newly_spawned_enemies_hold_fire_for_a_moment(monkeypatch, tmp_path):
    """敌人刷出来不会立刻动手：先留一段反应时间，之后才挥出第一刀。"""
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    app._start_run(1, tutorial=False)
    app._dismiss_floor_intro()
    _advance(app, main.ENEMY_SPAWN_DELAY + 0.1)

    assert app.room_enemies
    assert all(enemy.attack_ready is False for enemy in app.room_enemies)

    # 就算贴到脸上，缓冲期里也不会出手
    chaser = next(enemy for enemy in app.room_enemies if enemy.kind == "chaser")
    chaser.x = app.player.x + 40
    _advance(app, main.ENEMY_SPAWN_ATTACK_GRACE - 0.3)
    assert app.pending_enemy_attacks == []

    # 缓冲期结束后恢复进攻
    chaser.x = app.player.x + 40
    attacked = False
    for _ in range(60):
        app._update(1.0 / 60.0)
        if app.pending_enemy_attacks:
            attacked = True
            break

    assert attacked is True
    pygame.quit()


def test_spawn_countdown_display_actually_ticks(monkeypatch, tmp_path):
    """回归：倒计时面板必须随时间变化，且提示文案里不能写死秒数。"""
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    app._start_run(1, tutorial=False)
    app._dismiss_floor_intro()

    first = _countdown_panel_digest(app)
    _advance(app, 1.0)
    second = _countdown_panel_digest(app)
    assert first != second

    # 曾经在通知里写死“3 秒”，导致画面看起来一直停在 3
    assert not any(character.isdigit() for character in app.notification)

    _advance(app, main.ENEMY_SPAWN_DELAY)
    assert app.pending_spawn == []
    pygame.quit()


def test_projectile_parry_reflects_bullet_back_to_shooter(monkeypatch, tmp_path):
    """远程弹刀是“把子弹打回去”，伤害在飞回敌人时才结算。"""
    app, recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    app._start_run(1, tutorial=False)
    app._dismiss_floor_intro()
    thrower = SpearThrower(600, 522)
    app.room_enemies = [thrower]
    profile = thrower.scaled_attack()
    enemy_hp = thrower.hp

    near = PendingEnemyAttack(
        thrower,
        profile,
        profile.telegraph_time * 0.02,
        origin=(thrower.x, thrower.y - 52),
        target=(app.player.x, app.player.y - 54),
    )
    app.pending_enemy_attacks = [near]
    app._handle_key(app.keybinds["parry"])

    # 弹开瞬间：子弹转为“反弹中”，敌人还没掉血
    assert app.run_parries == 1
    assert len(app.reflected_projectiles) == 1
    assert thrower.hp == enemy_hp

    recorder.played.clear()
    _advance(app, 1.0)
    assert thrower.hp < enemy_hp
    assert app.reflected_projectiles == []
    assert "hit" in recorder.played
    pygame.quit()


def test_melee_parry_window_is_longer_than_before(monkeypatch, tmp_path):
    """近战弹刀窗口再延长 0.2 秒到 0.65 秒，闪光提前量与之保持一致。"""
    assert main.MELEE_FLASH_LEAD == Player.PARRY_INPUT_BUFFER
    assert Player.PARRY_INPUT_BUFFER >= 0.65

    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    app._start_run(1, tutorial=False)
    app._dismiss_floor_intro()
    enemy = Chaser(app.player.x + 40, 522)
    app.room_enemies = [enemy]
    starting_hp = app.player.hp

    # 命中前 0.4 秒按键（旧窗口已经失效）仍然算完美弹刀
    app._handle_key(app.keybinds["parry"])
    app.player.update(0.4, 0)
    app._resolve_enemy_attack(
        PendingEnemyAttack(enemy, enemy.scaled_attack(), 0.0)
    )
    assert app.player.hp == starting_hp
    assert app.run_parries == 1
    pygame.quit()


def test_lobby_music_stops_after_entering_level(monkeypatch, tmp_path):
    """进入关卡后，大厅音乐必须真正淡出并停止，而不只是变小。"""
    monkeypatch.setattr(main, "SAVE_FILE", tmp_path / "save.json")
    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)
    audio = app.audio

    assert audio.requested_track == "lobby"
    app._start_run(1, tutorial=True)
    app._sync_music()
    assert audio.requested_track == "battle"

    if not audio.enabled:
        pygame.quit()
        return

    assert audio.current_track == "battle"
    for _ in range(90):  # 推进 1.5 秒，覆盖 1 秒交叉淡化
        audio.update(1.0 / 60.0)

    channels = [pygame.mixer.Channel(0), pygame.mixer.Channel(1)]
    busy = [channel.get_busy() for channel in channels]
    volumes = [channel.get_volume() for channel in channels]
    assert busy.count(True) == 1  # 只剩战斗音乐在播放
    assert max(volumes) > 0.0
    assert min(volumes) == 0.0  # 大厅音乐声道音量为 0
    pygame.quit()


# -- 角色生存力、波次关卡、等级与回响能量、回响剑气 -------------------------


def test_player_survives_much_longer_than_before():
    """角色血量提升到原来的三倍以上，不再被几刀打死。"""
    player = Player(300, 566)

    assert player.max_hp >= 300
    assert player.hp == player.max_hp
    # 最疼的敌人也要打十几下才放倒
    assert player.max_hp / RiftWorm(0, 0).damage > 10


def test_vitals_hud_shows_numbers_and_tracks_damage(monkeypatch, tmp_path):
    """左上角状态区带具体数值，且血量变化必须反映在画面上。"""
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    _enter_level(app)
    region = pygame.Rect(0, 92, 500, 84)

    app.canvas.fill((0, 0, 0))
    app._draw_vitals()
    full = pygame.image.tobytes(app.canvas.subsurface(region), "RGB")
    assert pygame.mask.from_threshold(
        app.canvas, (0, 0, 0), threshold=(1, 1, 1, 255)
    ).count() > 0

    app.player.hp = app.player.max_hp // 4
    app.canvas.fill((0, 0, 0))
    app._draw_vitals()
    hurt = pygame.image.tobytes(app.canvas.subsurface(region), "RGB")

    assert full != hurt
    pygame.quit()


def test_each_floor_builds_its_designed_wave_composition(monkeypatch, tmp_path):
    """三层关卡各自的波次编成按设计表执行，且一波内部不会叠在同一点。"""
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    expected = {
        1: [
            ["chaser", "spear_thrower"],
            ["chaser", "spear_thrower", "spear_thrower"],
            ["chaser", "chaser", "spear_thrower", "spear_thrower"],
        ],
        2: [
            ["shield_guard", "spear_thrower"],
            ["shield_guard", "chaser", "spear_thrower"],
            [
                "shield_guard",
                "chaser",
                "chaser",
                "spear_thrower",
                "spear_thrower",
            ],
        ],
        3: [
            ["shield_guard", "rift_worm"],
            ["rift_worm", "rift_worm", "chaser"],
            ["shield_guard", "rift_worm", "resonance_mage"],
        ],
    }

    for floor, waves in expected.items():
        app._start_run(floor, tutorial=False)
        app._dismiss_floor_intro()

        assert [
            [enemy.kind for enemy in wave] for wave in app.wave_plan
        ] == waves
        for wave in app.wave_plan:
            positions = [enemy.x for enemy in wave]
            assert len(set(positions)) == len(positions)

    # 第四层是非战斗商店，第五层固定生成第一阶段首领
    app._start_run(4, tutorial=False)
    assert app.wave_plan == []
    app._start_run(5, tutorial=False)
    assert [[enemy.kind for enemy in wave] for wave in app.wave_plan] == [
        ["rust_crown_knight"]
    ]
    pygame.quit()


def test_fourth_floor_shop_requires_interaction_and_carries_upgrades_to_boss(
    monkeypatch, tmp_path
):
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    app._start_run(4, tutorial=False)

    assert app.overlay == "floor_intro"
    assert app._room_cleared() is False
    app._dismiss_floor_intro()
    assert app.overlay == "shop"

    app.run_currency = 100
    base_damage = app.player.attack_damage
    base_hp = app.player.max_hp
    assert app._purchase_shop_item(1) is True
    assert app._purchase_shop_item(2) is True
    assert app.player.attack_damage == base_damage + 4
    assert app.player.max_hp == base_hp + 45
    assert app.run_currency == 38
    assert app._stat("shop_purchases") == 2

    app._leave_shop()
    assert app._room_cleared() is True
    app._start_run(5, tutorial=False, keep_progress=True)
    assert app.player.attack_damage == base_damage + 4
    assert app.player.max_hp == base_hp + 45
    assert app.run_currency == 38
    pygame.quit()


def test_first_stage_boss_enters_phase_two_and_casts_memory_sever_at_medium_rate():
    boss = RustCrownKnight(900, 522, threat=0.0)
    boss.hp = round(boss.max_hp * boss.PHASE_TWO_THRESHOLD)
    boss.take_damage(1)

    assert boss.phase == 2
    assert 5.0 <= boss.SPECIAL_INTERVAL <= 9.0

    special = None
    for _ in range(240):
        intent = boss.update(1.0 / 30.0, (230, 566))
        if intent.attack is not None and intent.attack.tag == "boss_memory_sever":
            special = intent.attack
            break
    assert special is not None
    assert special.parryable is True
    assert special.telegraph_time >= 1.0


def test_unparried_memory_sever_ignores_dash_and_removes_most_health(
    monkeypatch, tmp_path
):
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    _grant_tracks(app, shadow_dash=1)
    _enter_level(app, floor=5)
    boss = app.room_enemies[0]
    profile = boss.scaled_attack(boss.execution_profile)
    starting_hp = app.player.hp
    assert app.player.dash() is True
    assert app.player.invulnerable is True

    app._resolve_enemy_attack(PendingEnemyAttack(boss, profile, 0.0))

    expected_loss = round(app.player.max_hp * main.BOSS_MEMORY_SEVER_DAMAGE_RATIO)
    assert app.player.hp == starting_hp - expected_loss
    assert expected_loss > app.player.max_hp * 0.75
    pygame.quit()


def test_parrying_memory_sever_stuns_boss_and_breaks_defense_for_three_seconds(
    monkeypatch, tmp_path
):
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    _enter_level(app, floor=5)
    boss = app.room_enemies[0]
    boss.phase = 2
    profile = boss.scaled_attack(boss.execution_profile)
    starting_hp = app.player.hp

    assert app.player.start_parry() is True
    app._resolve_enemy_attack(PendingEnemyAttack(boss, profile, 0.0))

    assert app.player.hp == starting_hp
    assert boss.vulnerable is True
    assert boss.defense_broken is True
    broken_damage = boss.take_damage(100, source_x=app.player.x)
    boss.update(0.5, app.player.position)  # 先让弹刀击退的滑行走完
    assert boss.update(2.4, app.player.position).action == "vulnerable"
    assert boss.defense_broken is True
    boss.update(0.2, app.player.position)
    assert boss.vulnerable is False
    assert boss.defense_broken is False
    normal_damage = boss.take_damage(100, source_x=app.player.x)
    assert broken_damage > normal_damage
    pygame.quit()


def test_fifth_floor_portal_finishes_first_stage(monkeypatch, tmp_path):
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    _enter_level(app, floor=5)
    boss = app.room_enemies[0]
    boss.hp = 0
    app._award_enemy_defeat(boss)
    assert app._stat("boss_kills") == 1
    app.room_enemies.clear()
    app.pending_spawn.clear()
    app.wave_plan = []
    app.wave_index = 0

    assert app._room_cleared() is True
    assert app._portal_choice_labels()[1] == "完成阶段并返回大厅"
    app._open_portal_choice()
    app._activate_portal_choice(1)
    assert app.page == "result"
    app._activate_page_button("lobby")
    assert app.page == "lobby"
    pygame.quit()


def test_unlocking_dash_is_required_before_it_can_be_used(monkeypatch, tmp_path):
    """闪避属于机制谱系：没点亮之前按冲刺键不会有反应。"""
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    app.profile = app._new_profile()
    _enter_level(app)

    assert app.player.dash_unlocked is False
    app._handle_key(app.keybinds["dash"])
    assert app.player.dash_active is False

    app._enter_lobby()
    _grant_tracks(app, shadow_dash=1)
    _start_expedition(app)
    app._dismiss_floor_intro()

    assert app.player.dash_unlocked is True
    app._handle_key(app.keybinds["dash"])
    assert app.player.dash_active is True
    pygame.quit()


def test_risk_covenant_unlocks_a_hard_mode_choice_before_the_run(
    monkeypatch, tmp_path
):
    """点亮风险契约后，开局前可以选择高压远征：敌人更强、遗晶更多。"""
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    app.profile = app._new_profile()
    app.profile["tutorial_completed"] = True
    _grant_tracks(app, risk_covenant=1)
    app._enter_lobby()

    app._activate_lobby_action(0)
    assert app.overlay == "difficulty"
    assert app.transition is None
    app._draw()

    app._confirm_difficulty(1)
    _advance(app, 1.6)

    assert app.page == "game"
    assert app.transition is None
    assert app.run_difficulty_hard is True
    assert app.run_threat > app._floor_threat(1)
    assert app._active_run_checkpoint()["hard_mode"] is True

    # 结算时高压远征按倍率发放遗晶
    app.room_enemies.clear()
    app.pending_spawn.clear()
    app.wave_plan = []
    app.wave_index = 0
    relics = app._settle_run()
    base = 30 + app.run_floor * 10 + min(app.run_parries * 2, 30)
    assert relics == round(base * main.DIFFICULTY_RELIC_MULTIPLIER)
    pygame.quit()


def test_floor_one_runs_through_three_waves_with_countdown(monkeypatch, tmp_path):
    """第一层按三波依次刷出，波与波之间用倒计时面板等待。"""
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    app._start_run(1, tutorial=False)
    app._dismiss_floor_intro()

    spawned: list[str] = []
    elapsed = 0.0
    while elapsed < 30.0 and not (
        app.wave_index >= len(app.wave_plan)
        and not app.pending_spawn
        and not app.room_enemies
    ):
        app.room_enemies.clear()
        app.pending_enemy_attacks.clear()
        app._update(1.0 / 60.0)
        spawned.extend(enemy.kind for enemy in app.room_enemies)
        elapsed += 1.0 / 60.0

    assert spawned == [
        "chaser",
        "spear_thrower",
        "chaser",
        "spear_thrower",
        "spear_thrower",
        "chaser",
        "chaser",
        "spear_thrower",
        "spear_thrower",
    ]
    # 后续波次用的是更短的间隔，面板上会写明是第几波
    assert app.spawn_countdown_total == main.WAVE_SPAWN_DELAY
    assert app.spawn_countdown_label.startswith("第 3 波")
    # 三波清空后房间才判定为胜利
    assert app._room_cleared() is True
    pygame.quit()


def test_new_floor_opens_a_briefing_about_its_enemies(monkeypatch, tmp_path):
    """进入每一层都弹出简报，介绍本层敌人的攻击方式，并暂停游戏世界。"""
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    app._start_run(1, tutorial=False)

    assert app.overlay == "floor_intro"
    first_floor = [name for name, _ in app._floor_briefing(1).entries]
    assert "追击者" in first_floor
    assert "投矛手" in first_floor

    # 简报期间敌人不会刷新，玩家也不能操作
    _advance(app, 1.0)
    assert app.enemy_spawn_timer == main.ENEMY_SPAWN_DELAY
    app._draw()

    app._dismiss_floor_intro()
    assert app.overlay is None
    assert app.page == "game"

    # 后两层简报各自点名本层的新敌人
    assert app._floor_briefing(2).entries[0][0] == "盾卫"
    third_floor = [name for name, _ in app._floor_briefing(3).entries]
    assert "裂隙虫" in third_floor
    assert "共鸣法师" in third_floor
    pygame.quit()


def test_level_curve_grows_and_difficulty_scales_with_floor():
    needs = [main.StartScreen._exp_needed(level) for level in range(1, 7)]

    assert needs == sorted(needs)
    assert len(set(needs)) == len(needs)
    assert main.StartScreen._floor_threat(1) < main.StartScreen._floor_threat(2)
    assert main.StartScreen._floor_threat(2) < main.StartScreen._floor_threat(3)


def test_defeating_enemies_grants_exp_and_level_ups_raise_stats(monkeypatch, tmp_path):
    """击败敌人给经验；升级同时提高生命上限与攻击力（技能一起吃加成）。"""
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    _enter_level(app)
    base_max_hp = app.player.max_hp
    base_damage = app.player.attack_damage

    assert app.player_level == 1
    assert app.player_exp == 0

    enemy = app.room_enemies[0]
    enemy.hp = 1
    app._start_player_attack()
    app.player.update(0.1, 0)
    app._resolve_player_attack()

    assert app.player_exp == app._enemy_exp(enemy) > 0

    app._gain_exp(app.exp_to_next - app.player_exp)

    assert app.player_level == 2
    assert app.player_exp == 0
    assert app.player.max_hp == base_max_hp + main.HP_PER_LEVEL
    assert app.player.attack_damage == base_damage + main.ATTACK_PER_LEVEL
    pygame.quit()


def test_enemy_exp_rewards_grow_with_floor(monkeypatch, tmp_path):
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    chaser = Chaser(600, 522)

    app._start_run(1, tutorial=False)
    shallow = app._enemy_exp(chaser)
    app._start_run(3, tutorial=False)
    deep = app._enemy_exp(chaser)

    assert deep > shallow
    pygame.quit()


def test_echo_energy_gains_match_design_and_cap_at_max(monkeypatch, tmp_path):
    """跳跃闪避不给能量；普通攻击 < 上劈下劈 < 完美弹刀 = 击败敌人。"""
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    _enter_level(app)

    assert app.echo_energy == 0
    assert main.ENERGY_GAIN_ATTACK < main.ENERGY_GAIN_HEAVY_ATTACK
    assert main.ENERGY_GAIN_HEAVY_ATTACK < main.ENERGY_GAIN_PARRY
    assert main.ENERGY_GAIN_PARRY == main.ENERGY_GAIN_DEFEAT
    # 五次完美弹刀刚好攒满一次技能
    assert main.ENERGY_GAIN_PARRY * 5 == main.ECHO_ENERGY_MAX

    # 跳跃 / 闪避 / 移动都不增加能量
    app._handle_key(app.keybinds["jump"])
    app._handle_key(app.keybinds["dash"])
    _advance(app, 0.3)
    assert app.echo_energy == 0

    # 完美弹刀会积攒能量
    enemy = Chaser(app.player.x + 40, 522)
    app.room_enemies = [enemy]
    app.player.start_parry()
    app.player.update(app.player.PERFECT_PARRY_WINDOW * 0.75, 1)
    app._resolve_enemy_attack(
        PendingEnemyAttack(enemy, enemy.scaled_attack(), 0.0)
    )
    assert app.run_parries == 1
    assert app.echo_energy == main.ENERGY_GAIN_PARRY

    # 满能量后不再溢出累积
    app.echo_energy = main.ECHO_ENERGY_MAX - 1
    app._gain_energy(1)
    assert app.energy_ready is True
    app._gain_energy(60)
    assert app.echo_energy == main.ECHO_ENERGY_MAX
    pygame.quit()


def test_energy_resets_at_the_start_of_every_floor(monkeypatch, tmp_path):
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    _enter_level(app)
    app.echo_energy = main.ECHO_ENERGY_MAX

    app._start_run(2, tutorial=False, keep_progress=True)

    assert app.echo_energy == 0
    pygame.quit()


def test_skill_needs_full_energy_and_makes_player_invulnerable(monkeypatch, tmp_path):
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    _enter_level(app)
    enemy = Chaser(app.player.x + 40, 522)
    app.room_enemies = [enemy]

    # 能量不满：按技能键没有任何反应
    app._handle_key(app.keybinds["skill"])
    assert app.player.skill_active is False
    assert app.skill_waves == []
    assert app.echo_energy == 0

    app.echo_energy = main.ECHO_ENERGY_MAX
    app._handle_key(app.keybinds["skill"])

    assert app.player.skill_active is True
    assert app.player.invulnerable is True
    assert app.echo_energy == 0

    # 释放期间无敌：敌人打中也不掉血、不打断连击
    starting_hp = app.player.hp
    app.run_combo = 4
    app._resolve_enemy_attack(
        PendingEnemyAttack(enemy, enemy.scaled_attack(), 0.0)
    )
    assert app.player.hp == starting_hp
    assert app.run_combo == 4

    app.player.update(Player.SKILL_DURATION, 0)
    assert app.player.invulnerable is False
    pygame.quit()


def test_skill_wave_damages_launches_enemies_and_clears_bullets(monkeypatch, tmp_path):
    """剑气：前方竖向半月、击飞敌人、斩灭沿途子弹，并造成大量伤害。"""
    app, recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    _enter_level(app)
    guard = ShieldGuard(app.player.x + 80, 522, facing=-1)
    thrower = SpearThrower(app.player.x + 300, 522)
    app.room_enemies = [guard, thrower]
    guard_hp = guard.hp
    start_x = guard.x
    profile = thrower.scaled_attack()
    bullet = PendingEnemyAttack(
        thrower,
        profile,
        profile.telegraph_time,
        origin=(thrower.x, thrower.y - 52),
        target=(app.player.x, app.player.y - 54),
    )
    app.pending_enemy_attacks = [bullet]
    assert guard.vulnerable is False

    app.echo_energy = main.ECHO_ENERGY_MAX
    app._handle_key(app.keybinds["skill"])
    _advance(app, Player.SKILL_CAST_TIME + 0.05)
    assert app.skill_waves, "起手结束后应当斩出剑气"

    launched = False
    for _ in range(90):
        app._update(1.0 / 60.0)
        if guard.y < guard.ground_y:
            launched = True
        if launched and not guard.being_knocked_back:
            break

    # 伤害是普通攻击的数倍，且盾卫的正面减伤挡不住剑气
    assert guard_hp - guard.hp >= app.player.attack_damage * 2
    # 先被击飞腾空，再落回地面；横向也被推开一段距离
    assert launched is True
    assert guard.y == guard.ground_y
    assert guard.x > start_x
    # 沿途子弹被斩灭
    assert bullet not in app.pending_enemy_attacks
    assert "hit" in recorder.played
    pygame.quit()


def test_launched_enemy_falls_back_to_the_ground(monkeypatch, tmp_path):
    """击退只持续一段滞空时间，敌人最终会落回地面并恢复行动。"""
    enemy = Chaser(600, 522)
    enemy.apply_knockback(-1, main.SKILL_KNOCKBACK_SPEED, main.SKILL_KNOCKBACK_LIFT)

    assert enemy.airborne is True
    assert enemy.update(1.0 / 60.0, (200, 522)).action == "knocked_back"

    for _ in range(240):
        enemy.update(1.0 / 60.0, (200, 522))

    assert enemy.y == enemy.ground_y
    assert enemy.being_knocked_back is False
    assert enemy.x < 600
    pygame.quit()


def test_broken_posture_is_a_temporary_window_not_a_permanent_stun():
    """韧性归零只该是一段破绽：窗口结束后韧性回满，敌人重新起身。"""
    boss = RustCrownKnight(900, 522)
    boss.take_damage(1, posture_damage=boss.max_posture)

    assert boss.posture == 0
    assert boss.vulnerable is True
    assert boss.BREAK_WINDOW >= 1.0

    # 破绽期间继续挨打：不会把僵直一次次续上
    for _ in range(20):
        boss.take_posture_damage(30)
        boss.update(1.0 / 60.0, (200, 522))
    assert boss.vulnerable is True

    for _ in range(90):
        boss.update(1.0 / 60.0, (200, 522))

    assert boss.posture == boss.max_posture
    assert boss.vulnerable is False
    assert boss.update(1.0 / 60.0, (200, 522)).action == "royal_advance"


def test_boss_keeps_attacking_after_its_posture_breaks(monkeypatch, tmp_path):
    """回归：首领被打空韧性后必须起身继续出手，不能站在原地震刀。"""
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    _enter_level(app, floor=5)
    boss = app.room_enemies[0]
    boss.take_damage(1, posture_damage=boss.max_posture)
    boss.x = app.player.x + 60
    assert boss.vulnerable is True

    attacked = False
    for _ in range(180):
        app._update(1.0 / 60.0)
        if app.pending_enemy_attacks:
            attacked = True
            break

    assert attacked is True
    assert boss.posture == boss.max_posture
    pygame.quit()


# -- 剑气横穿全屏、存档槽位 -------------------------------------------------


def test_skill_wave_travels_from_one_edge_to_the_other(monkeypatch, tmp_path):
    """剑气必须一路斩到屏幕另一侧，而不是走到画面中间就消失。"""
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    _enter_level(app)
    _clear_room(app)
    app.player.x = app.player.bounds_left
    app.echo_energy = main.ECHO_ENERGY_MAX

    app._handle_key(app.keybinds["skill"])
    _advance(app, Player.SKILL_CAST_TIME + 0.02)
    assert app.skill_waves

    # 亮度只在收招阶段衰减，而那时剑气已经飞出画面：全屏范围内都是满亮度
    first = app.skill_waves[0]
    fade_start_x = first.x + (
        main.SKILL_WAVE_LIFE - main.SKILL_WAVE_FADE_TIME
    ) * main.SKILL_WAVE_SPEED
    assert fade_start_x >= main.LOGICAL_SIZE[0]

    farthest = 0.0
    for _ in range(150):
        _advance(app, 1.0 / 60.0)
        for wave in app.skill_waves:
            farthest = max(farthest, wave.x)
        if not app.skill_waves:
            break

    assert farthest >= main.LOGICAL_SIZE[0]
    assert app.skill_waves == []
    pygame.quit()


def test_skill_wave_keeps_the_original_character_scale_crescent(monkeypatch, tmp_path):
    """剑气的模型保持原来那版：比角色略大一圈的半月，不是贯通全屏的光柱。"""
    assert main.SKILL_WAVE_HALF_HEIGHT * 2 > Player.BODY_HEIGHT
    assert main.SKILL_WAVE_HALF_HEIGHT * 2 < main.LOGICAL_SIZE[1] * 0.5

    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    _enter_level(app)
    _clear_room(app)
    app.player.x = app.player.bounds_left
    app.echo_energy = main.ECHO_ENERGY_MAX
    app._handle_key(app.keybinds["skill"])
    _advance(app, Player.SKILL_CAST_TIME + 0.02)

    # 把剑气推到画面右半段再取样，避开左上角 HUD 与角色本身
    for _ in range(120):
        if not app.skill_waves or app.skill_waves[0].x >= 900.0:
            break
        app._update(1.0 / 60.0)
    assert app.skill_waves
    wave = app.skill_waves[0]

    app._draw()
    window = pygame.Rect(round(wave.x) + 24, 200, 60, 420)
    raw = pygame.image.tobytes(app.canvas.subsurface(window), "RGB")
    rows = {
        (index // 3) // window.width
        for index in range(0, len(raw), 3)
        if raw[index] > 190 and raw[index + 1] > 190 and raw[index + 2] > 190
    }

    assert rows
    extent = max(rows) - min(rows) + 1
    assert extent > Player.BODY_HEIGHT * 0.8
    assert extent < 300
    pygame.quit()


def test_start_game_offers_six_slots_and_starts_a_new_save(monkeypatch, tmp_path):
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)

    assert main.SAVE_SLOT_COUNT == 6
    app._activate(1)  # 开始游戏

    assert app.overlay == "slots"
    assert app.slot_mode == "new"
    assert len(app._slot_row_rects()) == main.SAVE_SLOT_COUNT
    assert app.save_slots == [None] * main.SAVE_SLOT_COUNT
    app._draw()  # 六个槽位的列表必须能画出来

    app._activate_slot(2)

    assert app.active_slot == 2
    assert app.overlay is None
    assert app.page == "game"
    assert app.is_tutorial_run is True
    assert app.profile is app.save_slots[2]
    pygame.quit()


def test_new_save_resets_progress_and_restarts_the_tutorial(monkeypatch, tmp_path):
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    app.save_slots[0] = app._new_profile()
    app.save_slots[0]["tutorial_completed"] = True
    app.save_slots[0]["best_floor"] = 3
    app.save_slots[0]["echo_relics"] = 500
    app.save_slots[0]["progression"] = {
        "version": 2,
        "levels": {"vital_lattice": 3},
        "equipped_start_module": None,
    }
    app._activate_slot(0)
    app.player_level = 6
    app.player_exp = 120

    app._activate(1)  # 开始游戏
    app._activate_slot(0)  # 点已有存档：先要求确认

    assert app.slot_confirm_index == 0
    assert app.page == "menu"
    assert app.page != "game"

    app._activate_slot(0)  # 再确认一次才真正覆盖

    assert app.tutorial_completed is False
    assert app.echo_relics == 0
    assert all(level == 0 for level in app._track_levels().values())
    assert app.profile["best_floor"] == 0
    assert app.is_tutorial_run is True
    assert app.run_floor == 1
    assert app.player_level == 1
    assert app.player_exp == 0
    pygame.quit()


def test_continue_game_loads_the_selected_slot(monkeypatch, tmp_path):
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    app.save_slots[3] = app._new_profile()
    app.save_slots[3]["tutorial_completed"] = True
    app.save_slots[3]["best_floor"] = 2
    app.save_slots[3]["echo_relics"] = 120
    app.has_save = True
    app.items = app._build_items()

    app._activate(0)  # 继续游戏

    assert app.overlay == "slots"
    assert app.slot_mode == "continue"

    # 空槽位不能载入，面板保持打开
    app._activate_slot(3)
    assert app.active_slot == 3
    assert app.page == "lobby"
    assert app.echo_relics == 120
    assert app.profile["best_floor"] == 2
    assert app.tutorial_completed is True
    pygame.quit()


def test_continue_game_on_empty_slot_is_rejected(monkeypatch, tmp_path):
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    app.save_slots[1] = app._new_profile()
    app.save_slots[1]["tutorial_completed"] = True
    app.has_save = True
    app.items = app._build_items()
    app._activate(0)

    app._activate_slot(0)

    assert app.overlay == "slots"
    assert app.active_slot is None
    assert "空" in app.notification
    pygame.quit()


def test_continue_game_resumes_an_unfinished_tutorial(monkeypatch, tmp_path):
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
    app.save_slots[1] = app._new_profile()
    app.has_save = True
    app.items = app._build_items()

    app._activate(0)
    app._activate_slot(1)

    assert app.page == "game"
    assert app.is_tutorial_run is True
    assert app.run_floor == 1
    pygame.quit()


def test_slots_and_global_settings_persist_across_restarts(monkeypatch, tmp_path):
    save_file = tmp_path / "save.json"
    monkeypatch.setattr(main, "SAVE_FILE", save_file)
    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)
    app._set_volume(45)

    app._activate_slot(1)
    app.profile["tutorial_completed"] = True
    app.profile["echo_relics"] = 77
    app._save_profile()

    app._activate_slot(4)
    app.profile["echo_relics"] = 12
    app._save_profile()

    again = StartScreen(screen)

    assert again.settings["volume"] == 45
    assert again.save_slots[1]["echo_relics"] == 77
    assert again.save_slots[4]["echo_relics"] == 12
    assert again.save_slots[0] is None
    assert again.has_save is True
    pygame.quit()


def test_legacy_single_profile_save_migrates_into_the_first_slot(monkeypatch, tmp_path):
    """旧版单档案存档不能凭空消失：迁移到 1 号存档位。"""
    save_file = tmp_path / "save.json"
    monkeypatch.setattr(main, "SAVE_FILE", save_file)
    save_file.write_text(
        json.dumps(
            {
                "version": 2,
                "best_score": 900,
                "best_floor": 2,
                "scores": [{"score": 900, "floor": 2, "parries": 3}],
                "tutorial_completed": True,
                "echo_relics": 150,
                "progression": {
                    "unlocked_nodes": ["white_window_record"],
                    "equipped_start_module": None,
                },
                "lifetime_stats": {"settlements": 4},
                "settings": {"volume": 60, "keybinds": {"attack": 106}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)

    assert app.save_slots[0] is not None
    # 旧节点里没有对应新分支的「白窗记录」按原价 40 返还，150 + 40 = 190
    assert app.save_slots[0]["echo_relics"] == 190
    assert app.save_slots[0]["best_floor"] == 2
    # 旧的一次性节点被折叠成分级分支：白窗记录没有对应分支，只返还遗晶
    assert app.save_slots[0]["progression"]["version"] == 2
    assert app.save_slots[0]["progression"]["levels"]["vital_lattice"] == 0
    assert app.save_slots[0]["tutorial_completed"] is True
    assert all(slot is None for slot in app.save_slots[1:])
    assert app.settings["volume"] == 60
    assert app.keybinds["attack"] == 106
    assert app.has_save is True
    pygame.quit()
