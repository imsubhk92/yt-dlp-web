"""Isolated yt-dlp worker. stdout contains only application-owned JSON events.

The API keeps stdin open after the initial request. EOF means the parent exited;
the watchdog then terminates this whole process group, including FFmpeg.
"""

import contextlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from uuid import uuid4

from yt_dlp import YoutubeDL
from yt_dlp.postprocessor import PostProcessor
from yt_dlp.utils import DownloadError

from app.models import Entry, Inspection, source_url


def emit(event: dict):
    print(json.dumps(event, allow_nan=False), flush=True)


def safe_error(error: BaseException) -> str:
    """Return useful categories without leaking headers, cookies, paths or signed URLs."""
    message = str(error).lower()
    if "format" in message or "codec" in message:
        return "No compatible format is available for these output settings. Try Best quality."
    if any(s in message for s in ("sign in", "login", "cookie", "private", "age-restricted")):
        return "This content needs authentication. Check the configured local cookie file."
    if "live" in message or "upcoming" in message:
        return "Live and upcoming streams are not supported."
    if "drm" in message:
        return "This content is DRM protected and cannot be downloaded."
    if "space" in message or isinstance(error, OSError) and error.errno == 28:
        return "Not enough disk space to finish this download."
    if "unavailable" in message or "removed" in message or "404" in message:
        return "This video is unavailable or has been removed."
    if "unsupported" in message:
        return "yt-dlp could not find a supported video at this URL."
    return "The source could not be downloaded. Check access, network, and yt-dlp updates."


@contextlib.contextmanager
def private_cookies(cookie_file: str | None, directory: str | None = None):
    if not cookie_file:
        yield None
        return
    path = Path(cookie_file).expanduser()
    with path.open("rb") as source:
        if source.readline().strip() not in {b"# HTTP Cookie File", b"# Netscape HTTP Cookie File"}:
            raise ValueError("Invalid cookie file")
        source.seek(0)
        # mkstemp creates mode 0600. yt-dlp can safely update its own private jar.
        fd, name = tempfile.mkstemp(prefix="yt-dlp-web-cookies-", dir=directory)
        try:
            with os.fdopen(fd, "wb") as target:
                shutil.copyfileobj(source, target)
            yield name
        finally:
            Path(name).unlink(missing_ok=True)


class QuietLogger:
    def __init__(self):
        self.last_error = None

    def debug(self, message):
        pass

    info = debug
    warning = debug

    def error(self, message):
        self.last_error = message


def base_options(payload: dict, cookiefile: str | None) -> dict:
    return {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": QuietLogger(),
        "cachedir": False,
        "socket_timeout": 20,
        "retries": 3,
        "fragment_retries": 3,
        "js_runtimes": {"node": {"path": payload["node_path"]}},
        "cookiefile": cookiefile,
        "noplaylist": True,
    }


def normalize_inspection(
    info: dict, url: str, limit: int, authenticated: bool = False
) -> Inspection:
    playlist = info.get("_type") in {"playlist", "multi_video"}
    raw_entries = list(info.get("entries") or []) if playlist else [info]
    entries = []
    for position, raw in enumerate(raw_entries[:limit], 1):
        raw = raw or {}
        candidate = raw.get("webpage_url") or raw.get("url")
        if candidate and not candidate.startswith(("http://", "https://")):
            if raw.get("ie_key") == "Youtube" or raw.get("extractor_key") == "Youtube":
                candidate = f"https://www.youtube.com/watch?v={raw.get('id', candidate)}"
        try:
            candidate = source_url(candidate) if candidate else None
        except ValueError:
            candidate = None
        restricted = raw.get("availability") in {
            "private",
            "premium_only",
            "subscriber_only",
            "needs_auth",
            "unavailable",
        }
        unavailable_title = (raw.get("title") or "").strip("[]").lower() in {
            "private video",
            "deleted video",
            "unavailable video",
        }
        available = bool(candidate) and not unavailable_title and (authenticated or not restricted)
        entries.append(
            Entry(
                id=str(position),
                position=position,
                title=raw.get("title") or "Unavailable video",
                url=candidate,
                duration=raw.get("duration"),
                thumbnail=raw.get("thumbnail"),
                available=available,
            )
        )
    return Inspection(
        id=uuid4().hex,
        source_url=url,
        title=info.get("title") or "Untitled video",
        kind="playlist" if playlist else "video",
        entries=entries,
        truncated=len(raw_entries) > limit,
        limit=limit,
    )


def format_selector(preset: str, resolution: int | None):
    """Use yt-dlp's format ordering, enforce the cap on the shorter video edge."""

    def choose(context):
        formats = [f for f in context["formats"] if not f.get("has_drm")]
        if preset == "mp3":
            audio = [f for f in formats if f.get("acodec") != "none"]
            audio_only = [f for f in audio if f.get("vcodec") == "none"]
            if audio_only or audio:
                yield (audio_only or audio)[-1]
            return

        def suitable_video(f):
            if f.get("vcodec") == "none":
                return False
            dimensions = [f[k] for k in ("width", "height") if f.get(k)]
            if resolution and dimensions and min(dimensions) > resolution:
                return False
            if preset == "mp4":
                codec = f.get("vcodec")
                if codec and not re.match(r"^(avc1|h264)", codec):
                    return False
                if not codec and f.get("ext") != "mp4":
                    return False
                # Combined streams also need AAC; unknown direct-file codecs are probed later.
                acodec = f.get("acodec")
                if acodec and acodec != "none" and not re.match(r"^(mp4a|aac)", acodec):
                    return False
            return True

        videos = [f for f in formats if suitable_video(f)]
        if not videos:
            return
        audios = [f for f in formats if f.get("vcodec") == "none" and f.get("acodec") != "none"]
        if preset == "mp4":
            audios = [f for f in audios if re.match(r"^(mp4a|aac)", f.get("acodec") or "")]
        for video in reversed(videos):
            if video.get("acodec") != "none":
                yield video
                return
            if audios:
                audio = audios[-1]
                yield {
                    "format_id": f"{video['format_id']}+{audio['format_id']}",
                    "ext": "mp4" if preset == "mp4" else "mkv",
                    "requested_formats": [video, audio],
                    "protocol": f"{video['protocol']}+{audio['protocol']}",
                }
                return

    return choose


