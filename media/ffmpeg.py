import queue
import threading
import shutil
import ctypes
import subprocess
import json
import time
from datetime import datetime
from pathlib import Path


class WindowCaptureSegment:
    """Capture a selected window with Windows Graphics Capture."""


    def __init__(self, ffmpeg_path, hwnd, output_path):
        from windows_capture import WindowsCapture
        self.ffmpeg_path = ffmpeg_path
        self.hwnd = int(hwnd)
        self.output_path = output_path

        # Save window encoder errors beside the video segment

        output_name = Path(self.output_path).stem
        segment_number = output_name.split("_")[-1]
        self.log_path = Path(self.output_path).with_name(
            f"ffmpeg_screen_{segment_number}.log"
        )

        self.log_file = None
        self.capture = WindowsCapture(
            cursor_capture=True,
            draw_border=False,
            minimum_update_interval=33,
            window_hwnd=self.hwnd
        )

        self.stop_event = threading.Event()
        self.ready_event = threading.Event()
        self.writer_stop_event = threading.Event()
        self.frame_queue = queue.Queue(maxsize=2)

        self.thread = None
        self.writer_thread = None

        self.process = None
        self.capture_control = None

        self.error = None

        self.width = None
        self.height = None

        self.output_fps = 30

        self.capture_start_time = None
        self.frames_written = 0

        self.last_output_frame = None

        @self.capture.event
        def on_frame_arrived(frame, capture_control):

            # Stop the callback when recording ends

            if self.stop_event.is_set():
                capture_control.stop()
                return

            
            try:
                # Convert the captured image for FFmpeg

                bgr_frame = frame.convert_to_bgr()

                frame_buffer = bgr_frame.frame_buffer[:, :, :3]

                if self.process is None:
                    # Start FFmpeg after the first frame gives us its size

                    self.width = bgr_frame.width - (bgr_frame.width % 2)
                    self.height = bgr_frame.height - (bgr_frame.height % 2)

                    if self.width <= 0 or self.height <= 0:

                        raise ValueError("Invalid window capture dimensions.")
                    
                    command = []

                    command.append(str(self.ffmpeg_path))
                    
                    command.append("-y")
                    command.append("-hide_banner")
                    command.append("-loglevel")
                    command.append("error")
                    command.append("-f")
                    command.append("rawvideo")
                    command.append("-pixel_format")
                    command.append("bgr24")
                    command.append("-video_size")
                    command.append(f"{self.width}x{self.height}")
                    command.append("-framerate")


                    command.append(str(self.output_fps))

                    command.append("-i")
                    command.append("pipe:0")
                    command.append("-an")
                    command.append("-c:v")
                    command.append("libx264")
                    command.append("-preset")
                    command.append("ultrafast")
                    command.append("-tune")
                    command.append("zerolatency")
                    command.append("-crf")
                    command.append("23")
                    command.append("-pix_fmt")
                    command.append("yuv420p")
                    command.append("-f")
                    command.append("matroska")

                    command.append(str(self.output_path))

                    # Keep a log so window capture errors can be checked
                    self.log_file = open(
                        self.log_path,
                        "w",
                        encoding="utf-8",
                        errors="replace"
                    )



                    try:
                        self.process = subprocess.Popen(
                            command,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL,
                            stderr=self.log_file,
                            creationflags=subprocess.CREATE_NO_WINDOW
                        )

                    except Exception:
                        self.log_file.close()
                        self.log_file = None
                        raise

                    self.writer_thread = threading.Thread(
                        target=self._frame_writer,
                        daemon=True
                    )

                    self.writer_thread.start()

                    print(
                        f"Window capture: {self.width}x{self.height}, "
                        f"HWND {self.hwnd}"
                    )


                frame_buffer = frame_buffer[:self.height, :self.width, :3]

                if self.process.poll() is not None:
                    raise RuntimeError(
                        f"FFmpeg window encoder exited with code "
                        f"{self.process.returncode}."
                    )
                
                # Copy the frame because the capture library may reuse its
                # frame buffer after this callback returns.

                queued_frame = frame_buffer.copy()

                # Keep only recent frames. If encoding falls behind, discard
                # the oldest queued frame instead of blocking window capture.


                try:
                    self.frame_queue.put_nowait(queued_frame)

                except queue.Full:

                    try:
                        self.frame_queue.get_nowait()

                    except queue.Empty:
                        pass

                    try:
                        self.frame_queue.put_nowait(queued_frame)

                    except queue.Full:
                        pass


                self.ready_event.set()

            except Exception as error:

                self.error = error
                self.stop_event.set()
                self.ready_event.set()
                try:
                    capture_control.stop()

                except Exception:
                    pass

                
        @self.capture.event
        def on_closed():

            self.ready_event.set()


    def _frame_writer(self):

        """Write queued frames to FFmpeg outside the capture callback."""
        # Send queued frames without slowing the capture callback

        while (
            not self.writer_stop_event.is_set()
            or not self.frame_queue.empty()
        ):

            try:
                frame_buffer = self.frame_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            try:

                self._write_timed_frame(frame_buffer)


            except Exception as error:
                self.error = error
                self.stop_event.set()
                self.writer_stop_event.set()
                self.ready_event.set()
                return


    def _write_timed_frame(self, frame_buffer):

        """Write frames at 30 FPS, repeating the latest frame when needed."""

        if self.process is None or self.process.stdin is None:
            
            raise RuntimeError("Window video encoder is not ready.")
        
        if self.process.poll() is not None:

            raise RuntimeError(
                f"FFmpeg window encoder exited with code "
                f"{self.process.returncode}."
            )
        
        now = time.monotonic()

        if self.capture_start_time is None:
            self.capture_start_time = now
        # Match the output frame count to elapsed recording time


        target_frames = max(
            1,

            int((now - self.capture_start_time) * self.output_fps) + 1
        )

        frames_to_write = target_frames - self.frames_written

        if frames_to_write <= 0:
            return
        
        frame_bytes = frame_buffer.tobytes()

        for _ in range(frames_to_write):
            self.process.stdin.write(frame_bytes)
            self.frames_written += 1

        self.last_output_frame = frame_buffer.copy()


    def _pad_video_to_elapsed_time(self):
        """Repeat the last frame until the recording timeline reaches stop."""

        if (
            self.process is None
            or self.process.stdin is None
            or self.process.stdin.closed
            or self.capture_start_time is None
            or self.last_output_frame is None
        ):
            return

        
        # Keep the video duration aligned with the session time
        target_frames = max(
            1,
            int((time.monotonic() - self.capture_start_time) * self.output_fps) + 1
        )


        frame_bytes = self.last_output_frame.tobytes()

        while self.frames_written < target_frames:

            self.process.stdin.write(frame_bytes)
            self.frames_written += 1


    def _run(self):
        # Run window capture and finish the encoder when capture closes


        try:

            self.capture_control = self.capture.start_free_threaded()
            self.capture_control.wait()


        except Exception as error:

            self.error = error
            self.ready_event.set()


        finally:
            # Capture has ended, so no more frames should be queued.

            self.writer_stop_event.set()

            if self.writer_thread is not None:

                self.writer_thread.join(timeout=15)

            if self.writer_thread is not None and self.writer_thread.is_alive():

                self.error = TimeoutError(
                    "Window frame writer did not stop within 15 seconds."

                )


            if self.process is not None:

                try:
                    if self.process.stdin and not self.process.stdin.closed:
                        self._pad_video_to_elapsed_time()
                        self.process.stdin.close()

                except (OSError, ValueError):
                    pass

                try:
                    self.process.wait(timeout=10)

                except subprocess.TimeoutExpired:
                    self.process.terminate()
                    self.process.wait()

                # Close the encoder log after FFmpeg stops
                if self.log_file is not None:
                    self.log_file.close()
                    self.log_file = None


    def start(self):
        # Wait for the first frame before reporting a successful start

        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

        if not self.ready_event.wait(timeout=10):
            self.stop()
            raise TimeoutError(
                "Window capture did not deliver a frame within 10 seconds."
            )

        
        if self.error is not None:
            raise RuntimeError(
                f"Window capture failed: {self.error}"
            ) from self.error
        
        if self.process is None:
            raise RuntimeError(
                "Window capture closed before producing a video frame."
            )
        return self.process


    def stop(self):
        self.stop_event.set()
        # Tell Windows capture to release the selected window

        if self.capture_control is not None:
            try:
                self.capture_control.stop()

            except Exception as error:

                if self.error is None:
                    self.error = error

        if self.thread is not None:
            self.thread.join(timeout=15)

            if self.thread.is_alive():
                raise TimeoutError(
                    "Window capture did not stop within 15 seconds."
            )


