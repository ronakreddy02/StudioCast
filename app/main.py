import sys
import subprocess
from pathlib import Path

from PySide6.QtWidgets import QApplication
from app.ui.recording_window import RecordingWindow


def quote_powershell(value):
    # Keep paths safe inside the PowerShell command
    return "'" + str(value).replace("'", "''") + "'"


def cleanup_orphaned_ffmpeg():
    # Match only StudioCast's bundled FFmpeg and recording folder
    project_root = Path(__file__).resolve().parent.parent
    ffmpeg_path = project_root / "vendor" / "ffmpeg" / "ffmpeg.exe"
    recordings_path = project_root / "recordings"

    if not ffmpeg_path.exists() or not recordings_path.exists():
        return

    powershell_script = f"""
$ffmpegPath = {quote_powershell(ffmpeg_path)}
$recordingsPath = {quote_powershell(recordings_path)}

$processes = Get-CimInstance Win32_Process -Filter "Name = 'ffmpeg.exe'"

foreach ($process in $processes) {{
    $isStudioCast = (
        $process.ExecutablePath -and
        $process.ExecutablePath.Equals(
            $ffmpegPath,
            [System.StringComparison]::OrdinalIgnoreCase
        ) -and
        $process.CommandLine -and
        $process.CommandLine.IndexOf(
            $recordingsPath,
            [System.StringComparison]::OrdinalIgnoreCase
        ) -ge 0
    )

    if ($isStudioCast) {{
        $parent = Get-CimInstance Win32_Process `
            -Filter "ProcessId = $($process.ParentProcessId)" `
            -ErrorAction SilentlyContinue

        if ($null -eq $parent) {{
            try {{
                Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
                Write-Output $process.ProcessId
            }}
            catch {{
                Write-Error "Could not stop process $($process.ProcessId)"
            }}
        }}
    }}
}}
"""

    try:
        # Stop only matching FFmpeg processes whose parent app is gone
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                powershell_script,
            ],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

        for process_id in result.stdout.splitlines():
            if process_id.strip():
                print(
                    "Stopped orphan StudioCast FFmpeg process: "
                    f"{process_id.strip()}"
                )

        if result.returncode != 0 and result.stderr.strip():
            print(
                "Could not check for orphan FFmpeg processes: "
                f"{result.stderr.strip()}"
            )

    except (OSError, subprocess.TimeoutExpired) as error:
        # Let StudioCast open even if the cleanup check fails
        print(f"Orphan process cleanup could not run: {error}")


def main():
    # Clean up old capture processes before opening StudioCast
    cleanup_orphaned_ffmpeg()

    app = QApplication(sys.argv)
    window = RecordingWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()