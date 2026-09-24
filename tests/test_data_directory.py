import os
import shutil
from pathlib import Path

import pytest

from app.data_directory import (
    MODEL_CACHE_NAME,
    DataDirectoryError,
    ModelCacheError,
    ensure_desktop_model,
    resolve_model_cache,
    resolve_data_root,
    validate_model_cache,
)


def make_model_cache(root: Path, *, valid: bool = True) -> Path:
    cache = root / MODEL_CACHE_NAME
    snapshot = cache / "snapshots" / "revision-1"
    snapshot.mkdir(parents=True)
    (cache / "refs").mkdir()
    (cache / "refs" / "main").write_text("revision-1\n", encoding="utf-8")
    if valid:
        for name in ("config.json", "model.bin", "preprocessor_config.json", "tokenizer.json", "vocabulary.json"):
            (snapshot / name).write_bytes(b"model")
    return cache


def test_browser_default_is_project_root(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    # The resolver's browser default is based on the application source root.
    assert resolve_data_root(mode="browser", environ={}, create=False).name == "Local Whisper"


def test_browser_override(tmp_path):
    target = tmp_path / "資料 空間"
    assert resolve_data_root(mode="browser", environ={"WHISPER_DATA": str(target)}) == target.resolve()


def test_desktop_default_uses_local_app_data(tmp_path):
    target = tmp_path / "Local AppData"
    result = resolve_data_root(mode="desktop", environ={"LOCALAPPDATA": str(target)})
    assert result == (target / "LocalWhisper").resolve()


def test_desktop_override_wins(tmp_path):
    override = tmp_path / "自訂資料"
    result = resolve_data_root(
        mode="desktop",
        environ={"LOCALAPPDATA": str(tmp_path / "ignored"), "WHISPER_DATA": str(override)},
    )
    assert result == override.resolve()


def test_model_cache_is_independent_from_data_root(tmp_path):
    data = tmp_path / "runtime"
    model = tmp_path / "canonical-models"
    assert resolve_data_root(mode="browser", environ={"WHISPER_DATA": str(data)}) == data.resolve()
    assert resolve_model_cache(mode="browser", environ={"WHISPER_MODEL_CACHE": str(model)}) == model.resolve()
    assert data != model


def test_invalid_local_app_data_fails_closed(tmp_path):
    blocked = tmp_path / "blocked"
    blocked.write_text("file", encoding="utf-8")
    with pytest.raises(DataDirectoryError):
        resolve_data_root(mode="desktop", environ={"LOCALAPPDATA": str(blocked)})


def test_missing_local_app_data_fails_closed():
    with pytest.raises(DataDirectoryError):
        resolve_data_root(mode="desktop", environ={})


def test_valid_model_cache_is_discovered(tmp_path):
    cache = make_model_cache(tmp_path)
    assert validate_model_cache(cache) == cache / "snapshots" / "revision-1"


def test_partial_model_cache_is_invalid(tmp_path):
    cache = make_model_cache(tmp_path, valid=False)
    assert validate_model_cache(cache) is None


def test_model_copy_preserves_legacy_and_validates_destination(tmp_path, monkeypatch):
    legacy_root = tmp_path / "legacy" / "models"
    make_model_cache(legacy_root)
    data_root = tmp_path / "desktop"
    usage_type = type(shutil.disk_usage("."))
    monkeypatch.setattr("app.data_directory.shutil.disk_usage", lambda _path: usage_type(0, 0, 10 * 1024**3))
    result = ensure_desktop_model(data_root / "models", tmp_path / "legacy")
    assert result.is_dir()
    assert validate_model_cache(legacy_root / MODEL_CACHE_NAME) is not None
    assert validate_model_cache(data_root / "models" / MODEL_CACHE_NAME) is not None


def test_model_copy_fails_without_legacy(tmp_path, monkeypatch):
    usage_type = type(shutil.disk_usage("."))
    monkeypatch.setattr("app.data_directory.shutil.disk_usage", lambda _path: usage_type(0, 0, 10 * 1024**3))
    with pytest.raises(ModelCacheError, match="CACHE_MISSING_OR_INVALID"):
        ensure_desktop_model(tmp_path / "desktop" / "models", tmp_path / "legacy")


def test_model_copy_rejects_insufficient_space(tmp_path, monkeypatch):
    legacy_root = tmp_path / "legacy" / "models"
    make_model_cache(legacy_root)
    usage_type = type(shutil.disk_usage("."))
    monkeypatch.setattr("app.data_directory.shutil.disk_usage", lambda _path: usage_type(0, 0, 1))
    with pytest.raises(ModelCacheError, match="INSUFFICIENT_DISK_SPACE"):
        ensure_desktop_model(tmp_path / "desktop" / "models", tmp_path / "legacy")


def test_existing_destination_is_reused(tmp_path, monkeypatch):
    legacy_root = tmp_path / "legacy" / "models"
    make_model_cache(legacy_root)
    desktop_root = tmp_path / "desktop"
    make_model_cache(desktop_root / "models")
    monkeypatch.setattr(
        "app.data_directory.shutil.copytree",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("copy not expected")),
    )
    result = ensure_desktop_model(desktop_root / "models", tmp_path / "legacy")
    assert result == (desktop_root / "models" / MODEL_CACHE_NAME / "snapshots" / "revision-1").resolve()


def test_interrupted_copy_preserves_legacy_and_cleans_staging(tmp_path, monkeypatch):
    legacy_root = tmp_path / "legacy" / "models"
    make_model_cache(legacy_root)
    desktop_root = tmp_path / "desktop"
    usage_type = type(shutil.disk_usage("."))
    monkeypatch.setattr("app.data_directory.shutil.disk_usage", lambda _path: usage_type(0, 0, 10 * 1024**3))
    monkeypatch.setattr(
        "app.data_directory.shutil.copytree",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("interrupted")),
    )
    with pytest.raises(ModelCacheError, match="CACHE_COPY_FAILED"):
        ensure_desktop_model(desktop_root / "models", tmp_path / "legacy")
    assert validate_model_cache(legacy_root / MODEL_CACHE_NAME) is not None
    assert not list((desktop_root / "models").glob(".migration-*"))
