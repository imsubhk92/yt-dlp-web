# Downstream

A personal video downloader built with **FastAPI, yt-dlp, React, and TypeScript**. Preview a link, choose video or audio, select playlist entries, and save the results from your browser.

## Run locally

Requirements: **uv**, **Node 24**, **FFmpeg**, and **FFprobe**. Python 3.13 is selected by `.python-version`; uv can install it automatically. This version targets macOS and Linux because worker cleanup and the single-instance lock use POSIX process groups and file locking.

On macOS, dependencies can be installed with Homebrew:

```sh
brew install uv node@24 ffmpeg
export PATH="$(brew --prefix node@24)/bin:$PATH"
```

From the project directory:

```sh
make setup
make start
```

Open **http://127.0.0.1:8000**. The API serves the built React app. Interactive API documentation is at **http://127.0.0.1:8000/docs**. Stop with Ctrl+C.

For frontend development with hot reload:

```sh
make dev
```

Open **http://127.0.0.1:5173**. Vite proxies `/api` requests to FastAPI on port 8000. Both servers stop with Ctrl+C. Run only one API instance per data directory; avoid Uvicorn `--workers` and `--reload` while downloading. If `.tools/node/bin` exists, Make automatically uses that local Node installation.

## Run with Docker

Install Docker Engine with Compose, or Docker Desktop on macOS/Windows, then run:

```sh
make docker-up
```

This builds the React frontend and a Python 3.13 image containing Node 24, yt-dlp/EJS, FFmpeg, and FFprobe. A single FastAPI process serves both the UI and API at **http://127.0.0.1:8000**. Host Python, Node, and FFmpeg installations are not required for Docker. The service runs as a non-root user, publishes only to host loopback, and stores downloads and SQLite history in the persistent `yt-dlp-web_downloads` volume.

```sh
make docker-status                 # container and health status
make docker-logs                   # follow application logs
docker compose restart app         # restart without removing history/files
make docker-down                   # stop/remove the container; retain its data volume
```

