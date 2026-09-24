import logging
import shutil
import threading
import time

from concurrent.futures import ThreadPoolExecutor

from app.config import WORK as DATA
from app.audio import extract, preview_audio, MediaError
from app.transcriber import FasterWhisperProvider, NoAlignment
from app.subtitle import subtitles, export


class JobManager:

    def __init__(self):

        self.lock = threading.RLock()

        self.pool = ThreadPoolExecutor(
            max_workers=1
        )

        self.provider = FasterWhisperProvider()

        self.jobs = {}


    def get(self, id):

        with self.lock:

            return (
                dict(self.jobs[id])
                if id in self.jobs
                else None
            )


    def update(
        self,
        id,
        **values
    ):

        with self.lock:

            self.jobs[id].update(
                values
            )

            directory = (
                DATA /
                'outputs' /
                id
            )

            directory.mkdir(
                parents=True,
                exist_ok=True
            )


    def submit(
        self,
        id,
        filename,
        extension,
        language,
        traditional,
        processing_mode='standard'
    ):

        with self.lock:

            if any(
                j['status'] in (
                    'queued',
                    'running'
                )
                for j in self.jobs.values()
            ):

                raise ValueError(
                    '請等目前辨識完成後，再開始下一次辨識。'
                )


            for previous in list(
                self.jobs
            ):

                self.delete(
                    previous
                )


            self.jobs[id] = dict(
                id=id,
                file=filename,
                extension=extension,
                status='queued',
                stage='等待辨識',
                processed=0,
                duration=0,
                warning=None,
                mode=processing_mode
            )


        self.update(id)


        self.pool.submit(
            self.run,
            id,
            language,
            traditional,
            processing_mode
        )


    def run(
        self,
        id,
        language,
        traditional,
        processing_mode
    ):

        start = time.monotonic()


        # ====================================================
        # Working Files
        # ====================================================

        wav = (
            DATA /
            'temp' /
            f'{id}.wav'
        )


        enhanced_wav = (
            DATA /
            'temp' /
            f'{id}_enhanced.wav'
        )


        output_directory = (
            DATA /
            'outputs' /
            id
        )


        output_directory.mkdir(
            parents=True,
            exist_ok=True
        )


        # ====================================================
        # Permanent Enhanced WAV
        #
        # 這份檔案會保留給前端下載
        # ====================================================

        downloadable_enhanced_wav = (
            output_directory /
            'audio_a.wav'
        )


        target_wav = wav


        try:

            # =================================================
            # Extract Audio
            # =================================================

            self.update(
                id,
                status='running',
                stage='正在準備音訊'
            )


            duration = extract(
                DATA /
                'uploads' /
                id,
                wav
            )


            self.update(
                id,
                duration=duration
            )


            # =================================================
            # Browser Preview
            # =================================================

            self.update(
                id,
                stage='正在建立相容播放音訊'
            )


            preview_audio(
                wav,
                output_directory /
                'preview.mp3'
            )


            # =================================================
            # Pipeline A
            # 人聲增強
            # =================================================

            if processing_mode in (
                'enhanced',
                'dual_track'
            ):

                self.update(
                    id,
                    stage='正在執行 Pipeline A (人聲增強)'
                )


                from app.pipeline_a import SpeechEnhancer


                enhancer = SpeechEnhancer()


                success = enhancer.enhance_audio(
                    str(wav),
                    str(enhanced_wav)
                )


                # =============================================
                # Enhancement Success
                # =============================================

                if success:

                    target_wav = enhanced_wav


                    # -----------------------------------------
                    # 保留一份永久可下載的 WAV
                    #
                    # temp/{id}_enhanced.wav
                    #       ↓
                    # outputs/{id}/audio_a.wav
                    # -----------------------------------------

                    shutil.copy2(
                        enhanced_wav,
                        downloadable_enhanced_wav
                    )


                    self.update(
                        id,
                        warning='已套用人聲增強 (Pipeline A)'
                    )


                    logging.info(
                        'Enhanced WAV saved for download: %s',
                        downloadable_enhanced_wav
                    )


                # =============================================
                # Enhancement Failed
                # =============================================

                else:

                    self.update(
                        id,
                        warning=(
                            '人聲增強失敗，'
                            '已自動降級至 Standard 模式 (Fallback)'
                        )
                    )


                    target_wav = wav


                    downloadable_enhanced_wav.unlink(
                        missing_ok=True
                    )


                    # -----------------------------------------
                    # Dual Track 若 A 失敗
                    # 不重複辨識兩次原始音訊
                    # -----------------------------------------

                    if (
                        processing_mode ==
                        'dual_track'
                    ):

                        processing_mode = (
                            'standard'
                        )


            # =================================================
            # Dual Track
            # =================================================

            if (
                processing_mode ==
                'dual_track'
            ):

                # =============================================
                # Whisper A
                # =============================================

                self.update(
                    id,
                    stage=(
                        '雙軌辨識: '
                        '正在處理增強音軌 (A)'
                    )
                )


                (
                    segs_a,
                    lang,
                    probability,
                    device
                ) = self.provider.transcribe(
                    enhanced_wav,
                    language,
                    lambda **v:
                        self.update(
                            id,
                            **v
                        )
                )


                segs_a = (
                    NoAlignment()
                    .align(
                        enhanced_wav,
                        segs_a
                    )
                )


                # =============================================
                # Whisper B
                # =============================================

                self.update(
                    id,
                    stage=(
                        '雙軌辨識: '
                        '正在處理原始音軌 (B)'
                    )
                )


                (
                    segs_b,
                    _,
                    _,
                    _
                ) = self.provider.transcribe(
                    wav,
                    language,
                    lambda **v:
                        self.update(
                            id,
                            **v
                        )
                )


                segs_b = (
                    NoAlignment()
                    .align(
                        wav,
                        segs_b
                    )
                )


                # =============================================
                # Compare
                # =============================================

                self.update(
                    id,
                    stage='正在比對雙軌語意差異'
                )


                from app.comparator import (
                    TranscriptComparator
                )


                comparator = (
                    TranscriptComparator()
                )


                segs = (
                    comparator
                    .align_and_compare(
                        segs_a,
                        segs_b
                    )
                )


                # =============================================
                # Primary Evidence = A
                # =============================================

                for seg in segs:

                    seg['text'] = (
                        seg.get(
                            'transcript_a',
                            seg.get(
                                'text',
                                ''
                            )
                        )
                    )


                    seg['start'] = (
                        seg.get(
                            'start_time',
                            seg.get(
                                'start',
                                0
                            )
                        )
                    )


                    seg['end'] = (
                        seg.get(
                            'end_time',
                            seg.get(
                                'end',
                                0
                            )
                        )
                    )


            # =================================================
            # Standard / Enhanced
            # =================================================

            else:

                self.update(
                    id,
                    stage='正在辨識語音'
                )


                (
                    segs,
                    lang,
                    probability,
                    device
                ) = self.provider.transcribe(
                    target_wav,
                    language,
                    lambda **v:
                        self.update(
                            id,
                            **v
                        )
                )


                segs = (
                    NoAlignment()
                    .align(
                        target_wav,
                        segs
                    )
                )


            # =================================================
            # Traditional Chinese
            # =================================================

            from opencc import OpenCC


            convert = (
                OpenCC(
                    's2twp'
                ).convert
                if traditional
                else lambda s: s
            )


            for seg in segs:

                seg['display_text'] = (
                    convert(
                        seg['text']
                    )
                )


            # =================================================
            # Result
            # =================================================

            result = dict(

                file=self.get(id)['file'],

                duration=duration,

                language=lang,

                language_probability=probability,

                model='large-v3',

                device=device,

                compute_type=(
                    'float16'
                    if device == 'cuda'
                    else 'int8'
                ),

                processing_seconds=(
                    time.monotonic() -
                    start
                ),

                segments=segs,

                subtitles=subtitles(
                    segs,
                    convert
                ),

                recovery=(
                    self.provider
                    .last_recovery
                ),

                conversion=(
                    's2twp'
                    if traditional
                    else None
                ),

                max_chunk_seconds=300,

                processing_mode=(
                    processing_mode
                ),

                enhanced_audio_available=(
                    downloadable_enhanced_wav
                    .is_file()
                ),

                language_probability_note=(
                    '各音訊區塊的偵測信心平均值；'
                    '指定語言時不代表自動偵測信心。'
                )
            )


            if duration > 0:

                result[
                    'real_time_factor'
                ] = (
                    result[
                        'processing_seconds'
                    ]
                    /
                    duration
                )

            else:

                result[
                    'real_time_factor'
                ] = 0


            # =================================================
            # Export Transcript
            # =================================================

            export(
                result,
                output_directory
            )


            # =================================================
            # Done
            # =================================================

            self.update(
                id,
                status='done',
                stage='辨識完成',
                processed=duration,
                processing_seconds=(
                    result[
                        'processing_seconds'
                    ]
                ),
                enhanced_audio_available=(
                    downloadable_enhanced_wav
                    .is_file()
                )
            )


        # ====================================================
        # Error
        # ====================================================

        except Exception as exc:

            logging.exception(
                'Job %s failed',
                id
            )


            if isinstance(
                exc,
                MediaError
            ):

                message = str(exc)


            elif (
                isinstance(
                    exc,
                    OSError
                )
                and
                exc.errno == 28
            ):

                message = (
                    '磁碟空間不足，'
                    '請釋放空間後重新上傳。'
                )


            else:

                message = (
                    '辨識失敗。'
                    '請確認模型下載網路、'
                    '磁碟空間與安裝狀態；'
                    '詳細原因已記錄於 logs。'
                )


            self.update(
                id,
                status='error',
                stage=message
            )


        # ====================================================
        # Cleanup
        # ====================================================

        finally:

            # 原始暫存 WAV 可以刪除
            wav.unlink(
                missing_ok=True
            )


            # temp 裡的增強 WAV 可以刪除
            # 因為成功時已複製到：
            #
            # outputs/{id}/audio_a.wav
            enhanced_wav.unlink(
                missing_ok=True
            )


    def delete(
        self,
        id
    ):

        with self.lock:

            if (
                self.jobs[id]['status']
                in (
                    'queued',
                    'running'
                )
            ):

                return False


            (
                DATA /
                'uploads' /
                id
            ).unlink(
                missing_ok=True
            )


            shutil.rmtree(
                DATA /
                'outputs' /
                id,
                ignore_errors=True
            )


            del self.jobs[id]


            return True


    def close(self):

        from app.cleanup import (
            remove_session
        )


        self.pool.shutdown(
            wait=True,
            cancel_futures=True
        )


        with self.lock:

            self.jobs.clear()


            remove_session(
                DATA
            )