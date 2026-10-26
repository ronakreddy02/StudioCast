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
            if self.stop_event.is_set():
                capture_control.stop()
                return

            try:
                bgr_frame = frame.convert_to_bgr()
                frame_buffer = bgr_frame.frame_buffer[:, :, :3]

                if self.process is None:
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

                    self.process = subprocess.Popen(
                        command,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )

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

        target_frames = max(
            1,
            int((time.monotonic() - self.capture_start_time) * self.output_fps) + 1
        )

        frame_bytes = self.last_output_frame.tobytes()

        while self.frames_written < target_frames:
            self.process.stdin.write(frame_bytes)
            self.frames_written += 1

    def _run(self):
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

    def start(self):
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

        self.window_capture_worker = None

        self.current_region = None

        self.session_folder = None

        self.session_start_time = None

        self.session_end_time = None



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



        # Pause and Resume button handling 

    def get_process_handle(self,process):

        process_id = process.pid



        kernel32 = ctypes.windll.kernel32



        open_process = kernel32.OpenProcess

        process_handle = open_process(0x0800, False, process_id)



        return process_handle



    def suspend_process(self,process):



        process_handle = self.get_process_handle(process)

        ntdl = ctypes.windll.ntdll

        suspend_process = ntdl.NtSuspendProcess



        suspend_process(process_handle)



    def resume_recording(self):



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

            process = subprocess.Popen(

                command,

                stdin=subprocess.PIPE,

                stdout=subprocess.DEVNULL,

                stderr=None,

                creationflags=subprocess.CREATE_NO_WINDOW,

            )

            self.processes.append(process)

            print(f"Resumed recording: {command[-1]}")



        if window_mode:

            output_path = self.get_segment_path("screen")

            self.window_capture_worker = WindowCaptureSegment(

                self.ffmpeg_path, self.current_region["hwnd"], output_path

            )

            try:

                process = self.window_capture_worker.start()

                self.processes.append(process)

                print(f"Resumed window recording: {output_path}")

            except Exception:

                self.window_capture_worker = None

                raise



        if not commands and not window_mode:

            print("No recording source selected")

            return



    def pause_recording(self):



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



        filename = f"{source}_{self.segment_index:03d}.mkv"



        path = self.session_folder / filename

        self.segment_files[source].append(path)

        return path



    def concatenate_segments(self,source):

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



        command = [

            str(self.ffmpeg_path),

            "-f","concat",

            "-safe","0",

            "-i",str(list_path),

            "-c","copy","-y",

            str(output_path),

            ]



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





    # Screen commands

    def build_screen_command(self, region=None):

        output_path = self.get_segment_path("screen")



        command = []

        command.append(str(self.ffmpeg_path))

        command.append("-y")



        # Use info level while diagnosing capture failures.

        command.append("-loglevel")

        command.append("info")



        command.append("-f")

        command.append("gdigrab")

        command.append("-framerate")

        command.append("30")

        command.append("-draw_mouse")

        command.append("1")

        command.append("-rtbufsize")

        command.append("256M")

        command.append("-thread_queue_size")

        command.append("1024")

        command.append("-use_wallclock_as_timestamps")

        command.append("1")



        # Selected Area: capture a desktop rectangle.

        # Window mode is handled separately by WindowCaptureSegment.

        if region:

            x = int(region["x"])

            y = int(region["y"])

            width = int(region["width"])

            height = int(region["height"])



            width -= width % 2

            height -= height % 2



            if width <= 0 or height <= 0:

                raise ValueError("Capture region dimensions are invalid.")



            command.append("-offset_x")

            command.append(str(x))

            command.append("-offset_y")

            command.append(str(y))

            command.append("-video_size")

            command.append(f"{width}x{height}")



        command.append("-i")

        command.append("desktop")

        # Crop odd capture dimensions for H.264 compatibility

        command.append("-vf")

        command.append("crop=trunc(iw/2)*2:trunc(ih/2)*2")



        # Video codec settings

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

        command.append("-fps_mode")

        command.append("cfr")





        command.append(str(output_path))



        return command



    #webcam integration done 

    def build_webcam_command(self):



            output_path = self.get_segment_path("webcam")



            command = []

            command.append(str(self.ffmpeg_path))

            command.append("-y")

            command.append("-loglevel")

            command.append("error")



            #webcam input

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

            command.append("-i")

            command.append("video=Integrated Webcam")

            command.append("-use_wallclock_as_timestamps")

            command.append("1")



            #video codec

            command.append("-c:v")

            command.append("libx264")

            command.append("-pix_fmt")

            command.append("yuv420p")

            command.append("-b:v")

            command.append("2500k")

            command.append("-fps_mode")

            command.append("cfr")



            command.append(str(output_path))



            return command





    #microphone integration done

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

        command.append("-i")

        command.append("audio=Digital Microphone (2- Cirrus Logic High Definition Audio)")

        command.append("-use_wallclock_as_timestamps")

        command.append("1")



        #microphone audio

        command.append("-af")

        command.append("afftdn=nr=10:nf=-40,dynaudnorm=f=50:g=5")

        command.append("-c:a")  

        command.append("aac")

        command.append("-b:a")

        command.append("192k")



        command.append(str(output_path))



        return command



        #System_Audio integration done

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

        command.append("-i")

        command.append("audio=CABLE Output (VB-Audio Virtual Cable)")

        command.append("-use_wallclock_as_timestamps")

        command.append("1")



        #system audio

        command.append("-c:a")

        command.append("aac")

        command.append("-b:a")

        command.append("192k")





        command.append(str(output_path))



        return command





    #create recording session

    def create_session_folder(self):



        timestamp = datetime.now()

        filename_time = timestamp.strftime("%Y-%m-%d_%H-%M-%S")



        recordings_folder = Path(__file__).resolve().parent.parent / "recordings"

        recordings_folder.mkdir(exist_ok=True)



        session_folder = recordings_folder / f"recording_{filename_time}"

        session_folder.mkdir(exist_ok=True)



        self.session_folder = session_folder



        return session_folder





    #save recording timestamp

    def save_session_info(self):



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



        screen_file = self.session_folder /"screen.mkv"

        webcam_file = self.session_folder /"webcam.mkv"

        microphone_file = self.session_folder /"microphone.mkv"

        system_audio_file = self.session_folder /"system_audio.mkv"



        if screen_file.exists():

            screen_file.unlink()



        if webcam_file.exists():

            webcam_file.unlink()



        if microphone_file.exists():

            microphone_file.unlink()



        if system_audio_file.exists():

            system_audio_file.unlink()







        #final composition

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



        # video



        if self.record_screen and self.record_webcam:



            filters.append(

                f"[{webcam_index}:v]scale=160:120[webcam]"

            )



            filters.append(

                f"[{screen_index}:v][webcam]"

                "overlay=W-w-20:H-h-20[video]")





        # audio

        if self.record_microphone and self.record_system_audio:



            filters.append(

                f"[{microphone_index}:a]"

                f"[{system_audio_index}:a]"

                "amix=inputs=2:duration=longest:normalize=1,"

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

            command.append(f"{screen_index}:v")



        elif self.record_webcam:



            command.append("-map")

            command.append(f"{webcam_index}:v")



        # audio mapping



        if self.record_microphone and self.record_system_audio:



            command.append("-map")

            command.append("[audio]")



        elif self.record_microphone:



            command.append("-map")

            command.append(f"{microphone_index}:a")



        elif self.record_system_audio:



            command.append("-map")

            command.append(f"{system_audio_index}:a")



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



        self.processes = []

        self.window_capture_worker = None

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



        self.create_session_folder()
        self.session_start_time = datetime.now()

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

                process_start_time = datetime.now()

                log_path = self.session_folder / (

                    f"ffmpeg_{len(self.processes) + 1}.log"

                )
                with open(log_path, "w", encoding="utf-8") as log_file:

                    process = subprocess.Popen(

                        command,

                        stdin=subprocess.PIPE,

                        stdout=subprocess.DEVNULL,

                        stderr=log_file,

                        creationflags=subprocess.CREATE_NO_WINDOW,

                    )


                self.processes.append(process)
                print(f"Saving to: {command[-1]}")

                print(f"FFmpeg log: {log_path}")
                print(command)
                print(f"Process start time: {process_start_time}")

            if window_mode:

                output_path = self.get_segment_path("screen")

                self.window_capture_worker = WindowCaptureSegment(

                    self.ffmpeg_path, region["hwnd"], output_path

                )

                process = self.window_capture_worker.start()

                self.processes.append(process)

                print(f"Window recording started: {output_path}")



        except Exception as error:

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

        print("Recording started")

        self.segments.append({

            "segment_number": self.segment_index,

            "start_time": datetime.now().isoformat(),

            "end_time": None

        })

        print(f"Session start time: {self.session_start_time}")

        print(f"Session folder: {self.session_folder}")

        return True



    def stop_recording(self):



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



        self.session_end_time = datetime.now()

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

            for file in self.session_folder.glob("*.mkv"):

                try:

                    file.unlink()

                    print(f"Deleted temporary file: {file.name}")

                except OSError:

                    print(f"Could not delete file: {file.name}")



            for file in self.session_folder.glob("*_concat.txt"):

                try:

                    file.unlink()

                    print(f"Deleted temporary file: {file.name}")

                except OSError:

                    print(f"Could not delete file: {file.name}")

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
