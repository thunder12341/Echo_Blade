import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

import main
from game.entities import (
    ENEMY_CLASSES,
    Chaser,
    Enemy,
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
