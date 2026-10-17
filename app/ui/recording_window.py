from app.controllers.hotkey_controller import HotkeyController
from app.ui.window_selector import WindowSelector
from app.ui.region_selector import RegionSelector
from app.controllers.recording_controller import RecordingController

from PySide6.QtCore import QTimer, Qt, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class RecordingWindow(QWidget):

    def __init__(self):
        super().__init__()

        self.selected_region = None
        self.selected_window = None
        self.window_selector = None
        self.region_selector = None

        # Window
        self.setWindowTitle("StudioCast")
        self.resize(780, 700)
        self.setMinimumSize(680, 640)
        self.setObjectName("recordingWindow")

        # Heading
        self.title = QLabel("Welcome to StudioCast - AI Video Recorder")
        self.title.setObjectName("pageTitle")
        self.title.setWordWrap(True)

        # Recording sources
        self.screen = QCheckBox("Screen")
        self.webcam = QCheckBox("Webcam")
        self.microphone = QCheckBox("Microphone")
        self.system_audio = QCheckBox("System Audio")

        # Recording area
        self.area = QComboBox()
        self.area.addItems(["Full Screen", "Selected Area", "Window"])
        self.area.setMinimumHeight(46)

        # Buttons
        self.record_video = QPushButton("Start Recording")
        self.stop_video = QPushButton("Stop")
        self.pause_button = QPushButton("Pause")
        self.resume_button = QPushButton("Resume")

        self.record_video.setObjectName("primaryButton")
        self.stop_video.setObjectName("stopButton")
        self.pause_button.setObjectName("secondaryButton")
        self.resume_button.setObjectName("secondaryButton")
        for button in (
            self.record_video,
            self.stop_video,
            self.pause_button,
            self.resume_button,
        ):
            button.setMinimumHeight(48)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.stop_video.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.resume_button.setEnabled(False)

        # Status
        self.status = QLabel("Ready")
        self.status.setObjectName("statusLabel")
        self.timer_label = QLabel("00:00:00")
        self.timer_label.setObjectName("timerLabel")
        self.timer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Variables
        self.is_recording = False
        self.elapsed_time = 0
        self.is_paused = False

        # Timers
        self.timer = QTimer(self)
        self.process_monitor_timer = QTimer(self)

        # Controller
        self.controller = RecordingController()

        # Global keyboard shortcuts
        self.hotkeys = HotkeyController()

        self.hotkeys.start_requested.connect(
            self.start_recording
        )

        self.hotkeys.stop_requested.connect(
            self.stop_recording
        )

        self.hotkeys.pause_requested.connect(
            self.pause_recording
        )

        self.hotkeys.resume_requested.connect(
            self.resume_recording
        )

        # Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 30)
        layout.setSpacing(20)

        header = QHBoxLayout()
        header.setSpacing(16)
        brand_mark = QLabel("SC")
        brand_mark.setObjectName("brandMark")
        brand_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_mark.setFixedSize(54, 54)
        heading_stack = QVBoxLayout()
        heading_stack.setSpacing(5)
        heading_stack.addWidget(self.title)
        subtitle = QLabel("Capture your screen, camera, and audio in one place.")
        subtitle.setObjectName("subtitle")
        heading_stack.addWidget(subtitle)
        header.addWidget(brand_mark, 0, Qt.AlignmentFlag.AlignTop)
        header.addLayout(heading_stack, 1)
        layout.addLayout(header)

        layout.addWidget(self._section_heading(
            "Recording sources", "Choose what to include in this session."
        ))

        source_layout = QHBoxLayout()
        source_layout.setSpacing(12)
        source_layout.addWidget(self._source_card(
            self.screen, "▣", "Capture everything on your display."
        ))
        source_layout.addWidget(self._source_card(
            self.webcam, "◉", "Add your camera to the recording."
        ))
        source_layout.addWidget(self._source_card(
            self.microphone, "♩", "Record your voice."
        ))
        source_layout.addWidget(self._source_card(
            self.system_audio, "♫", "Include audio from your computer."
        ))
        layout.addLayout(source_layout)

        area_card = QFrame()
        area_card.setObjectName("surfaceCard")
        area_layout = QVBoxLayout(area_card)
        area_layout.setContentsMargins(20, 18, 20, 18)
        area_layout.setSpacing(9)
        area_label = QLabel("Capture area")
        area_label.setObjectName("fieldLabel")
        area_help = QLabel(
            "Record the full display, a custom region, or a specific window."
        )
        area_help.setObjectName("helperText")
        area_layout.addWidget(area_label)
        area_layout.addWidget(area_help)
        area_layout.addWidget(self.area)
        layout.addWidget(area_card)

        session_card = QFrame()
        session_card.setObjectName("sessionCard")
        session_layout = QVBoxLayout(session_card)
        session_layout.setContentsMargins(22, 18, 22, 18)
        session_layout.setSpacing(6)
        timer_caption = QLabel("SESSION TIME")
        timer_caption.setObjectName("eyebrow")
        timer_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        session_layout.addWidget(timer_caption)
        session_layout.addWidget(self.timer_label)
        session_layout.addWidget(self.status, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(session_card)

        control_label = QLabel("Recording controls")
        control_label.setObjectName("fieldLabel")
        layout.addWidget(control_label)
        controls = QHBoxLayout()
        controls.setSpacing(10)
        controls.addWidget(self.record_video, 2)
        controls.addWidget(self.pause_button, 1)
        controls.addWidget(self.resume_button, 1)
        controls.addWidget(self.stop_video, 1)
        layout.addLayout(controls)

        footer = QLabel(
            "Your recording is saved automatically when you stop."
        )
        footer.setObjectName("footerText")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(footer)

        self.setStyleSheet(self._dashboard_styles())

        # Signal connections
        self.timer.timeout.connect(self.update_timer)

        self.process_monitor_timer.timeout.connect(
            self.controller.check_processes
        )

        self.record_video.clicked.connect(self.start_recording)
        self.stop_video.clicked.connect(self.stop_recording)
        self.pause_button.clicked.connect(self.pause_recording)
        self.resume_button.clicked.connect(self.resume_recording)

        self.controller.finalization_finished.connect(
            self.on_finalization_finished
        )
        self.controller.process_failed.connect(
            self.on_process_failed
        )

    @staticmethod
    def _section_heading(title, description):
        heading = QWidget()
        layout = QVBoxLayout(heading)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        description_label = QLabel(description)
        description_label.setObjectName("helperText")
        layout.addWidget(title_label)
        layout.addWidget(description_label)
        return heading

    @staticmethod
    def _source_card(checkbox, symbol, description):
        card = QFrame()
        card.setObjectName("sourceCard")
        card.setMinimumHeight(126)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 13, 14, 13)
        layout.setSpacing(8)
        icon = QLabel(symbol)
        icon.setObjectName("sourceIcon")
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignLeft)
        checkbox.setObjectName("sourceCheck")
        layout.addWidget(checkbox)
        helper = QLabel(description)
        helper.setObjectName("helperText")
        helper.setWordWrap(True)
        layout.addWidget(helper)
        return card

    @staticmethod
    def _dashboard_styles():
        return """
            QWidget#recordingWindow {
                background: #f4f6fb;
                color: #172033;
                font-family: "Segoe UI", "Arial", sans-serif;
                font-size: 10pt;
            }
            QLabel#brandMark {
                background: #4f46e5;
                border-radius: 16px;
                color: white;
                font-size: 15pt;
                font-weight: 800;
            }
            QLabel#pageTitle {
                color: #172033;
                font-size: 19pt;
                font-weight: 700;
            }
            QLabel#subtitle, QLabel#helperText, QLabel#footerText {
                color: #778197;
                font-size: 9pt;
            }
            QLabel#sectionTitle, QLabel#fieldLabel {
                color: #253047;
                font-size: 11pt;
                font-weight: 700;
            }
            QFrame#sourceCard, QFrame#surfaceCard, QFrame#sessionCard {
                background: #ffffff;
                border: 1px solid #e4e8f0;
                border-radius: 14px;
            }
            QLabel#sourceIcon {
                color: #5b5bd6;
                font-size: 17pt;
                font-weight: 700;
            }
            QCheckBox#sourceCheck {
                color: #202b40;
                font-size: 10pt;
                font-weight: 650;
                spacing: 8px;
            }
            QCheckBox#sourceCheck::indicator {
                width: 18px;
                height: 18px;
                border: 1px solid #c8cfdd;
                border-radius: 5px;
                background: #ffffff;
            }
            QCheckBox#sourceCheck::indicator:checked {
                background: #4f46e5;
                border-color: #4f46e5;
            }
            QComboBox {
                background: #f9faff;
                border: 1px solid #dce2ed;
                border-radius: 9px;
                color: #253047;
                padding: 0 13px;
                font-size: 10pt;
            }
            QComboBox:focus { border: 1px solid #716cf0; }
            QComboBox::drop-down { border: 0; width: 34px; }
            QComboBox QAbstractItemView {
                background: #ffffff;
                border: 1px solid #dce2ed;
                color: #253047;
                selection-background-color: #e9eaff;
                selection-color: #253047;
                outline: 0;
                padding: 4px;
            }
            QLabel#sessionCard { color: #172033; }
            QLabel#eyebrow {
                color: #8791a5;
                font-size: 8pt;
                font-weight: 700;
                letter-spacing: 1px;
            }
            QLabel#timerLabel {
                color: #18243b;
                font-family: "Consolas", "Courier New", monospace;
                font-size: 29pt;
                font-weight: 700;
            }
            QLabel#statusLabel {
                background: #edf0f7;
                border-radius: 10px;
                color: #5c667b;
                font-size: 9pt;
                font-weight: 650;
                padding: 5px 12px;
            }
            QPushButton {
                border: 0;
                border-radius: 9px;
                font-size: 10pt;
                font-weight: 650;
                padding: 0 14px;
            }
            QPushButton#primaryButton {
                background: #4f46e5;
                color: #ffffff;
            }
            QPushButton#primaryButton:hover { background: #4338ca; }
            QPushButton#stopButton {
                background: #fff0f0;
                color: #bd3434;
            }
            QPushButton#stopButton:hover:enabled { background: #ffe1e1; }
            QPushButton#secondaryButton {
                background: #e9ecf5;
                color: #34415a;
            }
            QPushButton#secondaryButton:hover:enabled { background: #dce2f0; }
            QPushButton:disabled {
                background: #edf0f5;
                color: #a5adbb;
            }
            QLabel#footerText { padding-top: 1px; }
        """

    def update_timer(self):
        self.elapsed_time += 1

        hours, remainder = divmod(self.elapsed_time, 3600)
        minutes, seconds = divmod(remainder, 60)

        self.status.setText("Recording...")
        self.timer_label.setText(
            f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        )

    def start_recording(self):

        if self.is_recording or self.controller.is_finalizing:
            print("Recording or finalization already in progress")
            return

        record_screen = self.screen.isChecked()
        record_webcam = self.webcam.isChecked()
        record_microphone = self.microphone.isChecked()
        record_system_audio = self.system_audio.isChecked()

        if not any((
            record_screen,
            record_webcam,
            record_microphone,
            record_system_audio
        )):
            self.status.setText(
                "Select at least one recording source."
            )
            print("No recording source selected")
            return

        area = self.area.currentText()

        # Recording area selection
        if area == "Selected Area":
            self.selected_window = None

            if self.selected_region is None:
                self.status.setText(
                    "Select the screen region to record."
                )
                self.select_region()
                return

            region = self.selected_region

        elif area == "Window":
            self.selected_region = None

            if self.selected_window is None:
                self.status.setText(
                    "Select the window to record."
                )
                self.select_window()
                return

            region = self.selected_window

        else:
            # Full Screen
            self.selected_region = None
            self.selected_window = None
            region = None

        # Start recording
        result = self.controller.start(
            record_screen,
            record_webcam,
            record_microphone,
            record_system_audio,
            region=region
        )

        if result is not True:
            self.status.setText("Could not start recording.")
            return

        self.is_recording = True
        self.is_paused = False
        self.elapsed_time = 0

        self.timer_label.setText("00:00:00")
        self.timer.start(1000)
        self.process_monitor_timer.start(1000)

        self.status.setText("Recording...")
        self.record_video.setEnabled(False)
        self.stop_video.setEnabled(True)
        self.pause_button.setEnabled(True)
        self.resume_button.setEnabled(False)

    def select_region(self):
        self.region_selector = RegionSelector()

        self.region_selector.region_selected.connect(
            self.on_region_selected
        )

    def on_region_selected(self, region):
        self.selected_region = region
        print("Selected region:", self.selected_region)

        # Start recording after the user selects the region
        self.start_recording()

    def select_window(self):
        self.window_selector = WindowSelector()

        self.window_selector.window_selected.connect(
            self.on_window_selected
        )

        self.window_selector.show()
        self.window_selector.raise_()
        self.window_selector.activateWindow()

    def on_window_selected(self, region):
        self.selected_window = region

        print("Selected window region:", region)

        # Start recording after the user selects the window
        self.start_recording()

    def stop_recording(self):

        if not self.is_recording:
            return

        self.status.setText("Stopping recording...")
        self.stop_video.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.resume_button.setEnabled(False)

        # Stop the recording timer
        self.timer.stop()
        self.process_monitor_timer.stop()

        # Prevent another Stop request while capture shuts down
        self.is_recording = False

        # Start background finalization through the controller
        result = self.controller.stop()

        if result is not True:
            self.status.setText("Could not start finalization.")
            self.record_video.setEnabled(True)
            self.timer_label.setText("00:00:00")

    @Slot(bool)
    def on_finalization_finished(self, result):

        if result:
            self.status.setText("Recording saved successfully.")
        else:
            self.status.setText(
                "Finalization failed. Temporary files kept for recovery."
            )

        self.timer_label.setText("00:00:00")

        self.record_video.setEnabled(True)
        self.stop_video.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.resume_button.setEnabled(False)

        self.is_recording = False
        self.is_paused = False

    @Slot()
    def on_process_failed(self):
        self.process_monitor_timer.stop()
        self.status.setText(
            "Warning: A recording process stopped unexpectedly."
        )

    def pause_recording(self):

        if not self.is_recording or self.is_paused:
            return

        self.controller.pause_recording()
        self.is_paused = True

        self.timer.stop()
        self.process_monitor_timer.stop()
        self.status.setText("Paused")

        self.pause_button.setEnabled(False)
        self.resume_button.setEnabled(True)

    def resume_recording(self):

        if not self.is_recording or not self.is_paused:
            return

        self.controller.resume_recording()
        self.is_paused = False

        self.timer.start(1000)
        self.process_monitor_timer.start(1000)
        self.status.setText("Recording...")

        self.pause_button.setEnabled(True)
        self.resume_button.setEnabled(False)