class FFmpegWrapper:


    def __init__(self):
        self.ffmpeg_path = (
            Path(__file__).resolve().parent.parent
            / "vendor"
            / "ffmpeg"
            / "ffmpeg.exe"
        )


        self.processes = []
        self.process_details = {}
        self.window_capture_worker = None
        self.current_region = None
        self.session_folder = None
        self.session_start_time = None
        self.session_end_time = None
        self.duration_warning = None
        self.start_error = None
        self.segment_index = 1
        self.segments = []
        self.segment_files = {
            "screen" : [],
            "webcam" : [],
            "microphone" : [],
            "system_audio" : []
        }

        self.record_screen = False
        self.record_webcam = False
        self.record_microphone = False
        self.record_system_audio = False


    def get_process_handle(self,process):
        # Get the Windows handle used to pause or resume FFmpeg

        process_id = process.pid
        kernel32 = ctypes.windll.kernel32
        open_process = kernel32.OpenProcess
        process_handle = open_process(0x0800, False, process_id)
        return process_handle


    @staticmethod
    def _get_source_name(command):


        # Use the output filename to identify the recording source
        output_name = Path(command[-1]).name.lower()

        for source in ("system_audio", "microphone", "webcam", "screen"):

            if output_name.startswith(source + "_"):
                return source
            
        return "unknown"

    def preflight_recording(
        self,
        record_screen,
        record_webcam,
        record_microphone,
        record_system_audio
    ):
        # Check that at least one source is selected
        if not any((
            record_screen,
            record_webcam,
            record_microphone,
            record_system_audio
        )):
            return {
                "error": "Select at least one recording source.",
                "warning": None,
            }

        # Check that FFmpeg is available
        if not self.ffmpeg_path.exists():
            return {
                "error": f"FFmpeg was not found: {self.ffmpeg_path}",
                "warning": None,
            }

        # Check that selected camera and audio devices are available
        expected_devices = []

        if record_webcam:
            expected_devices.append(("Webcam", "Integrated Webcam"))

        if record_microphone:
            expected_devices.append((
                "Microphone",
                "Digital Microphone (2- Cirrus Logic High Definition Audio)"
            ))

        if record_system_audio:
            expected_devices.append((
                "System audio",
                "CABLE Output (VB-Audio Virtual Cable)"
            ))

        if expected_devices:
            command = []
            command.append(str(self.ffmpeg_path))
            command.append("-hide_banner")
            command.append("-list_devices")
            command.append("true")
            command.append("-f")
            command.append("dshow")
            command.append("-i")
            command.append("dummy")

            try:
                result = subprocess.run(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                return {
                    "error": f"Could not check recording devices: {error}",
                    "warning": None,
                }

            available_devices = (result.stdout or "").casefold()

            for source_name, device_name in expected_devices:
                if device_name.casefold() not in available_devices:
                    return {
                        "error": f"{source_name} device not found: {device_name}",
                        "warning": None,
                    }

        # Check the recording folder and estimate space for one hour
        recordings_folder = (
            Path(__file__).resolve().parent.parent / "recordings"
        )

        try:
            recordings_folder.mkdir(exist_ok=True)
            free_bytes = shutil.disk_usage(recordings_folder).free
        except OSError as error:
            return {
                "error": f"Could not check recording disk space: {error}",
                "warning": None,
            }

        screen_bitrate = 12_000_000
        webcam_bitrate = 2_500_000
        audio_bitrate = 192_000
        source_bitrate = 0
        final_bitrate = 0

        if record_screen:
            source_bitrate += screen_bitrate
            final_bitrate += screen_bitrate
        elif record_webcam:
            final_bitrate += webcam_bitrate

        if record_webcam:
            source_bitrate += webcam_bitrate

        if record_microphone:
            source_bitrate += audio_bitrate

        if record_system_audio:
            source_bitrate += audio_bitrate

        if record_microphone or record_system_audio:
            final_bitrate += audio_bitrate

        # Include temporary source files, final video, and extra room
        estimated_bytes = int(
            (source_bitrate + final_bitrate)
            * 60
            * 60
            / 8
            * 1.25
        )

        warning = None

        if free_bytes < estimated_bytes:
            free_gb = free_bytes / (1024 ** 3)
            estimated_gb = estimated_bytes / (1024 ** 3)
            warning = (
                f"Free space is about {free_gb:.1f} GB. "
                f"StudioCast estimates about {estimated_gb:.1f} GB "
                "for one hour of this recording. Continue anyway?"
            )

        # Check the timestamped session folder name
        session_name = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        session_folder = recordings_folder / f"recording_{session_name}"

        if session_folder.exists():
            return {
                "error": (
                    f"That recording folder already exists: {session_folder}"
                ),
                "warning": None,
            }

        return {
            "error": None,
            "warning": warning,
        }


    def _start_capture_process(self, command):
        # Save each source's FFmpeg errors in its own log


        source = self._get_source_name(command)
        progress_path = self.session_folder / (
            f"capture_{source}_{self.segment_index:03d}.progress"
        )
        command[-1:-1] = ["-progress", str(progress_path)]
        log_path = self.session_folder / (
            f"ffmpeg_{source}_{self.segment_index:03d}.log"
        )

        process_start_time = datetime.now()

        with open(
            log_path,
            "w",
            encoding="utf-8",
            errors="replace"
            
        ) as log_file:
            
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=log_file,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )


        self.processes.append(process)
        self.process_details[process.pid] = {
            "source": source,
            "log_path": log_path,
            "progress_path": progress_path,
            "log_offset": 0,
            "reported_warnings": set(),
        }


        print(f"Saving to: {command[-1]}")
        print(f"FFmpeg log: {log_path}")
        print(f"Process start time: {process_start_time}")
        return process


    def wait_for_capture_ready(self, timeout=12):
        # Wait until FFmpeg reports media progress for each selected source
        required_sources = [
            source
            for source, enabled in (
                ("screen", self.record_screen),
                ("webcam", self.record_webcam),
                ("microphone", self.record_microphone),
                ("system_audio", self.record_system_audio),
            )
            if enabled
        ]
        ready_sources = set()
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            for source in required_sources:
                if source in ready_sources:
                    continue

                source_process = next(
                    (
                        process
                        for process in self.processes
                        if self.process_details.get(process.pid, {}).get("source") == source
                    ),
                    None,
                )

                if source_process is not None and source_process.poll() is not None:
                    failure = self.get_process_failure(source_process)
                    if failure:
                        return False, f"{source}: {failure['message']}"
                    return False, f"{source} capture stopped during startup."

                if source == "screen" and self.window_capture_worker is not None:
                    if self.window_capture_worker.error is not None:
                        return False, f"screen: {self.window_capture_worker.error}"

                if source_process is not None:
                    progress_path = self.process_details.get(
                        source_process.pid, {}
                    ).get("progress_path")

                    if progress_path and Path(progress_path).exists():
                        try:
                            progress_text = Path(progress_path).read_text(
                                encoding="utf-8",
                                errors="replace",
                            )
                        except OSError:
                            progress_text = ""

                        progress_values = {}
                        for line in progress_text.splitlines():
                            if "=" in line:
                                key, value = line.split("=", 1)
                                progress_values[key] = value

                        try:
                            processed_time = int(
                                progress_values.get("out_time_us", "0")
                            )
                        except ValueError:
                            processed_time = 0

                        if processed_time > 0:
                            ready_sources.add(source)
                            continue

                # The window capture worker reports readiness after its first frame
                source_files = self.segment_files[source]
                if source == "screen" and self.window_capture_worker is not None:
                    if self.window_capture_worker.ready_event.is_set():
                        if self.window_capture_worker.error is None:
                            ready_sources.add(source)
                            continue

            if len(ready_sources) == len(required_sources):
                return True, None

            time.sleep(0.1)

        missing_sources = sorted(set(required_sources) - ready_sources)
        return False, (
            "Capture did not become ready for: "
            + ", ".join(missing_sources)
            + f" within {timeout} seconds."
        )



    def get_process_failure(self, process):


        # Only read the log after the capture process stops
        exit_code = process.poll()

        if exit_code is None:
            return None
        details = self.process_details.get(process.pid, {})
        source = details.get("source", "recording")
        log_path = details.get("log_path")
        log_text = ""

        # Read this source's FFmpeg log
        if log_path:
            try:
                log_text = Path(log_path).read_text(
                    encoding="utf-8",
                    errors="replace"
                )[-5000:]

            except OSError as error:
                print(f"Could not read the {source} log: {error}")
        lowered_log = log_text.lower()



        # Match common recording failures
        if any(message in lowered_log for message in (
            "no space left",
            "disk full",
            "not enough space",
        )):
            
            error_message = "Disk is full."

        elif any(message in lowered_log for message in (
            "permission denied",
            "access is denied",

        )):
            
            error_message = "Permission was denied."

        elif any(message in lowered_log for message in (
            "device or resource busy",
            "device busy",
            "already in use",
            "used by another process",
        )):
            
            error_message = "The device is busy or already in use."

        elif any(message in lowered_log for message in (
            "no such device",
            "could not find",
            "cannot find",
            "does not exist",
        )):

            
            error_message = "The selected device could not be found."

        else:
            # Keep the last log line for other failures
            log_lines = [
                line.strip()
                for line in log_text.splitlines()
                if line.strip()
            ]


            if log_lines:
                error_message = log_lines[-1][:300]

            else:

                error_message = (
                    f"Capture stopped with exit code {exit_code}."
                )


        return {
            "source": source,
            "message": error_message,
            "exit_code": exit_code,
        }

    def get_media_duration(self, media_path):

        # Read the file duration with FFprobe
        ffprobe_path = self.ffmpeg_path.with_name("ffprobe.exe")

        if not ffprobe_path.exists():
            raise FileNotFoundError("ffprobe.exe was not found.")

        command = []
        command.append(str(ffprobe_path))
        command.append("-v")
        command.append("error")
        command.append("-show_entries")
        command.append("format=duration")
        command.append("-of")
        command.append("default=noprint_wrappers=1:nokey=1")
        command.append(str(media_path))

        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

        if result.returncode != 0:
            raise RuntimeError(
                result.stderr.strip() or "FFprobe could not read the file."
            )

        return float(result.stdout.strip())


    def get_file_creation_time(self, media_path):
        # Use the Windows file creation time as the first capture timestamp
        stat_result = Path(media_path).stat()
        creation_time = getattr(stat_result, "st_birthtime", None)

        if creation_time is None:
            creation_time = stat_result.st_ctime

        return float(creation_time)


    def get_session_timeline_duration(self):
        # Use only the time StudioCast marked as actively recording
        total_duration = 0.0

        for segment in self.segments:
            
            start_time = datetime.fromisoformat(segment["start_time"])
            end_value = segment.get("end_time")
            end_time = (
                datetime.fromisoformat(end_value)
                if end_value
                else self.session_end_time
            )

            if end_time is not None and end_time > start_time:
                total_duration += (end_time - start_time).total_seconds()

        return total_duration


    def get_source_timing(self, source):
        # Trim startup and shutdown capture outside each active segment
        source_files = self.segment_files[source]

        if not source_files or len(source_files) != len(self.segments):
            return None

        timing = {
            "shifts": [],
            "boundaries": [],
            "starts": [],
            "ends": [],
            "ranges": [],
        }
        source_cursor = 0.0
        timeline_cursor = 0.0

        try:
            for segment, source_path in zip(self.segments, source_files):


                source_start = self.get_file_creation_time(source_path)
                source_duration = self.get_media_duration(source_path)
                segment_start = datetime.fromisoformat(
                    segment["start_time"]
                ).timestamp()
                segment_end_value = segment.get("end_time")
                segment_end = (
                    datetime.fromisoformat(segment_end_value).timestamp()
                    if segment_end_value
                    else self.session_end_time.timestamp()
                )

                trim_start = max(0.0, segment_start - source_start)
                trim_end = min(
                    source_duration,
                    max(0.0, segment_end - source_start),
                )
                input_start = source_cursor + min(trim_start, source_duration)
                
                input_end = source_cursor + trim_end
                
                source_delay = max(0.0, source_start - segment_start)
                
                desired_start = timeline_cursor + source_delay
                
                source_shift = desired_start - input_start

                timing["shifts"].append(source_shift)
                timing["boundaries"].append(input_end)
                timing["ranges"].append((input_start, input_end))
                timing["starts"].append(desired_start)
                timing["ends"].append(
                    desired_start + max(0.0, input_end - input_start)
                )

                source_cursor += source_duration
                timeline_cursor += max(0.0, segment_end - segment_start)

        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
            print(f"Could not read {source} capture timing: {error}")
            return None

        return timing


    def get_select_expression(self, timing):
        # Keep frames or samples only inside active segment time ranges
        if not timing or not timing["ranges"]:
            return "0"

        ranges = [
            f"gte(t\\,{start_time:.6f})*lt(t\\,{end_time:.6f})"
            for start_time, end_time in timing["ranges"]
            if end_time > start_time
        ]

        return "+".join(ranges) if ranges else "0"


    def get_pts_shift_expression(self, timing):
        # Build one timestamp correction for each joined segment
        if not timing or not timing["shifts"]:
            return "PTS"

        shifts = timing["shifts"]

        if all(abs(shift) < 0.001 for shift in shifts):
            return "PTS"

        expression = f"{shifts[-1]:.6f}"

        for index in range(len(shifts) - 2, -1, -1):
            boundary = timing["boundaries"][index]
            shift = shifts[index]
            expression = (
                f"if(lt(PTS*TB\\,{boundary:.6f})"
                f"\\,{shift:.6f}\\,{expression})"
            )

        return f"PTS+({expression})/TB"


    def get_overlay_enable_expression(self, timing):
        # Show webcam frames only while that segment was recording
        if not timing or not timing["starts"]:
            return ""

        windows = []

        for start_time, end_time in zip(timing["starts"], timing["ends"]):
            start_time = max(0.0, start_time)
            windows.append(
                f"between(t\\,{start_time:.6f}\\,{end_time:.6f})"
            )

        return "+".join(windows)


    def get_video_padding_duration(self, timing, timeline_duration):
        # Hold the last frame if another source ends later
        if not timing or not timing["ends"]:
            return 0.0

        return max(0.0, timeline_duration - max(timing["ends"]))


    def check_camera_microphone_duration(self):
        # Compare capture end times because each device can start later
        if not self.record_webcam or not self.record_microphone:
            return None

        webcam_files = self.segment_files["webcam"]
        microphone_files = self.segment_files["microphone"]

        try:
            webcam_duration = self.get_media_duration(
                self.session_folder / "webcam.mkv"
            )
            microphone_duration = self.get_media_duration(
                self.session_folder / "microphone.mkv"
            )
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
            return f"Duration check could not be completed: {error}"

        raw_difference = abs(webcam_duration - microphone_duration)
        largest_end_difference = 0.0
        largest_start_difference = 0.0

        try:
            for webcam_path, microphone_path in zip(webcam_files, microphone_files):
                
                webcam_start = self.get_file_creation_time(webcam_path)
                
                microphone_start = self.get_file_creation_time(microphone_path)
               
                webcam_segment_duration = self.get_media_duration(webcam_path)
               
                microphone_segment_duration = self.get_media_duration(microphone_path)
               
                webcam_end = webcam_start + webcam_segment_duration
               
                microphone_end = microphone_start + microphone_segment_duration

                largest_start_difference = max(
                    largest_start_difference,
                    abs(webcam_start - microphone_start),
                )
                
                largest_end_difference = max(
                    largest_end_difference,
                    abs(webcam_end - microphone_end),
                )

        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
            return f"Capture timing check could not be completed: {error}"

        if largest_end_difference > 1.0:
            
            return (
                f"Webcam and microphone estimated capture end times differ by "
                f"{largest_end_difference:.2f}s. Their raw durations differ by "
                f"{raw_difference:.2f}s because their starts differ by up to "
                f"{largest_start_difference:.2f}s. Source offsets will be "
                f"preserved in the final recording."
            )

        if raw_difference > 1.0:
            
            print(
                f"Raw webcam/microphone durations differ by {raw_difference:.2f}s, "
                f"but estimated capture ends differ by only "
                f"{largest_end_difference:.2f}s; preserving their start offsets."
            )

        return None


    def suspend_process(self,process):


        # Pause FFmpeg while keeping its current segment open
        process_handle = self.get_process_handle(process)
        ntdl = ctypes.windll.ntdll
        suspend_process = ntdl.NtSuspendProcess
        suspend_process(process_handle)


    def resume_recording(self):


        # Start a new file segment for each selected source
        self.start_error = None
        self.segment_index += 1
        self.segments.append({
            "segment_number": self.segment_index,
            "start_time": datetime.now().isoformat(),
            "end_time": None

        })


        commands = []
        window_mode = bool(
            self.record_screen
            and self.current_region
            and self.current_region.get("hwnd")
        )
        if self.record_screen and not window_mode:
            commands.append(self.build_screen_command(self.current_region))

        if self.record_webcam:
            commands.append(self.build_webcam_command())

        if self.record_microphone:
            commands.append(self.build_microphone_command())

        if self.record_system_audio:
            commands.append(self.build_system_audio_command())

        for command in commands:
            process = self._start_capture_process(command)

            print(f"Resumed recording: {command[-1]}")


        if window_mode:
            output_path = self.get_segment_path("screen")

            self.window_capture_worker = WindowCaptureSegment(
                self.ffmpeg_path,
                self.current_region["hwnd"],
                output_path


            )


            try:

                process = self.window_capture_worker.start()
                self.processes.append(process)
                self.process_details[process.pid] = {
                    "source": "screen",
                    "log_path": self.window_capture_worker.log_path,
                    "log_offset": 0,
                    "reported_warnings": set(),
                }


                print(f"Resumed window recording: {output_path}")

            except Exception:

                self.window_capture_worker = None
                raise


        if not commands and not window_mode:
            print("No recording source selected")
            self.start_error = "No recording source selected."
            return False

        ready, startup_error = self.wait_for_capture_ready()

        if not ready:
            self.start_error = startup_error

            if self.window_capture_worker is not None:
                try:
                    self.window_capture_worker.stop()
                except Exception as error:
                    print(f"Window capture cleanup failed: {error}")
                self.window_capture_worker = None

            for process in self.processes:
                if process.poll() is None and process.stdin:
                    try:
                        process.stdin.write(b"q\n")
                        process.stdin.flush()
                    except (OSError, ValueError):
                        pass

            for process in self.processes:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait()

            self.processes.clear()

            if self.segments and self.segments[-1]["end_time"] is None:
                self.segments[-1]["end_time"] = datetime.now().isoformat()

            return False

        self.segments[-1]["start_time"] = datetime.now().isoformat()
        return True


    def pause_recording(self):

        # Stop current source segments so they can be joined later
        window_process = None


        if self.window_capture_worker is not None:
            window_process = self.window_capture_worker.process
            self.window_capture_worker.stop()
            self.window_capture_worker = None

        for process in self.processes:
            if process is window_process:
                continue

            if process.poll() is None and process.stdin:
                process.stdin.write(b"q\n")
                process.stdin.flush()

        for process in self.processes:

            process.wait()

        if self.segments and self.segments[-1]["end_time"] is None:
            self.segments[-1]["end_time"] = datetime.now().isoformat()
        self.processes.clear()


    def get_segment_path(self,source):
        # Create and remember the next segment filename

        filename = f"{source}_{self.segment_index:03d}.mkv"
        path = self.session_folder / filename
        self.segment_files[source].append(path)
        return path


    def concatenate_segments(self,source):

        # Join the paused and resumed files for one source
        items = self.segment_files[source]
        count = len(items)
        output_path = self.session_folder / f"{source}.mkv"

        if count == 0:
            return None
        
        if count == 1:
            shutil.copy2(items[0], output_path)
            return output_path

        
        list_path = self.session_folder/ f"{source}_concat.txt"

        with open(list_path,"w",encoding="utf-8")as file:

            for item in items:
                path_text = str(item).replace("\\\\","/")
                file.write(f"file '{path_text}'\n")


        # Tell FFmpeg to join this source's segments
        command = []
        command.append(str(self.ffmpeg_path))
        if not (self.current_region and self.current_region.get("hwnd")):
            command.append("-copyts")
        command.append("-f")
        command.append("concat")
        command.append("-safe")
        command.append("0")
        command.append("-i")
        command.append(str(list_path))
        command.append("-c")
        command.append("copy")
        command.append("-y")
        command.append(str(output_path))


        try:
            process = subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=None,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )


            if process.returncode != 0:
                print(f"Failed to concatenate segments for {source}")
                return None

            
        except OSError as error:

            print(f"Could not run FFmpeg for {source}: {error}")
            return None
        
        if output_path.exists() and output_path.stat().st_size > 0:
            return output_path
        
        print(f"Concatenated file missing or empty for {source}")
        return None

    # Build full-screen or selected-area capture command


    def build_screen_command(self, region=None):
        output_path = self.get_segment_path("screen")

        # Capture the selected display through Desktop Duplication
        capture_input = "ddagrab=output_idx=0:framerate=30:draw_mouse=1"

        if region:
            x = int(region["x"])
            y = int(region["y"])
            width = int(region["width"])
            height = int(region["height"])
            width -= width % 2
            height -= height % 2

            if width <= 0 or height <= 0:
                raise ValueError("Capture region dimensions are invalid.")

            capture_input += f":video_size={width}x{height}"
            capture_input += f":offset_x={x}:offset_y={y}"

        command = []
        command.append(str(self.ffmpeg_path))
        command.append("-y")
        command.append("-loglevel")
        command.append("info")
        command.append("-f")
        command.append("lavfi")
        command.append("-i")
        command.append(capture_input)

        # Map desktop frames to the Intel QSV encoder
        command.append("-vf")
        command.append("hwmap=derive_device=qsv,format=qsv")
        command.append("-fps_mode")
        command.append("cfr")
        command.append("-bf")
        command.append("0")
        command.append("-c:v")
        command.append("h264_qsv")
        command.append("-b:v")
        command.append("4M")

        command.append(str(output_path))
        return command

    
    # Build webcam capture command
    def build_webcam_command(self):
        output_path = self.get_segment_path("webcam")
        command = []
        command.append(str(self.ffmpeg_path))
        command.append("-y")
        command.append("-loglevel")
        command.append("warning")

        # Keep the webcam input queue from filling during short bursts
        command.append("-rtbufsize")
        command.append("32M")
        command.append("-thread_queue_size")
        command.append("512")
        command.append("-f")
        command.append("dshow")
        command.append("-framerate")
        command.append("30")
        command.append("-video_size")
        command.append("640x480")
        command.append("-vcodec")
        command.append("mjpeg")
        command.append("-use_wallclock_as_timestamps")
        command.append("1")
        command.append("-i")
        command.append("video=Integrated Webcam")

        # Encode webcam video on Intel QSV
        command.append("-c:v")
        command.append("h264_qsv")
        command.append("-pix_fmt")
        command.append("nv12")
        command.append("-bf")
        command.append("0")
        command.append("-b:v")
        command.append("2500k")
        command.append("-fps_mode")
        command.append("cfr")
        command.append(str(output_path))
        return command

    
    # Build microphone capture command
    def build_microphone_command(self):
        output_path = self.get_segment_path("microphone")

        command = []

        command.append(str(self.ffmpeg_path))

        command.append("-y")
        command.append("-loglevel")
        command.append("error")
        #microphone input
        command.append("-thread_queue_size")
        command.append("512")
        command.append("-f")
        command.append("dshow")
        command.append("-sample_rate")
        command.append("48000")
        command.append("-use_wallclock_as_timestamps")
        command.append("1")
        
        command.append("-i")
        command.append("audio=Digital Microphone (2- Cirrus Logic High Definition Audio)")
        

        #microphone audio
        command.append("-af")
        command.append("afftdn=nr=10:nf=-40,dynaudnorm=f=50:g=5")
        command.append("-c:a")
        command.append("aac")
        command.append("-b:a")
        command.append("192k")


        command.append(str(output_path))
        return command

    
    # Build system audio capture command
    def build_system_audio_command(self):
        output_path = self.get_segment_path("system_audio")

        command =[]
        command.append(str(self.ffmpeg_path))

        command.append("-y")
        command.append("-loglevel")
        command.append("error")
        #system audio input
        command.append("-thread_queue_size")
        command.append("512")
        command.append("-f")
        command.append("dshow")
        command.append("-use_wallclock_as_timestamps")
        command.append("1")
        command.append("-i")
        command.append("audio=CABLE Output (VB-Audio Virtual Cable)")
   
        
        #system audio
        command.append("-c:a")
        command.append("aac")
        command.append("-b:a")
        command.append("192k")

        command.append(str(output_path))
        return command

    
    # Create a folder for this recording session
    def create_session_folder(self):
        # Make a new folder for this recording session
        timestamp = datetime.now()
        filename_time = timestamp.strftime("%Y-%m-%d_%H-%M-%S")
        recordings_folder = Path(__file__).resolve().parent.parent / "recordings"
        recordings_folder.mkdir(exist_ok=True)

        session_folder = recordings_folder / f"recording_{filename_time}"

        # Do not reuse a folder from an earlier recording
        session_folder.mkdir(exist_ok=False)

        self.session_folder = session_folder
        return session_folder


    
    # Save session times and segment details
    def save_session_info(self):

        # Save recording times and segment details
        session_file = self.session_folder / "session.json"
        session_info = {
            "start_time": self.session_start_time.isoformat(),
            "end_time": self.session_end_time.isoformat(),
            "duration": (
                self.session_end_time - self.session_start_time
            ).total_seconds(),

            "enabled_sources": [
                name for name,
                enabled in [
                    ("screen",self.record_screen),
                    ("webcam",self.record_webcam),
                    ("microphone",self.record_microphone),
                    ("system_audio",self.record_system_audio),
                ]
                if enabled
            ],
            "segments":self.segments,
        }

        with open(session_file, "w") as file:
            json.dump(session_info, file, indent=4,)



    def cleanup_temp_files(self):

        # Keep only the final video and session information
        keep_files = {"final.mp4", "session.json"}

        for file_path in self.session_folder.iterdir():

            if file_path.is_file() and file_path.name not in keep_files:

                try:
                    file_path.unlink()
                    print(f"Deleted temporary file: {file_path.name}")

                except OSError as error:
                    print(
                        f"Could not delete {file_path.name}: {error}"
                    )




    # Build the final combined video command
    def build_final_command(self):
        output_file = self.session_folder / "final.mp4"
        screen_file = self.session_folder / "screen.mkv"
        webcam_file = self.session_folder / "webcam.mkv"
        microphone_file = self.session_folder / "microphone.mkv"
        system_audio_file = self.session_folder / "system_audio.mkv"



        command = []
        command.append(str(self.ffmpeg_path))

        command.append("-y")
        command.append("-loglevel")
        command.append("error")
        command.append("-copyts")
        command.append("-start_at_zero")

        # input files
        input_index = 0
        screen_index = None
        webcam_index = None
        microphone_index = None
        system_audio_index = None

        
        if self.record_screen:
            command.append("-i")
            command.append(str(screen_file))
            screen_index = input_index
            input_index += 1


        if self.record_webcam:
            command.append("-i")
            command.append(str(webcam_file))
            webcam_index = input_index
            input_index += 1


        if self.record_microphone:
            command.append("-i")
            command.append(str(microphone_file))
            microphone_index = input_index
            input_index += 1


        if self.record_system_audio:
            command.append("-i")
            command.append(str(system_audio_file))
            system_audio_index = input_index
            input_index += 1


        # filter complex
        filters = []
        screen_timing = self.get_source_timing("screen") if self.record_screen else None
        webcam_timing = self.get_source_timing("webcam") if self.record_webcam else None
        microphone_timing = (
            self.get_source_timing("microphone") if self.record_microphone else None
        )
        system_audio_timing = (
            self.get_source_timing("system_audio") if self.record_system_audio else None
        )

        screen_pts = self.get_pts_shift_expression(screen_timing)
        webcam_pts = self.get_pts_shift_expression(webcam_timing)
        microphone_pts = self.get_pts_shift_expression(microphone_timing)
        system_audio_pts = self.get_pts_shift_expression(system_audio_timing)
        audio_timeline_duration = self.get_session_timeline_duration()

        for timing in (
            screen_timing,
            webcam_timing,
            microphone_timing,
            system_audio_timing,
        ):
            if timing and timing["ends"]:
                audio_timeline_duration = max(
                    audio_timeline_duration,
                    max(timing["ends"]),
                )

        session_timeline_duration = self.get_session_timeline_duration()

        if session_timeline_duration > 0:
            audio_timeline_duration = session_timeline_duration

        # Restore screen and webcam positions on the shared capture timeline
        if self.record_screen and self.record_webcam:
            screen_padding = self.get_video_padding_duration(
                screen_timing,
                audio_timeline_duration,
            )
            screen_select = self.get_select_expression(screen_timing)
            screen_filter = f"select='{screen_select}',setpts={screen_pts}"

            if screen_padding > 0.001:
                screen_filter += (
                    f",tpad=stop_mode=clone:stop_duration={screen_padding:.6f}"
                )

            filters.append(f"[{screen_index}:v]{screen_filter}[screen_sync]")

            filters.append(
                f"[{webcam_index}:v]"
                f"select='{self.get_select_expression(webcam_timing)}',"
                f"setpts={webcam_pts},scale=160:120[webcam]"
            )

            webcam_enable = self.get_overlay_enable_expression(webcam_timing)
            overlay_filter = "overlay=W-w-20:H-h-20:eof_action=pass:repeatlast=0"

            if webcam_enable:
                overlay_filter += f":enable='{webcam_enable}'"

            filters.append(f"[screen_sync][webcam]{overlay_filter}[video]")

        elif self.record_webcam:
            webcam_padding = self.get_video_padding_duration(
                webcam_timing,
                audio_timeline_duration,
            )
            webcam_select = self.get_select_expression(webcam_timing)
            webcam_filter = f"select='{webcam_select}',setpts={webcam_pts}"

            if webcam_padding > 0.001:
                webcam_filter += (
                    f",tpad=stop_mode=clone:stop_duration={webcam_padding:.6f}"
                )

            filters.append(f"[{webcam_index}:v]{webcam_filter}[video]")

        elif self.record_screen:
            screen_padding = self.get_video_padding_duration(
                screen_timing,
                audio_timeline_duration,
            )
            screen_select = self.get_select_expression(screen_timing)
            screen_filter = f"select='{screen_select}',setpts={screen_pts}"

            if screen_padding > 0.001:
                screen_filter += (
                    f",tpad=stop_mode=clone:stop_duration={screen_padding:.6f}"
                )

            filters.append(f"[{screen_index}:v]{screen_filter}[video]")

        # Keep the captured audio start times before mixing
        if self.record_microphone and self.record_system_audio:
            # Silence keeps the mix timeline alive before a device is ready
            filters.append(
                "anullsrc=r=48000:cl=stereo,"
                f"atrim=duration={audio_timeline_duration:.6f}[audio_timeline]"
            )
            filters.append(
                f"[{microphone_index}:a]"
                f"aselect='{self.get_select_expression(microphone_timing)}',"
                f"asetpts={microphone_pts}[microphone_sync]"
            )
            filters.append(
                f"[{system_audio_index}:a]"
                f"aselect='{self.get_select_expression(system_audio_timing)}',"
                f"asetpts={system_audio_pts}[system_audio_sync]"
            )
            filters.append(
                "[audio_timeline][microphone_sync][system_audio_sync]"
                "amix=inputs=3:duration=longest:normalize=1:weights='0 1 1',"
                "alimiter=limit=0.95[audio]"
            )

        elif self.record_microphone:
            filters.append(
                "anullsrc=r=48000:cl=stereo,"
                f"atrim=duration={audio_timeline_duration:.6f}[audio_timeline]"
            )
            filters.append(
                f"[{microphone_index}:a]"
                f"aselect='{self.get_select_expression(microphone_timing)}',"
                f"asetpts={microphone_pts}[microphone_sync]"
            )
            filters.append(
                "[audio_timeline][microphone_sync]"
                "amix=inputs=2:duration=longest:normalize=1:weights='0 1',"
                "alimiter=limit=0.95[audio]"
            )

        elif self.record_system_audio:
            filters.append(
                "anullsrc=r=48000:cl=stereo,"
                f"atrim=duration={audio_timeline_duration:.6f}[audio_timeline]"
            )
            filters.append(
                f"[{system_audio_index}:a]"
                f"aselect='{self.get_select_expression(system_audio_timing)}',"
                f"asetpts={system_audio_pts}[system_audio_sync]"
            )
            filters.append(
                "[audio_timeline][system_audio_sync]"
                "amix=inputs=2:duration=longest:normalize=1:weights='0 1',"
                "alimiter=limit=0.95[audio]"
            )

            
        if filters:
            command.append("-filter_complex")
            command.append(";".join(filters))


        # video mapping
        if self.record_screen and self.record_webcam:
            command.append("-map")
            command.append("[video]")

        elif self.record_screen:
            command.append("-map")
            command.append("[video]")


        elif self.record_webcam:

            command.append("-map")
            command.append("[video]")


        # audio mapping
        if self.record_microphone and self.record_system_audio:
            command.append("-map")
            command.append("[audio]")

        elif self.record_microphone:
            command.append("-map")
            command.append("[audio]")

        elif self.record_system_audio:
            command.append("-map")
            command.append("[audio]")



        # final video
        if self.record_screen or self.record_webcam:
            command.append("-c:v")
            command.append("libx264")
            command.append("-preset")
            command.append("faster")
            command.append("-pix_fmt")
            command.append("yuv420p")

        # final audio
        if self.record_microphone or self.record_system_audio:
            command.append("-c:a")
            command.append("aac")
            command.append("-b:a")
            command.append("192k")
            
        #command.append("-shortest")


        command.append("-movflags")
        command.append("+faststart")
        command.append(str(output_file))
        return command


    def start_recording(self, record_screen,
                    record_webcam,
                    record_microphone,
                    record_system_audio,
                    region=None):

        
        # Reset state and start the selected recording sources
        self.processes = []
        self.process_details = {}
        self.window_capture_worker = None
        self.duration_warning = None
        self.start_error = None
        self.segment_index = 1
        self.segments = []

        self.segment_files["screen"].clear()
        self.segment_files["webcam"].clear()
        self.segment_files["microphone"].clear()
        self.segment_files["system_audio"].clear()

        self.record_screen = record_screen
        self.record_webcam = record_webcam
        self.record_microphone = record_microphone
        self.record_system_audio = record_system_audio
        self.current_region = region


        if not self.ffmpeg_path.exists():
            print("FFmpeg executable not found")
            print(f"Expected path: {self.ffmpeg_path}")
            return False

        
        # Stop if another recording already created this folder
        try:
            self.create_session_folder()
        except FileExistsError:


            print("Recording folder already exists. Start again in a moment.")
            return False

        
        window_mode = bool(record_screen and region and region.get("hwnd"))



        commands = []

        if record_screen and not window_mode:
            commands.append(self.build_screen_command(region))

        if record_webcam:
            commands.append(self.build_webcam_command())
            
        if record_microphone:
            commands.append(self.build_microphone_command())

        if record_system_audio:
            commands.append(self.build_system_audio_command())


        if not commands and not window_mode:
            print("No recording source selected")
            return False

        
        try:
            for command in commands:
                process = self._start_capture_process(command)
                print(command)


            if window_mode:

                output_path = self.get_segment_path("screen")
                self.window_capture_worker = WindowCaptureSegment(
                    self.ffmpeg_path,
                    region["hwnd"],
                    output_path
                )


                process = self.window_capture_worker.start()
                self.processes.append(process)
                self.process_details[process.pid] = {
                    "source": "screen",
                    "log_path": self.window_capture_worker.log_path,
                    "log_offset": 0,
                    "reported_warnings": set(),
                }



                print(f"Window recording started: {output_path}")


            ready, startup_error = self.wait_for_capture_ready()

            if not ready:
                raise RuntimeError(startup_error)


        except Exception as error:
            self.start_error = str(error)
            print(f"Could not start recording: {error}")


            if self.window_capture_worker is not None:


                try:
                    self.window_capture_worker.stop()

                except Exception as stop_error:
                    print(f"Window capture cleanup failed: {stop_error}")


                self.window_capture_worker = None

            for active_process in self.processes:

                if active_process.poll() is None and active_process.stdin:

                    try:
                        active_process.stdin.write(b"q\n")
                        active_process.stdin.flush()
                    except (OSError, ValueError):
                        pass

            for active_process in self.processes:

                try:
                    active_process.wait(timeout=10)


                except subprocess.TimeoutExpired:
                    active_process.terminate()
                    active_process.wait()

            self.processes.clear()
            return False

        
        self.session_start_time = datetime.now()
        print("All selected sources are ready")
        self.segments.append({
            "segment_number": self.segment_index,
            "start_time": self.session_start_time.isoformat(),
            "end_time": None
        })

        print(f"Session start time: {self.session_start_time}")
        print(f"Session folder: {self.session_folder}")
        return True


    def stop_recording(self):
        self.session_end_time = datetime.now()

        # Stop captures, join source segments, and create the final video
        window_process = None

        if self.window_capture_worker is not None:

            window_process = self.window_capture_worker.process
            self.window_capture_worker.stop()
            self.window_capture_worker = None

        if self.processes:

            for process in self.processes:

                if process is window_process:
                    continue

                if process.poll() is None and process.stdin:
                    process.stdin.write(b"q\n")
                    process.stdin.flush()

            for process in self.processes:
                process.wait()
            self.processes.clear()



        if self.segments and self.segments[-1]["end_time"] is None:
            self.segments[-1]["end_time"] = self.session_end_time.isoformat()
        self.save_session_info()
        sources = {
            "screen": self.record_screen,
            "webcam": self.record_webcam,
            "microphone": self.record_microphone,
            "system_audio": self.record_system_audio
        }


        for source, enabled in sources.items():
            
            if enabled:
                result_path = self.concatenate_segments(source)


                if result_path is None:
                    print(f"No segments found for {source}")
                    return False
                
                print(f"Segments combined for {source}: {result_path}")



        # Check the source durations before building the final video
        self.duration_warning = self.check_camera_microphone_duration()

        if self.duration_warning:
            print(f"Duration warning: {self.duration_warning}")


        command = self.build_final_command()
        print("Creating final recording...")


        try:
            process = subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=None,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )


        except FileNotFoundError:
            print("FFmpeg executable or required file not found.")
            return False

        
        final_file = self.session_folder / "final.mp4"

        if (
            process.returncode == 0
            and final_file.exists()
            and final_file.stat().st_size > 0
        ):
            
            print("Final recording created")


            self.cleanup_temp_files()
            result = True

        else:
            print("Final recording failed")
            print("Temporary MKV files kept for recovery")
            result = False

        print(f"Final file: {final_file}")
        print(f"Session end time: {self.session_end_time}")

        duration = (
            self.session_end_time - self.session_start_time
        ).total_seconds()


        print(f"Recording duration: {duration:.2f} seconds")
        print(f"Recording saved to: {self.session_folder}")
        self.processes = []
        return result
