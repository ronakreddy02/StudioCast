
from pynput import keyboard
from PySide6.QtCore import QObject, Signal


class HotkeyController(QObject):

    start_requested = Signal()
    stop_requested = Signal()
    pause_requested = Signal()
    resume_requested = Signal()

    def __init__(self):
        super().__init__()

        self.hotkeys = [
            keyboard.HotKey(
                keyboard.HotKey.parse("<ctrl>+<alt>+r"),
                self.start_requested.emit,
            ),
            keyboard.HotKey(
                keyboard.HotKey.parse("<ctrl>+<alt>+s"),
                self.stop_requested.emit,
            ),
            keyboard.HotKey(
                keyboard.HotKey.parse("<ctrl>+<alt>+p"),
                self.pause_requested.emit,
            ),
            keyboard.HotKey(
                keyboard.HotKey.parse("<ctrl>+<alt>+u"),
                self.resume_requested.emit,
            ),
        ]

        self.listener = keyboard.Listener(
            on_press=self.on_key_press,
            on_release=self.on_key_release,
        )

        self.listener.start()

    def on_key_press(self, key):
        key = self.listener.canonical(key)

        for hotkey in self.hotkeys:
            hotkey.press(key)

    def on_key_release(self, key):
        key = self.listener.canonical(key)

        for hotkey in self.hotkeys:
            hotkey.release(key)

    def stop(self):
        if self.listener.is_alive():
            self.listener.stop()
