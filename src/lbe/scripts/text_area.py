"""Reusable multiline text area entity system."""


def update(dt):
    """Maintain scroll clamping and reveal caret for text area."""
    buffer = entity.components.get("buffer")
    if buffer is None or not entity.components.get("visible", True):
        return
    pitch = entity.components.get("pitch", 8)
    line = entity.components.get("line_height", 20)
    rows = max(1, int((entity.h - 12) // line))
    cols = max(1, int((entity.w - 64) // pitch))
    lines = buffer.text.split("\n")
    buffer.scroll = max(0, min(buffer.scroll, max(0, len(lines) - rows)))
    max_col = max((len(l) for l in lines), default=0)
    buffer.horizontal = max(0, min(buffer.horizontal, max(0, max_col - cols)))
