"""Configuration — centralized settings loaded from environment.

All secrets come from .env, never hardcoded.
"""
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    prime_api_key: str = ""
    prime_team_id: str = ""
    prime_base_url: str = "https://api.pinference.ai/api/v1"

    # Model selection — tuned from benchmarks
    model_fast: str = "google/gemini-2.5-flash"
    model_mediator: str = "qwen/qwen3-30b-a3b-instruct-2507"
    model_quality: str = "meta-llama/llama-3.3-70b-instruct"
    model_vision: str = "google/gemini-2.5-flash"
    model_thinking: str = "deepseek/deepseek-r1-0528"
    model_transcription: str = "google/gemini-2.5-flash"

    # Google Gemini direct (for Gemini Live realtime audio)
    gemini_api_key: str = ""
    gemini_live_model: str = "gemini-2.5-flash-native-audio-preview-12-2025"

    # Supabase Realtime (Snap Spectacles via snapcloud.dev)
    # Channel name must match what the Snap scene joins (e.g. "cursor")
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_channel: str = "cursor"

    # Signal processing
    piezo_sample_rate: int = 4000
    speech_threshold: float = 0.15
    pre_speech_threshold: float = 0.05

    model_config = {"env_file": str(Path(__file__).parent.parent.parent / "server" / ".env")}


settings = Settings()
