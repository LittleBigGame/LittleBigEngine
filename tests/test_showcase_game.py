"""Comprehensive verification test suite for 'The Dungeon of Alchemia' showcase game.

Derived from observable user requirements and engine contracts:
1. Hierarchy & Entity Architecture:
   - Root 'Application' has children 'Game' and 'Editor'.
   - 'Game' contains 'Player', 'Goblin', 'DungeonSlime', 'AlchemistToolkit', 'GameGUI'.
   - 'Player' has child linked entities: 'PlayerNameTag', 'PlayerHealthBar', 'Excalibur',
     'OrbOfPower' (with child 'OrbGlow'), and 'ShieldSatellite'.
   - 'Goblin' has child 'GoblinHP'.
   - 'DungeonSlime' has children 'SlimeNameTag' and 'SlimeHP'.
   - 'AlchemistToolkit' panel contains 'ToolkitHeader', 'PotionBar' (with 'HealPotionBtn',
     'ManaPotionBtn', 'SpeedPotionBtn'), and 'StatusDisplay'.
2. Dynamic Property Components:
   - Dynamic getters evaluate computed values:
     * player.HealthPercent == 85.0
     * player.ManaPercent == 60.0
     * player.SpeedMeters == 1.6
   - Setters mutate underlying ECS component state:
     * player.HealthPercent = 50.0 -> player.Health['current'] == 50.0
     * player.ManaPercent = 100.0 -> player.Stats['mana'] == 100.0
   - Euclidean distance properties dynamically track spatial coordinates:
     * goblin.DistanceToPlayer == math.hypot(goblin.Transform.x - player.Transform.x, goblin.Transform.y - player.Transform.y)
     * slime.DistanceToPlayer == math.hypot(slime.Transform.x - player.Transform.x, slime.Transform.y - player.Transform.y)
3. Input Handling & Movement:
   - Keyboard directional input moves player according to speed and delta time.
   - Spatial bounds clamping keeps player strictly within [40.0, 600.0] on X and [40.0, 400.0] on Y.
4. Linked Entity Multi-Orbit Weapon Physics:
   - Orbital weapons and shields rotate around player at designated speeds.
   - Clockwise (positive) and counter-clockwise (negative) angular rates.
   - Coordinates update to follow orbital circle: x = r * cos(theta), y = r * sin(theta).
5. Enemy AI State Transitions:
   - AI transitions dynamically between 'patrol' and 'chase' based on aggro radius.
   - During 'chase', enemy vectors towards the player's current coordinates.
6. Interactive UI Button Actions via UUID Exports:
   - Potion buttons trigger exported script actions via UUID export references.
   - Heal potion increases health by +25 HP (capped at max).
   - Mana potion increases mana by +30 MP (capped at max).
   - Swiftness tonic boosts speed.
7. Overhead UI Billboard Synchronization:
   - Health bar slider components track entity HealthPercent every tick.
8. Headless Simulation Runner:
   - run_headless_simulation executes multiple simulation ticks cleanly.
9. Persistence & Stale Safety:
   - Save and reload roundtrip preserves world state and property functionality.
   - Stale handle dispatch and deleted entity access fail safely.
10. Planned Features:
    - Automatic UUID rename refactoring, continuous orbital collision detection, transactional inventory rollback.
"""

import math
from pathlib import Path
import pytest

from LBE import Kernel
from LBE.proxy import EntityProxy
from LBE.types import Error, RuntimeIDNotFoundOnMemoryError
from main import populate_demo_world_if_empty, run_headless_simulation


def _find_entity_by_name(kernel: Kernel, name: str) -> EntityProxy | None:
    for rid in kernel.resources:
        if kernel.is_entity(rid):
            res = kernel.get_resource(rid)
            if res.get("name") == name:
                return kernel.get_entity_proxy(rid)
    return None


