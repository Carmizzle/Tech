"""Find a model the Vercel AI Gateway free tier can use, and turn on free mode.

  uv run python -m jevlab.freemodel                  # pick the first model that works
  uv run python -m jevlab.freemodel --fast           # skip "thinking" models (they answer too slowly)
  uv run python -m jevlab.freemodel <model> [...]    # try only these models, e.g. meta/llama-3.1-8b

Tries cheap, fast chat models one by one with your AI_GATEWAY_API_KEY. The first one that
answers is saved as JEV_FREE_MODEL in .env. Never prints your key.
To go back to the real Jev (paid credits), delete the JEV_FREE_MODEL line from .env.
"""

from __future__ import annotations

import os
import re
import sys
import time

import requests
from dotenv import load_dotenv

ENV = os.path.join(os.path.dirname(__file__), "..", ".env")
CHAT_URL = "https://ai-gateway.vercel.sh/v1/chat/completions"
MODELS_URL = "https://ai-gateway.vercel.sh/v1/models"

# "Thinking" models: they work, but take 5-15 s per answer, too slow for the loop.
THINKING = ("gpt-oss", "gpt-5", "o1", "o3", "o4", "deepseek-r1", "qwq", "magistral", "thinking", "reasoning")

# Small, fast models first. Anything else the gateway lists is tried after these, cheapest first.
PREFERRED = [
    "openai/gpt-oss-20b",
    "google/gemini-2.5-flash-lite",
    "openai/gpt-5-nano",
    "openai/gpt-4.1-nano",
    "meta/llama-3.1-8b",
    "mistral/ministral-3b",
    "google/gemini-2.0-flash-lite",
    "alibaba/qwen-3-14b",
]


def candidates() -> list[str]:
    names = list(PREFERRED)
    try:
        listed = requests.get(MODELS_URL, timeout=15).json().get("data", [])
        listed = [m for m in listed if m.get("type", "language") == "language" and m.get("id")]

        def price(m):
            try:
                return float((m.get("pricing") or {}).get("input", 1))
            except (TypeError, ValueError):
                return 1.0
        names += [m["id"] for m in sorted(listed, key=price) if m["id"] not in names][:12]
    except (requests.RequestException, ValueError):
        pass
    return names


def try_model(key: str, model: str) -> tuple[bool, str]:
    body = {"model": model, "temperature": 0, "max_tokens": 20,
            "messages": [{"role": "user", "content": 'Reply with only this JSON: {"ok": true}'}]}
    t0 = time.monotonic()
    try:
        r = requests.post(CHAT_URL, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=30)
    except requests.RequestException as exc:
        return False, f"no answer ({str(exc)[:60]})"
    ms = round((time.monotonic() - t0) * 1000)
    if r.status_code == 200:
        return True, f"works, {ms} ms"
    if r.status_code == 429:
        return False, "rate-limited (busy), skipping"
    try:
        msg = r.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        msg = r.text
    return False, f"HTTP {r.status_code}: {msg[:70]}"


def save(model: str) -> None:
    text = open(ENV, encoding="utf-8").read() if os.path.exists(ENV) else ""
    line = f"JEV_FREE_MODEL={model}"
    if re.search(r"(?m)^JEV_FREE_MODEL=.*$", text):
        text = re.sub(r"(?m)^JEV_FREE_MODEL=.*$", line, text)
    else:
        text = text.rstrip("\n") + "\n\n# Free mode: a general model stands in for Jev. Delete this line to use the real Jev.\n" + line + "\n"
    with open(ENV, "w", encoding="utf-8") as f:
        f.write(text)


def main() -> None:
    load_dotenv(ENV)
    key = os.getenv("AI_GATEWAY_API_KEY", "").strip()
    if not key:
        print("No AI_GATEWAY_API_KEY in .env yet. Paste your key there first, save, and run this again.")
        return
    args = sys.argv[1:]
    fast = "--fast" in args
    chosen = [a for a in args if not a.startswith("--")]
    models = chosen or candidates()
    if fast and not chosen:
        models = [m for m in models if not any(t in m.lower() for t in THINKING)]
    for model in models:
        ok, note = try_model(key, model)
        print(f"  {model:<36} {note}")
        if ok:
            save(model)
            print(f"\nFree mode is on: {model} will stand in for Jev (saved to .env).")
            print("Next: uv run python -m jevlab check")
            return
    print("\nNo free model answered. Wait a minute and try again (the free tier gets busy).")


if __name__ == "__main__":
    main()
