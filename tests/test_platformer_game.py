"""Comprehensive verification test suite for 'The Alchemical Jumper' 2D platformer.

Derived from observable user requirements, engine contracts, and failure cases:
1. Hierarchy & Platformer Entities (test_platformer_hierarchy_and_entities):
   - Root 'Application' has children 'Game' and 'Editor'.
   - 'Game' contains 'Player', 'GroundMain', 'PlatformLow', 'PlatformMid', 'PlatformHigh',
     'MovingPlatform', 'Coin1', 'Coin2', 'Coin3', 'GoalFlag', 'Goblin', 'AlchemistToolkit', 'GameGUI'.
   - 'Player' has components 'Transform', 'Health', 'Stats', 'PlatformerBody',
     'Property:HealthPercent', 'Property:LivesPercent', 'Property:CoinsPercent', 'Property:SpeedMeters'.
   - 'Player' linked children: 'PlayerNameTag', 'PlayerHealthBar', 'Excalibur'.
   - Retained subtrees: 'Goblin' with child 'GoblinHP', 'GameGUI' with 'Button',
     'Editor' with 'Hierarchy Panel' and 'Inspector Panel'.
2. Parent Value Projection on Child UI Components (test_child_component_uses_actual_parent_values):
   - Child PlayerHealthBar dynamically evaluates parent Player lives (LivesPercent / HealthPercent).
   - Live mutation of parent Health is immediately reflected in child property.
   - Headless ViewportPanel draws billboard slider with width projected from live parent value.
3. 2D Platformer Gravity & AABB Landing (test_platformer_gravity_and_landing):
   - Falling player accelerates downward under gravity (vy > 0).
   - Clean landing on platform surface: on_ground == True, vy == 0.0, foot aligns with platform top.
4. Keyboard Jump & Double Jump Input (test_platformer_jump_and_double_jump):
   - Jump key applies upward impulse when grounded.
   - Mid-air jump key applies double jump impulse and consumes can_double_jump.
   - Triple jump is strictly prohibited.
5. Moving Platform Ride-Along (test_moving_platform_ride_along):
   - Moving platform oscillates horizontally.
   - Grounded player riding on moving platform is carried horizontally along with platform.
6. Collectible Coin Pickup Proximity (test_collectible_coin_pickup):
   - Moving onto uncollected coin marks it collected, increments player coins, updates CoinsPercent.
   - Collected coins cannot be re-collected.
7. Action Button UUID Exports (test_platformer_action_button_exports):
   - SuperJumpBtn triggers exported super_jump_action, boosting jump force.
   - RespawnBtn triggers exported respawn_player_action, resetting coordinates.
   - HealBtn restores HP capped at max.
8. Pit Falling & Auto-Respawn (test_pit_falling_and_respawn):
   - Falling below y=420 deducts 1 life and resets position to start (100.0, 200.0).
   - Zero-life clamping on game over pit fall.
9. Persistence, Restart & Stale Safety:
   - JSON roundtrip preserves all entity state and dynamic property resolution.
   - Mutation persistence across independent Kernel sessions.
   - Stale handle access and deleted entity event dispatch fail safely without kernel corruption.
   - Failed script hot reload rolls back cleanly to previous working code.
10. Planned Features:
    - Skipped stubs for automatic UUID rename refactoring, sloped collision, tilemap chunking.
"""

import math
from pathlib import Path
import pytest

import dearpygui.dearpygui as dpg

from LBE import Kernel
from LBE.proxy import EntityProxy
from LBE.types import Error, RuntimeIDNotFoundOnMemoryError
from editor.session import EditorSession
from editor.viewport_panel import ViewportPanel
from main import populate_demo_world_if_empty, run_headless_simulation


@pytest.fixture
def dpg_context():
    """Isolated Dear PyGui context per test."""
    try:
        dpg.destroy_context()
    except Exception:
        pass
    dpg.create_context()
    yield
    try:
        dpg.destroy_context()
    except Exception:
        pass


