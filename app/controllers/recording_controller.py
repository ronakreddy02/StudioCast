from media.ffmpeg import FFmpegWrapper


class RecordingController:

    def __init__(self):
        self.is_recording = False

        self.wrapper = FFmpegWrapper()

    def start(self,record_screen,record_webcam,record_microphone,record_system_audio):
        result = self.wrapper.start_recording(record_screen, 
                                     record_webcam, 
                                     record_microphone, 
                                     record_system_audio)

        if result is False:
            print("Recording could not be started")
            return False

        self.is_recording = True
        print("Recording started ")

        return True
    
    def stop(self):
        print("STOP BUTTON CLICKED")
        self.is_recording = False
        print("Recording stopped")

        result = self.wrapper.stop_recording()

        return result

    def pause_recording(self):
        self.wrapper.pause_recording()

    def resume_recording(self):
        self.wrapper.resume_recording()
