# Project textures

Install `.[desktop]` for graphics and PNG/JPEG/BMP/GIF decoding. Animated images
currently use their first frame. The core still needs no graphics dependencies.

Drop an image file onto the editor window to copy it into `textures/` without
changing the original. Existing files are never overwritten. Alternatively copy
images into your project and use **Refresh project files**. Imports participate in
project-file undo/redo and recover after an interrupted save.

Drag the Project Files image into your script to insert a texture pill:

```python
ball_texture = asset("YOUR-ASSET-UUID")

def draw():
    graphics.sprite(ball_texture, 2, 3, 1.5, 1.5, key="ball")
```

The pill displays the texture name, but Python stores the UUID. Right-click it
to locate, replace, remove or copy its UUID. Rename/move the file through Project
Files to retain that UUID. Keep `project.json` with the project when copying it.

`asset(uuid)` returns a lazy `TextureAsset`, an `AssetRef` with a derived `path`.
It follows registry renames even when a script keeps the handle in a global.
Store an `AssetRef`/`TextureAsset` in components; save/load preserves its UUID,
not an absolute filesystem path or GPU object. Resolve saved references with
`asset(entity.sprite)` before drawing.

`graphics.sprite(texture, x, y, w=None, h=None, *, color=(255,255,255,255),
rotation=0, key=None, layer=1)` accepts a resolved texture or image path.
Coordinates use the same bottom-left world/top-left UI conventions as `rect()`.
Dimensions default to native pixels; specify dimensions inside a world view.
Rotation is clockwise in degrees around the center; RGB/RGBA color is a tint.
World sprites respect the camera and are clipped to their viewport.

GPU images are shared, checked once per frame, and refreshed when files change.
Stable `key` values reuse sprites. Unused sprites/textures and project-switch
resources are released. Missing or corrupt images report `texture.error` in the
editor and fall back to the existing colored entity drawing when available;
correcting the file restores textured drawing.

Drag an image onto an entity or its Inspector to assign its `sprite` component.
The editor renderer draws this texture instead of the default rectangle, using
optional `tint`, `rotation` and `layer` components. Custom scripts can call
`graphics.sprite()` explicitly instead.

Existing editor projects need `python -m lbe --project PATH --upgrade-template`.
Customized template files are preserved; merge updated `app.py` and `render.py`
into those files yourself when reported as customized.
