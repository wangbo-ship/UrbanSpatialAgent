from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
BACKEND_DIR = Path(__file__).resolve().parents[1]

# 把 .env 注入 os.environ，供 Agent / models 用 os.getenv 读取 API Key
load_dotenv(BACKEND_DIR / ".env", encoding="utf-8")
load_dotenv(ROOT_DIR / ".env", encoding="utf-8")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR / ".env", ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "UrbanSpatialAgent"
    data_dir: Path = DATA_DIR
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


settings = Settings()