def _find_entity_by_name(kernel: Kernel, name: str) -> EntityProxy | None:
    for rid in kernel.resources:
        if kernel.is_entity(rid):
            res = kernel.get_resource(rid)
            if res.get("name") == name:
                return kernel.get_entity_proxy(rid)
    return None


class TestPlatformerHierarchyAndEntities:
    """1. Verify hierarchy structure and entity composition of 'The Alchemical Jumper'."""

    def test_platformer_hierarchy_and_entities(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)

        # 1. Root Application
        roots = [
            kernel.get_entity_proxy(rid)
            for rid in kernel.resources
            if kernel.is_entity(rid) and kernel.get_entity_parent(rid) is None
        ]
        assert len(roots) == 1, f"Expected 1 root entity, got {[r.name for r in roots]}"
        app = roots[0]
        assert app.name == "Application"

        # Children of Application: Game and Editor
        app_child_names = {c.name for c in app.children}
        assert app_child_names == {"Game", "Editor"}

        # 2. Game Branch
        game = app.find_child("Game")
        assert game is not None
        game_child_names = {c.name for c in game.children}
        expected_game_children = {
            "Player",
            "GroundMain",
            "PlatformLow",
            "PlatformMid",
            "PlatformHigh",
            "MovingPlatform",
            "Coin1",
            "Coin2",
            "Coin3",
            "GoalFlag",
            "Goblin",
            "AlchemistToolkit",
            "GameGUI",
        }
        assert expected_game_children.issubset(game_child_names), (
            f"Missing game children: {expected_game_children - game_child_names}"
        )

        # 3. Player Entity & Components
        player = game.find_child("Player")
        assert player is not None
        assert player.has("PlatformerBody")
        assert player.has("Health")
        assert player.has("Stats")
        assert player.has("Transform")
        assert player.has("Property:CoinsPercent")
        assert player.has("Property:LivesPercent")
        assert player.has("Property:SpeedMeters")

        # Player Linked Children
        player_child_names = {c.name for c in player.children}
        expected_player_children = {"PlayerNameTag", "PlayerHealthBar", "Excalibur"}
        assert expected_player_children.issubset(player_child_names), (
            f"Missing player children: {expected_player_children - player_child_names}"
        )

        # PlayerHealthBar component validation
        hp_bar = player.find_child("PlayerHealthBar")
        assert hp_bar is not None
        assert hp_bar.has("UISlider")
        assert hp_bar.has("Property:Value") or hp_bar.has("Property:HealthPercent")

        # Platforms validation
        moving_plat = game.find_child("MovingPlatform")
        assert moving_plat is not None
        assert moving_plat.has("Platform")
        assert moving_plat.has("MovingPlatformData")

        # Collectibles validation
        for coin_name in ("Coin1", "Coin2", "Coin3"):
            coin = game.find_child(coin_name)
            assert coin is not None
            assert coin.has("Collectible")

        # Goal validation
        goal = game.find_child("GoalFlag")
        assert goal is not None
        assert goal.has("Goal")

        # Retained Subtrees: Goblin & GoblinHP
        goblin = game.find_child("Goblin")
        assert goblin is not None
        assert goblin.find_child("GoblinHP") is not None

        # Retained Subtrees: GameGUI & Button
        gui = game.find_child("GameGUI")
        assert gui is not None
        assert gui.find_child("Button") is not None

        # Retained Subtrees: Editor Panels
        editor = app.find_child("Editor")
        assert editor is not None
        assert editor.find_child("Hierarchy Panel") is not None
        assert editor.find_child("Inspector Panel") is not None

    def test_default_template_is_platformer(self, tmp_path: Path):
        """Verify populate_demo_world_if_empty defaults to platformer template."""
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)
        ground = _find_entity_by_name(kernel, "GroundMain")
        assert ground is not None
        assert ground.has("Platform")

    def test_idempotent_population(self, tmp_path: Path):
        """Calling populate_demo_world_if_empty on non-empty world does not duplicate entities."""
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)
        count_first = len(list(kernel.resources.keys()))

        populate_demo_world_if_empty(kernel)
        count_second = len(list(kernel.resources.keys()))
        assert count_first == count_second

    def test_platformer_uuid_33char_rejection_and_defect_documentation(self, tmp_path: Path):
        """Preserve reproducible defect: engine strictly validates 32/64 char UUIDs, rejecting 33-char UUIDs in main.py."""
        kernel = Kernel(tmp_path)
        UUID_33_CHAR = "a1000000000000000000000000000000b"
        assert len(UUID_33_CHAR) == 33

        res = kernel.create_entity(
            name="DefectiveEntity",
            components={
                "Property:Value": {"getter": UUID_33_CHAR},
            },
        )
        assert isinstance(res, Error)
        assert "hex string length must be 32 or 64 characters" in res.description


