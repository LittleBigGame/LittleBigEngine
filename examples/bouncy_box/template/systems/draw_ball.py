"""One independent UUID-attached drawing script per ball."""
import math
components = ('x', 'y', 'w', 'h', 'sprite', 'tint', 'rotation')
draw_sprite = getattr(graphics, 'sprite', None)
# Older kernels provide rect() but no texture API. Precompute horizontal chords
# for a round, pooled fallback instead of silently failing every ball's script.
bands = 16
chords = tuple(math.sqrt(1 - (2 * (band + 0.5) / bands - 1) ** 2)
               for band in range(bands))


def run(entity):
    if draw_sprite is not None:
        draw_sprite(asset(entity.sprite), entity.x, entity.y, entity.w, entity.h,
                    color=entity.tint, rotation=entity.rotation, key=entity.id, layer=1)
    else:
        for band, chord in enumerate(chords):
            graphics.rect(entity.x + entity.w * (1 - chord) / 2,
                          entity.y + entity.h * band / bands,
                          entity.w * chord, entity.h / bands, color=entity.tint[:3],
                          key=(entity.id, 'ball', band), layer=1)
