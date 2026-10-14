import dearpygui.dearpygui as dpg

dpg.create_context()
dpg.create_viewport()
dpg.setup_dearpygui()

with dpg.window() as w:
    dl = dpg.add_drawlist(width=300, height=100)
    # Test drawing a curved corner:
    # Vertical line coming down from (20, 0) to (20, 20 - R)
    R = 4.0
    x_p = 20.0
    y_mid = 20.0
    x_c = 40.0
    dpg.draw_line((x_p, 0.0), (x_p, y_mid - R), color=(255, 255, 255, 255), thickness=1.0, parent=dl)
    dpg.draw_bezier_quadratic((x_p, y_mid - R), (x_p, y_mid), (x_p + R, y_mid), color=(255, 255, 255, 255), thickness=1.0, parent=dl)
    dpg.draw_line((x_p + R, y_mid), (x_c, y_mid), color=(255, 255, 255, 255), thickness=1.0, parent=dl)

dpg.show_viewport()
dpg.render_dearpygui_frame()
print("draw_bezier_quadratic succeeded!")
dpg.destroy_context()
