from pathlib import Path
from PySide6.QtCore import QObject, QThread, Signal, Slot

from media.ffmpeg import FFmpegWrapper


class FinalizationWorker(QObject):

    finished = Signal(bool)

    def __init__(self, wrapper):
        super().__init__()
        self.wrapper = wrapper

    @Slot()
    def run(self):
        try:
            result = self.wrapper.stop_recording()
        except Exception as error:
            print(f"Finalization error: {error}")
            result = False

        self.finished.emit(bool(result))


class RecordingController(QObject):

    finalization_finished = Signal(bool)
    process_failed = Signal(str, str)

    def __init__(self):
        super().__init__()

        self.is_recording = False
        self.is_finalizing = False

        self.wrapper = FFmpegWrapper()

        self.finalization_thread = None
        self.finalization_worker = None

    def preflight_recording(
        self,
        record_screen,
        record_webcam,
        record_microphone,
        record_system_audio
    ):
        # Run checks before starting FFmpeg
        return self.wrapper.preflight_recording(
            record_screen,
            record_webcam,
            record_microphone,
            record_system_audio
        )

    def start(self, record_screen, record_webcam,
              record_microphone, record_system_audio,region=None):

        if self.is_finalizing:
            print("Previous recording is still finalizing")
            return False

        result = self.wrapper.start_recording(
            record_screen,
            record_webcam,
            record_microphone,
            record_system_audio,
            region,
        )

        if result is False:
            print("Recording could not be started")
            return False

        self.is_recording = True
        print("Recording started")

        return True

    def stop(self):

        if not self.is_recording or self.is_finalizing:
            return False

        print("STOP BUTTON CLICKED")

        self.is_recording = False
        self.is_finalizing = True

        self.finalization_thread = QThread(self)
        self.finalization_worker = FinalizationWorker(self.wrapper)

        self.finalization_worker.moveToThread(
            self.finalization_thread
        )

        self.finalization_thread.started.connect(
            self.finalization_worker.run
        )

        self.finalization_worker.finished.connect(
            self.handle_finalization_result
        )

        self.finalization_worker.finished.connect(
            self.finalization_thread.quit
        )

        self.finalization_worker.finished.connect(
            self.finalization_worker.deleteLater
        )

        self.finalization_thread.finished.connect(
            self._on_thread_finished
        )

        self.finalization_thread.finished.connect(
            self.finalization_thread.deleteLater
        )

        print("Finalizing recording in background...")

        self.finalization_thread.start()

        return True

    @Slot(bool)
    def handle_finalization_result(self, result):

        if result:
            print("Final recording created successfully")
        else:
            print("Final recording failed")

        self.finalization_finished.emit(result)

    @Slot()
    def _on_thread_finished(self):

        self.is_finalizing = False

        self.finalization_thread = None
        self.finalization_worker = None

        print("Finilization thread cleaned up")

    def pause_recording(self):
        self.wrapper.pause_recording()

    def resume_recording(self):
        return self.wrapper.resume_recording()

        
    def check_processes(self):
        if not self.is_recording or self.is_finalizing:
            return

        for process in self.wrapper.processes:
            exit_code = process.poll()

            if exit_code is None:
                continue

            details = self.wrapper.process_details.get(process.pid, {})
            source = details.get("source", "recording")
            log_path = details.get("log_path")
            log_text = ""

            if log_path:
                try:
                    log_text = Path(log_path).read_text(
                        encoding="utf-8",
                        errors="replace"
                    )[-5000:]
                except OSError as error:
                    print(f"Could not read FFmpeg log for {source}: {error}")

            lowered = log_text.lower()

            if any(text in lowered for text in (
                "no space left",
                "disk full",
                "not enough space",
            )):
                message = "Disk is full."
            elif "permission denied" in lowered or "access is denied" in lowered:
                message = "Permission was denied."
            elif any(text in lowered for text in (
                "device or resource busy",
                "device busy",
                "already in use",
                "used by another process",
            )):
                message = "The device is busy or already in use."
            elif any(text in lowered for text in (
                "no such device",
                "could not find",
                "cannot find",
                "does not exist",
            )):
                message = "The selected device could not be found."
            else:
                useful_lines = [
                    line.strip()
                    for line in log_text.splitlines()
                    if line.strip()
                ]
                message = (
                    useful_lines[-1][:300]
                    if useful_lines
                    else f"Capture process exited with code {exit_code}."
                )

            print(f"{source} capture failed: {message}")
            self.process_failed.emit(source, message)
            return
