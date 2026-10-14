import dearpygui.dearpygui as dpg

dpg.create_context()
dpg.create_viewport(title="1px Beveled Test", width=500, height=400)
dpg.setup_dearpygui()

with dpg.window(label="1px Beveled", width=480, height=380):
    dl = dpg.add_drawlist(width=460, height=360)
    
    # Try different colors and methods:
    colors = [
        ("Original Theme (80, 85, 100)", (80, 85, 100, 255)),
        ("Darker Theme (70, 75, 90)", (70, 75, 90, 255)),
        ("Neutral Gray (75, 75, 75)", (75, 75, 75, 255)),
        ("Current (55, 60, 72)", (55, 60, 72, 255)),
    ]
    
    # In each row, test:
    # 1. draw_line + draw_bezier_cubic (R=3.0, k=1.656)
    # 2. draw_line + 45-deg chamfer (R=2.0)
    # 3. draw_line + 2-segment circular bevel
    
    y = 30.0
    for name, c in colors:
        dpg.draw_text((20, y - 18), name, size=12)
        
        # Method A: draw_line + draw_bezier_cubic R=3.0
        x0 = 40.0
        R = 3.0
        k = 0.552 * R
        dpg.draw_line((x0, y), (x0, y + 20 - R), color=c, thickness=1.0, parent=dl)
        dpg.draw_bezier_cubic((x0, y + 20 - R), (x0, y + 20 - R + k), (x0 + R - k, y + 20), (x0 + R, y + 20), color=c, thickness=1.0, parent=dl)
        dpg.draw_line((x0 + R, y + 20), (x0 + 20, y + 20), color=c, thickness=1.0, parent=dl)

        # Method B: draw_line + 45-deg bevel chamfer (R=3.0)
        x1 = 180.0
        dpg.draw_line((x1, y), (x1, y + 20 - 3), color=c, thickness=1.0, parent=dl)
        dpg.draw_line((x1, y + 20 - 3), (x1 + 3, y + 20), color=c, thickness=1.0, parent=dl)
        dpg.draw_line((x1 + 3, y + 20), (x1 + 20, y + 20), color=c, thickness=1.0, parent=dl)

        # Method C: draw_line for each arc segment (exact 1px lines, no polyline blur!)
        x2 = 320.0
        R2 = 3.5
        import math
        arc_pts = []
        for i in range(5):
            th = math.pi + (i / 4) * (math.pi / 2.0)
            arc_pts.append((x2 + R2 + R2 * math.cos(th), (y + 20 - R2) - R2 * math.sin(th)))
        dpg.draw_line((x2, y), arc_pts[0], color=c, thickness=1.0, parent=dl)
        for i in range(len(arc_pts) - 1):
            dpg.draw_line(arc_pts[i], arc_pts[i+1], color=c, thickness=1.0, parent=dl)
        dpg.draw_line(arc_pts[-1], (x2 + 20, y + 20), color=c, thickness=1.0, parent=dl)

        y += 65.0

dpg.show_viewport()
for _ in range(5):
    dpg.render_dearpygui_frame()

out = "f:/ModEngine/scratch/test_1px_beveled.png"
dpg.output_frame_buffer(file=out)
for _ in range(5):
    dpg.render_dearpygui_frame()

dpg.destroy_context()
print("Saved", out)
