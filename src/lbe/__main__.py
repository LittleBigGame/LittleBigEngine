"""LittleBigEngine application entry point."""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="LittleBigEngine")
    parser.add_argument("--check", action="store_true", help="Check the core installation without opening a window")
    parser.add_argument("--headless", action="store_true", help="Use an offscreen graphics context")
    parser.add_argument("--frames", type=int, help="Close after this many rendered frames")
    parser.add_argument("--screenshot", help="Save the final frame as a PNG")
    parser.add_argument("--project", help="Directory containing app.py and application scripts")
    parser.add_argument("--upgrade-template", action="store_true", help="Upgrade unchanged managed template files and preserve custom edits")
    parser.add_argument("--demo", action="store_true", help="Show only the two-entity rendering demo")
    parser.add_argument("--template", default="editor", help="Template used to initialize a new project (editor, demo, counter)")
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
    if args.upgrade_template:
        from .project import template_path
        from .project_templates import upgrade_template
        if not args.project:
            parser.error("--upgrade-template requires --project")
        try:
            result = upgrade_template(args.project, template_path(args.template))
        except ValueError as error:
            parser.error(str(error))
        for name, status in result.items():
            print(f"{name}: {status}")
        return
    try:
        import pyglet  # noqa: F401
    except ImportError:
        parser.error('Desktop support requires: python -m pip install -e ".[desktop]"')
    from .desktop import launch
    from .project import load_project, template_path

    if args.project:
        name = "demo" if args.demo else args.template
        template = template_path(name)
        build = lambda w, g, i: load_project(w, g, i, args.project, template=template)
    elif args.demo:
        template = template_path("demo")
        build = lambda w, g, i: load_project(w, g, i, "workspace-demo", template=template)
    else:
        build = None

    launch(build, headless=args.headless, frames=args.frames, screenshot=args.screenshot)


if __name__ == "__main__":
    main()
