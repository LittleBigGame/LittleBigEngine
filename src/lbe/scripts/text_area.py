"""Reusable multiline text area entity system."""


def update(dt):
    """Maintain scroll clamping and reveal caret for text area."""
    buffer = entity.items.get_value("buffer")
    if buffer is None or not entity.items.get_value("visible", True):
        return
    pitch = entity.items.get_value("pitch", 8)
    line = entity.items.get_value("line_height", 20)
    rows = max(1, int((entity.h - 12) // line))
    cols = max(1, int((entity.w - 64) // pitch))
    lines = buffer.lines
    buffer.scroll = max(0, min(buffer.scroll, max(0, len(lines) - rows)))
    max_col = max((len(l) for l in lines), default=0)
    buffer.horizontal = max(0, min(buffer.horizontal, max(0, max_col - cols)))
