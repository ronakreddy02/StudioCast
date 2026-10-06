import ctypes
import subprocess
import json
from datetime import datetime
from pathlib import Path


class FFmpegWrapper:

    def __init__(self):
        self.ffmpeg_path = (
            Path(__file__).resolve().parent.parent
            / "vendor"
            / "ffmpeg"
            / "ffmpeg.exe"
        )
        self.processes = []
        self.session_folder = None
        self.session_start_time = None
        self.session_end_time = None

        self.record_screen = False
        self.record_webcam = False
        self.record_microphone = False
        self.record_system_audio = False
        
        # Pause and resume button handling 
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

    def resume_process(self,process):

        process_handle = self.get_process_handle(process)
        ntdl = ctypes.windll.ntdll
        resume_process = ntdl.NtResumeProcess

        resume_process(process_handle)

    def pause_recording(self):

        for record_screen in self.processes:
            self.suspend_process(record_screen)

    def resume_recording(self):
        
        for record_screen in self.processes:
            self.resume_process(record_screen)

    #screen commands

    def build_screen_command(self):

        output_file = self.session_folder / "screen.mkv"

        command = []
        command.append(str(self.ffmpeg_path))
        command.append("-y")
        command.append("-loglevel")
        command.append("error")

        #screen input
        command.append("-framerate")
        command.append("30")
        command.append("-draw_mouse")
        command.append("1")
        command.append("-rtbufsize")
        command.append("256M")
        command.append("-f")
        command.append("gdigrab")
        command.append("-i")
        command.append("desktop")

        #video codec

        command.append("-c:v")
        command.append("libx264")
        command.append("-pix_fmt")
        command.append("yuv420p")
        command.append("-b:v")
        command.append("2500k")

        command.append("-fps_mode")
        command.append("cfr")

        command.append(str(output_file))

        return command
    
    #webcam integration done 
    def build_webcam_command(self):

        output_file = self.session_folder / "webcam.mkv"

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

        #video codec
        command.append("-c:v")
        command.append("libx264")
        command.append("-pix_fmt")
        command.append("yuv420p")
        command.append("-b:v")
        command.append("2500k")
        command.append("-fps_mode")
        command.append("cfr")
        
        command.append(str(output_file))

        return command
    
    
    #microphone integration
    def build_microphone_command(self):

        output_file = self.session_folder / "microphone.mkv"

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

        #microphone audio
        command.append("-af")
        command.append("afftdn=nr=10:nf=-40,dynaudnorm=f=50:g=5")
        command.append("-c:a")
        command.append("aac")
        command.append("-b:a")
        command.append("192k")

        command.append(str(output_file))

        return command


        #System audio 
    def build_system_audio_command(self):

        output_file = self.session_folder / "system_audio.mkv"

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

        #system audio
        command.append("-c:a")
        command.append("aac")
        command.append("-b:a")
        command.append("192k")

        command.append(str(output_file))

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
                self.session_end_time
                - self.session_start_time
            ).total_seconds()
        }

        with open(session_file, "w") as file:
            json.dump(session_info, file, indent=4)


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
                f"[{webcam_index}:v]scale=200:150[webcam]"
            )

            filters.append(
                f"[{screen_index}:v][webcam]"
                "overlay=W-w-20:H-h-20[video]"
            )

        # audio
        if self.record_microphone and self.record_system_audio:

            filters.append(
                f"[{microphone_index}:a]"
                f"[{system_audio_index}:a]"
                "amix=inputs=2:duration=longest:normalize=0[audio]"
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
            command.append("veryfast")
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
                    record_system_audio):

        self.processes = []

        self.record_screen = record_screen
        self.record_webcam = record_webcam
        self.record_microphone = record_microphone
        self.record_system_audio = record_system_audio

        if not self.ffmpeg_path.exists():

            print("FFmpeg executable not found")
            print(f"Expected path: {self.ffmpeg_path}")

            return False

        #create recording session
        self.create_session_folder()

        #recording start timestamp
        self.session_start_time = datetime.now()

        commands = []

        if record_screen:

            command = self.build_screen_command()
            commands.append(command)

        if record_webcam:

            command = self.build_webcam_command()
            commands.append(command)

        if record_microphone:

            command = self.build_microphone_command()
            commands.append(command)

        if record_system_audio:

            command = self.build_system_audio_command()
            commands.append(command)

        if not commands:
            print("No recording source selected")
            return False

          #start all recording processes
        for command in commands:

            process_start_time = datetime.now()

            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=None,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

            self.processes.append(process)

            print(f"Saving to: {command[-1]}")
            print(command)
            print(f"Process start time: {process_start_time}")

        print("Recording started")
        print(f"Session start time: {self.session_start_time}")
        print(f"Session folder: {self.session_folder}")

        return True


    def stop_recording(self):

        if self.processes:

            for process in self.processes:
                if process.poll() is None:
                    process.stdin.write(b"q\n")
                    process.stdin.flush()

            for process in self.processes:
                process.wait()

            #recording end timestamp
            self.session_end_time = datetime.now()

            #save timestamp information
            self.save_session_info()

            #create final recording
            command = self.build_final_command()

            print("Creating final recording...")

            process = subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=None,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

            # Success failure handling
            if process.returncode == 0:
                print("Final recording created")
                print("Temporary MKV files kept for debugging")
                result = True

            else:
                print("Final recording failed")
                print("Temporary MKV files kept for recovery")
                result = False

            print(f"Final file: {self.session_folder / 'final.mp4'}")

            print(f"Session end time: {self.session_end_time}")

            duration = (
                self.session_end_time
                - self.session_start_time
            ).total_seconds()

            print(f"Recording duration: {duration:.2f} seconds")
            print(f"Recording saved to: {self.session_folder}")

            self.processes = []

            return result

        else:

            print("No active recording process")

            return False