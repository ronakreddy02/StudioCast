from app.controllers.recording_controller import RecordingController


from PySide6.QtCore import QTimer
import threading
from PySide6.QtWidgets import (
    QWidget,
    QLabel,
    QCheckBox,
    QComboBox,
    QPushButton,
    QVBoxLayout,
)


class RecordingWindow(QWidget):

    def __init__(self):
        super().__init__()



        # Window
        self.setWindowTitle("StudioCast")
        self.resize(600, 400)

        # Heading
        self.title = QLabel("Welcome to StudioCast - AI Video Recorder")

        # Recording sources
        self.screen = QCheckBox("Screen")
        self.webcam = QCheckBox("Webcam")
        self.microphone = QCheckBox("Microphone")
        self.system_audio = QCheckBox("System Audio")

        # Recording area
        self.area = QComboBox()
        self.area.addItems(["Full Screen", "Selected Area", "Window"])

        # Buttons
        self.record_video = QPushButton("Start")
        self.stop_video = QPushButton("Stop")
        self.pause_button = QPushButton("Pause")
        self.resume_button = QPushButton("Resume")

        self.stop_video.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.resume_button.setEnabled(False)

        # Status
        self.status = QLabel("Ready")
        self.timer_label = QLabel("00:00")

        # Variables
        self.is_recording = False
        self.elapsed_time = 0
        self.timer = QTimer()
        self.stop_thread = None
        self.stop_timer = QTimer()
        self.stop_result = None
        self.is_paused = False

        self.controller = RecordingController()

        # Layout
        layout = QVBoxLayout()
        layout.addWidget(self.title)
        layout.addWidget(self.screen)
        layout.addWidget(self.webcam)
        layout.addWidget(self.microphone)
        layout.addWidget(self.system_audio)
        layout.addWidget(self.area)
        layout.addWidget(self.record_video)
        layout.addWidget(self.stop_video)
        layout.addWidget(self.pause_button)
        layout.addWidget(self.resume_button)
        layout.addWidget(self.status)
        layout.addWidget(self.timer_label)
       

        self.setLayout(layout)

        # Signal connections
        self.timer.timeout.connect(self.update_timer)
        self.stop_timer.timeout.connect(self.check_stop_status)
        self.record_video.clicked.connect(self.start_recording)
        self.stop_video.clicked.connect(self.stop_recording)
        self.pause_button.clicked.connect(self.pause_recording)
        self.resume_button.clicked.connect(self.resume_recording)

    def update_timer(self):
        self.elapsed_time += 1
        m, s = divmod(self.elapsed_time, 60)
        h, m = divmod(m, 60)

        self.status.setText("Recording...")
        self.timer_label.setText(f"{h:02d}:{m:02d}:{s:02d}")

    def start_recording(self):
        if self.is_recording:
            print("Already recording")
            return
        

        if (
            self.screen.isChecked()
            or self.webcam.isChecked()
            or self.microphone.isChecked()
            or self.system_audio.isChecked()
        ):

            if self.area.currentText() == "Full Screen":
                print("Full Screen selected")

            elif self.area.currentText() == "Selected Area":
                print("Selected Area recording")

            elif self.area.currentText() == "Window":
                print("Window recording")


            #checking the integration part of screen webcam etc
            record_screen = self.screen.isChecked()
            record_webcam = self.webcam.isChecked()
            record_microphone = self.microphone.isChecked()
            record_system_audio = self.system_audio.isChecked()

            self.controller.start(record_screen,record_webcam,record_microphone,record_system_audio)

            self.is_recording = True
            self.elapsed_time = 0
            self.timer.start(1000)

            self.status.setText("Recording...")
            self.record_video.setEnabled(False)
            self.stop_video.setEnabled(True)
            self.pause_button.setEnabled(True)
            self.resume_button.setEnabled(False)


   

        else:
            self.status.setText("Select at least one recording source.")
            print("No recording source selected")

    

    def stop_recording(self):
        self.is_recording = False
        self.timer.stop()

        self.status.setText("Finalizing recording...")
        self.stop_video.setEnabled(False)

        self.stop_result = None

        def stop_task():
            self.stop_result = self.controller.stop()

        self.stop_thread = threading.Thread(
            target=stop_task
        )

        self.stop_thread.start()
        self.stop_timer.start(100)

    def pause_recording(self):

        if not self.is_recording: 
            return

        if self.is_paused:
             return

        self.controller.pause_recording() 
        self.is_paused = True


        self.timer.stop()
        self.status.setText("Paused")

        self.pause_button.setEnabled(False)
        self.resume_button.setEnabled(True)

    def resume_recording(self):

        if not self.is_recording:
             return

        if not self.is_paused:
             return
         
        self.controller.resume_recording()
        self.is_paused = False

        self.timer.start(1000)
        self.status.setText("Recording")
        self.pause_button.setEnabled(True)
        self.resume_button.setEnabled(False)

    def check_stop_status(self):

        if self.stop_thread and not self.stop_thread.is_alive():
            self.stop_timer.stop()

            if self.stop_result is True:
                     self.status.setText("Recording saved successfully.")

            elif self.stop_result is False:
                    self.status.setText(
                    "Finalization failed. Temporary files kept for recovery."
                )

            else:
                    self.status.setText("Finalization status unknown.")

            self.timer_label.setText("00:00")

            self.record_video.setEnabled(True)
            self.stop_video.setEnabled(False)
            self.pause_button.setEnabled(False)
            self.resume_button.setEnabled(False)