class TestShowcaseHierarchyAndEntities:
    """1. Verify hierarchy structure and entity composition of 'The Dungeon of Alchemia'."""

    def test_showcase_hierarchy_and_entities(self, tmp_path: Path):
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
        expected_game_children = {"Player", "Goblin", "DungeonSlime", "AlchemistToolkit", "GameGUI"}
        assert expected_game_children.issubset(game_child_names), (
            f"Missing game children: {expected_game_children - game_child_names}"
        )

        # 3. Player Entity & Linked Children
        player = game.find_child("Player")
        assert player is not None
        player_child_names = {c.name for c in player.children}
        expected_player_children = {
            "PlayerNameTag",
            "PlayerHealthBar",
            "Excalibur",
            "OrbOfPower",
            "ShieldSatellite",
        }
        assert expected_player_children.issubset(player_child_names), (
            f"Missing player children: {expected_player_children - player_child_names}"
        )

        # Child of OrbOfPower: OrbGlow
        orb = player.find_child("OrbOfPower")
        assert orb is not None
        orb_glow = orb.find_child("OrbGlow")
        assert orb_glow is not None
        assert orb_glow.has("UIText")

        # 4. Goblin Entity & Overhead UI
        goblin = game.find_child("Goblin")
        assert goblin is not None
        goblin_hp = goblin.find_child("GoblinHP")
        assert goblin_hp is not None
        assert goblin_hp.has("UISlider")

        # 5. DungeonSlime Entity & Overhead UI
        slime = game.find_child("DungeonSlime")
        assert slime is not None
        slime_name = slime.find_child("SlimeNameTag")
        assert slime_name is not None
        assert slime_name.has("UIText")
        slime_hp = slime.find_child("SlimeHP")
        assert slime_hp is not None
        assert slime_hp.has("UISlider")

        # 6. AlchemistToolkit Panel & UI Controls
        toolkit = game.find_child("AlchemistToolkit")
        assert toolkit is not None
        assert toolkit.has("Panel")
        assert toolkit.has("UIContainer")

        toolkit_header = toolkit.find_child("ToolkitHeader")
        assert toolkit_header is not None
        assert toolkit_header.has("UIText")

        status_display = toolkit.find_child("StatusDisplay")
        assert status_display is not None
        assert status_display.has("UIText")

        potion_bar = toolkit.find_child("PotionBar")
        assert potion_bar is not None
        assert potion_bar.has("UIContainer")

        potion_bar_children = {c.name for c in potion_bar.children}
        expected_buttons = {"HealPotionBtn", "ManaPotionBtn", "SpeedPotionBtn"}
        assert expected_buttons == potion_bar_children

        for btn_name in expected_buttons:
            btn = potion_bar.find_child(btn_name)
            assert btn is not None
            assert btn.has("UIButton")
            assert "on_click" in btn.UIButton


class TestShowcaseProperties:
    """2. Verify pure-UUID dynamic property getters, setters, and spatial queries."""

    def test_showcase_properties(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)

        player = _find_entity_by_name(kernel, "Player")
        goblin = _find_entity_by_name(kernel, "Goblin")
        slime = _find_entity_by_name(kernel, "DungeonSlime")

        assert player is not None and goblin is not None and slime is not None

        # Verify initial getters
        assert math.isclose(player.HealthPercent, 85.0, abs_tol=1e-4)
        assert math.isclose(player.ManaPercent, 60.0, abs_tol=1e-4)
        assert math.isclose(player.SpeedMeters, 1.6, abs_tol=1e-4)

        # Verify setter: HealthPercent
        player.HealthPercent = 50.0
        assert math.isclose(player.Health["current"], 50.0, abs_tol=1e-4)
        assert math.isclose(player.HealthPercent, 50.0, abs_tol=1e-4)

        # Verify setter: ManaPercent
        player.ManaPercent = 100.0
        assert math.isclose(player.Stats["mana"], 100.0, abs_tol=1e-4)
        assert math.isclose(player.ManaPercent, 100.0, abs_tol=1e-4)

        # Verify setter: SpeedMeters
        player.SpeedMeters = 2.4
        assert math.isclose(player.Stats["speed"], 240.0, abs_tol=1e-4)
        assert math.isclose(player.SpeedMeters, 2.4, abs_tol=1e-4)
        # Restore speed
        player.SpeedMeters = 1.6

        # Verify goblin.DistanceToPlayer
        expected_goblin_dist = math.hypot(
            float(goblin.Transform.x) - float(player.Transform.x),
            float(goblin.Transform.y) - float(player.Transform.y),
        )
        assert math.isclose(goblin.DistanceToPlayer, expected_goblin_dist, rel_tol=1e-4)
        assert math.isclose(goblin.DistanceToPlayer, 300.0, rel_tol=1e-4)

        # Verify slime.DistanceToPlayer
        expected_slime_dist = math.hypot(
            float(slime.Transform.x) - float(player.Transform.x),
            float(slime.Transform.y) - float(player.Transform.y),
        )
        assert math.isclose(slime.DistanceToPlayer, expected_slime_dist, rel_tol=1e-4)

        # Verify dynamic recalculation when entity positions change
        player.Transform.x = 200.0
        player.Transform.y = 250.0
        new_goblin_dist = math.hypot(float(goblin.Transform.x) - 200.0, float(goblin.Transform.y) - 250.0)
        assert math.isclose(goblin.DistanceToPlayer, new_goblin_dist, rel_tol=1e-4)

    def test_property_edge_cases_and_error_handling(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)

        player = _find_entity_by_name(kernel, "Player")
        assert player is not None

        # Zero max HP safety in health_percent_get -> protects against ZeroDivisionError
        player.Health["max"] = 0.0
        assert player.HealthPercent == 0.0

        # Non-existent property raises AttributeError
        with pytest.raises(AttributeError, match="has no component or attribute 'NonExistentProp'"):
            _ = player.NonExistentProp


