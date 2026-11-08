from dataclasses import dataclass, field
from pathlib import Path
import os
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    api_key: str = field(default="", repr=False)
    model: str = "openai/gpt-oss-20b"
    stt_model: str = "whisper-large-v3-turbo"


def load_config(secrets=None, environ=None, env_path=None):
    """Environment > Streamlit Secrets > root .env > defaults; empty key disables live."""
    values = dict(dotenv_values(env_path or ROOT / ".env"))
    values.update(dict(secrets or {}))
    values.update(dict(os.environ if environ is None else environ))
    return Config(str(values.get("GROQ_API_KEY") or ""),
                  str(values.get("GROQ_MODEL") or Config.model),
                  str(values.get("GROQ_STT_MODEL") or Config.stt_model))
