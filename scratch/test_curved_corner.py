import dearpygui.dearpygui as dpg

dpg.create_context()
dpg.create_viewport(title="Test Curved Corner", width=300, height=200)

with dpg.window(label="Test", width=280, height=180):
    dl = dpg.add_drawlist(width=260, height=140)

    # Sharp corner at x=50, y=50
    dpg.draw_line((50, 10), (50, 50), color=(100, 100, 100, 255), thickness=1.0)
    dpg.draw_line((50, 50), (90, 50), color=(100, 100, 100, 255), thickness=1.0)

    # Curved corner at x=150, y=50 with R=4.0
    R = 4.0
    xp = 150.0
    ym = 50.0
    xc = 190.0
    color = (100, 100, 100, 255)
    dpg.draw_line((xp, 10.0), (xp, ym - R), color=color, thickness=1.0)
    dpg.draw_bezier_quadratic((xp, ym - R), (xp, ym), (xp + R, ym), color=color, thickness=1.0)
    dpg.draw_line((xp + R, ym), (xc, ym), color=color, thickness=1.0)

dpg.setup_dearpygui()
dpg.show_viewport()

for _ in range(8):
    dpg.render_dearpygui_frame()

dpg.output_frame_buffer(file="f:/ModEngine/scratch/test_curved_corner.png")
for _ in range(8):
    dpg.render_dearpygui_frame()

dpg.destroy_context()
print("Saved curved corner test")
