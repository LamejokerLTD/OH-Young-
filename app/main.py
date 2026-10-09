import json
import logging
from logging.handlers import RotatingFileHandler
import mimetypes
import re
import shutil
import uuid
from urllib.parse import urlsplit

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import ROOT, DATA, WORK, EXTENSIONS, MAX_UPLOAD
from app.jobs import JobManager
from app.transcriber import gpu_status


# ============================================================
# VERSION
# ============================================================

BACKEND_VERSION = "LOCAL-WHISPER-20260924-R1"


# ============================================================
# Logging
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    handlers=[
        RotatingFileHandler(
            DATA / "logs" / "app.log",
            maxBytes=5_000_000,
            backupCount=3,
            encoding="utf-8",
        ),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)


# ============================================================
# Job Manager
# ============================================================

manager = JobManager()


# ============================================================
# Lifespan
# ============================================================

@asynccontextmanager
async def lifespan(app):

    logger.info("=" * 70)
    logger.info("歐陽｜本機逐字稿工具")
    logger.info("Backend Version: %s", BACKEND_VERSION)
    logger.info("Main File: %s", Path(__file__).resolve())
    logger.info("WORK: %s", WORK)
    logger.info("Hardware: %s", gpu_status())
    logger.info("=" * 70)

    from app.cleanup import start_watcher
    from app.prep.routes import startup as prep_startup

    watcher = start_watcher(WORK)
    logger.info("Prep startup: %s", prep_startup())

    try:
        yield
    finally:
        manager.close()


# ============================================================
# FastAPI
# ============================================================

app = FastAPI(
    title="歐陽｜本機逐字稿工具",
    lifespan=lifespan,
)


from app.prep.routes import install as install_prep

install_prep(app)


# ============================================================
# Trusted Host
# ============================================================

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=[
        "127.0.0.1",
        "localhost",
        "testserver",
    ],
)


# ============================================================
# Local Security
# ============================================================

def _is_allowed_local_origin(origin: str | None) -> bool:
    """Allow only the loopback HTTP origins used by the local launcher."""
    if origin is None:
        return True
    try:
        parsed = urlsplit(origin)
        return (
            parsed.scheme == "http"
            and parsed.hostname in {"127.0.0.1", "localhost"}
            and parsed.port is not None
            and 1 <= parsed.port <= 65535
            and not parsed.path
            and not parsed.query
            and not parsed.fragment
            and not parsed.username
            and not parsed.password
        )
    except ValueError:
        return False

@app.middleware("http")
async def local_security(request, call_next):

    if request.method not in (
        "GET",
        "HEAD",
        "OPTIONS",
    ):

        origin = request.headers.get("origin")
        local_request = request.headers.get("x-local-request")

        if not _is_allowed_local_origin(origin) or local_request != "1":

            from fastapi.responses import JSONResponse

            return JSONResponse(
                {
                    "detail": "拒絕非本機頁面的請求。"
                },
                status_code=403,
            )

    response = await call_next(request)

    response.headers["X-Content-Type-Options"] = "nosniff"

    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "media-src 'self' blob:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'"
    )

    return response


# ============================================================
# Static
# ============================================================

app.mount(
    "/static",
    StaticFiles(
        directory=ROOT / "static"
    ),
    name="static",
)


# ============================================================
# Homepage
# ============================================================

@app.get("/")
def index():

    return FileResponse(
        ROOT / "templates" / "index.html"
    )


# ============================================================
# System
# ============================================================

@app.get("/api/system")
def system():

    info = gpu_status()

    if isinstance(info, dict):
        info["backend_version"] = BACKEND_VERSION

    return info


# ============================================================
# DEBUG
# ============================================================

@app.get("/api/debug")
def debug():

    output_root = (WORK / "outputs").resolve()

    return {
        "status": "ok",
        "backend_version": BACKEND_VERSION,
        "main_file": str(Path(__file__).resolve()),
        "root": str(ROOT),
        "data": str(DATA),
        "work": str(WORK),
        "output_directory": str(output_root),
        "audio_download_route": "/api/jobs/{id}/download-audio",
        "audio_filename": "audio_a.wav",
        "audio_download_supported": True,
    }


# ============================================================
# Job History
# ============================================================

@app.get("/api/jobs")
def history():

    with manager.lock:

        return list(
            reversed(
                [
                    dict(j)
                    for j in manager.jobs.values()
                ]
            )
        )


# ============================================================
# Job Helper
# ============================================================

