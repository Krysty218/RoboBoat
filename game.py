import pygame
import pygame.mixer
import numpy as np
import pyaudio
import wave
import threading
import time
import aubio
import math
from queue import Queue

# Initialize pygame
pygame.init()
pygame.mixer.init()

# Screen setup
WIDTH, HEIGHT = 800, 600
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Pygame Karaoke")

# Colors
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
YELLOW = (255, 255, 0)

# Fonts
font_large = pygame.font.SysFont("Arial", 48)
font_medium = pygame.font.SysFont("Arial", 36)
font_small = pygame.font.SysFont("Arial", 24)

# Button class for UI elements
class Button:
    def __init__(self, x, y, width, height, text, color, hover_color):
        self.rect = pygame.Rect(x, y, width, height)
        self.text = text
        self.color = color
        self.hover_color = hover_color
        self.is_hovered = False
        
    def draw(self):
        # Draw button
        color = self.hover_color if self.is_hovered else self.color
        pygame.draw.rect(screen, color, self.rect)
        pygame.draw.rect(screen, WHITE, self.rect, 2)  # White border
        
        # Draw text
        text_surf = font_medium.render(self.text, True, WHITE)
        text_rect = text_surf.get_rect(center=self.rect.center)
        screen.blit(text_surf, text_rect)
        
    def check_hover(self, mouse_pos):
        self.is_hovered = self.rect.collidepoint(mouse_pos)
        return self.is_hovered
        
    def is_clicked(self, mouse_pos, mouse_clicked):
        return self.rect.collidepoint(mouse_pos) and mouse_clicked

class Song:
    def __init__(self, title, audio_file, lyrics_data):
        self.title = title
        self.audio_file = audio_file
        self.lyrics_data = lyrics_data  # List of (timestamp, lyric, pitch) tuples
        self.duration = 0  # Will be set when loading

    def load(self):
        pygame.mixer.music.load(self.audio_file)
        # Get duration (this is a simplified approach)
        sound = pygame.mixer.Sound(self.audio_file)
        self.duration = sound.get_length()

class PitchDetector:
    def __init__(self, sample_rate=44100, buffer_size=1024):
        self.sample_rate = sample_rate
        self.buffer_size = buffer_size
        
        # Audio input setup
        self.p = pyaudio.PyAudio()
        self.stream = self.p.open(
            format=pyaudio.paFloat32,
            channels=1,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=self.buffer_size
        )
        
        # Pitch detection with aubio
        self.pitch_o = aubio.pitch("yin", self.buffer_size, self.buffer_size, self.sample_rate)
        self.pitch_o.set_unit("Hz")
        self.pitch_o.set_silence(-40)
        
        self.pitch_history = []
        self.is_recording = False
        self.audio_queue = Queue()
        
    def start_recording(self):
        self.is_recording = True
        self.recording_thread = threading.Thread(target=self._record)
        self.recording_thread.daemon = True
        self.recording_thread.start()
        
    def stop_recording(self):
        self.is_recording = False
        if hasattr(self, 'recording_thread'):
            self.recording_thread.join(timeout=1)
        
    def _record(self):
        while self.is_recording:
            try:
                audio_data = self.stream.read(self.buffer_size, exception_on_overflow=False)
                self.audio_queue.put(audio_data)
            except Exception as e:
                print(f"Error recording audio: {e}")
                break
    
    def get_current_pitch(self):
        if self.audio_queue.empty():
            return 0
            
        audio_data = self.audio_queue.get()
        signal = np.frombuffer(audio_data, dtype=np.float32)
        
        pitch = self.pitch_o(signal)[0]
        confidence = self.pitch_o.get_confidence()
        
        if confidence < 0.8:  # Adjust this threshold as needed
            pitch = 0
            
        self.pitch_history.append(pitch)
        if len(self.pitch_history) > 10:  # Keep only recent history
            self.pitch_history.pop(0)
            
        return pitch

    def get_smoothed_pitch(self):
        if not self.pitch_history:
            return 0
        # Filter out zeros and calculate average
        valid_pitches = [p for p in self.pitch_history if p > 0]
        if not valid_pitches:
            return 0
        return sum(valid_pitches) / len(valid_pitches)
        
    def cleanup(self):
        self.stream.stop_stream()
        self.stream.close()
        self.p.terminate()

