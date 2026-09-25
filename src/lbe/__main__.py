"""LittleBigEngine application entry point."""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="LittleBigEngine")
    parser.add_argument("--check", action="store_true", help="Check the core installation without opening a window")
    parser.add_argument("--headless", action="store_true", help="Use an offscreen graphics context")
    parser.add_argument("--frames", type=int, help="Close after this many rendered frames")
    parser.add_argument("--screenshot", help="Save the final frame as a PNG")
    args = parser.parse_args()
    if args.check:
        from . import Runtime
        runtime = Runtime()
        entity = runtime.create(name="LittleBigEngine")
        print(f"{entity.name} (LBE) - core ready")
        runtime.close()
        return
    if args.frames is not None and args.frames < 1:
        parser.error("--frames must be positive")
    try:
        import pyglet  # noqa: F401
    except ImportError:
        parser.error('Desktop support requires: python -m pip install -e ".[desktop]"')
    from .desktop import launch
    from .scene import build_demo
    launch(build_demo, headless=args.headless, frames=args.frames, screenshot=args.screenshot)


if __name__ == "__main__":
    main()
