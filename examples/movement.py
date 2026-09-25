"""Behavior introduced entirely through components and an attached script."""

from lbe import Runtime, SystemDefinition


def main():
    runtime = Runtime()
    game = runtime.create(tags=["root"], name="Game")
    moving = runtime.create(parent=game, name="Moving", x=0.0, y=0.0)
    still = runtime.create(parent=game, name="Still", x=4.0, y=2.0)
    moving.vx = 2.0
    moving.vy = 1.0
    game.systems.attach("movement", SystemDefinition('''
def update(dt):
    for child in query("x", "y", "vx", "vy"):
        child.x += child.vx * dt
        child.y += child.vy * dt
'''))
    runtime.step(0.5)
    print(f"{moving.name}: ({moving.x}, {moving.y})")
    print(f"{still.name}: ({still.x}, {still.y})")
    runtime.close()


if __name__ == "__main__":
    main()