class KaraokeGame:
    def __init__(self):
        self.songs = []
        self.current_song = None
        self.game_state = "menu"  # menu, playing, results
        self.score = 0
        self.max_score = 0
        self.current_lyric_index = 0
        self.pitch_detector = PitchDetector()
        self.pitch_history = []
        self.expected_pitch_history = []
        self.clock = pygame.time.Clock()
        
        # Create stop button
        self.stop_button = Button(WIDTH - 120, 20, 100, 40, "STOP", RED, (255, 100, 100))
        
        # Track loop status and time
        self.is_looping = True
        self.loop_counter = 0
        self.loop_time = 0
        
    def add_song(self, song):
        self.songs.append(song)
        
    def select_song(self, index):
        if 0 <= index < len(self.songs):
            self.current_song = self.songs[index]
            self.current_song.load()
            
    def start_game(self):
        if self.current_song:
            self.game_state = "playing"
            self.score = 0
            self.max_score = 0
            self.current_lyric_index = 0
            self.pitch_history = []
            self.expected_pitch_history = []
            self.start_time = time.time()
            
            # Set music to loop infinitely
            self.is_looping = True
            self.loop_counter = 0
            self.loop_time = 0
            
            # Start playing with loop enabled (-1 means infinite loops)
            pygame.mixer.music.play(-1)
            self.pitch_detector.start_recording()
            
    def stop_game(self):
        pygame.mixer.music.stop()
        self.pitch_detector.stop_recording()
        self.is_looping = False
        self.game_state = "results"
            
    def update(self):
        if self.game_state == "playing":
            # Calculate the current time position within the song, accounting for loops
            current_total_time = time.time() - self.start_time
            
            # Check if we've looped
            if self.current_song.duration > 0:  # Avoid division by zero
                self.loop_counter = int(current_total_time / self.current_song.duration)
                self.loop_time = current_total_time % self.current_song.duration
            else:
                self.loop_time = current_total_time
            
            # This is the time position within the current loop
            current_time = self.loop_time
            
            # If we looped, reset the lyric index to start
            if self.loop_counter > 0 and current_time < 0.1:  # Small threshold to detect start of loop
                self.current_lyric_index = 0
                
            # Update current lyric
            while (self.current_lyric_index < len(self.current_song.lyrics_data) and 
                   current_time >= self.current_song.lyrics_data[self.current_lyric_index][0]):
                
                # Process current lyric
                _, _, expected_pitch = self.current_song.lyrics_data[self.current_lyric_index]
                current_pitch = self.pitch_detector.get_smoothed_pitch()
                
                self.pitch_history.append(current_pitch)
                self.expected_pitch_history.append(expected_pitch)
                
                # Calculate score for this note
                if expected_pitch > 0 and current_pitch > 0:
                    # Convert Hz to musical scale for better scoring
                    expected_note = 12 * math.log2(expected_pitch/440) + 69  # MIDI note number
                    current_note = 12 * math.log2(current_pitch/440) + 69    # MIDI note number
                    
                    # Calculate score based on how close we are (within 1 semitone is perfect)
                    note_diff = abs(expected_note - current_note)
                    if note_diff < 1:
                        note_score = 100
                    elif note_diff < 2:
                        note_score = 75
                    elif note_diff < 3:
                        note_score = 50
                    elif note_diff < 4:
                        note_score = 25
                    else:
                        note_score = 10
                        
                    self.score += note_score
                    self.max_score += 100
                    
                self.current_lyric_index += 1
                
                # If we've reached the end of the lyrics, but music is still looping,
                # reset the lyric index for the next loop
                if self.current_lyric_index >= len(self.current_song.lyrics_data):
                    self.current_lyric_index = 0
    
    def draw(self):
        screen.fill(BLACK)
        
        if self.game_state == "menu":
            self._draw_menu()
        elif self.game_state == "playing":
            self._draw_game()
        elif self.game_state == "results":
            self._draw_results()
            
        pygame.display.flip()
        
    def _draw_menu(self):
        title = font_large.render("KARAOKE GAME", True, WHITE)
        screen.blit(title, (WIDTH//2 - title.get_width()//2, 50))
        
        # Draw song list
        for i, song in enumerate(self.songs):
            color = YELLOW if self.current_song == song else WHITE
            song_text = font_medium.render(f"{i+1}. {song.title}", True, color)
            screen.blit(song_text, (WIDTH//2 - song_text.get_width()//2, 150 + i*50))
            
        # Instructions
        instructions = [
            "Press number keys to select a song",
            "Press SPACE to start singing",
            "Click STOP button or press 'S' to stop",
            "Press ESC to quit"
        ]
        
        for i, instruction in enumerate(instructions):
            text = font_small.render(instruction, True, WHITE)
            screen.blit(text, (WIDTH//2 - text.get_width()//2, HEIGHT - 170 + i*30))
    
    def _draw_game(self):
        # Draw song title
        title = font_medium.render(self.current_song.title, True, WHITE)
        screen.blit(title, (20, 20))
        
        # Draw loop counter
        loop_text = font_small.render(f"Loop: {self.loop_counter + 1}", True, WHITE)
        screen.blit(loop_text, (20, 60))
        
        # Draw current time within the loop
        time_text = font_small.render(f"Time: {self.loop_time:.1f}s / {self.current_song.duration:.1f}s", True, WHITE)
        screen.blit(time_text, (20, 90))
        
        # Draw score
        if self.max_score > 0:
            score_percent = (self.score / self.max_score) * 100
        else:
            score_percent = 0
        score_text = font_medium.render(f"Score: {score_percent:.1f}%", True, WHITE)
        screen.blit(score_text, (WIDTH//2 - score_text.get_width()//2, 20))
        
        # Draw stop button
        self.stop_button.draw()
        
        # Draw current and upcoming lyrics
        current_lyric = ""
        next_lyric = ""
        
        # Find current and next lyrics based on current time within the loop
        for i in range(len(self.current_song.lyrics_data)):
            timestamp, lyric, _ = self.current_song.lyrics_data[i]
            if timestamp <= self.loop_time and (i == len(self.current_song.lyrics_data) - 1 or 
                                             self.current_song.lyrics_data[i+1][0] > self.loop_time):
                current_lyric = lyric
                if i < len(self.current_song.lyrics_data) - 1:
                    next_lyric = self.current_song.lyrics_data[i+1][1]
                else:
                    # If we're at the last lyric, the next one is the first (for loop)
                    next_lyric = self.current_song.lyrics_data[0][1]
                break
                
        # Draw current lyric
        current_lyric_text = font_large.render(current_lyric, True, YELLOW)
        screen.blit(current_lyric_text, (WIDTH//2 - current_lyric_text.get_width()//2, HEIGHT//2 - 50))
        
        # Draw next lyric
        next_lyric_text = font_medium.render(next_lyric, True, WHITE)
        screen.blit(next_lyric_text, (WIDTH//2 - next_lyric_text.get_width()//2, HEIGHT//2 + 30))
        
        # Draw pitch visualization
        current_pitch = self.pitch_detector.get_smoothed_pitch()
        
        # Find expected pitch for the current time
        expected_pitch = 0
        for i in range(len(self.current_song.lyrics_data)):
            timestamp, _, pitch = self.current_song.lyrics_data[i]
            if timestamp <= self.loop_time and (i == len(self.current_song.lyrics_data) - 1 or 
                                             self.current_song.lyrics_data[i+1][0] > self.loop_time):
                expected_pitch = pitch
                break
        
        # Draw pitch meter
        self._draw_pitch_meter(current_pitch, expected_pitch)
        
        # Draw singing guide (last few seconds of pitch history)
        self._draw_pitch_guide()
    
    def _draw_pitch_meter(self, current_pitch, expected_pitch):
        # Convert pitch to position
        def pitch_to_y(pitch):
            if pitch <= 0:
                return HEIGHT - 100  # Bottom position for silence
            
            # Log scale for better visualization
            min_pitch = 50   # Hz
            max_pitch = 1000  # Hz
            
            # Clamp pitch to our range
            pitch = max(min_pitch, min(max_pitch, pitch))
            
            # Convert to log scale and map to screen position
            log_min = math.log10(min_pitch)
            log_max = math.log10(max_pitch)
            log_pitch = math.log10(pitch)
            
            normalized = (log_pitch - log_min) / (log_max - log_min)
            return HEIGHT - 100 - normalized * (HEIGHT - 200)
        
        # Draw pitch scale
        pygame.draw.rect(screen, WHITE, (WIDTH - 50, 100, 30, HEIGHT - 200), 1)
        
        # Draw expected pitch marker
        if expected_pitch > 0:
            expected_y = pitch_to_y(expected_pitch)
            pygame.draw.rect(screen, GREEN, (WIDTH - 60, expected_y - 5, 50, 10))
        
        # Draw current pitch marker
        if current_pitch > 0:
            current_y = pitch_to_y(current_pitch)
            pygame.draw.circle(screen, RED, (WIDTH - 35, current_y), 10)
    
    def _draw_pitch_guide(self):
        # Draw a scrolling pitch history/guide
        if not self.pitch_history:
            return
            
        guide_width = WIDTH - 100
        guide_height = 200
        guide_x = 50
        guide_y = HEIGHT - 300
        
        # Draw background
        pygame.draw.rect(screen, (50, 50, 50), (guide_x, guide_y, guide_width, guide_height))
        
        # Draw grid lines
        for i in range(1, 10):
            line_y = guide_y + i * (guide_height / 10)
            pygame.draw.line(screen, (100, 100, 100), (guide_x, line_y), (guide_x + guide_width, line_y))
            
        # Only show the last 100 points or less
        history_len = min(100, len(self.pitch_history))
        if history_len < 2:
            return
            
        # Draw expected pitch line
        expected_points = []
        for i in range(history_len):
            idx = len(self.expected_pitch_history) - history_len + i
            if idx >= 0 and idx < len(self.expected_pitch_history):
                expected_pitch = self.expected_pitch_history[idx]
                if expected_pitch > 0:
                    # Convert pitch to position (simplified)
                    normalized = min(1.0, max(0.0, (math.log(expected_pitch) - math.log(100)) / (math.log(1000) - math.log(100))))
                    point_x = guide_x + (i / history_len) * guide_width
                    point_y = guide_y + guide_height - normalized * guide_height
                    expected_points.append((point_x, point_y))
        
        if len(expected_points) >= 2:
            pygame.draw.lines(screen, GREEN, False, expected_points, 2)
        
        # Draw actual pitch line
        points = []
        for i in range(history_len):
            idx = len(self.pitch_history) - history_len + i
            pitch = self.pitch_history[idx]
            if pitch > 0:
                # Convert pitch to position (simplified)
                normalized = min(1.0, max(0.0, (math.log(pitch) - math.log(100)) / (math.log(1000) - math.log(100))))
                point_x = guide_x + (i / history_len) * guide_width
                point_y = guide_y + guide_height - normalized * guide_height
                points.append((point_x, point_y))
                
        if len(points) >= 2:
            pygame.draw.lines(screen, RED, False, points, 2)
    
    def _draw_results(self):
        # Draw final score
        title = font_large.render("Game Over!", True, WHITE)
        screen.blit(title, (WIDTH//2 - title.get_width()//2, 100))
        
        if self.max_score > 0:
            score_percent = (self.score / self.max_score) * 100
        else:
            score_percent = 0
            
        score_text = font_large.render(f"Final Score: {score_percent:.1f}%", True, WHITE)
        screen.blit(score_text, (WIDTH//2 - score_text.get_width()//2, 200))
        
        # Show loop info
        loops_text = font_medium.render(f"Completed Loops: {self.loop_counter}", True, WHITE)
        screen.blit(loops_text, (WIDTH//2 - loops_text.get_width()//2, 250))
        
        # Grade based on score
        grade = "F"
        if score_percent >= 95:
            grade = "S"
        elif score_percent >= 90:
            grade = "A+"
        elif score_percent >= 80:
            grade = "A"
        elif score_percent >= 70:
            grade = "B"
        elif score_percent >= 60:
            grade = "C"
        elif score_percent >= 50:
            grade = "D"
        
        grade_text = font_large.render(f"Grade: {grade}", True, YELLOW)
        screen.blit(grade_text, (WIDTH//2 - grade_text.get_width()//2, 300))
        
        # Instructions
        instructions = font_small.render("Press SPACE to return to menu", True, WHITE)
        screen.blit(instructions, (WIDTH//2 - instructions.get_width()//2, HEIGHT - 100))
    
    def handle_event(self, event):
        if event.type == pygame.QUIT:
            return False
            
        # Check mouse position for button hover
        if event.type == pygame.MOUSEMOTION:
            if self.game_state == "playing":
                self.stop_button.check_hover(event.pos)
                
        # Check mouse click for button press
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:  # Left mouse button
                if self.game_state == "playing" and self.stop_button.is_clicked(event.pos, True):
                    self.stop_game()
            
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                if self.game_state == "playing":
                    self.stop_game()
                else:
                    return False
                    
            elif event.key == pygame.K_s:  # Additional key for stopping
                if self.game_state == "playing":
                    self.stop_game()
                    
            elif self.game_state == "menu":
                # Song selection
                if pygame.K_1 <= event.key <= pygame.K_9:
                    song_idx = event.key - pygame.K_1
                    if song_idx < len(self.songs):
                        self.select_song(song_idx)
                        
                elif event.key == pygame.K_SPACE:
                    if self.current_song:
                        self.start_game()
                        
            elif self.game_state == "results":
                if event.key == pygame.K_SPACE:
                    self.game_state = "menu"
                    
        return True
        
    def run(self):
        running = True
        while running:
            self.clock.tick(60)  # 60 FPS
            
            for event in pygame.event.get():
                running = self.handle_event(event)
                if not running:
                    break
                    
            self.update()
            self.draw()
            
        self.pitch_detector.cleanup()
        pygame.quit()

# Example song data
# In a real game, this would be loaded from files
example_lyrics = [
    (1.0, "Example lyrics 1", 220.0),  # Timestamp, Lyrics, Expected pitch (Hz)
    (3.5, "Example lyrics 2", 246.9),
    (5.0, "Example lyrics 3", 261.6),
    (8.0, "Example lyrics 4", 293.7),
    (10.0, "Example lyrics 5", 329.6),
    (12.0, "Example lyrics 6", 349.2),
    (14.0, "Example lyrics 7", 392.0),
]

# Main function
def main():
    game = KaraokeGame()
    
    # Add songs
    song1 = Song("Example Song", "a.mp3", example_lyrics)
    game.add_song(song1)
    
    # More songs would be added here
    
    # Start with first song selected
    if game.songs:
        game.select_song(0)
    
    # Run the game
    game.run()

if __name__ == "__main__":
    main()