def reject_streams(info, *, incomplete):
    if info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming"}:
        return "Live and upcoming streams are not supported."
    return None


class FinalPath(PostProcessor):
    def run(self, info):
        self.final_path = info.get("filepath")
        return [], info


def finite(value):
    return (
        value if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0 else None
    )


def verify_media(path: Path, preset: str, resolution: int | None):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    streams = json.loads(result.stdout)["streams"]
    videos = [
        s
        for s in streams
        if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")
    ]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    if preset == "mp3":
        if not audios or any(s.get("codec_name") != "mp3" for s in audios):
            raise ValueError("No compatible audio format")
        return
    if not videos or not audios:
        raise ValueError("No compatible combined video and audio format")
    if resolution and any(min(s.get("width", 0), s.get("height", 0)) > resolution for s in videos):
        raise ValueError("No compatible resolution format")
    if preset == "mp4" and (
        any(s.get("codec_name") != "h264" for s in videos)
        or any(s.get("codec_name") != "aac" for s in audios)
    ):
        raise ValueError("No compatible MP4 codec")


def download(payload: dict, options: dict):
    directory = Path(payload["directory"]).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    last_event = 0

    def progress(data):
        nonlocal last_event
        if data["status"] == "finished":
            emit({"event": "processing"})
        elif data["status"] == "downloading" and time.monotonic() - last_event >= 0.2:
            last_event = time.monotonic()
            emit(
                {
                    "event": "progress",
                    "downloaded_bytes": finite(data.get("downloaded_bytes")) or 0,
                    "total_bytes": finite(
                        data.get("total_bytes") or data.get("total_bytes_estimate")
                    ),
                    "speed": finite(data.get("speed")),
                    "eta": finite(data.get("eta")),
                }
            )

    options.update(
        {
            "format": format_selector(payload["preset"], payload["resolution"]),
            "outtmpl": str(directory / "%(title).120B [%(id).40B].%(ext)s"),
            "restrictfilenames": True,
            "windowsfilenames": True,
            "merge_output_format": "mp4" if payload["preset"] == "mp4" else "mkv",
            "progress_hooks": [progress],
            "postprocessor_hooks": [lambda _: emit({"event": "processing"})],
            "match_filter": reject_streams,
            "break_on_reject": True,
            "overwrites": False,
        }
    )
    if payload["preset"] == "mp3":
        options["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
        ]
    elif payload["preset"] == "mp4":
        options["postprocessors"] = [{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}]
    with YoutubeDL(options) as ydl:
        final = FinalPath(ydl)
        final.final_path = None
        ydl.add_post_processor(final, when="after_move")
        info = ydl.extract_info(source_url(payload["url"]), download=True)
        if not final.final_path:
            raise DownloadError("Unavailable video or unsupported live stream")
        path = Path(final.final_path).resolve()
        if not path.is_relative_to(directory) or not path.is_file():
            raise ValueError("Invalid output file")
        verify_media(path, payload["preset"], payload["resolution"])
        emit({"event": "completed", "path": str(path), "title": info.get("title", path.stem)})


def parent_watchdog():
    # Raw reads avoid holding Python's buffered-stdin lock during interpreter shutdown.
    while os.read(sys.stdin.fileno(), 4096):
        pass
    os.killpg(os.getpgrp(), signal.SIGTERM)


def main():
    def stop(signum, frame):
        # Unwind the cookie context on SIGTERM as well as normal completion.
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, stop)
    payload = json.loads(sys.stdin.buffer.readline())
    threading.Thread(target=parent_watchdog, daemon=True).start()
    try:
        with private_cookies(
            payload.get("cookie_file"), payload.get("cookie_temp_dir")
        ) as cookiefile:
            options = base_options(payload, cookiefile)
            if payload["mode"] == "inspect":
                options.update(
                    {
                        "extract_flat": "in_playlist",
                        "skip_download": True,
                        "ignoreerrors": True,
                        "noplaylist": not payload["playlist"],
                        "playlistend": payload["limit"] + 1,
                    }
                )
                with YoutubeDL(options) as ydl:
                    info = ydl.extract_info(payload["url"], download=False)
                    if not info:
                        raise DownloadError(options["logger"].last_error or "Unavailable video")
                    inspection = normalize_inspection(
                        info, payload["url"], payload["limit"], authenticated=bool(cookiefile)
                    )
                    emit({"event": "inspection", "data": inspection.model_dump()})
            else:
                download(payload, options)
    except Exception as error:
        emit({"event": "error", "message": safe_error(error)})
        sys.exit(1)


if __name__ == "__main__":
    main()
