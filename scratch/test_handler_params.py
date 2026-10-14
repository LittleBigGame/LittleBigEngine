import dearpygui.dearpygui as dpg

dpg.create_context()
dpg.create_viewport()
dpg.setup_dearpygui()

def on_click(sender, app_data, user_data):
    print("sender:", sender)
    print("app_data:", app_data)
    print("user_data:", user_data)
    print("has sender rect_min?", end=" ")
    try:
        print(dpg.get_item_rect_min(sender))
    except Exception as e:
        print("ERROR:", type(e), e)
    
    print("user_data[3] (item_tag) rect_min:", dpg.get_item_rect_min(user_data[3]))

with dpg.window() as w:
    dl = dpg.add_drawlist(width=200, height=30)
    with dpg.item_handler_registry() as hr:
        dpg.add_item_clicked_handler(button=0, callback=on_click, user_data=("entity_1", False, 10.0, dl))
    dpg.bind_item_handler_registry(dl, hr)

dpg.show_viewport()
dpg.render_dearpygui_frame()

# Simulate callback
# In DPG callback:
on_click(hr, [0, dl], ("entity_1", False, 10.0, dl))

dpg.destroy_context()
