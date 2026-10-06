"""One independent UUID-attached drawing script per ball."""
components = ('x', 'y', 'w', 'h', 'sprite', 'tint', 'rotation')


def run(entity):
    graphics.sprite(asset(entity.sprite), entity.x, entity.y, entity.w, entity.h,
                    color=entity.tint, rotation=entity.rotation, key=entity.id, layer=1)
