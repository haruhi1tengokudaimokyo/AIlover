"""Real codec transport check using a synthetic tone, not a model-quality claim."""
import io
import json
import math
import struct
import subprocess
import wave
from imageio_ffmpeg import get_ffmpeg_exe

buffer = io.BytesIO()
with wave.open(buffer, 'wb') as wav:
    wav.setnchannels(1)
    wav.setsampwidth(2)
    wav.setframerate(32000)
    wav.writeframes(b''.join(struct.pack('<h', int(2000 * math.sin(2 * math.pi * 440 * i / 32000))) for i in range(6400)))
ffmpeg = get_ffmpeg_exe()
encoded = subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-i', 'pipe:0', '-f', 'mp3', 'pipe:1'],
                         input=buffer.getvalue(), capture_output=True, check=True, timeout=30).stdout
subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-i', 'pipe:0', '-f', 'null', '-'],
               input=encoded, capture_output=True, check=True, timeout=30)
print(json.dumps({'wav_to_mp3_and_decode': 'passed', 'mp3_bytes': len(encoded), 'source': 'synthetic codec fixture, not trained voice'}))
