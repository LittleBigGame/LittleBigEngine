"""LittleBigEngine - Main Entry Point

Launches the LittleBigEngine Desktop Editor with live Entity Hierarchy,
Interactive Scene View, Component Inspector, and Storage Resources panels.
Includes graceful headless simulation fallback if GUI libraries are absent.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


DEFAULT_APPLICATION_ID = "2e4b8702e1e9514338d026d79d39f704"
DEFAULT_WORLD_PATH = Path(__file__).resolve().parent / "Example World"


def populate_demo_world_if_empty(kernel) -> None:
    """Populate the world with 'The Dungeon of Alchemia' showcase scene hierarchy."""
    if any(kernel.is_entity(rid) for rid in kernel.resources):
        # Existing entities found, do not overwrite/inject demo world
        for rid in kernel.resources:
            if kernel.is_entity(rid):
                proxy = kernel.get_entity_proxy(rid)
                if not isinstance(proxy, Exception) and proxy.has("Transform"):
                    proxy.transform.setdefault("x", 0.0)
                    proxy.transform.setdefault("y", 0.0)
                    proxy.transform.setdefault("z", 0.0)
                    proxy.transform.setdefault("rot_z", 0.0)
        return

    # 1. Create Application Root
    app_root = kernel.create_entity(name="Application")

    # 2. Create Game branch under Application
    game_branch = kernel.create_entity(name="Game", parent_id=app_root)

    UUID_HEALTH_GET = "a1000000000000000000000000000001"
    UUID_HEALTH_SET = "a1000000000000000000000000000002"
    UUID_MANA_GET = "a1000000000000000000000000000003"
    UUID_MANA_SET = "a1000000000000000000000000000004"
    UUID_SPEED_GET = "a1000000000000000000000000000005"
    UUID_SPEED_SET = "a1000000000000000000000000000006"
    UUID_DIST_GET = "a1000000000000000000000000000007"
    UUID_HEAL_ACT = "a1000000000000000000000000000008"
    UUID_MANA_ACT = "a1000000000000000000000000000009"
    UUID_SPEED_ACT = "a100000000000000000000000000000a"

    # 3. Create Scripts with @export functions
    alchemical_logic_code = f"""import math

def _find_player(entity):
    world = getattr(entity, "world", None)
    if world is not None and hasattr(world, "query"):
        for p in world.query("Health", "Stats"):
            if "player" in (getattr(p, "name", "") or "").lower():
                return p
        for p in world.query("Health"):
            if "player" in (getattr(p, "name", "") or "").lower():
                return p
    return None

@export("{UUID_HEALTH_GET}")
def health_percent_get(entity):
    max_hp = float(entity.Health.max)
    if max_hp <= 0.0:
        return 0.0
    return (float(entity.Health.current) / max_hp) * 100.0

@export("{UUID_HEALTH_SET}")
def health_percent_set(entity, val):
    entity.Health.current = float(entity.Health.max) * (float(val) / 100.0)

@export("{UUID_MANA_GET}")
def mana_percent_get(entity):
    max_m = float(entity.Stats.max_mana)
    if max_m <= 0.0:
        return 0.0
    return (float(entity.Stats.mana) / max_m) * 100.0

@export("{UUID_MANA_SET}")
def mana_percent_set(entity, val):
    entity.Stats.mana = float(entity.Stats.max_mana) * (float(val) / 100.0)

@export("{UUID_SPEED_GET}")
def speed_meters_get(entity):
    return float(entity.Stats.speed) / 100.0

@export("{UUID_SPEED_SET}")
def speed_meters_set(entity, val):
    entity.Stats.speed = float(val) * 100.0

@export("{UUID_DIST_GET}")
def distance_to_player_get(entity):
    player = _find_player(entity)
    if player is not None:
        return math.hypot(float(entity.Transform.x) - float(player.Transform.x), float(entity.Transform.y) - float(player.Transform.y))
    return 0.0

@export("{UUID_HEAL_ACT}")
def heal_potion_action(entity):
    player = _find_player(entity)
    if player is not None:
        player.Health.current = min(float(player.Health.max), float(player.Health.current) + 25.0)

