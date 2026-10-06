# StudioCast

StudioCast is a desktop screen-recording application built using Python, PySide6 and FFmpeg.

The application is designed to capture screen, webcam, microphone and system audio, and then compose the captured streams into a final MP4 recording.

## Technologies Used

- Python
- PySide6
- FFmpeg
- FFprobe
- DirectShow
- gdigrab
- VB-Audio Virtual Cable

## Features

- Screen recording
- Webcam recording
- Microphone recording
- System-audio recording
- Independent capture of recording sources
- Pause and Resume recording
- Final video composition
- Webcam overlay on screen recording
- Microphone and system-audio mixing
- Final MP4 generation
- FFprobe-based output verification

## Project Architecture

StudioCast uses separate layers for the application UI, controller logic and media processing.

```text
PySide6 UI
    ↓
RecordingController
    ↓
FFmpegWrapper
    ↓
Independent FFmpeg Capture Processes
    ├── Screen
    ├── Webcam
    ├── Microphone
    └── System Audio
    ↓
Temporary MKV Files
    ↓
Final Composition
    ↓
final.mp4


## Project Architecture

STUDIOCAST/
├── app/
│   ├── main.py
│   └── controllers/
│       └── recording_controller.py
├── capture/
├── media/
│   └── ffmpeg.py
├── ui/
│   └── recording_window.py
├── vendor/
│   └── ffmpeg/
├── .gitignore
└── README.md

## How to Run

### 1. Open the project folder

Open PowerShell in the StudioCast project folder:

```powershell
cd "C:\Users\padma\OneDrive\Desktop\STUDIOCAST"

Activate the virtual environment
.\.venv\Scripts\Activate.ps1

Run StudioCast
python -m app.main