def job(id):

    if not re.fullmatch(
        r"[a-f0-9]{32}",
        id,
    ):
        raise HTTPException(
            404,
            "找不到工作。",
        )

    found = manager.get(id)

    if found is None:
        raise HTTPException(
            404,
            "找不到工作。",
        )

    return found


# ============================================================
# Upload
# ============================================================

@app.post(
    "/api/jobs",
    status_code=202,
)
async def upload(
    request: Request,
    filename: str,
    language: str = "zh",
    traditional: bool = True,
    model: str = "large-v3",
    processing_mode: str = "standard",
):

    # --------------------------------------------------------
    # Model / Language
    # --------------------------------------------------------

    if (
        model != "large-v3"
        or language not in (
            "zh",
            "en",
            "ja",
            "ko",
            "auto",
        )
    ):
        raise HTTPException(
            400,
            "不支援的模型或語言。",
        )


    # --------------------------------------------------------
    # Processing Mode
    # --------------------------------------------------------

    if processing_mode not in (
        "standard",
        "enhanced",
        "dual_track",
    ):
        raise HTTPException(
            400,
            "不支援的處理模式。",
        )


    # --------------------------------------------------------
    # Filename
    # --------------------------------------------------------

    safe = (
        filename
        .replace("\\", "/")
        .split("/")[-1]
    )

    extension = (
        Path(safe)
        .suffix
        .lower()
    )

    if (
        extension not in EXTENSIONS
        or not safe
        or any(
            ord(c) < 32
            for c in safe
        )
    ):
        raise HTTPException(
            415,
            "不支援的檔案類型。",
        )


    # --------------------------------------------------------
    # Content Type
    # --------------------------------------------------------

    content_type = (
        request.headers
        .get(
            "content-type",
            "",
        )
        .split(";")[0]
    )

    if not (
        content_type.startswith(
            (
                "audio/",
                "video/",
            )
        )
        or content_type == "application/octet-stream"
    ):
        raise HTTPException(
            415,
            "請上傳音訊或影片。",
        )


    # --------------------------------------------------------
    # Check Active Job
    # --------------------------------------------------------

    with manager.lock:

        if any(
            j["status"] in (
                "queued",
                "running",
            )
            for j in manager.jobs.values()
        ):
            raise HTTPException(
                409,
                "請等目前辨識完成後，再開始下一次辨識。",
            )


    # --------------------------------------------------------
    # Job ID
    # --------------------------------------------------------

    id = uuid.uuid4().hex

    path = (
        WORK /
        "uploads" /
        id
    )

    size = 0


    # --------------------------------------------------------
    # Save Upload
    # --------------------------------------------------------

    try:

        with path.open("wb") as output:

            async for chunk in request.stream():

                size += len(chunk)

                if size > MAX_UPLOAD:
                    raise HTTPException(
                        413,
                        "檔案超過 30 GB 限制。",
                    )

                if (
                    shutil.disk_usage(DATA).free
                    <
                    len(chunk) + 512 * 1024 ** 2
                ):
                    raise HTTPException(
                        507,
                        "磁碟空間不足，請先釋放空間。",
                    )

                output.write(chunk)


        if not size:
            raise HTTPException(
                400,
                "檔案是空的。",
            )


        try:

            manager.submit(
                id,
                safe,
                extension,
                None
                if language == "auto"
                else language,
                traditional,
                processing_mode,
            )

        except ValueError as exc:

            raise HTTPException(
                409,
                str(exc),
            ) from exc


    except BaseException:

        path.unlink(
            missing_ok=True
        )

        raise


    return {
        "id": id
    }


# ============================================================
# Job Status
# ============================================================

@app.get("/api/jobs/{id}")
def status(id: str):

    return job(id)


# ============================================================
# Result
# ============================================================

@app.get("/api/jobs/{id}/result")
def result(id: str):

    if job(id)["status"] != "done":
        raise HTTPException(
            409,
            "辨識尚未完成。",
        )

    path = (
        WORK /
        "outputs" /
        id /
        "transcript.json"
    )

    if not path.is_file():
        raise HTTPException(
            404,
            "找不到逐字稿結果。",
        )

    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


# ============================================================
# Transcript Download
#
# 注意：
# 這裡只處理逐字稿。
# WAV 已完全拆到 /download-audio
# ============================================================