The `unless-stopped` restart policy brings the container back after process failure or a Docker engine restart. Docker itself must start after a system reboot. On Docker Desktop, enable **Settings → General → Start Docker Desktop when you sign in to your computer**; on macOS the app becomes available after sign-in and Docker startup, not before login. On Linux, enable the Docker system service at boot. An intentionally stopped/removed container stays stopped until you run `make docker-up` again. Health checks report readiness; an unhealthy status alone does not trigger a Docker restart. See [Docker restart policies](https://docs.docker.com/engine/containers/start-containers-automatically/) and [Desktop startup settings](https://docs.docker.com/desktop/settings-and-maintenance/settings/).

Docker storage is separate from native `./data`. To import an existing native library **before the first Docker start**:

```sh
# Stop the native app first; the destination Docker data volume must be empty.
docker compose build
make docker-import-data
make docker-up
```

The importer takes the native app lock, mounts the source read-only, copies media, backs up SQLite, and sets container ownership. It preserves the native files and refuses to overwrite a populated Docker volume. Do not run native and Docker instances on the same port. Avoid `docker compose down --volumes`: that explicitly deletes the Docker library.

Concurrency, playlist limit, and inspection timeout can be set in `.env` using the same variables documented below; recreate the container with `make docker-up` after changing them. Container data and Node paths are fixed to their packaged locations. A host cookie-file path is not automatically passed into the container. To use cookies in Docker, copy the jar into its data volume and configure its **container** path:

```sh
docker compose cp /absolute/path/to/cookies.txt app:/app/data/cookies.txt
docker compose exec --user root app chown 1000:1000 /app/data/cookies.txt
docker compose exec --user root app chmod 600 /app/data/cookies.txt
```

Create a local `compose.override.yaml` containing the following, then run `make docker-up`:

```yaml
services:
  app:
    environment:
      YTDLP_COOKIE_FILE: /app/data/cookies.txt
```

The jar stays outside the image and repository. Native cookie configuration and worker isolation behave as documented below.

## Download workflow

1. Paste an HTTP(S) video or playlist URL and click **Find media**.
2. For a video link that also includes a playlist, check **Include playlist** to inspect the playlist. A plain playlist URL is recognized automatically.
3. Choose **MP4 video**, **Best quality**, or **MP3 audio**, and a video resolution limit if applicable.
4. Select available entries and start downloading. Progress, merging/conversion, failures, and completed files appear under downloads.
5. Save individual files, or download the ZIP created for a settled playlist. A failed entry does not stop the remaining items.

**MP4** selects H.264/AAC without transcoding. **Best quality** keeps source codecs and uses MKV for merged streams; a combined source file keeps its original container. **MP3** converts audio to 192 kbps. Source audio quality still determines the result. Resolution limits apply to the shorter dimension, including portrait videos. When direct-file metadata omits codecs or dimensions, the downloaded file is verified with FFprobe before being marked complete.

Transfers use two download slots globally. Downloading and post-processing are separate phases; unknown byte totals remain indeterminate. A video-only transfer reaching its byte total does not mean merging is finished.

Use **Color theme** in the header to choose **System**, **Light**, or **Dark**. System follows your device appearance, including changes while the app is open. An explicit choice is saved in your browser and synchronized across tabs. The initial page background is applied before React loads; if browser storage is blocked, theme changes still work for the current session. Theme selection does not reset your current download form or job history.

## Persistent storage and recovery

SQLite metadata and media files live in `./data/` by default. Completed files and history remain until you delete the job. **Delete files** first stops any active workers/archive generation, then removes that job's managed files and database records. Already-saved browser copies are independent files.

Queued items resume after restart. Previously active items become **interrupted**; use **Retry unsuccessful** to create a new job with failed, cancelled, or interrupted entries. Completed entries remain in the original job. Incomplete media is cleaned up. A ZIP contains successful entries in playlist order, with numeric prefixes preventing duplicate-name collisions. ZIP failures are reported separately; the media files remain available. ZIPs require additional disk space and support ZIP64.

## Configuration

Copy `.env.example` to `.env` to override defaults. Restart the API after changes.

| Variable | Default | Purpose |
| --- | --- | --- |
| `YTDLP_DATA_DIR` | `./data` | Database and managed media directory |
| `YTDLP_CONCURRENCY` | `2` | Concurrent media workers, from 1 to 8 |
| `YTDLP_PLAYLIST_LIMIT` | `500` | Maximum preview entries, from 1 to 10,000 |
| `YTDLP_INSPECT_TIMEOUT` | `60` | Seconds allowed for metadata inspection |
| `YTDLP_COOKIE_FILE` | unset | Local Mozilla/Netscape cookie file |
| `YTDLP_NODE_PATH` | `node` | Node executable name or absolute path |

When a playlist exceeds the configured limit, the preview explicitly reports the cap and only those entries can be selected. Previews are temporary metadata, periodically cleaned up after one day; download jobs are retained. History is paginated in groups of 25.

### Optional website cookies

Set an absolute local path, for example:

```dotenv
YTDLP_COOKIE_FILE=/absolute/path/to/cookies.txt
```

The first line must be `# Netscape HTTP Cookie File` or `# HTTP Cookie File`. Use a valid Mozilla/Netscape-format export for the source site and restrict its permissions (`chmod 600 /absolute/path/to/cookies.txt`). Follow yt-dlp's [cookie instructions](https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp) and [YouTube-specific export guidance](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies).

Each worker uses its own temporary 0600 cookie copy, cleaned up when it exits or is cancelled. The original jar is preserved. Cookie contents are never returned by the API, written to the database, or logged. The browser cannot upload cookies or configure filesystem paths. Login requirements, expired cookies, source restrictions, and bot challenges can still prevent a download.

## API

| Method | Endpoint | Behavior |
| --- | --- | --- |
| GET | `/api/health` | Readiness, executable/storage checks, cookie configuration status |
| POST | `/api/inspect` | `{ "url": "https://…", "playlist": false }` → preview ID and entries |
| POST | `/api/jobs` | `{ "inspection_id": "…", "entry_ids": ["1"], "preset": "mp4", "resolution": 1080 }` → `202` and job |
| GET | `/api/jobs?limit=25&offset=0` | Download history, newest first |
| GET | `/api/jobs/{id}` | Job, item progress, file IDs, archive status, and errors |
| POST | `/api/jobs/{id}/cancel` | Cancel queued/active work; completed files remain |
| POST | `/api/jobs/{id}/retry` | New job containing unsuccessful items; `202` |
| GET | `/api/jobs/{id}/files/{file_id}` | Download a recorded completed file |
| GET | `/api/jobs/{id}/archive` | Download a prepared playlist ZIP |
| DELETE | `/api/jobs/{id}` | Stop work and remove the job/files; `204` |

Presets are `mp4`, `best`, and `mp3`. Resolution is `480`, `720`, `1080`, `1440`, `2160`, or `null` for unrestricted. Entry IDs refer to the inspected snapshot; submission order does not change playlist order. Requests cannot submit custom yt-dlp flags, output paths, or commands.

Job states are `queued`, `downloading`, `processing`, `completed`, `partial`, `failed`, `cancelled`, and `interrupted`. ZIP status is tracked independently. Retry requires a settled job; archive requests return `409` until ready. Invalid inputs return `422`, missing records/files `404`, and unmet runtime requirements `503`.

## Validation

```sh
make check
make test
cd frontend
npm exec playwright install chromium
npm run test:e2e
```

Backend tests cover selection, persistent queues, restart recovery, cancellation, partial playlist failures, retries, ZIP order/collisions, cookie isolation, file access, and dependency failures. The integration tests generate small local media files and use **real yt-dlp and FFmpeg** through a temporary loopback HTTP server. They require permissions to bind local sockets.

Frontend tests cover selection, unavailable entries, preview invalidation, audio settings, and API errors. Playwright starts isolated API/Vite servers and tests the browser flow on desktop and mobile viewports. The browser server uses a deterministic fixture downloader; its media files are test data. Screenshots and traces are written under `frontend/test-results/`. Stop other services on ports 8000 and 5173 before running browser tests.

Theme tests cover system changes, saved preferences, blocked storage, tab synchronization, and desktop/mobile reloads. The playlist/file/ZIP browser flow also runs in dark mode. Stop the Docker app with `make docker-down` before running the native browser suite because it uses the same port.

Live YouTube downloads and real account cookies are separate external checks, not part of deterministic test coverage.

## Troubleshooting and updates

- **Setup banner:** `/api/health` identifies missing FFmpeg, FFprobe, Node 24+, invalid cookie configuration, or unwritable/full storage. Downloads require at least 64 MiB free at admission; an individual download can require much more.
- **No compatible format:** choose Best quality, change the resolution limit, or check source availability. MP4 does not silently convert incompatible codecs.
- **Private/unavailable video:** check access and the configured cookie jar. Some sites require additional authentication mechanisms unsupported by this app.
- **Website behavior changed:** update yt-dlp and its EJS companion, then rerun validation:

  ```sh
  uv lock --upgrade-package yt-dlp --upgrade-package yt-dlp-ejs
  uv sync --locked
  make test
  ```

- **App already running:** stop the other process using this data directory. The OS releases the lock automatically when the owning process exits; do not delete a live process's lock file.
- **Missing media file:** app history remains if files are manually moved or removed. Start a new job to download it again.

## Architecture and boundaries

`app/` contains the API, Pydantic contracts, SQLite repository, scheduler, and isolated worker. `frontend/` contains React, TypeScript API types, and the Vite build. `tests/` contains deterministic fixtures and real local media integration tests.

The FastAPI lifespan owns the queue and data-directory lock. Each media item runs in a separate Python process using yt-dlp's embedding API. Application-owned JSON events carry progress; download completion is accepted only after post-processing, final-path verification, and successful worker exit. Cancellation terminates the entire process group, including FFmpeg. An EOF watchdog stops workers if their parent exits. ZIP generation runs in a background thread with cooperative cancellation.

This is a **trusted-user local app**, bound to loopback with permitted localhost hosts/origins and no application login. It is not a network sandbox: yt-dlp follows source/CDN links and can reach URLs accessible to your machine. Do not expose it publicly. Multi-user accounts, distributed workers, live recording, DRM handling, and public deployment are outside this version. Availability on yt-dlp supported sites depends on the site, access requirements, and the installed extractor version.

References: [yt-dlp embedding API](https://github.com/yt-dlp/yt-dlp#embedding-yt-dlp), [JavaScript runtime setup](https://github.com/yt-dlp/yt-dlp/wiki/EJS), [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/), [Vite](https://vite.dev/guide/).
