import json
import os
from pathlib import Path

import pytest

from app.config import Settings
from app.runtime import preflight
from app.worker import format_selector, normalize_inspection, private_cookies, safe_error


def video(id, height, codec="avc1.640028", audio="none", ext="mp4", **extra):
    return {
        "format_id": id,
        "width": height * 16 // 9,
        "height": height,
        "vcodec": codec,
        "acodec": audio,
        "ext": ext,
        "protocol": "https",
        **extra,
    }


def test_format_policy_and_vertical_resolution():
    audio = {"format_id": "audio", "vcodec": "none", "acodec": "mp4a.40.2", "protocol": "https"}
    h264 = video("1080-h264", 1080)
    vp9 = video("2160-vp9", 2160, codec="vp9", ext="webm")
    formats = [audio, h264, vp9]
    selected = list(format_selector("mp4", 1080)({"formats": formats}))[0]
    assert selected["format_id"] == "1080-h264+audio"
    assert selected["ext"] == "mp4"
    selected = list(format_selector("best", None)({"formats": formats}))[0]
    assert selected["format_id"] == "2160-vp9+audio"
    assert selected["ext"] == "mkv"
    assert list(format_selector("mp4", 720)({"formats": formats})) == []
    vertical = video("short", 1920, audio="mp4a.40.2", width=1080)
    assert list(format_selector("mp4", 1080)({"formats": [vertical]}))[0] == vertical


def test_audio_selector_and_drm_exclusion():
    audio = {"format_id": "opus", "vcodec": "none", "acodec": "opus"}
    formats = [audio, video("combined", 1080, audio="mp4a.40.2")]
    assert list(format_selector("mp3", None)({"formats": formats})) == [audio]
    drm = video("protected", 1080, has_drm=True)
    assert list(format_selector("best", None)({"formats": [drm]})) == []


def test_compatible_combined_stream_fallback_when_separate_audio_is_unavailable():
    combined = video("combined", 720, audio="mp4a.40.2")
    high_video_only = video("video-only", 1080)
    assert list(format_selector("mp4", 1080)({"formats": [combined, high_video_only]})) == [
        combined
    ]


def test_accessible_private_video_with_configured_cookie_file():
    info = {
        "title": "My private video",
        "availability": "private",
        "webpage_url": "https://example.com/private",
    }
    assert (
        normalize_inspection(info, info["webpage_url"], 500, authenticated=True)
        .entries[0]
        .available
    )


def test_cookie_isolation_permissions_and_cleanup(tmp_path):
    original = tmp_path / "private.txt"
    contents = (
        "# Netscape HTTP Cookie File\n.example.com\tTRUE\t/\tTRUE\t0\tsession\tsecret-value\n"
    )
    original.write_text(contents)
    with private_cookies(str(original)) as name:
        assert name != str(original)
        assert Path(name).read_text() == contents
        assert os.stat(name).st_mode & 0o777 == 0o600
        Path(name).write_text("modified jar")
    assert not Path(name).exists()
    assert original.read_text() == contents
    with pytest.raises(RuntimeError):
        with private_cookies(str(original)) as name:
            raise RuntimeError("cancelled")
    assert not Path(name).exists()
    assert "secret-value" not in safe_error(ValueError(contents))


def test_invalid_cookie_and_missing_dependencies(tmp_path, monkeypatch):
    cookie = tmp_path / "cookies.txt"
    cookie.write_text("not a cookie jar")
    with pytest.raises(ValueError, match="cookie"):
        with private_cookies(str(cookie)):
            pass
    monkeypatch.setattr("app.runtime.shutil.which", lambda _: None)
    health = preflight(Settings(cookie_file=cookie, _env_file=None), tmp_path)
    assert not health.ready
    assert not health.dependencies["cookies"]
    assert not health.dependencies["ffmpeg"]
    assert str(cookie) not in health.model_dump_json()


def test_playlist_limit_and_unavailable_entries():
    info = {
        "_type": "playlist",
        "title": "A playlist",
        "entries": [
            {"id": "one", "url": "one", "ie_key": "Youtube", "title": "One"},
            None,
            {"url": "https://example.com/3", "title": "Three"},
        ],
    }
    result = normalize_inspection(info, "https://example.com/list", 2)
    assert result.truncated
    assert len(result.entries) == 2
    assert result.entries[0].url == "https://www.youtube.com/watch?v=one"
    assert not result.entries[1].available
    assert json.loads(result.model_dump_json())["limit"] == 2
