import dearpygui.dearpygui as dpg

print('version', dpg.get_dearpygui_version())

dpg.create_context()
with dpg.texture_registry(tag='test_registry'):
    pass
print('exists before', dpg.does_item_exist('test_tex'))
tex = dpg.add_dynamic_texture(width=2, height=2, default_value=[1.0]*16, tag='test_tex', parent='test_registry')
print('created', tex, dpg.does_item_exist('test_tex'))
dpg.delete_item('test_tex')
print('deleted', dpg.does_item_exist('test_tex'))
tex2 = dpg.add_dynamic_texture(width=2, height=2, default_value=[1.0]*16, tag='test_tex', parent='test_registry')
print('recreated', tex2, dpg.does_item_exist('test_tex'))
dpg.delete_item('test_registry', children_only=True)
dpg.delete_item('test_registry')
dpg.destroy_context()
