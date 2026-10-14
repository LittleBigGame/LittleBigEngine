"""Main desktop application entry point for the LittleBigEngine Dear PyGui Editor."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import dearpygui.dearpygui as dpg

from LBE.kernel import Kernel
from .hierarchy_panel import HierarchyPanel
from .inspector_panel import InspectorPanel
from .session import EditorSession
from .storage_panel import StoragePanel
from .theme import create_editor_theme
from .ui_bridge import UIBridgePanel
from .viewport_panel import ViewportPanel


DEFAULT_DPG_INI = """[Window][WindowOverViewport_11111111]
Pos=0,0
Size=1264,761
Collapsed=0

[Window][###22]
Pos=0,0
Size=280,539
Collapsed=0
DockId=0x00000003,0

[Window][###23]
Pos=282,0
Size=620,539
Collapsed=0
DockId=0x00000006,0

[Window][###24]
Pos=904,0
Size=360,761
Collapsed=0
DockId=0x00000004,0

[Window][###25]
Pos=0,541
Size=902,220
Collapsed=0
DockId=0x00000005,0

[Window][Debug##Default]
Pos=60,60
Size=400,400
Collapsed=0

[Docking][Data]
DockSpace       ID=0x08BD597D Window=0x1BBC0F80 Pos=0,0 Size=1264,761 Split=X
  DockNode      ID=0x00000001 Parent=0x08BD597D SizeRef=904,761 Split=Y
    DockNode    ID=0x00000002 Parent=0x00000001 SizeRef=904,541 Split=X
      DockNode  ID=0x00000003 Parent=0x00000002 SizeRef=280,541 Selected=0xB1702D4E
      DockNode  ID=0x00000006 Parent=0x00000002 SizeRef=624,541 CentralNode=1 Selected=0x896142E2
    DockNode    ID=0x00000005 Parent=0x00000001 SizeRef=904,220 Selected=0x1906230A
  DockNode      ID=0x00000004 Parent=0x08BD597D SizeRef=360,761 Selected=0x21174CA6
"""


class EditorApp:
    """The dockable desktop editor application hosting panels, docking space, and menu bars."""

    def __init__(
        self,
        kernel: Kernel | None = None,
        folder_location: Path | str | None = None,
        title: str = "LittleBigEngine Editor",
        width: int = 1280,
        height: int = 800,
        auto_build: bool = True,
    ) -> None:
        if kernel is None:
            folder = Path(folder_location or "./project_data")
            folder.mkdir(parents=True, exist_ok=True)
            self.kernel = Kernel(folder)
        else:
            self.kernel = kernel

        self.session = EditorSession(self.kernel)
        self.title = title
        self.width = width
        self.height = height

        self.theme: int | str | None = None
        self.hierarchy_panel: HierarchyPanel | None = None
        self.viewport_panel: ViewportPanel | None = None
        self.inspector_panel: InspectorPanel | None = None
        self.storage_panel: StoragePanel | None = None
        self.ui_bridge_panel: UIBridgePanel | None = None

        self._is_setup: bool = False
        self._viewport_created: bool = False

        if auto_build:
            self.setup_ui()

    def setup_ui(self) -> None:
        """Initialize Dear PyGui context, styling, panels, and docking space."""
        if self._is_setup:
            return

        dpg.create_context()

        # Ensure default dock layout exists so all panels start docked immediately
        ini_file = Path("dpg.ini")
        if not ini_file.exists():
            ini_file.write_text(DEFAULT_DPG_INI, encoding="utf-8")

        dpg.configure_app(
            docking=True,
            docking_space=True,
            init_file=str(ini_file),
            load_init_file=True,
            auto_save_init_file=True,
        )

        self.theme = create_editor_theme()
        dpg.bind_theme(self.theme)

        self._build_menu_bar()

        self.hierarchy_panel = HierarchyPanel(self.session, use_vector_cards=True)
        self.hierarchy_panel.build()

        self.viewport_panel = ViewportPanel(self.session)
        self.viewport_panel.build()

        self.inspector_panel = InspectorPanel(self.session)
        self.inspector_panel.build()

        self.storage_panel = StoragePanel(self.session)
        self.storage_panel.build()

        self.extra_inspectors: list[InspectorPanel] = []
        self.session.spawn_inspector = self.spawn_inspector
        self.session.active_viewport = self.viewport_panel

        self._build_status_bar()
        self.update_status_bar()

        self.session.subscribe_state_changed(self.update_status_bar)
        if dpg.does_item_exist("window_hierarchy"):
            dpg.focus_item("window_hierarchy")
        self._is_setup = True

    def _build_menu_bar(self) -> None:
        with dpg.viewport_menu_bar(tag="app_menu_bar"):
            with dpg.menu(label="File"):
                dpg.add_menu_item(
                    label="Save Dirty",
                    callback=lambda: self.session.save_dirty_resources(),
                )
                dpg.add_menu_item(
                    label="Save All",
                    callback=lambda: self.session.save_all_resources(),
                )
                dpg.add_separator()
                dpg.add_menu_item(label="Exit", callback=self.stop)

            with dpg.menu(label="Entities"):
                dpg.add_menu_item(
                    label="Create Entity",
                    callback=lambda: self.session.create_entity(),
                )
                dpg.add_menu_item(
                    label="Delete Selected",
                    callback=self._on_menu_delete_selected,
                )
                dpg.add_menu_item(
                    label="Clear Selection",
                    callback=lambda: self.session.select_entity(None),
                )

            with dpg.menu(label="Windows"):
                dpg.add_menu_item(
                    label="Toggle Hierarchy",
                    callback=lambda: self.toggle_window("window_hierarchy"),
                )
                dpg.add_menu_item(
                    label="Toggle Scene View",
                    callback=lambda: self.toggle_window("window_viewport"),
                )
                dpg.add_menu_item(
                    label="Toggle Inspector",
                    callback=lambda: self.toggle_window("window_inspector"),
                )
                dpg.add_menu_item(
                    label="Toggle Storage",
                    callback=lambda: self.toggle_window("window_storage"),
                )

    def spawn_inspector(
        self,
        target_id: RuntimeID | None = None,
        locked: bool = True,
    ) -> InspectorPanel:
        """Spawn and dock/display an additional independent InspectorPanel instance."""
        idx = len(self.extra_inspectors) + 2
        tag = f"window_inspector_{idx}"
        insp = InspectorPanel(
            self.session,
            tag=tag,
            target_entity_id=target_id,
            is_locked=locked,
        )
        insp.build()
        self.extra_inspectors.append(insp)
        return insp

    def _build_status_bar(self) -> None:
        with dpg.window(
            tag="app_status_bar",
            no_title_bar=True,
            no_resize=True,
            no_move=True,
            no_scrollbar=True,
            no_collapse=True,
            no_docking=True,
        ):
            dpg.add_text("", tag="app_status_text", color=(180, 190, 205))

    def update_status_bar(self) -> None:
        """Update the status bar text with live engine stats."""
        if not dpg.does_item_exist("app_status_text"):
            return

        entity_count = sum(1 for rid in self.kernel.resources if self.kernel.is_entity(rid))
        dirty_count = self.session.get_dirty_count()
        folder = str(self.kernel.folder_location)

        status_text = (
            f"Loaded Entities: {entity_count}  |  "
            f"Dirty Resources: {dirty_count}  |  "
            f"Storage Folder: {folder}"
        )
        dpg.set_value("app_status_text", status_text)

    def _on_viewport_resize(self) -> None:
        w = dpg.get_viewport_client_width()
        h = dpg.get_viewport_client_height()
        if dpg.does_item_exist("app_status_bar"):
            dpg.set_item_pos("app_status_bar", [0, max(0, h - 26)])
            dpg.configure_item("app_status_bar", width=w, height=26)

    def toggle_window(self, tag: str | int) -> None:
        """Toggle visibility of a window panel."""
        if dpg.does_item_exist(tag):
            is_shown = dpg.is_item_shown(tag)
            dpg.configure_item(tag, show=not is_shown)

    def _on_menu_delete_selected(self) -> None:
        sel = self.session.selected_entity_id
        if sel is not None:
            self.session.delete_entity(sel)

    def setup_viewport(self, show: bool = True) -> None:
        """Configure viewport without blocking."""
        if not self._is_setup:
            self.setup_ui()
        if not self._viewport_created:
            dpg.create_viewport(title=self.title, width=self.width, height=self.height)
            dpg.set_viewport_resize_callback(self._on_viewport_resize)
            dpg.setup_dearpygui()
            if show:
                dpg.show_viewport()
                self._on_viewport_resize()
            self._viewport_created = True

    def start_non_blocking(self, render_frame: bool = True) -> None:
        """Initialize the editor UI and viewport and render a single frame without blocking."""
        self.setup_viewport(show=True)
        if render_frame:
            dpg.render_dearpygui_frame()

    def run(self) -> None:
        """Start the Dear PyGui event loop with real-time simulation ticking."""
        import time

        self.setup_viewport(show=True)
        last_time = time.perf_counter()

        while dpg.is_dearpygui_running():
            now = time.perf_counter()
            dt = now - last_time
            last_time = now
            dt = min(dt, 0.1)

            if self.session.is_playing:
                self.session.step_simulation(dt)

            dpg.render_dearpygui_frame()

        self.destroy()

    def stop(self) -> None:
        """Stop Dear PyGui execution."""
        if dpg.is_dearpygui_running():
            dpg.stop_dearpygui()

    def destroy(self) -> None:
        """Tear down and destroy Dear PyGui context."""
        try:
            if self._viewport_created:
                dpg.save_init_file("dpg.ini")
        except Exception:
            pass
        for insp in getattr(self, "extra_inspectors", []):
            try:
                insp.destroy()
            except Exception:
                pass
        if getattr(self, "hierarchy_panel", None) is not None:
            try:
                self.hierarchy_panel.destroy()
            except Exception:
                pass
        if getattr(self, "inspector_panel", None) is not None:
            try:
                self.inspector_panel.destroy()
            except Exception:
                pass
        if getattr(self, "viewport_panel", None) is not None:
            try:
                self.viewport_panel.destroy()
            except Exception:
                pass
        if getattr(self, "ui_bridge_panel", None) is not None:
            try:
                self.ui_bridge_panel.destroy()
            except Exception:
                pass
        self.stop()
        dpg.destroy_context()
        self._is_setup = False
        self._viewport_created = False

