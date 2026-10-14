"""Visual theme definition and color tokens for LittleBigEngine Dear PyGui Editor."""

from __future__ import annotations

import dearpygui.dearpygui as dpg

# Central Color Tokens (The High-Tech Card Aesthetic)
ACCENT_BLUE = (0, 120, 255, 255)
ACCENT_BLUE_HOVER = (64, 176, 255, 255)
CARD_BG = (22, 22, 22, 255)
CARD_BG_HOVER = (36, 36, 36, 255)
CARD_BORDER = (80, 80, 80, 255)
CARD_BORDER_HOVER = (255, 255, 255, 255)
DISABLED_TEXT = (90, 90, 90, 255)
DISABLED_BG = (15, 15, 15, 255)

def _is_theme_valid(tag: str) -> bool:
    try:
        return dpg.does_item_exist(tag) and dpg.get_item_type(tag) == "mvAppItemType::mvTheme"
    except Exception:
        return False


def get_card_theme(selected: bool = False, disabled: bool = False) -> str:
    """Return a cached Dear PyGui theme for card rows based on selection/disabled state."""
    if disabled:
        tag = "lbe_theme_card_disabled"
        if _is_theme_valid(tag):
            return tag
        if dpg.does_item_exist(tag):
            dpg.delete_item(tag)
        with dpg.theme(tag=tag):
            for comp_type in (dpg.mvButton, dpg.mvTreeNode, dpg.mvSelectable):
                with dpg.theme_component(comp_type):
                    dpg.add_theme_color(dpg.mvThemeCol_Button, DISABLED_BG)
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, DISABLED_BG)
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, DISABLED_BG)
                    dpg.add_theme_color(dpg.mvThemeCol_Header, DISABLED_BG)
                    dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, DISABLED_BG)
                    dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, DISABLED_BG)
                    dpg.add_theme_color(dpg.mvThemeCol_Border, (50, 50, 50, 255))
                    dpg.add_theme_color(dpg.mvThemeCol_BorderShadow, (0, 0, 0, 0))
                    dpg.add_theme_color(dpg.mvThemeCol_Text, DISABLED_TEXT)
                    if comp_type == dpg.mvTreeNode:
                        dpg.add_theme_color(dpg.mvThemeCol_TreeLines, (50, 50, 50, 255))
                        dpg.add_theme_style(dpg.mvStyleVar_TreeLinesSize, 1.0)
                        dpg.add_theme_style(dpg.mvStyleVar_TreeLinesRounding, 0.0)
                        dpg.add_theme_style(dpg.mvStyleVar_IndentSpacing, 20.0)
                    dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1)
                    dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 3)
                    dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 6, 4)
        return tag

    if selected:
        tag = "lbe_theme_card_selected"
        if _is_theme_valid(tag):
            return tag
        if dpg.does_item_exist(tag):
            dpg.delete_item(tag)
        with dpg.theme(tag=tag):
            for comp_type in (dpg.mvButton, dpg.mvTreeNode, dpg.mvSelectable):
                with dpg.theme_component(comp_type):
                    dpg.add_theme_color(dpg.mvThemeCol_Button, (18, 48, 88, 255))
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (24, 60, 108, 255))
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (32, 72, 128, 255))
                    dpg.add_theme_color(dpg.mvThemeCol_Header, (18, 48, 88, 255))
                    dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, (24, 60, 108, 255))
                    dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, (32, 72, 128, 255))
                    dpg.add_theme_color(dpg.mvThemeCol_Border, ACCENT_BLUE)
                    dpg.add_theme_color(dpg.mvThemeCol_BorderShadow, (0, 0, 0, 0))
                    dpg.add_theme_color(dpg.mvThemeCol_Text, (0, 190, 255, 255))
                    if comp_type == dpg.mvTreeNode:
                        dpg.add_theme_color(dpg.mvThemeCol_TreeLines, (80, 85, 100, 255))
                        dpg.add_theme_style(dpg.mvStyleVar_TreeLinesSize, 1.0)
                        dpg.add_theme_style(dpg.mvStyleVar_TreeLinesRounding, 0.0)
                        dpg.add_theme_style(dpg.mvStyleVar_IndentSpacing, 20.0)
                    dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 2)
                    dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 3)
                    dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 6, 4)
        return tag

    # Unselected default
    tag = "lbe_theme_card_unselected"
    if _is_theme_valid(tag):
        return tag
    if dpg.does_item_exist(tag):
        dpg.delete_item(tag)
    with dpg.theme(tag=tag):
        for comp_type in (dpg.mvButton, dpg.mvTreeNode, dpg.mvSelectable):
            with dpg.theme_component(comp_type):
                dpg.add_theme_color(dpg.mvThemeCol_Button, CARD_BG)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, CARD_BG_HOVER)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (45, 45, 45, 255))
                dpg.add_theme_color(dpg.mvThemeCol_Header, CARD_BG)
                dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, CARD_BG_HOVER)
                dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, (45, 45, 45, 255))
                dpg.add_theme_color(dpg.mvThemeCol_Border, CARD_BORDER)
                dpg.add_theme_color(dpg.mvThemeCol_BorderShadow, (0, 0, 0, 0))
                dpg.add_theme_color(dpg.mvThemeCol_Text, (220, 220, 225, 255))
                if comp_type == dpg.mvTreeNode:
                    dpg.add_theme_color(dpg.mvThemeCol_TreeLines, (80, 85, 100, 255))
                    dpg.add_theme_style(dpg.mvStyleVar_TreeLinesSize, 1.0)
                    dpg.add_theme_style(dpg.mvStyleVar_TreeLinesRounding, 0.0)
                    dpg.add_theme_style(dpg.mvStyleVar_IndentSpacing, 20.0)
                dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 3)
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 6, 4)
    return tag


