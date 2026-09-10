import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from main import StartScreen


def test_start_screen_menu_states():
    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    app = StartScreen(screen)

    assert len(app.items) == 5
    assert app.selected == 1

    app._handle_key(pygame.K_DOWN)
    assert app.selected == 2
    app._handle_key(pygame.K_UP)
    assert app.selected == 1

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
