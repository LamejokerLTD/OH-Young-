import os
import logging
import numpy as np
import soundfile as sf
import noisereduce as nr

logger = logging.getLogger(__name__)

class SpeechEnhancer:
    def __init__(self, model_type="noisereduce"):
        self.model_type = model_type

    def enhance_audio(self, input_wav: str, output_wav: str) -> bool:
        """
        使用 noisereduce 進行頻譜減法降噪，保護人聲並消除冷氣與環境底噪。
        """
        logger.info(f"開始執行 Pipeline A (光譜降噪): {input_wav}")
        try:
            # 讀取音訊
            data, rate = sf.read(input_wav)
            
            # 若為雙聲道（Stereo），轉為單聲道（Mono）以利降噪
            if len(data.shape) > 1:
                data = np.mean(data, axis=1)

            # 執行降噪處理
            reduced_noise = nr.reduce_noise(y=data, sr=rate, prop_decrease=0.8)

            # 寫入輸出的增強音檔
            sf.write(output_wav, reduced_noise, rate)
            
            return os.path.exists(output_wav)
        except Exception as e:
            logger.error(f"Pipeline A 降噪處理失敗: {e}")
            return False