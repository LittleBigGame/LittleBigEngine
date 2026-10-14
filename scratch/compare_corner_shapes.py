import dearpygui.dearpygui as dpg

dpg.create_context()
dpg.create_viewport(title="Test Curves", width=500, height=400)
dpg.setup_dearpygui()

with dpg.window(label="Compare Corners", width=480, height=380):
    dl = dpg.add_drawlist(width=460, height=360)
    
    color = (80, 90, 110, 255)
    
    # Column 1: Current code (curves on both T-junction and L-corner)
    dpg.draw_text((20, 10), "Current (Weird Stretched T-junctions)", size=13)
    # T-junction:
    dpg.draw_line((40, 30), (40, 70), color=color, thickness=1.0, parent=dl)
    dpg.draw_bezier_quadratic((40, 50 - 3.5), (40, 50), (40 + 3.5, 50), color=color, thickness=1.0, parent=dl)
    dpg.draw_line((40 + 3.5, 50), (70, 50), color=color, thickness=1.0, parent=dl)
    # L-corner (quadratic):
    dpg.draw_line((40, 70), (40, 90 - 3.5), color=color, thickness=1.0, parent=dl)
    dpg.draw_bezier_quadratic((40, 90 - 3.5), (40, 90), (40 + 3.5, 90), color=color, thickness=1.0, parent=dl)
    dpg.draw_line((40 + 3.5, 90), (70, 90), color=color, thickness=1.0, parent=dl)

    # Column 2: Clean T-junction + Proper Cubic Arc L-corner (R=3.0)
    dpg.draw_text((240, 10), "Clean: Straight T-junction + Round L", size=13)
    # T-junction: straight vertical + straight horizontal
    dpg.draw_line((260, 30), (260, 70), color=color, thickness=1.0, parent=dl)
    dpg.draw_line((260, 50), (290, 50), color=color, thickness=1.0, parent=dl)
    
    # L-corner: cubic bezier arc with R=3.0 (k = 0.552 * R = 1.65)
    R = 3.0
    k = 0.552 * R
    dpg.draw_line((260, 70), (260, 90 - R), color=color, thickness=1.0, parent=dl)
    dpg.draw_bezier_cubic(
        (260, 90 - R),
        (260, 90 - R + k),
        (260 + R - k, 90),
        (260 + R, 90),
        color=color,
        thickness=1.0,
        parent=dl
    )
    dpg.draw_line((260 + R, 90), (290, 90), color=color, thickness=1.0, parent=dl)

dpg.show_viewport()
for _ in range(5):
    dpg.render_dearpygui_frame()

out_file = "f:/ModEngine/scratch/test_corner_shapes.png"
dpg.output_frame_buffer(file=out_file)
for _ in range(5):
    dpg.render_dearpygui_frame()
dpg.destroy_context()
print("Saved", out_file)