class TestParentValueProjectionOnChildComponents:
    """2. Verify dynamic parent property value projection onto child UI components."""

    def test_child_component_uses_actual_parent_values(self, tmp_path: Path, dpg_context):
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)

        player = _find_entity_by_name(kernel, "Player")
        assert player is not None
        player_hp_bar = player.find_child("PlayerHealthBar")
        assert player_hp_bar is not None

        # 1. Full health (3/3 lives) -> child Value dynamically returns 1.0
        val = getattr(player_hp_bar, "Value", None)
        assert val is not None
        assert math.isclose(float(val), 1.0, abs_tol=1e-3)

        # 2. Mutate parent health -> child Value dynamically updates to 1.0 / 3.0
        player.Health["current"] = 1.0
        val_mutated = getattr(player_hp_bar, "Value", None)
        assert val_mutated is not None
        assert math.isclose(float(val_mutated), 1.0 / 3.0, abs_tol=1e-3)

        # 3. ViewportPanel widget projection
        session = EditorSession(kernel)
        vp = ViewportPanel(session)
        vp.build()
        vp.redraw()

        items = dpg.get_item_children(vp.drawlist_tag, 2)
        assert len(items) > 0
        rects = [it for it in items if dpg.get_item_type(it) == "mvAppItemType::mvDrawRect"]
        expected_inner_w = (40.0 - 2.0) * (1.0 / 3.0)
        matched_inner_w = any(
            math.isclose(dpg.get_item_configuration(r)["pmax"][0] - dpg.get_item_configuration(r)["pmin"][0], expected_inner_w, abs_tol=0.5)
            for r in rects
        )
        assert matched_inner_w, "ViewportPanel did not render child slider with projected parent health ratio"

    def test_child_component_value_projection_contract_isolated(self, tmp_path: Path, dpg_context):
        """Isolated verification of parent property value projection and ViewportPanel rendering using valid 32-char UUID."""
        kernel = Kernel(tmp_path)
        UUID_CHILD_HEALTH_GET = "a100000000000000000000000000000b"
        UUID_HEALTH_GET = "a1000000000000000000000000000001"
        assert len(UUID_CHILD_HEALTH_GET) == 32
        assert len(UUID_HEALTH_GET) == 32

        code = f'''
@export("{UUID_HEALTH_GET}")
def health_percent_get(entity):
    max_hp = float(entity.Health.max)
    return (float(entity.Health.current) / max_hp) * 100.0 if max_hp > 0 else 0.0

@export("{UUID_CHILD_HEALTH_GET}")
def child_health_percent_get(entity):
    parent = getattr(entity, "parent", None)
    if parent is not None:
        val = getattr(parent, "HealthPercent", 100.0)
        return float(val) / 100.0
    return 1.0
'''
        script = kernel.create_script_resource(name="ProjectionLogic", requires=[], code=code)
        player_id = kernel.create_entity(
            name="Hero",
            components={
                "Transform": {"x": 100.0, "y": 200.0, "z": 0.0},
                "Health": {"current": 3.0, "max": 3.0},
                "Property:HealthPercent": {"getter": UUID_HEALTH_GET},
            },
        )
        kernel.attach_script(player_id, script)

        hp_bar_id = kernel.create_entity(
            name="HeroHPBar",
            parent_id=player_id,
            components={
                "Transform": {"x": 0.0, "y": -16.0, "z": 0.0},
                "UISlider": {"label": "Lives", "value": 1.0, "min": 0.0, "max": 1.0},
                "Property:Value": {"getter": UUID_CHILD_HEALTH_GET},
            },
        )
        player = kernel.get_entity_proxy(player_id)
        hp_bar = kernel.get_entity_proxy(hp_bar_id)

        # 1. Full health projection
        assert math.isclose(float(hp_bar.Value), 1.0, abs_tol=1e-3)

        # 2. Mutate parent health to 1.0 / 3.0
        player.Health["current"] = 1.0
        assert math.isclose(float(hp_bar.Value), 1.0 / 3.0, abs_tol=1e-3)

        # 3. ViewportPanel rendering
        session = EditorSession(kernel)
        vp = ViewportPanel(session)
        vp.build()
        vp.redraw()

        items = dpg.get_item_children(vp.drawlist_tag, 2)
        rects = [it for it in items if dpg.get_item_type(it) == "mvAppItemType::mvDrawRect"]
        expected_inner_w = (40.0 - 2.0) * (1.0 / 3.0)
        matched_inner_w = any(
            math.isclose(dpg.get_item_configuration(r)["pmax"][0] - dpg.get_item_configuration(r)["pmin"][0], expected_inner_w, abs_tol=0.5)
            for r in rects
        )
        assert matched_inner_w, "Isolated ViewportPanel test did not render child slider with projected ratio"


