import json
import os

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

    for _ in range(180):
        player.update(1.0 / 60.0, 1)
    assert player.x == player.bounds_right

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
    app._start_run(1, tutorial=False)
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
    app.profile["progression"] = {
        "unlocked_nodes": ["reserve_carry"],
        "equipped_start_module": None,
    }

    app._start_run(1, tutorial=False)

    assert app.run_currency == 20
    pygame.quit()


def test_defeated_enemy_is_removed_from_active_room(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "SAVE_FILE", tmp_path / "save.json")

    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)
    app._start_run(1, tutorial=False)
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
    enemy = Chaser(app.player.x + 40, 522)
    app.room_enemies = [enemy]
    app.player.hp = enemy.damage
    app.run_score = 420
    app.run_currency = 17
    app.pending_enemy_attacks = [
        PendingEnemyAttack(enemy, enemy.scaled_attack(), 0.001)
    ]

    app._update(1.0 / 60.0)

    assert app.player.hp == 0
    assert app.page == "failure"
    assert app.result_score == 420
    assert app.result_relics == 25
    assert app.pending_enemy_attacks == []
    assert app._stat("failures") == 1
    assert json.loads(save_file.read_text(encoding="utf-8"))["echo_relics"] == 25

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
    app._start_run(1, tutorial=False)
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
        if app._current_tutorial_step.action == "finish":
            break
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

    app._activate_lobby_action(0)
    assert app.page == "game"
    assert app.is_tutorial_run is False
    assert app.tutorial_index == len(app.tutorial_steps) - 1
    pygame.quit()


def test_lobby_nexus_unlocks_available_node_and_persists(monkeypatch, tmp_path):
    save_file = tmp_path / "save.json"
    monkeypatch.setattr(main, "SAVE_FILE", save_file)

    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)
    app.profile["tutorial_completed"] = True
    app.profile["echo_relics"] = 40
    app._enter_lobby()
    app._activate_lobby_action(1)

    assert app.overlay == "progression"
    app._activate_progression_node(0)

    assert "aftershock_calibration" in app._unlocked_nodes()
    assert app.echo_relics == 0
    saved = json.loads(save_file.read_text(encoding="utf-8"))
    assert "aftershock_calibration" in saved["progression"]["unlocked_nodes"]
    assert saved["echo_relics"] == 0
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
    app._start_run(1, tutorial=False)

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
    app.player.update(app.player.PARRY_DURATION, 0)
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
    assert app.profile["settings"]["volume"] == 35

    app._change_setting(0, 5)
    assert app.settings["volume"] == 40
    assert recorder.volume == 40
    pygame.quit()


def test_dash_has_cooldown_and_grants_invulnerability(monkeypatch, tmp_path):
    app, _recorder = _app_with_recording_audio(monkeypatch, tmp_path)
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
