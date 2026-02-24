"""
Test
A Class Widgets plugin.
"""

from ClassWidgets.SDK import CW2Plugin, PluginAPI


class Plugin(CW2Plugin):
    def __init__(self, api: PluginAPI):
        super().__init__(api)
        # 请在此导入第三方库 / Import third-party libraries here

    def on_load(self):
        super().on_load()
        print(f"Test loaded")

    def on_unload(self):
        print(f"Test unloaded")
