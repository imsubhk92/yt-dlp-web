With **Docker Desktop running**, execute:

```bash
cd /Users/zubhxk/Projects/yt-dlp-web
make docker-up
```

Open **http://127.0.0.1:8000**.

Other useful commands:

```bash
make docker-status   # Check application health
make docker-logs     # View logs
make docker-down     # Stop the app; preserve downloads and history
```