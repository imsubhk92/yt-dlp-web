from enum import StrEnum
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Preset(StrEnum):
    MP4 = "mp4"
    BEST = "best"
    MP3 = "mp3"


Resolution = Literal[480, 720, 1080, 1440, 2160] | None
Status = Literal[
    "queued",
    "downloading",
    "processing",
    "completed",
    "partial",
    "failed",
    "cancelled",
    "interrupted",
]
TERMINAL = {"completed", "partial", "failed", "cancelled", "interrupted"}
UNSUCCESSFUL = {"failed", "cancelled", "interrupted"}


def source_url(value: str) -> str:
    value = value.strip()
    try:
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or any(ord(c) < 32 for c in value)
        ):
            raise ValueError
        _ = parts.port
    except ValueError:
        raise ValueError("Enter an HTTP(S) video URL without embedded credentials.") from None
    return value


class InspectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(max_length=8192)
    playlist: bool = False

    validate_url = field_validator("url")(source_url)


class Entry(BaseModel):
    id: str
    position: int
    title: str
    url: str | None = None
    duration: float | None = None
    thumbnail: str | None = None
    available: bool = True


class Inspection(BaseModel):
    id: str
    source_url: str
    title: str
    kind: Literal["video", "playlist"]
    entries: list[Entry]
    truncated: bool = False
    limit: int


class JobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inspection_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    entry_ids: list[str] = Field(min_length=1, max_length=10000)
    preset: Preset = Preset.MP4
    resolution: Resolution = 1080

    @field_validator("entry_ids")
    @classmethod
    def unique_entries(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("Select each entry only once.")
        return value


class Item(BaseModel):
    id: str
    position: int
    title: str
    status: Status
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    speed: float | None = None
    eta: float | None = None
    error: str | None = None
    file_id: str | None = None
    filename: str | None = None
    size: int | None = None


class Job(BaseModel):
    id: str
    title: str
    source_url: str
    kind: Literal["video", "playlist"]
    preset: Preset
    resolution: Resolution
    status: Status
    created_at: str
    completed_count: int
    total_count: int
    archive_status: Literal["none", "building", "ready", "failed"]
    archive_error: str | None = None
    items: list[Item]


class Health(BaseModel):
    ready: bool
    dependencies: dict[str, bool]
    issues: list[str]
    cookie_configured: bool