class TestPlayerKeyboardMovementAndBounds:
    """3. Verify keyboard input processing, directional movement, and bounding box clamping."""

    def test_player_keyboard_movement_and_bounds(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)

        player = _find_entity_by_name(kernel, "Player")
        assert player is not None

        # Start player at exact coordinates (100.0, 200.0)
        player.Transform.x = 100.0
        player.Transform.y = 200.0
        player.Stats.speed = 160.0

        # Move Right (D)
        kernel.input_state["keys"] = {"D"}
        kernel.tick(0.1)
        assert player.Transform.x > 100.0
        # spd=160, dt=0.1 -> dx = +16.0
        assert math.isclose(player.Transform.x, 116.0, abs_tol=1e-3)

        # Move Up (W)
        kernel.input_state["keys"] = {"W"}
        kernel.tick(0.1)
        assert player.Transform.y < 200.0
        # spd=160, dt=0.1 -> dy = -16.0
        assert math.isclose(player.Transform.y, 184.0, abs_tol=1e-3)

        # Move Left (A)
        kernel.input_state["keys"] = {"A"}
        kernel.tick(0.1)
        assert math.isclose(player.Transform.x, 100.0, abs_tol=1e-3)

        # Move Down (S)
        kernel.input_state["keys"] = {"S"}
        kernel.tick(0.1)
        assert math.isclose(player.Transform.y, 200.0, abs_tol=1e-3)

        # Bounds Clamping: Max Bounds [600.0, 400.0]
        player.Transform.x = 750.0
        player.Transform.y = 550.0
        kernel.input_state["keys"] = set()
        kernel.tick(0.01)
        assert math.isclose(player.Transform.x, 600.0, abs_tol=1e-3)
        assert math.isclose(player.Transform.y, 400.0, abs_tol=1e-3)

        # Continuing to move right while at max boundary keeps position clamped at 600.0
        kernel.input_state["keys"] = {"D"}
        kernel.tick(0.1)
        assert math.isclose(player.Transform.x, 600.0, abs_tol=1e-3)

        # Bounds Clamping: Min Bounds [40.0, 40.0]
        player.Transform.x = 10.0
        player.Transform.y = -20.0
        kernel.input_state["keys"] = set()
        kernel.tick(0.01)
        assert math.isclose(player.Transform.x, 40.0, abs_tol=1e-3)
        assert math.isclose(player.Transform.y, 40.0, abs_tol=1e-3)

        # Continuing to move left while at min boundary keeps position clamped at 40.0
        kernel.input_state["keys"] = {"A"}
        kernel.tick(0.1)
        assert math.isclose(player.Transform.x, 40.0, abs_tol=1e-3)


