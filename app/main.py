import sys
from PySide6.QtWidgets import QApplication
from app.ui.recording_window import RecordingWindow


def main():
    app = QApplication(sys.argv)

    window = RecordingWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()