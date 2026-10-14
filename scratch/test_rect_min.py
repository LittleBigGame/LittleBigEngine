import traceback
import sys

try:
    import dearpygui.dearpygui as dpg
    dpg.create_context()
    dpg.create_viewport()
    dpg.setup_dearpygui()
    with dpg.window() as w:
        dl = dpg.add_drawlist(width=200, height=30)
    dpg.show_viewport()
    dpg.render_dearpygui_frame()
    print("rect_min:", dpg.get_item_rect_min(dl))
    dpg.destroy_context()
except Exception as e:
    traceback.print_exc()
    sys.exit(2)