class TestOrbitalWeaponPhysics:
    """4. Verify multi-orbit rotation physics of linked weapons and shields."""

    def test_orbital_weapon_physics(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)

        player = _find_entity_by_name(kernel, "Player")
        assert player is not None

        excalibur = player.find_child("Excalibur")
        orb = player.find_child("OrbOfPower")
        shield = player.find_child("ShieldSatellite")

        assert excalibur is not None
        assert orb is not None
        assert shield is not None

        # Verify initial configurations
        init_excalibur_rot = float(excalibur.Transform.rot_z)
        init_orb_rot = float(orb.Transform.rot_z)
        init_shield_rot = float(shield.Transform.rot_z)

        assert math.isclose(init_excalibur_rot, 0.0, abs_tol=1e-3)
        assert math.isclose(init_orb_rot, 0.0, abs_tol=1e-3)
        assert math.isclose(init_shield_rot, 0.0, abs_tol=1e-3)

        # Run orbital physics tick: dt = 0.2
        # Excalibur: orbit_speed = 120.0 -> cur_angle = (0.0 + 120.0 * 0.2) = 24.0
        # OrbOfPower: orbit_speed = -150.0 -> cur_angle = (180.0 - 150.0 * 0.2) = 150.0
        # ShieldSatellite: orbit_speed = 80.0 -> cur_angle = (90.0 + 80.0 * 0.2) = 106.0
        dt = 0.2
        kernel.tick(dt)

        assert math.isclose(excalibur.Transform.rot_z, 24.0, abs_tol=1e-3)
        assert math.isclose(orb.Transform.rot_z, 150.0, abs_tol=1e-3)
        assert math.isclose(shield.Transform.rot_z, 106.0, abs_tol=1e-3)

        # Excalibur rotated clockwise (angle increased)
        assert excalibur.Transform.rot_z > 0.0

        # OrbOfPower rotated counter-clockwise (angle decreased from initial component angle of 180.0)
        assert orb.Weapon["angle"] < 180.0

        # Check orbital spatial positions match trigonometric coordinates (r * cos(a), r * sin(a))
        expected_exc_x = 32.0 * math.cos(math.radians(24.0))
        expected_exc_y = 32.0 * math.sin(math.radians(24.0))
        assert math.isclose(excalibur.Transform.x, expected_exc_x, abs_tol=1e-3)
        assert math.isclose(excalibur.Transform.y, expected_exc_y, abs_tol=1e-3)


class TestEnemyAIPatrolAndChase:
    """5. Verify enemy AI state machine transitions (patrol <-> chase)."""

    def test_enemy_ai_patrol_and_chase(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)

        player = _find_entity_by_name(kernel, "Player")
        goblin = _find_entity_by_name(kernel, "Goblin")
        assert player is not None and goblin is not None

        # 1. Player far away: (100, 200), Goblin at (400, 200) -> distance 300 > aggro 150
        player.Transform.x = 100.0
        player.Transform.y = 200.0
        goblin.Transform.x = 400.0
        goblin.Transform.y = 200.0

        kernel.tick(0.1)
        assert goblin.AI["state"] == "patrol"

        # 2. Move player within aggro radius: (350, 200) -> distance 50 < aggro 150
        player.Transform.x = 350.0
        player.Transform.y = 200.0
        goblin_x_before = float(goblin.Transform.x)

        kernel.tick(0.1)
        assert goblin.AI["state"] == "chase"
        # Goblin must move closer to player (dx = 350 - 400 = -50, x decreases)
        assert goblin.Transform.x < goblin_x_before

    def test_slime_ai_aggro_transition(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)

        player = _find_entity_by_name(kernel, "Player")
        slime = _find_entity_by_name(kernel, "DungeonSlime")
        assert player is not None and slime is not None

        # Slime starts at (260, 300), aggro_radius = 120
        # Player at (100, 200) -> dist = hypot(160, 100) ? 188.68 > 120
        player.Transform.x = 100.0
        player.Transform.y = 200.0
        kernel.tick(0.1)
        assert slime.AI["state"] == "patrol"

        # Move player close to slime: (250, 290) -> dist = hypot(10, 10) ? 14.14 < 120
        player.Transform.x = 250.0
        player.Transform.y = 290.0
        kernel.tick(0.1)
        assert slime.AI["state"] == "chase"