class TestPlatformerPhysicsAndMovement:
    """3. Verify 2D platformer physics, gravity, jumping, and moving platform kinematics."""

    def test_platformer_gravity_and_landing(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)

        player = _find_entity_by_name(kernel, "Player")
        assert player is not None

        # Position player in the air directly above GroundMain (x=250.0, y=250.0, below PlatformMid)
        player.Transform.x = 250.0
        player.Transform.y = 250.0
        player.PlatformerBody["vy"] = 0.0
        player.PlatformerBody["on_ground"] = False

        # Advance 1 tick -> downward gravity acceleration
        kernel.tick(0.05)
        assert float(player.PlatformerBody.vy) > 0.0

        # Advance ticks until player lands on GroundMain (plat_y=340.0, height=30.0 -> plat_top=325.0)
        for _ in range(25):
            kernel.tick(0.05)

        # GroundMain top is 325.0; player foot is y + 16.0 -> landed y is 309.0
        assert bool(player.PlatformerBody.on_ground) is True
        assert math.isclose(float(player.PlatformerBody.vy), 0.0, abs_tol=1e-3)
        assert math.isclose(float(player.Transform.y), 309.0, abs_tol=1e-1)

    def test_platformer_horizontal_movement(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)

        player = _find_entity_by_name(kernel, "Player")
        assert player is not None
        player.Transform.x = 250.0
        player.Transform.y = 309.0
        player.PlatformerBody["on_ground"] = True
        player.PlatformerBody["vy"] = 0.0

        # Move right with 'D' key
        kernel.input_state = {"keys": {"D"}}
        kernel.tick(0.05)
        assert float(player.Transform.x) > 250.0

        # Move left with 'A' key
        cur_x = float(player.Transform.x)
        kernel.input_state = {"keys": {"A"}}
        kernel.tick(0.1)
        assert float(player.Transform.x) < cur_x

    def test_platformer_jump_and_double_jump(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)

        player = _find_entity_by_name(kernel, "Player")
        assert player is not None
        player.Transform.x = 250.0
        player.Transform.y = 309.0
        player.PlatformerBody["vy"] = 0.0
        player.PlatformerBody["on_ground"] = True

        # First jump from ground
        kernel.input_state = {"keys": {"SPACE"}}
        kernel.tick(0.02)
        assert float(player.PlatformerBody.vy) < 0.0
        assert bool(player.PlatformerBody.on_ground) is False
        assert bool(player.PlatformerBody.can_double_jump) is True

        # Release jump key while in air
        kernel.input_state = {"keys": set()}
        kernel.tick(0.02)

        # Execute double jump while in air
        kernel.input_state = {"keys": {"SPACE"}}
        kernel.tick(0.02)
        assert bool(player.PlatformerBody.can_double_jump) is False
        assert float(player.PlatformerBody.vy) < 0.0

    def test_triple_jump_prohibited(self, tmp_path: Path):
        """After double jump is consumed, pressing jump again in mid-air does not apply another impulse."""
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)

        player = _find_entity_by_name(kernel, "Player")
        assert player is not None
        player.Transform.x = 250.0
        player.Transform.y = 309.0
        player.PlatformerBody["vy"] = 0.0
        player.PlatformerBody["on_ground"] = True

        # Jump 1
        kernel.input_state = {"keys": {"SPACE"}}
        kernel.tick(0.02)
        # Release
        kernel.input_state = {"keys": set()}
        kernel.tick(0.02)
        # Double Jump
        kernel.input_state = {"keys": {"SPACE"}}
        kernel.tick(0.02)
        assert bool(player.PlatformerBody.can_double_jump) is False

        # Attempt triple jump
        kernel.input_state = {"keys": set()}
        kernel.tick(0.02)
        pre_vy = float(player.PlatformerBody.vy)
        kernel.input_state = {"keys": {"SPACE"}}
        kernel.tick(0.02)

        # vy should continue falling under gravity, not boosted upward
        assert float(player.PlatformerBody.vy) >= pre_vy

    def test_moving_platform_ride_along(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)

        player = _find_entity_by_name(kernel, "Player")
        moving_plat = _find_entity_by_name(kernel, "MovingPlatform")
        assert player is not None and moving_plat is not None

        init_plat_x = float(moving_plat.Transform.x)
        plat_top = float(moving_plat.Transform.y) - float(moving_plat.Platform.height) / 2.0

        # Place player on top of moving platform
        player.Transform.x = init_plat_x
        player.Transform.y = plat_top - 16.0
        player.PlatformerBody["on_ground"] = True
        player.PlatformerBody["vy"] = 0.0

        # Tick simulation
        for _ in range(5):
            kernel.tick(0.1)

        # Platform moved horizontally
        assert float(moving_plat.Transform.x) != init_plat_x
        # Player rode along horizontally with the platform
        assert math.isclose(float(player.Transform.x), float(moving_plat.Transform.x), abs_tol=10.0)
        assert bool(player.PlatformerBody.on_ground) is True

    def test_pit_falling_and_respawn(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)

        player = _find_entity_by_name(kernel, "Player")
        assert player is not None
        initial_hp = float(player.Health.current)

        # Place player into bottom pit (y > 420.0)
        player.Transform.y = 450.0
        kernel.tick(0.02)

        # Lost 1 life
        assert float(player.Health.current) == initial_hp - 1.0
        # Auto-respawned at start coordinates (100.0, 200.0)
        assert math.isclose(float(player.Transform.x), 100.0, abs_tol=1e-3)
        assert math.isclose(float(player.Transform.y), 200.0, abs_tol=1e-3)

    def test_game_over_pit_loss(self, tmp_path: Path):
        """Falling into pit at 1 HP reduces health to 0 without going negative."""
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)

        player = _find_entity_by_name(kernel, "Player")
        assert player is not None
        player.Health["current"] = 1

        player.Transform.y = 450.0
        kernel.tick(0.02)
        assert float(player.Health.current) == 0.0


