"""Draw one entity only when its explicit geometry and colour are present."""
from lbe.space import world_position
components = ("x", "y", "w", "h", "color")

def run(entity):
    x,y = world_position(entity)
    graphics.rect(x,y,entity.w,entity.h,color=entity.color,key=entity.id,
                  layer=entity.items.get_value('layer', 1))