@app.get(
    "/api/jobs/{id}/download/{format}"
)
def download_transcript(
    id: str,
    format: str,
):

    allowed_formats = (
        "srt",
        "txt",
        "timed.txt",
        "vtt",
        "json",
    )

    if format not in allowed_formats:

        logger.warning(
            "Unsupported transcript download format: %s",
            format,
        )

        raise HTTPException(
            404,
            "不支援的逐字稿下載格式。",
        )


    info = job(id)

    if info["status"] != "done":
        raise HTTPException(
            409,
            "辨識尚未完成。",
        )


    output_root = (
        WORK /
        "outputs" /
        id
    ).resolve()


    path = (
        output_root /
        f"transcript.{format}"
    ).resolve()


    if not path.is_relative_to(
        output_root
    ):
        raise HTTPException(
            403,
            "禁止存取此檔案。",
        )


    if not path.is_file():

        logger.warning(
            "Transcript file missing: %s",
            path,
        )

        raise HTTPException(
            404,
            "找不到逐字稿下載檔案。",
        )


    logger.info(
        "Transcript download: %s",
        path,
    )


    return FileResponse(
        path=path,
        filename=f"transcript.{format}",
        media_type="application/octet-stream",
    )


# ============================================================
# Enhanced Audio Download
#
# 完全獨立的音檔下載 API
#
# URL:
# /api/jobs/{id}/download-audio
#
# File:
# outputs/{id}/audio_a.wav
# ============================================================

@app.get(
    "/api/jobs/{id}/download-audio"
)
def download_audio(
    id: str,
):

    logger.info(
        "Audio download requested. Job ID: %s",
        id,
    )


    # --------------------------------------------------------
    # Job
    # --------------------------------------------------------

    info = job(id)


    if info["status"] != "done":

        raise HTTPException(
            409,
            "辨識尚未完成。",
        )


    # --------------------------------------------------------
    # Output Directory
    # --------------------------------------------------------

    output_root = (
        WORK /
        "outputs" /
        id
    ).resolve()


    # --------------------------------------------------------
    # audio_a.wav
    # --------------------------------------------------------

    path = (
        output_root /
        "audio_a.wav"
    ).resolve()


    logger.info(
        "Audio download path: %s",
        path,
    )


    # --------------------------------------------------------
    # Security
    # --------------------------------------------------------

    if not path.is_relative_to(
        output_root
    ):

        raise HTTPException(
            403,
            "禁止存取此檔案。",
        )


    # --------------------------------------------------------
    # Exists
    # --------------------------------------------------------

    if not path.is_file():

        logger.warning(
            "audio_a.wav does not exist: %s",
            path,
        )

        raise HTTPException(
            404,
            (
                "找不到增強音檔 audio_a.wav。"
                "下載功能已正常連線到新版後端，"
                "但人聲增強流程沒有產生 audio_a.wav。"
            ),
        )


    # --------------------------------------------------------
    # File Size
    # --------------------------------------------------------

    file_size = path.stat().st_size


    if file_size <= 0:

        raise HTTPException(
            500,
            "增強音檔存在，但檔案大小為 0 bytes。",
        )


    logger.info(
        "Sending enhanced audio: %s (%s bytes)",
        path,
        file_size,
    )


    # --------------------------------------------------------
    # Download
    # --------------------------------------------------------

    return FileResponse(
        path=path,
        filename="enhanced_audio.wav",
        media_type="audio/wav",
    )


# ============================================================
# Original Media
# ============================================================

@app.get("/api/jobs/{id}/media")
def media(id: str):

    info = job(id)

    path = (
        WORK /
        "uploads" /
        id
    )

    media_type = (
        mimetypes.guess_type(
            "file" +
            info["extension"]
        )[0]
        or
        "application/octet-stream"
    )

    return FileResponse(
        path,
        media_type=media_type,
    )


# ============================================================
# Preview
# ============================================================

@app.get("/api/jobs/{id}/preview")
def preview(id: str):

    job(id)

    path = (
        WORK /
        "outputs" /
        id /
        "preview.mp3"
    )

    if not path.is_file():
        raise HTTPException(
            404,
            "相容音訊尚未準備完成。",
        )

    return FileResponse(
        path,
        media_type="audio/mpeg",
    )


# ============================================================
# Delete
# ============================================================

@app.delete("/api/jobs/{id}")
def delete(id: str):

    job(id)

    if not manager.delete(id):

        raise HTTPException(
            409,
            "請等辨識完成後再刪除。",
        )

    return {
        "deleted": True
    }
