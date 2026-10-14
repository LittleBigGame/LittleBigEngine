import dearpygui.dearpygui as dpg

dpg.create_context()
dpg.create_viewport(width=400, height=300)
dpg.setup_dearpygui()

with dpg.window(label="Test Pipes", width=380, height=280):
    dl = dpg.add_drawlist(width=360, height=260)
    
    # Compare:
    # Column 1: L-bend curved, T-junction straight
    # Column 2: Both curved
    
    color = (120, 130, 150, 255)
    R = 4.0
    
    # Row 1: T-junction (not last) - option A: straight trunk + straight horizontal
    # Row 2: L-bend (last) - curved
    y1 = 30.0
    y2 = 70.0
    x_p = 40.0
    x_c = 70.0
    
    # Option A:
    dpg.draw_text((30, 10), "Option A: T-straight, L-curved", size=14)
    # T-junction:
    dpg.draw_line((x_p, 20.0), (x_p, 60.0), color=color, thickness=1.0, parent=dl)
    dpg.draw_line((x_p, y1), (x_c, y1), color=color, thickness=1.0, parent=dl)
    # L-bend:
    dpg.draw_line((x_p, 60.0), (x_p, y2 - R), color=color, thickness=1.0, parent=dl)
    dpg.draw_bezier_quadratic((x_p, y2 - R), (x_p, y2), (x_p + R, y2), color=color, thickness=1.0, parent=dl)
    dpg.draw_line((x_p + R, y2), (x_c, y2), color=color, thickness=1.0, parent=dl)

    # Option B:
    x_p2 = 220.0
    x_c2 = 250.0
    dpg.draw_text((200, 10), "Option B: Both with curve", size=14)
    # T-junction with curve:
    dpg.draw_line((x_p2, 20.0), (x_p2, 60.0), color=color, thickness=1.0, parent=dl)
    dpg.draw_bezier_quadratic((x_p2, y1 - R), (x_p2, y1), (x_p2 + R, y1), color=color, thickness=1.0, parent=dl)
    dpg.draw_line((x_p2 + R, y1), (x_c2, y1), color=color, thickness=1.0, parent=dl)
    # L-bend:
    dpg.draw_line((x_p2, 60.0), (x_p2, y2 - R), color=color, thickness=1.0, parent=dl)
    dpg.draw_bezier_quadratic((x_p2, y2 - R), (x_p2, y2), (x_p2 + R, y2), color=color, thickness=1.0, parent=dl)
    dpg.draw_line((x_p2 + R, y2), (x_c2, y2), color=color, thickness=1.0, parent=dl)

dpg.show_viewport()
dpg.render_dearpygui_frame()
dpg.destroy_context()
