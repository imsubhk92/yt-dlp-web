"""Run both development servers; Ctrl+C stops both process groups."""

import os
import signal
import subprocess
import time
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent.parent
    processes = []
    try:
        processes.append(
            subprocess.Popen(
                ["uv", "run", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
                cwd=root,
                start_new_session=True,
            )
        )
        processes.append(
            subprocess.Popen(
                ["npm", "run", "dev", "--", "--host", "127.0.0.1"],
                cwd=root / "frontend",
                start_new_session=True,
            )
        )
        while all(p.poll() is None for p in processes):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for process in processes:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


if __name__ == "__main__":
    main()