class TestCollectiblesAndInteractions:
    """4. Verify collectible coin pickup, coin counters, and enemy interactions."""

    def test_collectible_coin_pickup(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)

        player = _find_entity_by_name(kernel, "Player")
        coin1 = _find_entity_by_name(kernel, "Coin1")
        assert player is not None and coin1 is not None

        assert bool(coin1.Collectible["collected"]) is False
        assert int(player.Stats["coins"]) == 0

        # Move player to coin position
        player.Transform.x = float(coin1.Transform.x)
        player.Transform.y = float(coin1.Transform.y)
        kernel.tick(0.02)

        assert bool(coin1.Collectible["collected"]) is True
        assert int(player.Stats["coins"]) == 1
        # Dynamic CoinsPercent: 1 / 5 = 20.0%
        assert math.isclose(float(player.CoinsPercent), 20.0, abs_tol=1e-3)

    def test_multiple_coin_collection(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)

        player = _find_entity_by_name(kernel, "Player")
        coin1 = _find_entity_by_name(kernel, "Coin1")
        coin2 = _find_entity_by_name(kernel, "Coin2")
        assert player is not None and coin1 is not None and coin2 is not None

        player.Transform.x = float(coin1.Transform.x)
        player.Transform.y = float(coin1.Transform.y)
        kernel.tick(0.02)

        player.Transform.x = float(coin2.Transform.x)
        player.Transform.y = float(coin2.Transform.y)
        kernel.tick(0.02)

        assert int(player.Stats["coins"]) == 2
        assert math.isclose(float(player.CoinsPercent), 40.0, abs_tol=1e-3)

    def test_already_collected_coin_cannot_be_recollected(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)

        player = _find_entity_by_name(kernel, "Player")
        coin1 = _find_entity_by_name(kernel, "Coin1")
        assert player is not None and coin1 is not None

        player.Transform.x = float(coin1.Transform.x)
        player.Transform.y = float(coin1.Transform.y)
        kernel.tick(0.02)
        assert int(player.Stats["coins"]) == 1

        # Stay on coin for another tick
        kernel.tick(0.02)
        assert int(player.Stats["coins"]) == 1

    def test_stomp_goblin_enemy(self, tmp_path: Path):
        """Falling onto Goblin from above eliminates Goblin and bounces player upward."""
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)

        player = _find_entity_by_name(kernel, "Player")
        goblin = _find_entity_by_name(kernel, "Goblin")
        assert player is not None and goblin is not None

        assert float(goblin.Health.current) == 50.0

        # Run 1 tick so goblin begins its active patrol position on its orbital circle
        kernel.tick(0.02)
        gob_x = float(goblin.Transform.x)
        gob_y = float(goblin.Transform.y)

        # Position player directly above goblin, falling downward (vy > 0)
        player.Transform.x = gob_x
        player.Transform.y = gob_y - 20.0
        player.PlatformerBody["vy"] = 100.0
        player.PlatformerBody["on_ground"] = False

        # Run tick on enemy patrol script
        kernel.tick(0.02)

        # Goblin stomped to 0 HP
        assert float(goblin.Health.current) == 0.0
        # Player bounced upward
        assert float(player.PlatformerBody.vy) < 0.0



