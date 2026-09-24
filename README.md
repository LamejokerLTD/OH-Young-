# 歐陽｜本機逐字稿工具

Windows 本機音訊／影片逐字稿工作站。FastAPI + faster-whisper Large-v3，預設 CUDA float16；無法使用 CUDA 時才重新以 CPU int8 辨識，頁面會警告。沒有使用 LLM 改寫、補字或摘要。

## 開始使用

1. 第一次雙擊 `install.bat`。會尋找 Python；沒有時從 python.org 下載並驗證簽章、安裝 Python 3.12，建立 `.venv` 並安裝套件與 NVIDIA CUDA 函式庫。FFmpeg 使用 imageio-ffmpeg 隨套件提供的 Windows 執行檔，已有 PATH 版本時優先使用。
2. 雙擊桌面或開始功能表的「Local Whisper」捷徑，瀏覽器自動開啟 http://127.0.0.1:8000 。工具在背景執行，不會顯示命令視窗。直接執行 `start.bat` 時才會保留啟動視窗，方便查看錯誤。
3. 拖入媒體、選語言，按「開始辨識」。模型第一次自動下載約 3 GB，保存於 `models/`。首次需要網路，模型完整快取後可離線運作；音訊不會上傳第三方。
4. 完成後可以搜尋、點時間碼播放、複製文字，下載 SRT、TXT、帶時間碼 TXT、VTT、JSON。

建議預留至少 15 GB 安裝空間，另加原始影片與解碼音訊空間。單檔上限 30 GB，一次處理一個工作。音訊暫存約每小時 115 MB，相容播放 MP3 約每小時 43 MB。

## 資料與原文

- JSON `segments[].text` 和 `segments[].words` 保留 Whisper 原始文字、原始秒數、字詞信心；`display_text` 是 OpenCC s2twp 台灣用語轉換結果。
- `subtitles` 是獨立字幕整理層，只分組，不生成文字；TXT、SRT、VTT 使用這層的顯示文字。要取原始辨識文字請讀 JSON segments。
- OpenCC s2twp 包括字形及台灣詞彙轉換，沒有 LLM 潤稿。取消繁體選項即不轉換。
- 語音切分依停頓、字詞時間、標點及長度；不自行估計新的字詞時間。
- 每次最多解碼五分鐘，接近邊界時優先找低音量切點，並將時間加回原檔位置。極長連續語音可能在邊界被截斷；Whisper 上下文在區塊間重設。各區塊內保留 condition_on_previous_text=True。
- word timestamps 是 Whisper 模型估計，不能視為人工校準的逐字對齊。未使用 WhisperX；已保留 TranscriptionProvider／AlignmentProvider 介面。
- 自動語言模式以第一個有語音的區塊偵測結果作為後續語言；指定中文時仍可辨識中英夾雜，但效果依音訊而異。language_probability 是區塊信心平均值，指定語言時不是獨立偵測準確率。
- 每個區塊先以原速辨識。若整個有明顯聲音的區塊沒有文字，或字詞平均信心偏低，工具會把該段以 1.5 倍長度降速後再辨識，成功才取代原結果；原始影片時間碼會同步換算回來。這可減少漏字幕，但背景音、多人重疊、極不清楚的錄音仍無法保證完全正確。JSON 的 `recovery` 欄位會記錄重試次數。

## 檔案配置

| 路徑 | 用途 |
|---|---|
| app/main.py | 串流上傳、工作 API、下載與本機來源限制 |
| app/jobs.py | 單一背景 worker、當次狀態、錯誤與清理 |
| app/transcriber.py | Large-v3、GPU fallback、provider 介面 |
| app/audio.py | FFmpeg 容器驗證、抽音軌、分塊與相容播放器音訊 |
| app/subtitle.py | 保留原文的字幕分組、五種輸出 |
| app/diagnostics.py | GPU／CUDA DLL／FFmpeg 檢查 |
| templates/、static/ | 繁體中文介面、進度、搜尋、播放器同步 |
| launcher.py、start.bat | 本機啟動與開啟瀏覽器 |
| scripts/install.ps1、install.bat | 一鍵安裝 |
| tests/ | 匯出、時間碼、FFmpeg 與 API 安全測試 |
| models/ | 固定模型快取 |
| temp/session-*/ | 當次上傳副本、逐字稿與播放音訊；自動清除 |
| logs/app.log | 完整錯誤紀錄，5 MB 輪替，保留三份 |

介面只有上傳、辨識、結果三個步驟，不保留工作紀錄。當次結果可播放、搜尋及下載；接受下一次辨識後，上一份上傳副本及結果會自動清除。關閉工具的啟動視窗也會清除當次檔案（Windows 背景清理程序會在服務結束後執行）；只關閉瀏覽器分頁不會停止工具。需要保留請先下載。原始來源檔案、已下載的副本與模型快取不受影響。突然斷電時清理程序無法執行，可能需要手動清理 temp/session-* 暫存資料夾。

## 安全與容器驗證

只綁定 127.0.0.1，不開放區域網路。上傳採串流、限制大小與磁碟預留空間；副檔名與 MIME 初步檢查後，背景 FFmpeg 以允許的實際 demuxer 驗證容器、完整抽出音轨。損壞／偽造媒體會成為失敗工作，不進入 Whisper。檔名不參與磁碟路徑；下載只使用工作 ID 和固定格式白名單。外部網站無法發送帶本機自訂標頭的寫入請求。所有外部程式使用參數陣列，沒有 shell=True。

## 故障排除

- **CUDA 不可用**：更新 NVIDIA 驅動後重新 install.bat。安裝套件包含 cuBLAS 12 與 cuDNN 9；啟動的硬體偵測不是完整模型推論驗證，實際工作顯示裝置才是最終結果。
- **GPU 記憶體不足**：關閉其他 GPU 應用；程式會嘗試以 CPU int8 從頭辨識。實測電腦與需求中的硬體可能不同，介面顯示真正偵測結果。
- **模型下載失敗**：確認可存取 Hugging Face，保留 models 快取後重試；不必刪除已下載資料。
- **無法播放影片**：瀏覽器並非支援全部編碼，自動切換 MP3 相容音訊。仍可依時間碼檢查聲音；畫面請用本機影片播放器。
- **磁碟不足／檔案損壞／沒有音軌**：頁面顯示可讀錯誤，詳細紀錄在 logs。
- **重複啟動**：若歐陽已在執行，再次雙擊 start.bat 會直接開啟既有網頁。只有其他程式占用 8000 埠時才會提示衝突。
- **長時間靜音／背景音樂**：VAD 可減少誤辨識，但模型仍可能漏字、重複或幻覺；重要逐字稿請配合播放器人工確認。

## 開發驗證

執行 `.venv\Scripts\python.exe -m pytest -q`。測試使用合成資料和隔離暫存資料夾，不會執行模型下載。GPU 實測另執行 `.venv\Scripts\python.exe -m app.diagnostics`；實際 Large-v3 推論需透過上傳音檔確認。

本次完整實測結果、真正的 GPU 型號及尚未測試的項目請見 [VERIFICATION.md](VERIFICATION.md)。安裝採用 `requirements-lock.txt` 鎖定已實測的完整版本。

faster-whisper 官方安裝與 CUDA 說明：https://github.com/SYSTRAN/faster-whisper


## 介面改版

編輯式橘色介面的功能對照、響應式設計與測試紀錄，請見 [UI_REDESIGN.md](UI_REDESIGN.md)。
