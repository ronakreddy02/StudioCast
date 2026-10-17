
import sys
from pathlib import Path

from windows_capture import WindowsCapture, InternalCaptureControl


def main():
    if len(sys.argv) != 2:
        print(
            "Usage: python test_window_capture.py <HWND>"
        )
        return

    hwnd = int(sys.argv[1])

    output_path = Path("window_capture_test.png")

    capture = WindowsCapture(
        cursor_capture=True,
        draw_border=False,
        window_hwnd=hwnd,
    )

    @capture.event
    def on_frame_arrived(
        frame,
        capture_control: InternalCaptureControl,
    ):
        frame.save_as_image(str(output_path))
        print("Captured frame:", output_path.resolve())
        capture_control.stop()

    @capture.event
    def on_closed():
        print("Window capture session closed")

    capture.start()


if __name__ == "__main__":
    main()
