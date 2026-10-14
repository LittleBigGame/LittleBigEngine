"""LittleBigEngine - Main Entry Point

Launches the LittleBigEngine Desktop Editor with live Entity Hierarchy,
Interactive Scene View, Component Inspector, and Storage Resources panels.
Includes graceful headless simulation fallback if GUI libraries are absent.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def populate_demo_world_if_empty(kernel) -> None:
    """Populate the world with a bootstrapped root hierarchy:
    Application (Root)
      ├── Game (contains Player, Excalibur, Goblin, GameGUI)
      └── Editor (contains Hierarchy Panel, Inspector Panel)
    """
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

    # 3. Create Player with Transform and Health under Game
    player = kernel.create_entity(
        name="Player",
        parent_id=game_branch,
        components={
            "Transform": {"x": 100.0, "y": 200.0, "z": 0.0, "rot_z": 0.0},
            "Health": {"current": 100, "max": 100},
            "Stats": {"speed": 250.0, "defense": 15},
        },
    )
    kernel.create_entity(
        name="PlayerNameTag",
        parent_id=player,
        components={
            "Transform": {"x": 0.0, "y": -26.0, "z": 0.0},
            "UIText": {"content": "Hero", "bullet": False},
        },
    )

    # 4. Add equipped Weapon as child of Player
    kernel.spawn(
        template={
            "name": "Excalibur",
            "components": {
                "Weapon": {"damage": 45, "range": 1.5, "element": "Light"},
                "Transform": {"x": 20.0, "y": 0.0, "z": 0.0, "rot_z": 0.0},
            },
        },
        parent_id=player,
    )

    # 5. Create Goblin under Game
    goblin = kernel.create_entity(
        name="Goblin",
        parent_id=game_branch,
        components={
            "Transform": {"x": 400.0, "y": 200.0, "z": 0.0},
            "Health": {"current": 50, "max": 50},
            "AI": {"aggro_radius": 150.0, "state": "idle"},
        },
    )
    kernel.create_entity(
        name="GoblinHP",
        parent_id=goblin,
        components={
            "Transform": {"x": 0.0, "y": -22.0, "z": 0.0},
            "UISlider": {"label": "HP", "value": 0.8, "min": 0.0, "max": 1.0},
        },
    )

    # 6. Create GameGUI and Button under Game
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

    # 7. Create Editor branch under Application
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

    # 8. Create and attach gameplay script to Player
    player_uid = kernel.get_storage_id(player).hex()
    combat_script = kernel.create_script_resource(
        name="PlayerCombat",
        requires=["Transform", "Health"],
        code=f"""# Player Combat Script
hero = <|0|{player_uid}|>

def update(self, dt):
    for weapon in self.query_children("Weapon"):
        weapon.transform.rot_z += 45.0 * dt
""",
    )
    kernel.attach_script(player, combat_script)

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

            weapon_info = ""
            if player_proxy:
                weapons = player_proxy.query_children("Weapon")
                if weapons:
                    w = weapons[0]
                    weapon_info = f" | Child '{w.storage_id.hex()[:8]}' rot_z: {w.transform.get('rot_z', 0.0):.1f}°"

            print(f"[Tick {tick_num:02d}] dt={dt:.4f}s{weapon_info}")

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
        default="./Example World",
        help="Path to the world project folder (default: './Example World')",
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
    world_path.mkdir(parents=True, exist_ok=True)

    from LBE import Kernel
    kernel = Kernel(world_path)
    populate_demo_world_if_empty(kernel)

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