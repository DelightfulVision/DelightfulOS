"""Test Prime Intellect API connectivity and model availability.

Loads credentials from .env — never hardcodes keys.
Run: cd server && .venv/Scripts/python -m tests.test_prime_api
"""
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from openai import OpenAI


def get_client():
    api_key = os.environ.get("PRIME_API_KEY")
    team_id = os.environ.get("PRIME_TEAM_ID")
    if not api_key:
        print("ERROR: PRIME_API_KEY not set. Copy .env.example to .env and fill in your key.")
        sys.exit(1)
    headers = {}
    if team_id:
        headers["X-Prime-Team-ID"] = team_id
    return OpenAI(
        api_key=api_key,
        base_url="https://api.pinference.ai/api/v1",
        default_headers=headers,
    )


def test_models():
    print("=== Model List ===")
    client = get_client()
    models = client.models.list()
    print(f"  {len(models.data)} models available")
    for m in models.data[:5]:
        print(f"    {m.id}")
    print(f"    ... and {len(models.data) - 5} more")


def test_chat():
    print("\n=== Chat Completion ===")
    client = get_client()
    models_to_test = [
        "qwen/qwen3-30b-a3b-instruct-2507",
        "google/gemini-2.5-flash",
        "meta-llama/llama-3.3-70b-instruct",
    ]
    for model in models_to_test:
        start = time.time()
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Say OK in one word."}],
                max_tokens=8,
                temperature=0,
            )
            elapsed = time.time() - start
            text = resp.choices[0].message.content
            print(f"  {model}: {text!r} ({elapsed:.1f}s)")
        except Exception as e:
            print(f"  {model}: FAIL - {str(e)[:80]}")


def test_streaming():
    print("\n=== Streaming First-Token Latency ===")
    client = get_client()
    models = [
        "qwen/qwen3-30b-a3b-instruct-2507",
        "google/gemini-2.5-flash",
    ]
    for model in models:
        start = time.time()
        first_token_time = None
        try:
            stream = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "Reply with only JSON: {\"action\":\"none\"}"},
                    {"role": "user", "content": "test"},
                ],
                max_tokens=32, temperature=0, stream=True,
            )
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    if first_token_time is None:
                        first_token_time = time.time() - start
            total = time.time() - start
            print(f"  {model}: first_token={first_token_time:.2f}s total={total:.2f}s")
        except Exception as e:
            print(f"  {model}: FAIL - {str(e)[:80]}")


if __name__ == "__main__":
    test_models()
    test_chat()
    test_streaming()
    print("\nAll tests complete.")
