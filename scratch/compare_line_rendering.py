import dearpygui.dearpygui as dpg

dpg.create_context()
dpg.create_viewport(title="Compare Line Rendering", width=600, height=400)
dpg.setup_dearpygui()

with dpg.window(label="Line Rendering Test", width=580, height=380):
    dl = dpg.add_drawlist(width=560, height=360)
    
    col = (80, 85, 100, 255)
    
    # Test 1: draw_line straight + draw_line straight (clean 1px)
    dpg.draw_text((20, 10), "1. draw_line (pure 1px, no curve)", size=12)
    dpg.draw_line((50, 30), (50, 70), color=col, thickness=1.0, parent=dl)
    dpg.draw_line((50, 70), (90, 70), color=col, thickness=1.0, parent=dl)

    # Test 2: draw_polyline (what subagent wrote)
    dpg.draw_text((180, 10), "2. draw_polyline (full line)", size=12)
    pts = [(210, 30)]
    cx, cy, r = 210 + 4, 70 - 4, 4
    import math
    for i in range(9):
        th = math.pi + (i / 8) * (math.pi / 2.0)
        pts.append((cx + r * math.cos(th), cy - r * math.sin(th)))
    pts.append((250, 70))
    dpg.draw_polyline(pts, color=col, thickness=1.0, parent=dl)

    # Test 3: draw_line for straight segments + only curve with draw_bezier_cubic (R=2.5)
    dpg.draw_text((340, 10), "3. draw_line straight + cubic arc (R=2.5)", size=12)
    R = 2.5
    k = 0.552 * R
    dpg.draw_line((370, 30), (370, 70 - R), color=col, thickness=1.0, parent=dl)
    dpg.draw_bezier_cubic((370, 70 - R), (370, 70 - R + k), (370 + R - k, 70), (370 + R, 70), color=col, thickness=1.0, parent=dl)
    dpg.draw_line((370 + R, 70), (410, 70), color=col, thickness=1.0, parent=dl)

    # Test 4: draw_line straight + sharp bevel 45-degree chamfer (1px)
    dpg.draw_text((20, 120), "4. draw_line with 1px chamfer", size=12)
    dpg.draw_line((50, 140), (50, 180 - 2), color=col, thickness=1.0, parent=dl)
    dpg.draw_line((50, 180 - 2), (50 + 2, 180), color=col, thickness=1.0, parent=dl)
    dpg.draw_line((50 + 2, 180), (90, 180), color=col, thickness=1.0, parent=dl)

    # Test 5: What color is (80, 85, 100) vs (55, 60, 72) vs (60, 60, 60)?
    dpg.draw_text((180, 120), "Colors: (80,85,100) vs (55,60,72) vs (60,60,60)", size=12)
    dpg.draw_line((200, 150), (250, 150), color=(80, 85, 100, 255), thickness=1.0, parent=dl)
    dpg.draw_text((260, 145), "(80, 85, 100) Theme TreeLines", size=11)
    
    dpg.draw_line((200, 170), (250, 170), color=(55, 60, 72, 255), thickness=1.0, parent=dl)
    dpg.draw_text((260, 165), "(55, 60, 72) Current PIPE_LINE_COLOR", size=11)

    dpg.draw_line((200, 190), (250, 190), color=(60, 60, 60, 255), thickness=1.0, parent=dl)
    dpg.draw_text((260, 185), "(60, 60, 60) Dark Gray", size=11)

dpg.show_viewport()
for _ in range(5):
    dpg.render_dearpygui_frame()

out = "f:/ModEngine/scratch/compare_line_rendering.png"
dpg.output_frame_buffer(file=out)
for _ in range(5):
    dpg.render_dearpygui_frame()

dpg.destroy_context()
print("Saved to", out)
