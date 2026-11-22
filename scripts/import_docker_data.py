"""Copy native app data into an empty Docker volume without changing the source."""

import fcntl
import subprocess
from pathlib import Path

IMPORT_CODE = """
import os, shutil, sqlite3
from contextlib import closing
from pathlib import Path
source, target = Path('/import'), Path('/app/data')
if any(target.iterdir()):
    raise SystemExit('Docker data is not empty; refusing to overwrite it.')
for path in source.iterdir():
    if path.name in {'.instance.lock', '.DS_Store', 'jobs.sqlite3',
                     'jobs.sqlite3-wal', 'jobs.sqlite3-shm'}:
        continue
    if path.is_dir():
        shutil.copytree(path, target / path.name)
    else:
        shutil.copy2(path, target / path.name)
if (source / 'jobs.sqlite3').exists():
    with closing(sqlite3.connect('file:/import/jobs.sqlite3?mode=ro', uri=True)) as src:
        with closing(sqlite3.connect(target / 'jobs.sqlite3')) as dst:
            src.backup(dst)
for path in [target, *target.rglob('*')]:
    os.chown(path, 1000, 1000)
print('Imported native downloads and history; source files were preserved.')
"""


def main():
    root = Path(__file__).resolve().parent.parent
    source = root / "data"
    if not source.is_dir():
        raise SystemExit("No native ./data found. Start Docker normally for a fresh library.")
    with (source / ".instance.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise SystemExit("Stop the native app before importing its data.") from None
        subprocess.run(
            [
                "docker",
                "compose",
                "run",
                "--rm",
                "--no-deps",
                "--user",
                "root",
                "--entrypoint",
                "python",
                "--volume",
                f"{source}:/import:ro",
                "app",
                "-c",
                IMPORT_CODE,
            ],
            cwd=root,
            check=True,
        )


if __name__ == "__main__":
    main()
