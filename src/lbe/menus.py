"""Context actions and popup menus built from ordinary UI entities."""

from .ui import ACCENT, FIELD, INK, MUTED, contains, put, stack


def close_menu(ui):
    menu = ui.root.relations.pop("context_menu", None)
    if menu is not None:
        ui.runtime.destroy(menu)


def open_menu(ui, target, x, y, actions=None):
    """Query context_actions(target) providers, or show explicit action dictionaries.

    Actions have label, run(target), and optional enabled fields. None separates
    groups. Providers live on the UI root or target; targets may be any object.
    """
    close_menu(ui)
    if actions is None:
        actions = []
        owners = (ui.root,) if target is ui.root else (ui.root, target)
        for owner in owners:
            provider = getattr(owner, "components", {}).get("context_actions")
            if provider:
                actions.extend(provider(target))
    actions = [dict(a, enabled=a.get('enabled', True) and callable(a.get('run'))) if a is not None else None
               for a in actions]
    if not actions:
        return None
    width = min(ui.window.width, max(160, max(len(a["label"]) * ui.pitch + 24 for a in actions if a) if any(actions) else 160))
    height = min(ui.window.height, 8 + sum(8 if a is None else 28 for a in actions))
    layer = max((e.components.get("layer", 2) for e in ui.controls()), default=2) + 10
    menu = ui.create(ui.root, "ContextMenu", "panel", w=width, h=height,
                     x=max(0, min(x, ui.window.width-width)),
                     y=max(0, min(y, ui.window.height-height)), layer=layer,
                     context_target=target, active=-1, padding=4, gap=0,
                     ignore_layout=True, modal=True, offset=0)
    ui.root.relations["context_menu"] = menu
    for action in actions:
        if action is None:
            ui.create(menu, "Separator", "rect", h=8, w=width-8, layer=layer+1)
        else:
            ink = action.get("ink", INK if action.get("enabled", True) else MUTED)
            color = action.get("color", FIELD)
            ui.create(menu, action["label"], "button", text=action["label"], h=28,
                      w=width-8, layer=layer+1, menu_action=dict(action),
                      ink=ink, color=color)
    _layout(menu)
    return menu


def _layout(menu):
    stack(menu, gap=0, padding=4)
    for child in menu.children:
        put(child, y=child.y-menu.offset,
            visible=child.y-menu.offset >= menu.y+4 and child.y-menu.offset+child.h <= menu.y+menu.h-4)


def _activate(ui, menu, item):
    action = item.menu_action
    if not action.get("enabled", True):
        return
    target = menu.context_target
    close_menu(ui)
    if hasattr(target, "alive") and not target.alive:
        return
    action["run"](target)


def dispatch_menu(ui, event):
    """Capture popup input before application callbacks and normal controls."""
    menu = ui.root.relations.get("context_menu")
    kind = event[0]
    if menu is not None:
        if hasattr(menu.context_target, "alive") and not menu.context_target.alive:
            close_menu(ui)
            return True
        items = [c for c in menu.children if "menu_action" in c.components]
        if kind == "motion":
            menu.active = next((i for i, item in enumerate(items)
                                if item.visible and contains(item, event[1], event[2])
                                and item.menu_action.get("enabled", True)), -1)
            for i, item in enumerate(items):
                put(item, color=ACCENT if i == menu.active else FIELD)
        elif kind == "key":
            key = event[1]
            if key == "ESCAPE":
                close_menu(ui)
            elif key in ("UP", "DOWN"):
                enabled = [i for i, c in enumerate(items) if c.menu_action.get("enabled", True)]
                if enabled:
                    pos = enabled.index(menu.active) if menu.active in enabled else (-1 if key == "DOWN" else 0)
                    menu.active = enabled[(pos + (1 if key == "DOWN" else -1)) % len(enabled)]
                    item = items[menu.active]
                    menu.offset = max(0, menu.offset + min(0, item.y-menu.y-4) + max(0, item.y+item.h-menu.y-menu.h+4))
                    _layout(menu)
                    for i, child in enumerate(items):
                        put(child, color=ACCENT if i == menu.active else FIELD)
            elif key in ("ENTER", "RETURN", "NUM_ENTER") and 0 <= menu.active < len(items):
                _activate(ui, menu, items[menu.active])
        elif kind == "click":
            if not contains(menu, event[1], event[2]):
                close_menu(ui)
            elif event[3] == 1:
                for item in items:
                    if item.visible and contains(item, event[1], event[2]):
                        _activate(ui, menu, item)
                        break
        elif kind == "scroll":
            maximum = max(0, sum(c.h for c in menu.children)+8-menu.h)
            menu.offset = max(0, min(maximum, menu.offset-event[4]*28))
            _layout(menu)
        return True
    if kind != "click" or event[3] != 4:
        return False
    controls = [c for c in ui.controls() if ui.visible(c) and contains(c, event[1], event[2])]
    controls.reverse()
    controls.sort(key=lambda c: (c.layer, c.depth), reverse=True)
    target = controls[0] if controls else ui.root
    resolver = ui.root.components.get("context_target")
    if resolver:
        target = resolver(target, event)
    open_menu(ui, target, event[1], event[2])
    return True
