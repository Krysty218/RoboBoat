import librosa
import numpy as np
import sounddevice as sd
import queue
import threading
import time
from scipy.spatial.distance import cdist

# ==== SETTINGS ====
REF_PATH = "ref.wav"                   # Reference song file (wav format)
CHUNK_DURATION = 2.0                   # Seconds per audio chunk
SAMPLE_RATE = 22050                    # Audio sample rate

# ==== LOAD REFERENCE ====
ref_audio, sr = librosa.load(REF_PATH, sr=SAMPLE_RATE)
ref_pitch = librosa.yin(ref_audio, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('C7'))

# ==== AUDIO QUEUE SETUP ====
audio_queue = queue.Queue()

def audio_callback(indata, frames, time_info, status):
    audio_queue.put(indata.copy().flatten())

def start_stream():
    stream = sd.InputStream(callback=audio_callback,
                            channels=1,
                            samplerate=SAMPLE_RATE,
                            blocksize=int(SAMPLE_RATE * CHUNK_DURATION))
    stream.start()
    return stream

# ==== AUDIO PITCH ANALYSIS ====
def get_pitch_seq(y):
    try:
        pitch = librosa.yin(y, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('C7'))
        return pitch
    except Exception as e:
        print("Pitch error:", e)
        return np.zeros(len(y))

# ==== SCORE CALCULATION ====
def compute_score(ref, user):
    ref = ref[:len(user)]
    ref = ref.reshape(-1, 1)
    user = user.reshape(-1, 1)
    dist = cdist(ref, user, 'euclidean')
    try:
        dtw_dist = librosa.sequence.dtw(C=dist)[0][-1, -1]
        score = 100 * np.exp(-dtw_dist / 1000)  # Convert distance to score
        return int(score)
    except Exception as e:
        print("DTW error:", e)
        return 0

# ==== AUDIO PROCESSING LOOP ====
def process_loop():
    print("🎤 Start singing...")
    while True:
        if not audio_queue.empty():
            chunk = audio_queue.get()
            y = chunk.astype(np.float32)
            pitch_seq = get_pitch_seq(y)
            ref_window = ref_pitch[:len(pitch_seq)]
            score = compute_score(ref_window, pitch_seq)
            print(f"Score: {score}")
        time.sleep(CHUNK_DURATION)

# ==== MAIN START ====
stream = start_stream()
process_thread = threading.Thread(target=process_loop)
process_thread.start()
