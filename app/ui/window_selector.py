
import ctypes
from ctypes import wintypes

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QMessageBox,
)


class WindowSelector(QWidget):
    window_selected = Signal(dict)

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Select Window")
        self.setMinimumSize(450, 350)

        self.windows = []

        layout = QVBoxLayout(self)

        title = QLabel("Select a window to record")
        layout.addWidget(title)

        self.window_list = QListWidget()
        layout.addWidget(self.window_list)

        self.refresh_button = QPushButton("Refresh Windows")
        self.refresh_button.clicked.connect(self.load_windows)
        layout.addWidget(self.refresh_button)

        self.select_button = QPushButton("Select Window")
        self.select_button.clicked.connect(self.select_window)
        layout.addWidget(self.select_button)

        self.load_windows()

    def load_windows(self):
        self.window_list.clear()
        self.windows.clear()

        user32 = ctypes.windll.user32

        EnumWindows = user32.EnumWindows
        GetWindowTextLengthW = user32.GetWindowTextLengthW
        GetWindowTextW = user32.GetWindowTextW
        IsWindowVisible = user32.IsWindowVisible
        IsIconic = user32.IsIconic
        GetWindowRect = user32.GetWindowRect

        EnumWindowsProc = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HWND,
            wintypes.LPARAM,
        )

        def callback(hwnd, lparam):
            if not IsWindowVisible(hwnd) or IsIconic(hwnd):
                return True

            length = GetWindowTextLengthW(hwnd)

            if length == 0:
                return True

            title_buffer = ctypes.create_unicode_buffer(length + 1)

            GetWindowTextW(
                hwnd,
                title_buffer,
                length + 1,
            )

            title = title_buffer.value.strip()

            if not title:
                return True

            rect = wintypes.RECT()

            if not GetWindowRect(
                hwnd,
                ctypes.byref(rect),
            ):
                return True

            # Get primary screen boundaries
            screen_width = user32.GetSystemMetrics(0)
            screen_height = user32.GetSystemMetrics(1)

            # Clip window rectangle to the primary screen
            left = max(0, rect.left)
            top = max(0, rect.top)
            right = min(screen_width, rect.right)
            bottom = min(screen_height, rect.bottom)

            width = right - left
            height = bottom - top

            if width <= 0 or height <= 0:
                return True

            self.windows.append({
                "hwnd": int(hwnd),
                "title": title,
                "x": left,
                "y": top,
                "width": width,
                "height": height,
            })

            self.window_list.addItem(title)

            return True

        callback_ref = EnumWindowsProc(callback)

        EnumWindows(callback_ref, 0)

    def select_window(self):
        index = self.window_list.currentRow()

        if index < 0:
            QMessageBox.warning(
                self,
                "No Window Selected",
                "Please select a window first.",
            )
            return

        window = self.windows[index]

        region = {
            "hwnd": window["hwnd"],
            "capture_title": window["title"],
            "x": window["x"],
            "y": window["y"],
            "width": window["width"],
            "height": window["height"],
        }

        print("Selected window title:", window["title"])
        print("Selected window HWND:", window["hwnd"])
        print("Selected window region:", region)

        # Close the picker without activating the selected window.
        self.close()

        # Send the selected window information to RecordingWindow.
        self.window_selected.emit(region)