@export("{UUID_MANA_ACT}")
def mana_potion_action(entity):
    player = _find_player(entity)
    if player is not None and player.has("Stats"):
        player.Stats.mana = min(float(player.Stats.max_mana), float(player.Stats.mana) + 30.0)

@export("{UUID_SPEED_ACT}")
def speed_potion_action(entity):
    player = _find_player(entity)
    if player is not None and player.has("Stats"):
        cur = float(player.Stats.speed)
        player.Stats.speed = cur + 50.0 if cur < 300.0 else 150.0
"""
    alchemical_logic = kernel.create_script_resource(
        name="AlchemicalLogic",
        requires=[],
        code=alchemical_logic_code,
    )
    kernel.attach_script(game_branch, alchemical_logic)

    hero_controller_code = """import math

_anim_t = 0.0

def update(self, dt):
    global _anim_t
    keys = getattr(kernel, "input_state", {}).get("keys", set())
    if keys:
        dx, dy = 0.0, 0.0
        if "W" in keys or "UP" in keys:
            dy -= 1.0
        if "S" in keys or "DOWN" in keys:
            dy += 1.0
        if "A" in keys or "LEFT" in keys:
            dx -= 1.0
        if "D" in keys or "RIGHT" in keys:
            dx += 1.0
        if dx != 0.0 or dy != 0.0:
            length = math.hypot(dx, dy)
            spd = float(self.Stats.speed)
            self.Transform.x += (dx / length) * spd * dt
            self.Transform.y += (dy / length) * spd * dt
    else:
        # Autonomous smooth hover/wander for simulation / idle
        _anim_t += dt
        self.Transform.x += math.sin(_anim_t * 1.5) * 20.0 * dt
        self.Transform.y += math.cos(_anim_t * 1.5) * 20.0 * dt

    # Clamp to bounds [40, 600], [40, 400]
    self.Transform.x = max(40.0, min(600.0, float(self.Transform.x)))
    self.Transform.y = max(40.0, min(400.0, float(self.Transform.y)))

    # Update child health billboard
    hp_bar = self.find_child("PlayerHealthBar")
    if hp_bar and hp_bar.has("UISlider"):
        hp_bar.UISlider["value"] = max(0.0, min(1.0, float(self.HealthPercent) / 100.0))
"""
    hero_controller = kernel.create_script_resource(
        name="HeroController",
        requires=["Transform", "Health", "Stats"],
        code=hero_controller_code,
    )

    orbital_physics_code = """import math

def update(self, dt):
    for weapon in self.children:
        w_comp = weapon.get("Weapon") or weapon.get("Shield")
        if w_comp:
            rad = float(w_comp.get("orbit_radius", 30.0))
            spd = float(w_comp.get("orbit_speed", 90.0))
            cur_angle = (float(w_comp.get("angle", 0.0)) + spd * dt) % 360.0
            w_comp["angle"] = cur_angle
            weapon.Transform.x = rad * math.cos(math.radians(cur_angle))
            weapon.Transform.y = rad * math.sin(math.radians(cur_angle))
            weapon.Transform.rot_z = cur_angle
"""
    orbital_physics = kernel.create_script_resource(
        name="OrbitalPhysics",
        requires=["Transform"],
        code=orbital_physics_code,
    )

    enemy_ai_code = """import math

def update(self, dt):
    dist = float(self.DistanceToPlayer)
    aggro = float(self.AI.get("aggro_radius", 150.0))
    if dist < aggro:
        self.AI["state"] = "chase"
        player = next((p for p in self.world.query("Health", "Stats") if "player" in (p.name or "").lower()), None)
        if player:
            dx = float(player.Transform.x) - float(self.Transform.x)
            dy = float(player.Transform.y) - float(self.Transform.y)
            l = max(0.001, math.hypot(dx, dy))
            spd = float(self.AI.get("speed", 50.0))
            self.Transform.x += (dx / l) * spd * dt
            self.Transform.y += (dy / l) * spd * dt
    else:
        self.AI["state"] = "patrol"
        ang = (float(self.AI.get("angle", 0.0)) + 45.0 * dt) % 360.0
        self.AI["angle"] = ang
        cx = float(self.AI.get("patrol_center_x", 380.0))
        cy = float(self.AI.get("patrol_center_y", 180.0))
        r = float(self.AI.get("radius", 45.0))
        self.Transform.x = cx + r * math.cos(math.radians(ang))
        self.Transform.y = cy + r * math.sin(math.radians(ang))

    # Update child overhead HP
    for c in self.children:
        if c.has("UISlider"):
            c.UISlider["value"] = max(0.0, min(1.0, float(self.HealthPercent) / 100.0))