class TestPlatformerUIAndActionButtons:
    """5. Verify UI button event dispatch via export UUIDs."""

    def test_platformer_action_button_exports(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)

        player = _find_entity_by_name(kernel, "Player")
        toolkit = _find_entity_by_name(kernel, "AlchemistToolkit")
        assert player is not None and toolkit is not None

        super_jump = toolkit.find_child("SuperJumpBtn", recursive=True)
        respawn = toolkit.find_child("RespawnBtn", recursive=True)
        heal = toolkit.find_child("HealBtn", recursive=True)

        assert super_jump is not None
        assert respawn is not None
        assert heal is not None

        # 1. Super Jump button (+150 jump force)
        init_jf = float(player.PlatformerBody.get("jump_force", 380.0))
        err = kernel.trigger_ui_event(super_jump.id, "on_click")
        assert not isinstance(err, Error)
        assert float(player.PlatformerBody.jump_force) == init_jf + 150.0

        # 2. Respawn button
        player.Transform.x = 450.0
        player.Transform.y = 300.0
        err = kernel.trigger_ui_event(respawn.id, "on_click")
        assert not isinstance(err, Error)
        assert math.isclose(float(player.Transform.x), 100.0, abs_tol=1e-3)
        assert math.isclose(float(player.Transform.y), 200.0, abs_tol=1e-3)

        # 3. Heal Elixir button (+1 HP capped at max)
        player.Health["current"] = 1.0
        err = kernel.trigger_ui_event(heal.id, "on_click")
        assert not isinstance(err, Error)
        assert float(player.Health.current) == 2.0

    def test_platformer_action_buttons_contract_isolated(self, tmp_path: Path):
        """Isolated verification of UI button action execution with valid 32-char UUIDs."""
        kernel = Kernel(tmp_path)
        UUID_JUMP = "a1000000000000000000000000000009"
        UUID_RESPAWN = "a100000000000000000000000000000a"
        assert len(UUID_JUMP) == 32
        assert len(UUID_RESPAWN) == 32

        code = f'''
def _find_player(entity):
    world = getattr(entity, "world", None)
    if world is not None and hasattr(world, "query"):
        for p in world.query("PlatformerBody", "Transform"):
            return p
    return None

@export("{UUID_JUMP}")
def super_jump_action(entity):
    player = _find_player(entity)
    if player is not None and player.has("PlatformerBody"):
        cur = float(player.PlatformerBody.get("jump_force", 380.0))
        player.PlatformerBody["jump_force"] = cur + 150.0

@export("{UUID_RESPAWN}")
def respawn_player_action(entity):
    player = _find_player(entity)
    if player is not None:
        player.Transform.x = 100.0
        player.Transform.y = 200.0
'''
        script = kernel.create_script_resource(name="BtnLogic", requires=[], code=code)
        player_id = kernel.create_entity(
            name="Player",
            components={
                "Transform": {"x": 300.0, "y": 200.0},
                "PlatformerBody": {"jump_force": 380.0},
            },
        )
        kernel.attach_script(player_id, script)

        jump_btn_id = kernel.create_ui_entity(
            name="JumpBtn",
            component_type="UIButton",
            component_props={"label": "Jump", "on_click": UUID_JUMP},
        )
        respawn_btn_id = kernel.create_ui_entity(
            name="RespawnBtn",
            component_type="UIButton",
            component_props={"label": "Respawn", "on_click": UUID_RESPAWN},
        )

        player = kernel.get_entity_proxy(player_id)
        # Click Jump
        err = kernel.trigger_ui_event(jump_btn_id, "on_click")
        assert not isinstance(err, Error)
        assert float(player.PlatformerBody.jump_force) == 530.0

        # Click Respawn
        err = kernel.trigger_ui_event(respawn_btn_id, "on_click")
        assert not isinstance(err, Error)
        assert math.isclose(float(player.Transform.x), 100.0, abs_tol=1e-3)
        assert math.isclose(float(player.Transform.y), 200.0, abs_tol=1e-3)


