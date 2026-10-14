import dearpygui.dearpygui as dpg

dpg.create_context()
dpg.create_viewport()
dpg.setup_dearpygui()
dpg.show_viewport()

w = dpg.add_window()
dl = dpg.add_drawlist(parent=w, width=100, height=100)

reg = dpg.add_item_handler_registry()
def cb(s, a, u):
    print("cb called: s=", s, "a=", a, "u=", u)
    print("s type:", dpg.get_item_type(s))
    print("u type:", dpg.get_item_type(u))
    print("u rect_min:", dpg.get_item_rect_min(u))

dpg.add_item_clicked_handler(callback=cb, user_data=dl, parent=reg)
dpg.bind_item_handler_registry(dl, reg)

dpg.render_dearpygui_frame()

print("dl state:", dpg.get_item_state(dl))
print("dl rect_min:", dpg.get_item_rect_min(dl))

dpg.destroy_context()
