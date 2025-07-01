import os
import argparse
from pydub import AudioSegment
from pydub.silence import detect_nonsilent

class AudioProcessor:
    def __init__(self, input_file_path):
        self.input_file_path = input_file_path
        self.audio = AudioSegment.from_file(input_file_path)

    def split_audio_by_silence(self, min_silence_len, threshold):
        return detect_nonsilent(self.audio, min_silence_len=min_silence_len, silence_thresh=threshold)

    def save_audio(self, audio, output_path):
        audio.export(output_path, format="mp3")
        print(f"Saved audio to {output_path}")

    def save_timeline_to_text(self, timeline_data, output_path):
        with open(output_path, 'w') as file:
            file.write("[")
            for start, end in timeline_data:
                file.write(f"({start}, {end}), ")
            file.write("]")
        print(f"Saved timeline data to {output_path}")

    def is_fully_silent(self, min_silence_len=5000, threshold=-30):
        # Detect non-silent parts
        non_silent_segments = self.split_audio_by_silence(min_silence_len, threshold)
        # If the list of non-silent segments is empty, the audio is fully silent
        return not non_silent_segments
    
    def detect_dead_air(self, min_silence_len=3000, threshold=-30, skip_start_ms=10000, skip_end_ms=10000):
        """
        Detect dead air gaps in the audio
        
        Args:
            min_silence_len: Minimum duration of silence to be considered dead air (in milliseconds)
            threshold: Silence threshold in dBFS
            skip_start_ms: Skip this many milliseconds from the start
            skip_end_ms: Skip this many milliseconds from the end
            
        Returns:
            Dictionary containing:
                - gaps: List of gap dictionaries with start/end times and durations
                - total_gaps: Total number of gaps found
                - total_dead_air_ms: Total duration of dead air in milliseconds
                - evaluation_boundaries: Start and end times of evaluation window
        """
        # Get audio duration
        audio_duration_ms = len(self.audio)
        
        # Calculate evaluation boundaries
        eval_start_ms = skip_start_ms
        eval_end_ms = max(eval_start_ms, audio_duration_ms - skip_end_ms)
        
        # Detect non-silent parts
        non_silent_segments = self.split_audio_by_silence(min_silence_len, threshold)
        
        # Find gaps between non-silent segments
        gaps = []
        
        # Add initial gap if audio starts with silence after skip_start
        if non_silent_segments and non_silent_segments[0][0] > eval_start_ms:
            gap_start = eval_start_ms
            gap_end = non_silent_segments[0][0]
            gap_duration = gap_end - gap_start
            if gap_duration >= min_silence_len:
                gaps.append({
                    'start_ms': gap_start,
                    'end_ms': gap_end,
                    'duration_ms': gap_duration,
                    'start_time': gap_start / 1000.0,
                    'end_time': gap_end / 1000.0,
                    'duration': gap_duration / 1000.0
                })
        
        # Find gaps between consecutive non-silent segments
        for i in range(len(non_silent_segments) - 1):
            gap_start = non_silent_segments[i][1]
            gap_end = non_silent_segments[i + 1][0]
            
            # Only consider gaps within evaluation boundaries
            if gap_start >= eval_end_ms:
                break
            if gap_end <= eval_start_ms:
                continue
                
            # Clip to evaluation boundaries
            gap_start = max(gap_start, eval_start_ms)
            gap_end = min(gap_end, eval_end_ms)
            
            gap_duration = gap_end - gap_start
            if gap_duration >= min_silence_len:
                gaps.append({
                    'start_ms': gap_start,
                    'end_ms': gap_end,
                    'duration_ms': gap_duration,
                    'start_time': gap_start / 1000.0,
                    'end_time': gap_end / 1000.0,
                    'duration': gap_duration / 1000.0
                })
        
        # Add final gap if audio ends with silence before skip_end
        if non_silent_segments and non_silent_segments[-1][1] < eval_end_ms:
            gap_start = non_silent_segments[-1][1]
            gap_end = eval_end_ms
            gap_duration = gap_end - gap_start
            if gap_duration >= min_silence_len:
                gaps.append({
                    'start_ms': gap_start,
                    'end_ms': gap_end,
                    'duration_ms': gap_duration,
                    'start_time': gap_start / 1000.0,
                    'end_time': gap_end / 1000.0,
                    'duration': gap_duration / 1000.0
                })
        
        # Handle case where entire evaluation window is silent
        if not non_silent_segments and eval_end_ms > eval_start_ms:
            gap_duration = eval_end_ms - eval_start_ms
            if gap_duration >= min_silence_len:
                gaps.append({
                    'start_ms': eval_start_ms,
                    'end_ms': eval_end_ms,
                    'duration_ms': gap_duration,
                    'start_time': eval_start_ms / 1000.0,
                    'end_time': eval_end_ms / 1000.0,
                    'duration': gap_duration / 1000.0
                })
        
        # Calculate total dead air
        total_dead_air_ms = sum(gap['duration_ms'] for gap in gaps)
        
        return {
            'gaps': gaps,
            'total_gaps': len(gaps),
            'total_dead_air_ms': total_dead_air_ms,
            'total_dead_air_seconds': total_dead_air_ms / 1000.0,
            'evaluation_boundaries': {
                'start_ms': eval_start_ms,
                'end_ms': eval_end_ms,
                'start_time': eval_start_ms / 1000.0,
                'end_time': eval_end_ms / 1000.0
            },
            'audio_duration_ms': audio_duration_ms,
            'audio_duration_seconds': audio_duration_ms / 1000.0,
            'parameters': {
                'min_silence_len_ms': min_silence_len,
                'threshold_dbfs': threshold,
                'skip_start_ms': skip_start_ms,
                'skip_end_ms': skip_end_ms
            }
        }

    def process_audio(self, min_silence_len=5000, threshold=-30, output_folder='output'):
        try:
            print("Processing audio...")
            non_silent_parts = self.split_audio_by_silence(min_silence_len, threshold)
            audio_silent = AudioSegment.empty()
            audio_non_silent = AudioSegment.empty()
            silent_parts_times = []
            non_silent_parts_times = []

            for i, (start_time, end_time) in enumerate(non_silent_parts):
                audio_non_silent += self.audio[start_time:end_time]
                non_silent_parts_times.append((start_time, end_time))

                if i == 0:
                    silent_start_time = 0
                else:
                    silent_start_time = non_silent_parts[i - 1][1]
                silent_end_time = start_time

                audio_silent += self.audio[silent_start_time:silent_end_time]
                silent_parts_times.append((silent_start_time, silent_end_time))

            # Create the output folder if it doesn't exist
            os.makedirs(output_folder, exist_ok=True)

            output_silent_path = os.path.join(output_folder, 'interview_silent.mp3')
            output_non_silent_path = os.path.join(output_folder, 'interview_non_silent.mp3')
            silent_txt_path = os.path.join(output_folder, 'silent_parts.txt')
            non_silent_txt_path = os.path.join(output_folder, 'non_silent_parts.txt')

            self.save_audio(audio_silent, output_silent_path)
            self.save_audio(audio_non_silent, output_non_silent_path)
            self.save_timeline_to_text(silent_parts_times, silent_txt_path)
            self.save_timeline_to_text(non_silent_parts_times, non_silent_txt_path)

            print("Audio processing completed.")
            print("Audio with silent parts saved to:", output_silent_path)
            print("Audio with non-silent parts saved to:", output_non_silent_path)
            print("Silent parts timeline saved to:", silent_txt_path)
            print("Non-silent parts timeline saved to:", non_silent_txt_path)

        except Exception as e:
            print("An error occurred:", str(e))

def main():
    parser = argparse.ArgumentParser(description="Audio processing script")
    parser.add_argument("input_file", help="Input audio file path")
    parser.add_argument("--output_folder", default="output", help="Output folder path")
    parser.add_argument("--min_silence_len", type=int, default=5000, help="Minimum silence length (in milliseconds)")
    parser.add_argument("--threshold", type=int, default=-30, help="Silence threshold in dBFS")

    args = parser.parse_args()

    audio_processor = AudioProcessor(args.input_file)
    audio_processor.process_audio(min_silence_len=args.min_silence_len, threshold=args.threshold, output_folder=args.output_folder)

if __name__ == "__main__":
    main()