class TestPlatformerPersistenceAndResilience:
    """6. Verify save/reload roundtrips, mutation persistence, stale handle safety, and rollback."""

    def test_platformer_save_and_reload_roundtrip(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)

        kernel.save_dirty_resources()
        kernel.save_project()

        # Reload in a clean second Kernel
        k2 = Kernel(tmp_path)
        load_res = k2.load_project()
        assert not isinstance(load_res, Error)

        player = _find_entity_by_name(k2, "Player")
        assert player is not None
        assert player.has("PlatformerBody")
        assert player.has("Health")
        assert player.has("Stats")
        assert player.has("Transform")

        # Check platforms
        ground = _find_entity_by_name(k2, "GroundMain")
        assert ground is not None
        assert ground.has("Platform")

        moving_plat = _find_entity_by_name(k2, "MovingPlatform")
        assert moving_plat is not None
        assert moving_plat.has("MovingPlatformData")

        # Check collectibles
        coin = _find_entity_by_name(k2, "Coin1")
        assert coin is not None
        assert coin.has("Collectible")

    def test_platformer_mutation_persistence(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)

        player = _find_entity_by_name(kernel, "Player")
        assert player is not None

        # Mutate health and coins
        player.Health["current"] = 2.0
        player.Stats["coins"] = 3
        player.Transform.x = 222.0
        player.Transform.y = 333.0

        kernel.save_dirty_resources()
        kernel.save_project()

        # Reload
        k2 = Kernel(tmp_path)
        k2.load_project()
        reloaded_player = _find_entity_by_name(k2, "Player")
        assert reloaded_player is not None
        assert math.isclose(float(reloaded_player.Health.current), 2.0, abs_tol=1e-4)
        assert int(reloaded_player.Stats.coins) == 3
        assert math.isclose(float(reloaded_player.Transform.x), 222.0, abs_tol=1e-4)
        assert math.isclose(float(reloaded_player.Transform.y), 333.0, abs_tol=1e-4)
        # Dynamic property on reloaded state
        assert math.isclose(float(reloaded_player.CoinsPercent), 60.0, abs_tol=1e-4)

    def test_platformer_stale_handle_safety(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)

        coin3 = _find_entity_by_name(kernel, "Coin3")
        assert coin3 is not None
        stale_id = coin3.id

        kernel.delete_entity(stale_id)

        # Triggering UI event on deleted entity handle returns Error without crash
        err = kernel.trigger_ui_event(stale_id, "on_click")
        assert isinstance(err, Error)
        assert err.code == RuntimeIDNotFoundOnMemoryError

        # Accessing proxy methods on destroyed entity raises AttributeError
        with pytest.raises(AttributeError, match="destroyed and is no longer valid"):
            _ = coin3.name

    def test_failed_hot_reload_rollback_on_platformer_script(self, tmp_path: Path):
        """Broken script update fails compilation and retains previous working script module."""
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)

        player = _find_entity_by_name(kernel, "Player")
        assert player is not None

        # Find platformer controller script
        script_id = None
        for rid in kernel.resources:
            res = kernel.get_resource(rid)
            if res.get("name") == "PlatformerController":
                script_id = rid
                break
        assert script_id is not None

        # Attempt to hot-reload with syntax error
        bad_code = "def update(self, dt):\n    syntax error in script!"
        err = kernel.update_script_source(script_id, bad_code)
        assert isinstance(err, Error)

        # Previous working script must still function
        player.PlatformerBody["vy"] = 0.0
        player.PlatformerBody["on_ground"] = False
        kernel.tick(0.05)
        assert float(player.PlatformerBody.vy) > 0.0

    def test_platformer_headless_simulation(self, tmp_path: Path, capsys):
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)

        run_headless_simulation(kernel, ticks=5)

        captured = capsys.readouterr().out
        assert "LittleBigEngine - Headless Simulation Mode" in captured
        assert "Simulation completed successfully." in captured


class TestPlannedPlatformerFeatures:
    """7. Clearly separated planned tests for future / unimplemented platformer features."""

    @pytest.mark.skip(reason="Planned test: Preprocessor or editor automatic call-site refactoring when an export UUID is renamed")
    def test_planned_uid_function_rename_refactoring(self):
        """When an export UUID is renamed, UI components and properties referencing the old UUID should be safely refactored."""
        pass

    @pytest.mark.skip(reason="Planned test: Sloped and curved platform surface collision resolution")
    def test_planned_platformer_sloped_collision(self):
        """Raycast-based landing and slope sliding physics on non-horizontal platform geometry."""
        pass

    @pytest.mark.skip(reason="Planned test: Spatial 2D tilemap streaming and collision chunking")
    def test_planned_platformer_tilemap_chunking(self):
        """Spatial hashing and chunking for high-performance large-scale platformer levels."""
        pass