class TestPotionButtonActionDispatch:
    """6. Verify UI button action dispatch via pure-UUID function export resolution."""

    def test_potion_button_action_dispatch(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)

        player = _find_entity_by_name(kernel, "Player")
        toolkit = _find_entity_by_name(kernel, "AlchemistToolkit")
        assert player is not None and toolkit is not None

        # Find buttons
        heal_btn = toolkit.find_child("HealPotionBtn", recursive=True)
        mana_btn = toolkit.find_child("ManaPotionBtn", recursive=True)
        speed_btn = toolkit.find_child("SpeedPotionBtn", recursive=True)

        assert heal_btn is not None
        assert mana_btn is not None
        assert speed_btn is not None

        # 1. Heal Potion (+25 HP)
        player.Health["current"] = 50.0
        err = kernel.trigger_ui_event(heal_btn.id, "on_click")
        assert not isinstance(err, Error), f"trigger_ui_event failed: {err}"
        assert math.isclose(player.Health["current"], 75.0, abs_tol=1e-3)

        # 2. Mana Potion (+30 MP)
        player.Stats["mana"] = 20.0
        err = kernel.trigger_ui_event(mana_btn.id, "on_click")
        assert not isinstance(err, Error), f"trigger_ui_event failed: {err}"
        assert math.isclose(player.Stats["mana"], 50.0, abs_tol=1e-3)

        # 3. Speed Potion (+50 spd)
        player.Stats["speed"] = 160.0
        err = kernel.trigger_ui_event(speed_btn.id, "on_click")
        assert not isinstance(err, Error), f"trigger_ui_event failed: {err}"
        assert math.isclose(player.Stats["speed"], 210.0, abs_tol=1e-3)

    def test_potion_capping_and_safety(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)

        player = _find_entity_by_name(kernel, "Player")
        toolkit = _find_entity_by_name(kernel, "AlchemistToolkit")
        assert player is not None and toolkit is not None

        heal_btn = toolkit.find_child("HealPotionBtn", recursive=True)
        mana_btn = toolkit.find_child("ManaPotionBtn", recursive=True)
        speed_btn = toolkit.find_child("SpeedPotionBtn", recursive=True)

        # Health caps at max (100.0)
        player.Health["current"] = 95.0
        player.Health["max"] = 100.0
        kernel.trigger_ui_event(heal_btn.id, "on_click")
        assert math.isclose(player.Health["current"], 100.0, abs_tol=1e-3)

        # Mana caps at max_mana (100.0)
        player.Stats["mana"] = 90.0
        player.Stats["max_mana"] = 100.0
        kernel.trigger_ui_event(mana_btn.id, "on_click")
        assert math.isclose(player.Stats["mana"], 100.0, abs_tol=1e-3)

        # Speed tonic resets to 150.0 if speed reaches or exceeds 300.0
        player.Stats["speed"] = 320.0
        kernel.trigger_ui_event(speed_btn.id, "on_click")
        assert math.isclose(player.Stats["speed"], 150.0, abs_tol=1e-3)


class TestOverheadUIBillboardSynchronization:
    """7. Verify overhead UI billboard sliders synchronize with health percentages each frame."""

    def test_overhead_ui_slider_synchronization(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)

        player = _find_entity_by_name(kernel, "Player")
        goblin = _find_entity_by_name(kernel, "Goblin")
        slime = _find_entity_by_name(kernel, "DungeonSlime")

        assert player is not None and goblin is not None and slime is not None

        # 1. Player Health Bar synchronization
        player.Health["current"] = 25.0
        player.Health["max"] = 100.0
        kernel.tick(0.0167)

        hp_bar = player.find_child("PlayerHealthBar")
        assert hp_bar is not None
        assert math.isclose(float(hp_bar.UISlider["value"]), 0.25, abs_tol=1e-3)

        # 2. Goblin Health Bar synchronization (10 / 50 = 0.2)
        goblin.Health["current"] = 10.0
        goblin.Health["max"] = 50.0
        kernel.tick(0.0167)

        goblin_hp = goblin.find_child("GoblinHP")
        assert goblin_hp is not None
        assert math.isclose(float(goblin_hp.UISlider["value"]), 0.2, abs_tol=1e-3)

        # 3. Slime Health Bar synchronization (7 / 35 = 0.2)
        slime.Health["current"] = 7.0
        slime.Health["max"] = 35.0
        kernel.tick(0.0167)

        slime_hp = slime.find_child("SlimeHP")
        assert slime_hp is not None
        assert math.isclose(float(slime_hp.UISlider["value"]), 0.2, abs_tol=1e-3)


class TestHeadlessSimulationRunner:
    """8. Verify headless simulation runner execution."""

    def test_run_headless_simulation_integration(self, tmp_path: Path, capsys):
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)

        # Run 5 ticks of headless simulation
        run_headless_simulation(kernel, ticks=5)

        captured = capsys.readouterr().out
        assert "LittleBigEngine - Headless Simulation Mode" in captured
        assert "Simulation completed successfully." in captured
        assert "dt=0.0167s" in captured
        assert "Player pos:" in captured


