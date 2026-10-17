
import subprocess
import threading
from pathlib import Path

from windows_capture import WindowsCapture, InternalCaptureControl


FFMPEG_PATH = Path("vendor/ffmpeg/ffmpeg.exe")
OUTPUT_PATH = Path("window_video_test.mkv")
RECORD_SECONDS = 5


def main():
    hwnd_text = input("Enter the selected window HWND: ").strip()
    hwnd = int(hwnd_text)

    capture_finished = threading.Event()
    stop_requested = threading.Event()
    ffmpeg_process = None
    frame_count = 0

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
        nonlocal ffmpeg_process, frame_count

        if stop_requested.is_set():
            capture_control.stop()
            return

        try:
            bgr_frame = frame.convert_to_bgr()
            frame_bytes = bgr_frame.frame_buffer.tobytes()

            if ffmpeg_process is None:
                width = bgr_frame.width
                height = bgr_frame.height

                width -= width % 2
                height -= height % 2

                if width <= 0 or height <= 0:
                    raise ValueError("Invalid captured frame dimensions")

                command = []
                command.append(str(FFMPEG_PATH.resolve()))
                command.append("-y")
                command.append("-hide_banner")
                command.append("-loglevel")
                command.append("error")
                command.append("-f")
                command.append("rawvideo")
                command.append("-pixel_format")
                command.append("bgr24")
                command.append("-video_size")
                command.append(f"{width}x{height}")
                command.append("-framerate")
                command.append("30")
                command.append("-i")
                command.append("pipe:0")
                command.append("-an")
                command.append("-c:v")
                command.append("libx264")
                command.append("-preset")
                command.append("ultrafast")
                command.append("-pix_fmt")
                command.append("yuv420p")
                command.append("-f")
                command.append("matroska")
                command.append(str(OUTPUT_PATH.resolve()))

                ffmpeg_process = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )

                print(f"Frame size: {width}x{height}")

            # Crop only if the captured dimensions are odd.
            if bgr_frame.width % 2 or bgr_frame.height % 2:
                bgr_frame = bgr_frame.crop(
                    0,
                    0,
                    bgr_frame.width - (bgr_frame.width % 2),
                    bgr_frame.height - (bgr_frame.height % 2),
                )
                frame_bytes = bgr_frame.frame_buffer.tobytes()

            ffmpeg_process.stdin.write(frame_bytes)
            frame_count += 1

        except Exception as error:
            print(f"Frame delivery failed: {error}")
            stop_requested.set()
            capture_control.stop()

    @capture.event
    def on_closed():
        capture_finished.set()
        print("Window capture session closed")

    timer = threading.Timer(RECORD_SECONDS, stop_requested.set)
    timer.start()

    try:
        print(f"Capturing HWND {hwnd} for about {RECORD_SECONDS} seconds...")
        capture.start()
    finally:
        stop_requested.set()
        timer.cancel()

        if ffmpeg_process is not None:
            if ffmpeg_process.stdin:
                ffmpeg_process.stdin.close()

            return_code = ffmpeg_process.wait(timeout=10)
            error_output = ffmpeg_process.stderr.read().decode(
                errors="replace"
            )
            ffmpeg_process.stderr.close()

            print("FFmpeg exit code:", return_code)
            if error_output:
                print("FFmpeg errors:")
                print(error_output)

    print("Frames written:", frame_count)
    print("Output exists:", OUTPUT_PATH.exists())
    if OUTPUT_PATH.exists():
        print("Output size:", OUTPUT_PATH.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