def get_flyout_theme() -> str:
    """Return theme for pop-out corner window chrome buttons."""
    tag = "lbe_theme_flyout"
    if _is_theme_valid(tag):
        return tag
    if dpg.does_item_exist(tag):
        dpg.delete_item(tag)
    with dpg.theme(tag=tag):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (28, 28, 32, 230))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (48, 52, 62, 255))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (64, 70, 84, 255))
            dpg.add_theme_color(dpg.mvThemeCol_Border, (90, 95, 110, 255))
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 4)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 5, 2)
    return tag


def get_tree_content_theme() -> str:
    """Return theme for hierarchy tree content child window with zero item spacing."""
    tag = "lbe_theme_tree_content"
    if _is_theme_valid(tag):
        return tag
    if dpg.does_item_exist(tag):
        dpg.delete_item(tag)
    with dpg.theme(tag=tag):
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 0)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 0, 0)
    return tag


def create_editor_theme() -> int | str:
    """Build and return a sleek dark palette theme with refined borders and accents."""
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvAll):
            # Window & frame rounding
            dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 8)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 6)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 5)
            dpg.add_theme_style(dpg.mvStyleVar_PopupRounding, 6)
            dpg.add_theme_style(dpg.mvStyleVar_ScrollbarRounding, 6)
            dpg.add_theme_style(dpg.mvStyleVar_GrabRounding, 4)
            dpg.add_theme_style(dpg.mvStyleVar_TabRounding, 6)

            # Borders
            dpg.add_theme_style(dpg.mvStyleVar_WindowBorderSize, 1)
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1)
            dpg.add_theme_style(dpg.mvStyleVar_PopupBorderSize, 1)

            # Padding & Spacing
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 10, 10)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 8, 5)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 8, 6)
            dpg.add_theme_style(dpg.mvStyleVar_ItemInnerSpacing, 6, 4)
            dpg.add_theme_style(dpg.mvStyleVar_IndentSpacing, 20.0)

            # Palette - Backgrounds
            dpg.add_theme_color(dpg.mvThemeCol_WindowBg, (20, 21, 24, 255))
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (24, 25, 28, 255))
            dpg.add_theme_color(dpg.mvThemeCol_PopupBg, (28, 30, 36, 255))
            dpg.add_theme_color(dpg.mvThemeCol_Border, (55, 58, 68, 255))
            dpg.add_theme_color(dpg.mvThemeCol_BorderShadow, (0, 0, 0, 0))

            # Frame Backgrounds
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (32, 34, 40, 255))
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, (45, 50, 60, 255))
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, (56, 64, 80, 255))

            # Headers & Title Bar
            dpg.add_theme_color(dpg.mvThemeCol_TitleBg, (18, 19, 22, 255))
            dpg.add_theme_color(dpg.mvThemeCol_TitleBgActive, (26, 28, 36, 255))
            dpg.add_theme_color(dpg.mvThemeCol_TitleBgCollapsed, (18, 19, 22, 200))
            dpg.add_theme_color(dpg.mvThemeCol_MenuBarBg, (22, 23, 27, 255))

            # Text
            dpg.add_theme_color(dpg.mvThemeCol_Text, (225, 230, 240, 255))
            dpg.add_theme_color(dpg.mvThemeCol_TextDisabled, DISABLED_TEXT)

            # Buttons (Default Indigo/Slate)
            dpg.add_theme_color(dpg.mvThemeCol_Button, (44, 50, 65, 255))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (60, 72, 98, 255))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (75, 92, 128, 255))

            # Headers
            dpg.add_theme_color(dpg.mvThemeCol_Header, (40, 46, 60, 255))
            dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, (55, 65, 88, 255))
            dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, (70, 84, 115, 255))

            # Tabs
            dpg.add_theme_color(dpg.mvThemeCol_Tab, (28, 32, 40, 255))
            dpg.add_theme_color(dpg.mvThemeCol_TabHovered, (55, 68, 92, 255))
            dpg.add_theme_color(dpg.mvThemeCol_TabActive, (42, 52, 74, 255))
            dpg.add_theme_color(dpg.mvThemeCol_TabUnfocused, (22, 24, 30, 255))
            dpg.add_theme_color(dpg.mvThemeCol_TabUnfocusedActive, (32, 38, 50, 255))

            # Scrollbar & Grabbers
            dpg.add_theme_color(dpg.mvThemeCol_ScrollbarBg, (18, 19, 22, 200))
            dpg.add_theme_color(dpg.mvThemeCol_ScrollbarGrab, (45, 50, 62, 255))
            dpg.add_theme_color(dpg.mvThemeCol_ScrollbarGrabHovered, (65, 72, 88, 255))
            dpg.add_theme_color(dpg.mvThemeCol_ScrollbarGrabActive, (85, 95, 118, 255))
            dpg.add_theme_color(dpg.mvThemeCol_CheckMark, ACCENT_BLUE)
            dpg.add_theme_color(dpg.mvThemeCol_SliderGrab, (80, 105, 160, 255))
            dpg.add_theme_color(dpg.mvThemeCol_SliderGrabActive, ACCENT_BLUE)

            # Separators
            dpg.add_theme_color(dpg.mvThemeCol_Separator, (45, 48, 58, 255))
            dpg.add_theme_color(dpg.mvThemeCol_SeparatorHovered, (65, 75, 95, 255))
            dpg.add_theme_color(dpg.mvThemeCol_SeparatorActive, (85, 100, 130, 255))

            # Tree connector lines ("pipes")
            dpg.add_theme_color(dpg.mvThemeCol_TreeLines, (80, 85, 100, 255))
            dpg.add_theme_style(dpg.mvStyleVar_TreeLinesSize, 1.0)
            dpg.add_theme_style(dpg.mvStyleVar_TreeLinesRounding, 0.0)

            # Tables
            dpg.add_theme_color(dpg.mvThemeCol_TableHeaderBg, (28, 32, 40, 255))
            dpg.add_theme_color(dpg.mvThemeCol_TableBorderStrong, (45, 48, 58, 255))
            dpg.add_theme_color(dpg.mvThemeCol_TableBorderLight, (35, 38, 46, 255))
            dpg.add_theme_color(dpg.mvThemeCol_TableRowBg, (22, 23, 27, 255))
            dpg.add_theme_color(dpg.mvThemeCol_TableRowBgAlt, (28, 30, 36, 255))

            # Docking preview
            dpg.add_theme_color(dpg.mvThemeCol_DockingPreview, (0, 120, 255, 180))
            dpg.add_theme_color(dpg.mvThemeCol_DockingEmptyBg, (16, 17, 20, 255))

    return theme