class TestShowcasePersistenceAndStaleSafety:
    """9. Verify mutation persistence across restarts and stale handle resilience."""

    def test_persistence_roundtrip_and_reload(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)

        player = _find_entity_by_name(kernel, "Player")
        assert player is not None

        # Mutate player state
        player.Health["current"] = 42.0
        player.Stats["mana"] = 88.0
        player.Transform.x = 222.0
        player.Transform.y = 333.0

        # Persist to disk
        kernel.save_dirty_resources()
        kernel.save_project()

        # Create fresh Kernel pointing to same directory
        k2 = Kernel(tmp_path)
        k2.load_project()
        # Calling populate_demo_world_if_empty on non-empty world must NOT overwrite or duplicate
        populate_demo_world_if_empty(k2)

        reloaded_player = _find_entity_by_name(k2, "Player")
        assert reloaded_player is not None
        assert math.isclose(reloaded_player.Health["current"], 42.0, abs_tol=1e-4)
        assert math.isclose(reloaded_player.Stats["mana"], 88.0, abs_tol=1e-4)
        assert math.isclose(reloaded_player.Transform.x, 222.0, abs_tol=1e-4)
        assert math.isclose(reloaded_player.Transform.y, 333.0, abs_tol=1e-4)

        # Property evaluation works on reloaded entity
        assert math.isclose(reloaded_player.HealthPercent, 42.0, abs_tol=1e-4)
        assert math.isclose(reloaded_player.ManaPercent, 88.0, abs_tol=1e-4)

    def test_stale_handle_safety_after_deletion(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)

        toolkit = _find_entity_by_name(kernel, "AlchemistToolkit")
        assert toolkit is not None
        heal_btn = toolkit.find_child("HealPotionBtn", recursive=True)
        assert heal_btn is not None

        stale_id = heal_btn.id
        kernel.delete_entity(stale_id)

        # Triggering UI event on deleted entity handle returns Error without crash
        err = kernel.trigger_ui_event(stale_id, "on_click")
        assert isinstance(err, Error)
        assert err.code == RuntimeIDNotFoundOnMemoryError

        # Accessing proxy methods on destroyed entity raises AttributeError
        with pytest.raises(AttributeError, match="destroyed and is no longer valid"):
            _ = heal_btn.name

class TestViewportInputIntegration:
    """10. Verify ViewportPanel key down/release input event processing."""

    def test_viewport_key_down_release_scalar_app_data(self, tmp_path: Path):
        """When app_data is a scalar key integer, the key is registered and discarded from input_state."""
        import dearpygui.dearpygui as dpg
        from editor.session import EditorSession
        from editor.viewport_panel import ViewportPanel

        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)
        vp = ViewportPanel(session)

        key_w = getattr(dpg, "mvKey_W", 568)
        vp._on_key_down(0, key_w)
        assert "W" in kernel.input_state["keys"]

        vp._on_key_release(0, key_w)
        assert "W" not in kernel.input_state["keys"]

    def test_viewport_key_down_list_app_data_handling(self, tmp_path: Path):
        """DPG mvKeyDownHandler passes app_data as [key, duration]. Unwrapping ensures list app_data works seamlessly."""
        import dearpygui.dearpygui as dpg
        from editor.session import EditorSession
        from editor.viewport_panel import ViewportPanel

        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)
        vp = ViewportPanel(session)

        key_w = getattr(dpg, "mvKey_W", 568)
        # Dear PyGui passes [key_code, duration] to mvKeyDownHandler callbacks
        vp._on_key_down(0, [key_w, 0.016])
        assert "W" in kernel.input_state["keys"]


class TestPlannedShowcaseFeatures:
    """10. Clearly separated planned tests for future / unimplemented engine features."""

    @pytest.mark.skip(reason="Planned test: Preprocessor or editor automatic call-site refactoring when an export UUID is renamed")
    def test_planned_export_uuid_rename_automatic_refactoring(self):
        """When an exported function UUID is renamed, UI components and properties referencing the old UUID should be safely refactored."""
        pass

    @pytest.mark.skip(reason="Planned test: Continuous collision detection between orbital weapons and enemies")
    def test_planned_orbital_continuous_collision_detection(self):
        """Swept-volume continuous collision detection between Excalibur / OrbOfPower and Goblin hitboxes."""
        pass

    @pytest.mark.skip(reason="Planned test: Transactional inventory and savegame state rollback on script failure")
    def test_planned_transactional_inventory_rollback_on_script_failure(self):
        """If an alchemical recipe or potion script raises an unhandled exception, previous ECS component state rolls back cleanly."""
        pass