"""
    enemy_ai = kernel.create_script_resource(
        name="EnemyAI",
        requires=["Transform", "Health", "AI"],
        code=enemy_ai_code,
    )

    # 4. Create Player Entity
    player = kernel.create_entity(
        name="Player",
        parent_id=game_branch,
        components={
            "Transform": {"x": 100.0, "y": 200.0, "z": 0.0, "rot_z": 0.0},
            "Health": {"current": 85.0, "max": 100.0},
            "Stats": {"speed": 160.0, "defense": 15, "mana": 60.0, "max_mana": 100.0},
            "Property:HealthPercent": {
                "getter": UUID_HEALTH_GET,
                "setter": UUID_HEALTH_SET,
                "presentation": "slider",
                "presentation_args": {"min": 0.0, "max": 100.0},
            },
            "Property:ManaPercent": {
                "getter": UUID_MANA_GET,
                "setter": UUID_MANA_SET,
                "presentation": "slider",
                "presentation_args": {"min": 0.0, "max": 100.0},
            },
            "Property:SpeedMeters": {
                "getter": UUID_SPEED_GET,
                "setter": UUID_SPEED_SET,
                "presentation": "text",
            },
        },
    )
    kernel.attach_script(player, hero_controller)
    kernel.attach_script(player, orbital_physics)

    kernel.create_entity(
        name="PlayerNameTag",
        parent_id=player,
        components={
            "Transform": {"x": 0.0, "y": -26.0, "z": 0.0},
            "UIText": {"content": "Alchemist Hero", "bullet": False},
        },
    )
    kernel.create_entity(
        name="HeroTag",
        parent_id=player,
        components={
            "Transform": {"x": 0.0, "y": -38.0, "z": 0.0},
            "UIText": {"content": "Hero", "bullet": False},
        },
    )
    kernel.create_entity(
        name="PlayerHealthBar",
        parent_id=player,
        components={
            "Transform": {"x": 0.0, "y": -16.0, "z": 0.0},
            "UISlider": {"label": "Hero HP", "value": 0.85, "min": 0.0, "max": 1.0},
        },
    )
    kernel.create_entity(
        name="Excalibur",
        parent_id=player,
        components={
            "Weapon": {"damage": 45, "range": 1.5, "element": "Light", "orbit_radius": 32.0, "orbit_speed": 120.0, "angle": 0.0},
            "Transform": {"x": 32.0, "y": 0.0, "z": 0.0, "rot_z": 0.0},
        },
    )
    orb = kernel.create_entity(
        name="OrbOfPower",
        parent_id=player,
        components={
            "Weapon": {"damage": 25, "element": "Arcane", "orbit_radius": 36.0, "orbit_speed": -150.0, "angle": 180.0},
            "Transform": {"x": -36.0, "y": 0.0, "z": 0.0, "rot_z": 0.0},
        },
    )
    kernel.create_entity(
        name="OrbGlow",
        parent_id=orb,
        components={
            "Transform": {"x": 0.0, "y": -10.0, "z": 0.0},
            "UIText": {"content": "⚡ Arcane", "bullet": False},
        },
    )
    kernel.create_entity(
        name="ShieldSatellite",
        parent_id=player,
        components={
            "Shield": {"defense_boost": 12, "orbit_radius": 26.0, "orbit_speed": 80.0, "angle": 90.0},
            "Transform": {"x": 0.0, "y": 26.0, "z": 0.0, "rot_z": 0.0},
        },
    )

    # 5. Create Goblin Entity
    goblin = kernel.create_entity(
        name="Goblin",
        parent_id=game_branch,
        components={
            "Transform": {"x": 400.0, "y": 200.0, "z": 0.0},
            "Health": {"current": 50.0, "max": 50.0},
            "AI": {"aggro_radius": 150.0, "patrol_center_x": 380.0, "patrol_center_y": 180.0, "radius": 45.0, "angle": 0.0, "state": "patrol", "speed": 55.0},
            "Property:DistanceToPlayer": {
                "getter": UUID_DIST_GET,
                "presentation": "text",
            },
            "Property:HealthPercent": {
                "getter": UUID_HEALTH_GET,
                "setter": UUID_HEALTH_SET,
                "presentation": "slider",
                "presentation_args": {"min": 0.0, "max": 100.0},
            },
        },
    )
    kernel.attach_script(goblin, enemy_ai)
    kernel.create_entity(
        name="GoblinHP",
        parent_id=goblin,
        components={
            "Transform": {"x": 0.0, "y": -22.0, "z": 0.0},
            "UISlider": {"label": "Goblin HP", "value": 1.0, "min": 0.0, "max": 1.0},
        },
    )
    kernel.create_entity(
        name="HPTag",
        parent_id=goblin,
        components={
            "Transform": {"x": 0.0, "y": -34.0, "z": 0.0},
            "UIText": {"content": "HP", "bullet": False},
        },
    )

    # 6. Create DungeonSlime Entity
    slime = kernel.create_entity(
        name="DungeonSlime",
        parent_id=game_branch,
        components={
            "Transform": {"x": 260.0, "y": 300.0, "z": 0.0},
            "Health": {"current": 35.0, "max": 35.0},
            "AI": {"aggro_radius": 120.0, "patrol_center_x": 260.0, "patrol_center_y": 300.0, "radius": 35.0, "angle": 90.0, "state": "patrol", "speed": 40.0},
            "Property:DistanceToPlayer": {
                "getter": UUID_DIST_GET,
                "presentation": "text",
            },
            "Property:HealthPercent": {
                "getter": UUID_HEALTH_GET,
                "setter": UUID_HEALTH_SET,
                "presentation": "slider",
                "presentation_args": {"min": 0.0, "max": 100.0},
            },
        },
    )
    kernel.attach_script(slime, enemy_ai)
    kernel.create_entity(
        name="SlimeNameTag",
        parent_id=slime,
        components={
            "Transform": {"x": 0.0, "y": -20.0, "z": 0.0},
            "UIText": {"content": "Acid Slime", "bullet": False},
        },
    )
    kernel.create_entity(
        name="SlimeHP",
        parent_id=slime,
        components={
            "Transform": {"x": 0.0, "y": -12.0, "z": 0.0},
            "UISlider": {"label": "Slime HP", "value": 1.0, "min": 0.0, "max": 1.0},
        },
    )

    # 7. Create AlchemistToolkit panel under Game
    toolkit = kernel.create_entity(
        name="AlchemistToolkit",
        parent_id=game_branch,
        components={
            "Panel": {"title": "Alchemist Toolkit", "panel_type": "custom", "minimized": False},
            "UIContainer": {"layout": "vertical", "gap": 6.0, "padding": 8.0},
        },
    )
    kernel.create_ui_entity(
        name="ToolkitHeader",
        component_type="UIText",
        component_props={"content": "🧪 Alchemical Lab Controls", "bullet": False},
        parent_id=toolkit,
    )
    potion_bar = kernel.create_ui_entity(
        name="PotionBar",
        component_type="UIContainer",
        component_props={"layout": "horizontal", "gap": 4.0},
        parent_id=toolkit,
    )
    kernel.create_ui_entity(
        name="HealPotionBtn",
        component_type="UIButton",
        component_props={"label": "Drink Elixir (+25 HP)", "width": 145.0, "on_click": UUID_HEAL_ACT},
        parent_id=potion_bar,
    )
    kernel.create_ui_entity(
        name="ManaPotionBtn",
        component_type="UIButton",
        component_props={"label": "Drink Mana (+30 MP)", "width": 140.0, "on_click": UUID_MANA_ACT},
        parent_id=potion_bar,
    )
    kernel.create_ui_entity(
        name="SpeedPotionBtn",
        component_type="UIButton",
        component_props={"label": "Swiftness Tonic", "width": 120.0, "on_click": UUID_SPEED_ACT},
        parent_id=potion_bar,
    )
    kernel.create_ui_entity(
        name="StatusDisplay",
        component_type="UIText",
        component_props={"content": "Hero Status: Healthy", "bullet": False},
        parent_id=toolkit,
    )

    # 8. Retain GameGUI and Button under Game for test compatibility
    gui_container = kernel.create_ui_entity(
        name="GameGUI",
        component_type="UIContainer",
        component_props={"layout": "vertical", "gap": 6.0, "padding": 8.0},
        parent_id=game_branch,
    )
    kernel.create_ui_entity(
        name="Button",
        component_type="UIButton",
        component_props={"label": "Action", "width": 120.0},
        parent_id=gui_container,
    )

    # 9. Retain Editor branch under Application for test compatibility
    editor_branch = kernel.create_entity(name="Editor", parent_id=app_root)
    hierarchy_panel = kernel.create_entity(
        name="Hierarchy Panel",
        parent_id=editor_branch,
        components={
            "Panel": {"title": "Hierarchy", "panel_type": "hierarchy", "minimized": False},
        },
    )
    kernel.create_ui_entity(
        name="SearchInput",
        component_type="UITextInput",
        component_props={"hint": "Search hierarchy...", "is_search": True, "label": ""},
        parent_id=hierarchy_panel,
    )
    filter_bar = kernel.create_ui_entity(
        name="FilterBar",
        component_type="UIContainer",
        component_props={"layout": "horizontal", "gap": 4.0},
        parent_id=hierarchy_panel,
    )
    kernel.create_ui_entity(
        name="AllFilter",
        component_type="UIButton",
        component_props={"label": "All", "width": 45.0},
        parent_id=filter_bar,
    )
    kernel.create_ui_entity(
        name="GameFilter",
        component_type="UIButton",
        component_props={"label": "Game World", "width": 75.0},
        parent_id=filter_bar,
    )
    kernel.create_ui_entity(
        name="ToolsFilter",
        component_type="UIButton",
        component_props={"label": "UI & Tools", "width": 75.0},
        parent_id=filter_bar,
    )
    kernel.create_ui_entity(
        name="TreeContainer",
        component_type="UIContainer",
        component_props={"layout": "vertical"},
        parent_id=hierarchy_panel,
    )

    inspector_panel = kernel.create_entity(
        name="Inspector Panel",
        parent_id=editor_branch,
        components={
            "Panel": {"title": "Inspector", "panel_type": "inspector", "minimized": False, "locked": False},
        },
    )
    header_bar = kernel.create_ui_entity(
        name="HeaderBar",
        component_type="UIContainer",
        component_props={"layout": "horizontal", "gap": 4.0},
        parent_id=inspector_panel,
    )
    kernel.create_ui_entity(
        name="TitleText",
        component_type="UIText",
        component_props={"content": "Inspector"},
        parent_id=header_bar,
    )
    kernel.create_ui_entity(
        name="FocusBtn",
        component_type="UIButton",
        component_props={"label": "Focus", "width": 50.0},
        parent_id=header_bar,
    )
    kernel.create_ui_entity(
        name="LockBtn",
        component_type="UIButton",
        component_props={"label": "Lock", "width": 50.0},
        parent_id=header_bar,
    )
    kernel.create_ui_entity(
        name="ComponentContainer",
        component_type="UIContainer",
        component_props={"layout": "vertical"},
        parent_id=inspector_panel,
    )

    # Flush all newly spawned entities to disk
    kernel.save_dirty_resources()


def run_headless_simulation(kernel, ticks: int = 10, dt: float = 1.0 / 60.0) -> None:
    """Run a headless simulation loop printing entity states and script updates."""
    print("=" * 65)
    print(" LittleBigEngine - Headless Simulation Mode")
    print(f" World Path: {kernel.folder_location}")
    print(f" Loaded Entities: {sum(1 for rid in kernel.resources if kernel.is_entity(rid))}")
    print("=" * 65)

    for tick_num in range(1, ticks + 1):
        errs = kernel.tick(dt)
        if errs:
            print(f"[Tick {tick_num:02d}] Errors encountered: {errs}")
        else:
            player_proxy = None
            for rid in kernel.resources:
                if kernel.is_entity(rid):
                    p = kernel.get_entity_proxy(rid)
                    if not isinstance(p, Exception) and "player" in kernel.get_resource(rid).get("name", "").lower():
                        player_proxy = p
                        break

            player_info = ""
            weapon_info = ""
            if player_proxy:
                try:
                    hp_pct = player_proxy.HealthPercent
                    player_info = f" | Player pos: ({player_proxy.Transform.x:.1f}, {player_proxy.Transform.y:.1f}) HP: {hp_pct:.1f}%"
                except Exception:
                    player_info = f" | Player pos: ({player_proxy.Transform.x:.1f}, {player_proxy.Transform.y:.1f})"

                weapons = player_proxy.query_children("Weapon")
                if weapons:
                    w = weapons[0]
                    weapon_info = f" | Child '{w.storage_id.hex()[:8]}' rot_z: {w.transform.get('rot_z', 0.0):.1f} deg"

            print(f"[Tick {tick_num:02d}] dt={dt:.4f}s{player_info}{weapon_info}")

    # Persist any modified state
    dirty_count = len(kernel.dirty_runtime_ids)
    if dirty_count > 0:
        kernel.save_dirty_resources()
        print(f"Flushed {dirty_count} dirty resources to disk.")
    print("Simulation completed successfully.")


def print_missing_gui_banner() -> None:
    """Print clear diagnostic and resolution instructions when GUI dependencies are absent."""
    exe = sys.executable
    print("\n" + "=" * 70)
    print(" [LittleBigEngine] Desktop Editor Dependency Notice")
    print("=" * 70)
    print(f" Current Python: {exe}")
    print(" Module 'dearpygui' is not installed in this environment.")
    print("\n To install Dear PyGui and Raylib for the Desktop Editor, run:")
    print("     python -m pip install dearpygui raylib")
    print("\n Or run directly with the project virtual environment:")
    print("     .\\.venv\\Scripts\\python.exe main.py")
    print("  or:")
    print("     .\\.venv1\\Scripts\\python.exe main.py")
    print("\n Alternatively, run in headless simulation mode without GUI:")
    print("     python main.py --headless")
    print("=" * 70 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="LittleBigEngine Main Entry Point")
    parser.add_argument(
        "--world",
        type=str,
        default=str(DEFAULT_WORLD_PATH),
        help="Path to the world project folder (default: Example World beside main.py)",
    )
    parser.add_argument(
        "--application-id",
        default=DEFAULT_APPLICATION_ID,
        help="Persistent ID of the Application root to open",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run in headless simulation mode without launching the GUI editor",
    )
    parser.add_argument(
        "--ticks",
        type=int,
        default=10,
        help="Number of simulation ticks to run in headless mode (default: 10)",
    )
    args = parser.parse_args()

    world_path = Path(args.world)
    if not world_path.is_dir():
        print(f"[Error] Project folder '{world_path}' does not exist.")
        return

    from LBE import Kernel, Error
    kernel = Kernel(world_path)
    load_res = kernel.load_project(root_storage_id=args.application_id)
    if isinstance(load_res, Error):
        print(f"\n[Error] Failed to load project '{world_path}': {load_res.message} - {load_res.description}\n")
        return

    print(f"Loaded Application {args.application_id} with {len(kernel.resources)} resources.")
    if load_res["broken_references"]:
        print(f"[Warning] Application has {load_res['broken_references']} broken references; see kernel diagnostics.")

    if args.headless:
        run_headless_simulation(kernel, ticks=args.ticks)
        return

    # Attempt to launch the interactive Dear PyGui Desktop Editor
    try:
        from editor import EditorApp
    except (ImportError, ModuleNotFoundError) as ex:
        print_missing_gui_banner()
        print(f"Falling back to headless simulation test due to missing GUI module: {ex}\n")
        run_headless_simulation(kernel, ticks=args.ticks)
        return

    print(f"Launching LittleBigEngine Editor for '{world_path.resolve()}'...")
    app = EditorApp(kernel=kernel, title="LittleBigEngine Editor")
    app.run()


if __name__ == "__main__":
    main()
