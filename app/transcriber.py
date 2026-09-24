import gc
import logging
from typing import Protocol
import numpy as np
from app.config import MODEL_CACHE
from app.data_directory import MODEL_REPOSITORY
from app.audio import chunks

class AlignmentProvider(Protocol):
    def align(self, audio_path, segments): ...

class NoAlignment:
    def align(self, audio_path, segments):
        return segments

class TranscriptionProvider(Protocol):
    def transcribe(self, path, language, update): ...

def gpu_status():
    import subprocess
    info = {'gpu':'未偵測到 NVIDIA GPU', 'vram':'未知', 'cuda':False, 'model':'large-v3', 'compute':'float16'}
    try:
        row = subprocess.check_output(['nvidia-smi','--query-gpu=name,memory.total,memory.used','--format=csv,noheader'], timeout=10, text=True).strip().splitlines()[0].split(',')
        info.update(gpu=row[0].strip(), vram=row[1].strip(), used=row[2].strip())
        import ctranslate2
        info['cuda'] = 'float16' in ctranslate2.get_supported_compute_types('cuda')
    except Exception:
        pass
    return info

class FasterWhisperProvider:
    RECOVERY_SPEED = 1.5
    LOW_WORD_PROBABILITY = .45
    AUDIBLE_RMS = .003

    def __init__(self):
        self.model = None
        self.device = None
        self.last_recovery = {'attempted': 0, 'replaced': 0, 'speed_factor': self.RECOVERY_SPEED}

    @staticmethod
    def _stretch(audio, speed):
        """Return slowed samples. Whisper timestamps are divided by speed afterwards."""
        samples = np.asarray(audio, dtype=np.float32)
        if len(samples) < 2:
            return samples
        positions = np.linspace(0, len(samples) - 1, int(round(len(samples) * speed)))
        return np.interp(positions, np.arange(len(samples)), samples).astype(np.float32)

    @classmethod
    def _audible(cls, audio):
        samples = np.asarray(audio, dtype=np.float32)
        return len(samples) and float(np.sqrt(np.mean(samples ** 2))) >= cls.AUDIBLE_RMS

    @classmethod
    def _low_confidence(cls, segment):
        words = segment.get('words') or []
        return bool(words) and sum(w['probability'] for w in words) / len(words) < cls.LOW_WORD_PROBABILITY

    @classmethod
    def _uncovered_audible_windows(cls, audio, offset, segments, rate=16000):
        """Find one-second audible regions without any first-pass subtitle coverage."""
        uncovered = []
        for start_sample in range(0, len(audio), rate):
            end_sample = min(len(audio), start_sample + rate)
            start, end = offset + start_sample / rate, offset + end_sample / rate
            covered = any(segment['end'] > start and segment['start'] < end for segment in segments)
            if not covered and cls._audible(audio[start_sample:end_sample]):
                if uncovered and abs(uncovered[-1][1] - start) < .001:
                    uncovered[-1] = (uncovered[-1][0], end)
                else:
                    uncovered.append((start, end))
        return uncovered

    def _read_stream(self, audio, language, offset=0, scale=1, clamp=None):
        stream, info = self.model.transcribe(
            audio, language=language, beam_size=5, word_timestamps=True,
            vad_filter=True, condition_on_previous_text=True)
        segments = []
        for source in stream:
            text = (source.text or '').strip()
            if not text:
                continue
            start = offset + source.start / scale
            end = offset + source.end / scale
            if clamp:
                start = max(clamp[0], start)
                end = min(clamp[1], end)
            if end <= start:
                continue
            words = []
            for word in source.words or []:
                word_start = offset + word.start / scale
                word_end = offset + word.end / scale
                if not clamp or (word_end > clamp[0] and word_start < clamp[1]):
                    words.append({'word': word.word, 'start': max(clamp[0], word_start) if clamp else word_start,
                                  'end': min(clamp[1], word_end) if clamp else word_end,
                                  'probability': word.probability})
            segments.append({'start': start, 'end': end, 'text': source.text, 'words': words})
        return segments, info

    def _recover(self, audio, offset, language, window, update):
        start, end = window
        rate = 16000
        first = max(0, int((start - offset) * rate))
        last = min(len(audio), int((end - offset) * rate))
        source = np.asarray(audio)[first:last]
        if not self._audible(source):
            return []
        self.last_recovery['attempted'] += 1
        update(stage='正在以降速音訊重新辨識不清楚片段')
        slowed = self._stretch(source, self.RECOVERY_SPEED)
        recovered, _ = self._read_stream(slowed, language, start, self.RECOVERY_SPEED, window)
        if recovered:
            self.last_recovery['replaced'] += 1
        return recovered

    @staticmethod
    def _number(segments):
        """Sort and discard any recovery overlap left by timestamp rounding."""
        result = []
        for segment in sorted(segments, key=lambda item: (item['start'], item['end'])):
            if result and segment['start'] < result[-1]['end']:
                if segment['end'] <= result[-1]['end']:
                    continue
                segment = dict(segment, start=result[-1]['end'])
            segment['id'] = len(result)
            result.append(segment)
        return result

    def load(self, device, update):
        if self.model is not None and self.device == device:
            return
        self.model = None
        gc.collect()
        from faster_whisper import WhisperModel
        from huggingface_hub import snapshot_download
        repo = MODEL_REPOSITORY
        try:
            folder = snapshot_download(repo, cache_dir=str(MODEL_CACHE), local_files_only=True)
            from pathlib import Path
            if not (Path(folder)/'model.bin').is_file():
                raise FileNotFoundError('Incomplete model cache')
        except Exception:
            update(stage='正在下載 Whisper Large-v3（首次下載需要網路）')
            folder = snapshot_download(repo, cache_dir=str(MODEL_CACHE), allow_patterns=['*.json','*.bin','*.txt'])
        update(stage='正在載入 Whisper Large-v3')
        self.model = WhisperModel(folder, device=device, compute_type='float16' if device == 'cuda' else 'int8')
        self.device = device

    def transcribe(self, path, language, update):
        warning = None
        for device in ('cuda','cpu'):
            try:
                self.load(device, update)
                segments = []
                self.last_recovery = {'attempted': 0, 'replaced': 0, 'speed_factor': self.RECOVERY_SPEED}
                detected = language
                probabilities = []
                for offset, audio in chunks(path):
                    update(stage='正在辨識', device=device, compute='float16' if device=='cuda' else 'int8', warning=warning)
                    chunk_end = offset + len(audio) / 16000
                    original, info = self._read_stream(audio, detected, offset)
                    if detected is None and info.duration_after_vad > 0:
                        detected = info.language
                    probabilities.append(info.language_probability)
                    if not original and self._audible(audio):
                        original = self._recover(audio, offset, detected, (offset, chunk_end), update)
                    else:
                        recovered = []
                        for segment in original:
                            if self._low_confidence(segment):
                                replacement = self._recover(audio, offset, detected, (segment['start'], segment['end']), update)
                                recovered.extend(replacement or [segment])
                            else:
                                recovered.append(segment)
                        for window in self._uncovered_audible_windows(audio, offset, original):
                            recovered.extend(self._recover(audio, offset, detected, window, update))
                        original = recovered
                    segments.extend(original)
                    for segment in original:
                        update(processed=segment['end'])
                    update(processed=offset+len(audio)/16000)
                return self._number(segments), detected or 'unknown', sum(probabilities)/max(1,len(probabilities)), device
            except Exception as exc:
                logging.exception('Transcription failure on %s', device)
                gpu_error = any(s in str(exc).lower() for s in ('cuda','cudnn','cublas','out of memory','float16','driver'))
                if device == 'cuda' and gpu_error:
                    warning = 'CUDA 無法運作或 GPU 記憶體不足，已重新使用 CPU int8 辨識；速度會較慢。'
                    update(warning=warning, processed=0)
                    self.model = None
                    gc.collect()
                    continue
                raise
