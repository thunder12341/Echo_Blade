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
from main import StartScreen


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
    app._start_run(1)
    enemy = app.room_enemies[0]
    starting_hp = enemy.hp

    app._start_player_attack()
    app.player.update(0.1, 0)
    app._resolve_player_attack()

    assert enemy.hp < starting_hp
    assert app.run_score > 0
    pygame.quit()


def test_initial_room_move_and_jump_use_game_loop_input(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "SAVE_FILE", tmp_path / "save.json")

    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)
    app._start_run(1)
    starting_x = app.player.x

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


def test_down_attack_hit_bounces_player_up(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "SAVE_FILE", tmp_path / "save.json")

    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)
    app._start_run(1)
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

    app._handle_key(app.keybinds["parry"])
    assert app._current_tutorial_step.action == "finish"

    app._activate_page_button("finish")
    assert app.page == "result"
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
