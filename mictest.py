import sounddevice as sd
import numpy as np
import scipy.io.wavfile as wav

DURATION = 10  # seconds
SAMPLERATE = 22050  # Hz
FILENAME = "test_recording.wav"

print("🎙️ Recording for 10 seconds...")

# Record audio
recording = sd.rec(int(DURATION * SAMPLERATE), samplerate=SAMPLERATE, channels=1, dtype='float32')
sd.wait()

# Normalize to int16 for saving
recording_int16 = np.int16(recording * 32767)

# Save to WAV
wav.write(FILENAME, SAMPLERATE, recording_int16)

print(f"✅ Recording saved as '{FILENAME}'")
