"""Resolve and validate Local Whisper's runtime data directory."""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path


class DataDirectoryError(RuntimeError):
    """Raised when the selected runtime data directory is unusable."""


class ModelCacheError(RuntimeError):
    """Raised when a known Whisper cache cannot be safely reused."""


MODEL_CACHE_NAME = "models--Systran--faster-whisper-large-v3"
MODEL_REPOSITORY = "Systran/faster-whisper-large-v3"
MODEL_REQUIRED_FILES = (
    "config.json",
    "model.bin",
    "preprocessor_config.json",
    "tokenizer.json",
    "vocabulary.json",
)


def _local_app_data(environ: dict[str, str]) -> Path:
    value = environ.get("LOCALAPPDATA")
    if not value:
        raise DataDirectoryError("LOCALAPPDATA is not available")
    return Path(value) / "LocalWhisper"


def _validate(path: Path, *, create: bool) -> Path:
    try:
        resolved = path.expanduser().resolve()
        if create:
            resolved.mkdir(parents=True, exist_ok=True)
        if not resolved.is_dir():
            raise DataDirectoryError(f"Data directory is not a directory: {resolved}")
        probe = resolved / f".local-whisper-write-test-{uuid.uuid4().hex}"
        probe.touch(exist_ok=False)
        probe.unlink()
        return resolved
    except DataDirectoryError:
        raise
    except (OSError, RuntimeError) as exc:
        raise DataDirectoryError(f"Data directory is not writable: {path}") from exc


def resolve_data_root(*, mode: str = "browser", environ=None, create: bool = True) -> Path:
    """Resolve the data root without importing any backend module.

    Browser mode preserves the historical project-root default. Desktop mode
    uses LocalAppData unless WHISPER_DATA explicitly overrides it.
    """
    if mode not in {"browser", "desktop"}:
        raise ValueError(f"Unsupported data directory mode: {mode}")
    env = os.environ if environ is None else environ
    override = env.get("WHISPER_DATA")
    selected = Path(override) if override else (
        _local_app_data(env) if mode == "desktop" else Path(__file__).resolve().parent.parent
    )
    return _validate(selected, create=create)


def resolve_model_cache(*, mode: str = "browser", environ=None, create: bool = True) -> Path:
    """Resolve the canonical Hugging Face cache independently from DATA."""
    if mode not in {"browser", "desktop"}:
        raise ValueError(f"Unsupported model cache mode: {mode}")
    env = os.environ if environ is None else environ
    override = env.get("WHISPER_MODEL_CACHE")
    selected = Path(override) if override else _local_app_data(env) / "models"
    return _validate(selected, create=create)


def validate_model_cache(cache_root: Path) -> Path | None:
    """Return the validated snapshot directory, or None for an incomplete cache."""
    cache_root = Path(cache_root).resolve()
    refs = cache_root / "refs" / "main"
    snapshots = cache_root / "snapshots"
    if not refs.is_file() or not snapshots.is_dir():
        return None
    revision = refs.read_text(encoding="utf-8").strip()
    if not revision or Path(revision).name != revision:
        return None
    snapshot = (snapshots / revision).resolve()
    if not snapshot.is_dir() or not snapshot.is_relative_to(snapshots):
        return None
    for name in MODEL_REQUIRED_FILES:
        file_path = snapshot / name
        if not file_path.is_file() or file_path.stat().st_size == 0:
            return None
    return snapshot


def ensure_desktop_model(model_cache_root: Path, project_root: Path) -> Path:
    """Reuse or safely copy the known legacy model cache for Desktop mode."""
    model_cache_root = Path(model_cache_root).resolve()
    project_root = Path(project_root).resolve()
    destination = model_cache_root / MODEL_CACHE_NAME
    existing = validate_model_cache(destination)
    if existing is not None:
        return existing

    legacy = project_root / "models" / MODEL_CACHE_NAME
    legacy_snapshot = validate_model_cache(legacy)
    if legacy_snapshot is None:
        raise ModelCacheError("CACHE_MISSING_OR_INVALID")

    source_files = [path for path in legacy.rglob("*") if path.is_file()]
    source_bytes = sum(path.stat().st_size for path in source_files)
    safety_margin = max(512 * 1024**2, source_bytes // 10)
    try:
        free_bytes = shutil.disk_usage(model_cache_root).free
    except OSError as exc:
        raise ModelCacheError("DISK_SPACE_UNAVAILABLE") from exc
    if free_bytes < source_bytes + safety_margin:
        raise ModelCacheError("INSUFFICIENT_DISK_SPACE")

    models_root = model_cache_root
    models_root.mkdir(parents=True, exist_ok=True)
    staging = models_root / f".migration-{uuid.uuid4().hex}"
    staged_cache = staging / MODEL_CACHE_NAME
    try:
        shutil.copytree(legacy, staged_cache)
        if validate_model_cache(staged_cache) is None:
            raise ModelCacheError("CACHE_COPY_VALIDATION_FAILED")
        backup = None
        if destination.exists():
            backup = models_root / f".invalid-{uuid.uuid4().hex}"
            os.replace(destination, backup)
        try:
            os.replace(staged_cache, destination)
        except Exception:
            if backup is not None and not destination.exists():
                os.replace(backup, destination)
            raise
        validated = validate_model_cache(destination)
        if validated is None:
            raise ModelCacheError("CACHE_ACTIVATION_FAILED")
        return validated
    except ModelCacheError:
        raise
    except (OSError, shutil.Error) as exc:
        raise ModelCacheError("CACHE_COPY_FAILED") from exc
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
