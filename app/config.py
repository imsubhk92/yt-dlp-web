from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="YTDLP_", env_file=".env", extra="ignore")

    data_dir: Path = Path("data")
    concurrency: int = Field(default=2, ge=1, le=8)
    playlist_limit: int = Field(default=500, ge=1, le=10000)
    inspect_timeout: int = Field(default=60, ge=1, le=300)
    cookie_file: Path | None = None
    node_path: str = "node"


ROOT = Path(__file__).resolve().parent.parent
