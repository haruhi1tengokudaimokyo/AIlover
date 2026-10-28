"""Measured waveform checks for mono, little-endian signed 16-bit PCM.

No trimming, denoising, transcription, source separation or voice/music overlap
detection. These numeric checks do not establish that a clip has one speaker,
is free from background music, or is correctly transcribed.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import struct
import unicodedata

import numpy as np


def audio_metrics(pcm_bytes: bytes, sample_rate: int = 32000) -> dict:
    """Measure raw mono s16le PCM. Endpoint ratios are signed amplitudes.

    Frame RMS uses consecutive 10 ms windows, including the final short window.
    Start/end RMS each use up to a complete 10 ms of actual samples. Empty PCM
    returns zeros and its real SHA256; incomplete int16 input is rejected.
    """
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate <= 0:
        raise ValueError('sample_rate must be a positive integer')
    if not isinstance(pcm_bytes, (bytes, bytearray, memoryview)):
        raise TypeError('pcm_bytes must contain raw s16le bytes')
    raw = bytes(pcm_bytes)
    if len(raw) % 2:
        raise ValueError('s16le PCM has an incomplete final sample')
    pcm = np.frombuffer(raw, dtype='<i2')
    count = len(pcm)
    frame_samples = max(1, round(sample_rate / 100))
    values = pcm.astype(np.float64)
    duration = count / sample_rate
    if count:
        squared = values * values
        starts = np.arange(0, count, frame_samples)
        lengths = np.minimum(frame_samples, count - starts)
        frame_rms = np.sqrt(np.add.reduceat(squared, starts) / lengths)
        nonquiet = np.flatnonzero(frame_rms >= 100)
        leading = min(int(nonquiet[0]) * frame_samples, count) / sample_rate if len(nonquiet) else duration
        trailing = (count - min((int(nonquiet[-1]) + 1) * frame_samples, count)) / sample_rate if len(nonquiet) else duration
        metrics = {
            'rms': float(np.sqrt(np.mean(squared))),
            'peak_ratio': float(np.max(np.abs(values)) / 32768),
            'clipped_sample_ratio': float(np.count_nonzero(np.abs(values) >= 32760) / count),
            'active_frame_ratio': float(np.count_nonzero(frame_rms >= 200) / len(frame_rms)),
            'leading_silence_seconds': float(leading),
            'trailing_silence_seconds': float(trailing),
            'start_10ms_rms': float(np.sqrt(np.mean(squared[:frame_samples]))),
            'end_10ms_rms': float(np.sqrt(np.mean(squared[-frame_samples:]))),
            'start_sample_ratio': float(values[0] / 32768),
            'end_sample_ratio': float(values[-1] / 32768),
        }
    else:
        metrics = {name: 0.0 for name in (
            'rms', 'peak_ratio', 'clipped_sample_ratio', 'active_frame_ratio',
            'leading_silence_seconds', 'trailing_silence_seconds', 'start_10ms_rms',
            'end_10ms_rms', 'start_sample_ratio', 'end_sample_ratio')}
    return {'duration_seconds': duration, 'samples': count, 'sample_rate': sample_rate,
            'frame_samples': frame_samples, 'frame_seconds': frame_samples / sample_rate,
            **metrics, 'pcm_sha256': hashlib.sha256(raw).hexdigest(),
            'isolation_music_overlap_status': 'not_measured_requires_listening'}


_KATAKANA_TO_HIRAGANA = str.maketrans({chr(n): chr(n - 0x60) for n in range(0x30a1, 0x30f7)})
_NONVERBAL = re.compile(
    r'(?:はぁ+[っ]?|ふ[うぅ]+[っ]?|あぁ+[っ]?|ん{2,}[っ]?|んっ|'
    r'(?:む|ぶ)?ちゅ[うぅっ]*|[Zz]{2,})+'
)


def _text_without_punctuation(text: str) -> str:
    normalized = unicodedata.normalize('NFKC', text).translate(_KATAKANA_TO_HIRAGANA)
    return ''.join(char for char in normalized
                   if not char.isspace() and unicodedata.category(char)[0] not in {'P', 'S', 'Z', 'C'}
                   and char != 'ー')


def quality_reasons(metrics: dict, ja_text: str | None) -> list[str]:
    """Return hard exclusion codes using the project's documented thresholds.

    Text check recognizes only complete nonverbal strings; ordinary short
    Japanese utterances such as はい/うん/いいよ/そうだね remain usable.
    """
    reasons = []
    if metrics['duration_seconds'] < 1.0:
        reasons.append('duration_too_short')
    if metrics['duration_seconds'] > 20.0:
        reasons.append('duration_too_long')
    if metrics['rms'] < 100:
        reasons.append('rms_below_100')
    if metrics['active_frame_ratio'] < .05:
        reasons.append('active_frame_ratio_below_0_05')
    if metrics['clipped_sample_ratio'] > .005:
        reasons.append('clipped_sample_ratio_above_0_005')
    if not isinstance(ja_text, str) or not ja_text.strip():
        reasons.append('empty_text')
    else:
        compact = _text_without_punctuation(ja_text)
        if not compact:
            reasons.append('punctuation_only_text')
        elif _NONVERBAL.fullmatch(compact):
            reasons.append('nonverbal_utterance')
    return reasons


def quality_flags(metrics: dict) -> list[str]:
    """Return review flags. High peak alone is not a clipping exclusion."""
    flags = []
    if ((metrics['start_10ms_rms'] > 800 and abs(metrics['start_sample_ratio']) > .05)
            or (metrics['end_10ms_rms'] > 800 and abs(metrics['end_sample_ratio']) > .05)):
        flags.append('potential_cut_boundary')
    if metrics['leading_silence_seconds'] > 1.5 or metrics['trailing_silence_seconds'] > 1.5:
        flags.append('excess_silence')
    if metrics['peak_ratio'] > .98:
        flags.append('high_peak')
    return flags


def opus_metadata(path: str | Path) -> dict:
    """Read one Ogg Opus stream's header duration without audio decoding.

    Granule positions use a 48 kHz clock. Input sample-rate is only a hint.
    CRC/audio corruption, channel content, audibility and language are untested.
    """
    raw = Path(path).read_bytes()
    offset, serials, last_granule, header, pages = 0, set(), None, None, 0
    while offset < len(raw):
        if raw[offset:offset + 4] != b'OggS' or offset + 27 > len(raw):
            raise ValueError('invalid_ogg_page')
        begin = offset + 27 + raw[offset + 26]
        if begin > len(raw):
            raise ValueError('truncated_ogg_lacing_table')
        end = begin + sum(raw[offset + 27:begin])
        if end > len(raw):
            raise ValueError('truncated_ogg_page')
        if raw[begin:end].startswith(b'OpusHead'):
            if end - begin < 19:
                raise ValueError('truncated_opus_head')
            header = raw[begin:begin + 19]
        granule = struct.unpack_from('<Q', raw, offset + 6)[0]
        if granule != 0xffffffffffffffff:
            last_granule = granule
        serials.add(struct.unpack_from('<I', raw, offset + 14)[0])
        offset = end
        pages += 1
    if header is None or last_granule is None or len(serials) != 1:
        raise ValueError('missing_opus_header_or_chained_stream')
    pre_skip = struct.unpack_from('<H', header, 10)[0]
    if last_granule < pre_skip:
        raise ValueError('invalid_opus_granule')
    return {'codec': 'opus', 'channels': header[9], 'decoded_sample_rate': 48000,
            'input_sample_rate_hint': struct.unpack_from('<I', header, 12)[0], 'pre_skip': pre_skip,
            'duration_seconds': (last_granule - pre_skip) / 48000, 'ogg_pages': pages,
            'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'audio_decoding_performed': False}
