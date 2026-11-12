"""Deterministic browser-test server. Never use this fixture to download real media."""

from app import runtime
from app.config import Settings
from app.main import create_app
from app.models import Health
from tests.conftest import FakeRunner

runtime.preflight = lambda *_: Health(
    ready=True,
    dependencies={"node": True, "ffmpeg": True, "ffprobe": True, "storage": True},
    issues=[],
    cookie_configured=False,
)
app = create_app(Settings(), FakeRunner())
