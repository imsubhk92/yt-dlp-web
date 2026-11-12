import asyncio
import functools
import http.server
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from app.config import Settings
from app.runtime import WorkerRunner


@pytest.fixture(scope="module")
def media_server(tmp_path_factory):
    directory = tmp_path_factory.mktemp("local-media")
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x6554d8:s=320x180:r=15:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(directory / "sample.mp4"),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(directory / "sample.mp4"),
            "-c",
            "copy",
            "-f",
            "dash",
            "-adaptation_sets",
            "id=0,streams=v id=1,streams=a",
            str(directory / "manifest.mpd"),
        ],
        check=True,
        capture_output=True,
    )

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            if "slow=1" in self.path:
                time.sleep(5)
            try:
                super().do_GET()
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    handler = functools.partial(QuietHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/sample.mp4"
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.mark.integration
@pytest.mark.parametrize(
    "preset,manifest",
    [
        ("mp4", False),
        ("best", False),
        ("mp3", False),
        ("mp4", True),
        ("best", True),
    ],
)
async def test_real_local_download_and_conversion(media_server, tmp_path, preset, manifest):
    settings = Settings(data_dir=tmp_path, _env_file=None)
    runner = WorkerRunner(settings)
    events = []
    url = media_server.replace("sample.mp4", "manifest.mpd") if manifest else media_server

    async def collect(event):
        events.append(event)

    await asyncio.wait_for(
        runner.run(
            {
                "mode": "inspect",
                "url": url,
                "playlist": False,
                "limit": 500,
            },
            collect,
        ),
        timeout=30,
    )
    assert events[-1]["event"] == "inspection"
    assert events[-1]["data"]["kind"] == "video"
    events.clear()
    await asyncio.wait_for(
        runner.run(
            {
                "mode": "download",
                "url": url,
                "preset": preset,
                "resolution": 1080,
                "directory": str(tmp_path / preset),
            },
            collect,
        ),
        timeout=30,
    )
    assert events[-1]["event"] == "completed"
    path = Path(events[-1]["path"])
    assert path.is_file()
    expected = ".mp3" if preset == "mp3" else ".mkv" if manifest and preset == "best" else ".mp4"
    assert path.suffix == expected
    assert any(e["event"] == "processing" for e in events)


@pytest.mark.integration
async def test_cancellation_cleans_private_cookie_files(media_server, tmp_path, monkeypatch):
    from app import runtime

    cookie = tmp_path / "cookies.txt"
    contents = "# Netscape HTTP Cookie File\n"
    cookie.write_text(contents)
    settings = Settings(cookie_file=cookie, _env_file=None)
    runner = WorkerRunner(settings)
    captured = []
    original_spawn = asyncio.create_subprocess_exec

    async def spawn(*args, **kwargs):
        process = await original_spawn(*args, **kwargs)
        captured.append(process)
        return process

    monkeypatch.setattr(runtime.asyncio, "create_subprocess_exec", spawn)
    tempdirs = []
    original_temp = runtime.tempfile.TemporaryDirectory

    def temporary(*args, **kwargs):
        result = original_temp(*args, **kwargs)
        tempdirs.append(result.name)
        return result

    monkeypatch.setattr(runtime.tempfile, "TemporaryDirectory", temporary)

    async def event(_):
        pass

    task = asyncio.create_task(
        runner.run(
            {
                "mode": "inspect",
                "url": media_server + "?slow=1",
                "playlist": False,
                "limit": 500,
            },
            event,
        )
    )
    deadline = asyncio.get_running_loop().time() + 5
    while not tempdirs or not list(Path(tempdirs[0]).glob("yt-dlp-web-cookies-*")):
        assert asyncio.get_running_loop().time() < deadline
        await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert captured[0].returncode is not None
    assert not Path(tempdirs[0]).exists()
    assert cookie.read_text() == contents


@pytest.mark.integration
async def test_parent_pipe_closure_stops_worker_and_removes_cookies(media_server, tmp_path):
    cookie = tmp_path / "original.txt"
    cookie.write_text("# Netscape HTTP Cookie File\n")
    private = tmp_path / "private"
    private.mkdir()
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "app.worker",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        process.stdin.write(
            json.dumps(
                {
                    "mode": "inspect",
                    "url": media_server + "?slow=1",
                    "playlist": False,
                    "limit": 500,
                    "node_path": "node",
                    "cookie_file": str(cookie),
                    "cookie_temp_dir": str(private),
                }
            ).encode()
            + b"\n"
        )
        await process.stdin.drain()
        deadline = asyncio.get_running_loop().time() + 5
        while not list(private.iterdir()):
            assert asyncio.get_running_loop().time() < deadline
            await asyncio.sleep(0.02)
        process.stdin.close()
        await asyncio.wait_for(process.wait(), 5)
        assert process.returncode == 143
        assert list(private.iterdir()) == []
    finally:
        if process.returncode is None:
            os.killpg(process.pid, 9)
            await process.wait()


@pytest.mark.integration
async def test_cancelling_process_group_stops_descendants(tmp_path, monkeypatch):
    from app import runtime

    original_spawn = asyncio.create_subprocess_exec
    processes = []
    child_file = tmp_path / "child.pid"
    code = (
        "import subprocess,sys,time,pathlib; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
        f"pathlib.Path({str(child_file)!r}).write_text(str(child.pid)); "
        "time.sleep(60)"
    )

    async def spawn(*args, **kwargs):
        process = await original_spawn(sys.executable, "-c", code, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(runtime.asyncio, "create_subprocess_exec", spawn)

    async def event(_):
        pass

    task = asyncio.create_task(WorkerRunner(Settings(_env_file=None)).run({}, event))
    deadline = asyncio.get_running_loop().time() + 5
    while not child_file.exists():
        assert asyncio.get_running_loop().time() < deadline
        await asyncio.sleep(0.02)
    child_pid = int(child_file.read_text())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert processes[0].returncode is not None
    for _ in range(100):
        result = await asyncio.to_thread(
            subprocess.run,
            ["ps", "-o", "stat=", "-p", str(child_pid)],
            capture_output=True,
            text=True,
        )
        if not result.stdout.strip() or result.stdout.strip().startswith("Z"):
            break
        await asyncio.sleep(0.02)
    else:
        pytest.fail("A descendant survived cancellation")
