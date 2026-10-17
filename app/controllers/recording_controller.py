
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
    process_failed = Signal()

    def __init__(self):
        super().__init__()

        self.is_recording = False
        self.is_finalizing = False

        self.wrapper = FFmpegWrapper()

        self.finalization_thread = None
        self.finalization_worker = None

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
        self.wrapper.resume_recording()

        
    def check_processes(self):

        if not self.is_recording or self.is_finalizing:
            return

        for process in self.wrapper.processes:
            exit_code = process.poll()

            if exit_code is not None:
                print(
                    "Warning: An FFmpeg recording process "
                    "has stopped unexpectedly"
                )
                print(f"FFmpeg process ID: {process.pid}")
                print(f"FFmpeg exit code: {exit_code}")

                if process.stderr:
                    try:
                        error_output = process.stderr.read()
                        if error_output:
                            print("FFmpeg error output:")
                            print(error_output)
                    except Exception as error:
                        print(f"Could not read FFmpeg error: {error}")

                self.process_failed.emit()
                return

