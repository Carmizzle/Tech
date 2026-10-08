"""The Jev client. Sends one state plus typed questions, gets typed answers back.

Jev question types (TypeSafe systemone API):
  noul    yes/no, answered as a probability of "yes"
  choice  pick one option from a dict of options
  score   pick a level from a list ordered low -> high

Answers are normalised to:
  noul   -> {"p": float}
  choice -> {"choice": str, "probs": {option: float}}
  score  -> {"score": float (0-based level, may be an expected value), "probs": [float, ...]}

Reaches Jev through the Vercel AI Gateway (AI_GATEWAY_API_KEY), or directly with a
TypeSafe key (TYPESAFE_API_KEY) if you have one.

Free mode: set JEV_FREE_MODEL in .env (e.g. JEV_FREE_MODEL=openai/gpt-oss-20b) to ask a
general chat model through the same gateway instead. It works on Vercel's free tier, but
it's slower than Jev and its confidence scores are the model's own guess.
"""

from __future__ import annotations

import json
import os
import random
import re
import time

import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

JEV_GATEWAY_URL = "https://ai-gateway.vercel.sh/typesafe/v1/systemone"
JEV_DIRECT_URL = "https://api.typesafe.ai/v1/systemone"
CHAT_URL = "https://ai-gateway.vercel.sh/v1/chat/completions"


class JudgeError(Exception):
    pass


def _post(url: str, key: str, body: dict, timeout: float, retries: int = 6) -> dict:
    for attempt in range(retries + 1):
        retry_after = None
        try:
            r = requests.post(
                url,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=body,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            if attempt == retries:
                raise JudgeError(str(exc)) from exc
        else:
            if r.status_code == 200:
                return r.json()
            if r.status_code not in (429, 500, 502, 503, 529) or attempt == retries:
                raise JudgeError(f"HTTP {r.status_code}: {r.text[:300]}")
            retry_after = r.headers.get("retry-after")
        # 429 = the free tier is busy. Back off (honouring Retry-After) rather than drop the call.
        try:
            wait = float(retry_after)
        except (TypeError, ValueError):
            wait = min(8.0, 0.75 * 2**attempt) + random.random()
        time.sleep(wait)
    raise JudgeError("unreachable")


# ---------------------------------------------------------------- normalising

def _norm_probs(raw, options: list[str]) -> dict:
    if isinstance(raw, dict):
        probs = {o: float(raw.get(o, 0.0)) for o in options}
    elif isinstance(raw, list) and len(raw) == len(options):
        probs = dict(zip(options, map(float, raw)))
    else:
        return {}
    total = sum(probs.values())
    return {o: p / total for o, p in probs.items()} if total > 0 else {}


def normalise(questions: dict, raw_answers: dict) -> dict:
    """Coerce any judge's raw answers into the one shape the labs score."""
    out = {}
    for qid, q in questions.items():
        a = raw_answers.get(qid)
        if a is None:
            raise JudgeError(f"missing answer for '{qid}'")
        if q["type"] == "noul":
            p = a.get("noul", a.get("p")) if isinstance(a, dict) else a
            out[qid] = {"p": max(0.0, min(1.0, float(p)))}
        elif q["type"] == "choice":
            options = list(q["criteria"])
            probs = _norm_probs(a.get("probabilities", a.get("probs")), options)
            choice = a.get("choice")
            if choice not in options:
                if not probs:
                    raise JudgeError(f"bad choice answer for '{qid}': {a}")
                choice = max(probs, key=probs.get)
            if not probs:
                probs = {o: float(o == choice) for o in options}
            out[qid] = {"choice": choice, "probs": probs}
        elif q["type"] == "score":
            # Jev returns score as an expected level (e.g. 1.69) with probabilities
            # keyed "0".."n-1"; other judges may return a label or an index.
            levels = q["criteria"]
            score = a.get("score")
            if isinstance(score, str):
                score = levels.index(score) if score in levels else float(score)
            raw_p = a.get("probabilities", a.get("probs"))
            if isinstance(raw_p, dict) and all(str(k).isdigit() for k in raw_p):
                raw_p = {levels[int(k)]: v for k, v in raw_p.items() if int(k) < len(levels)}
            probs_d = _norm_probs(raw_p, levels)
            probs = [probs_d.get(l, 0.0) for l in levels] if probs_d else [
                float(i == round(float(score))) for i in range(len(levels))
            ]
            out[qid] = {"score": max(0.0, min(len(levels) - 1.0, float(score))), "probs": probs}
    return out


# ---------------------------------------------------------------- judges

class JevJudge:
    name = "jev"

    def __init__(self):
        direct = os.getenv("TYPESAFE_API_KEY", "").strip()
        gateway = os.getenv("AI_GATEWAY_API_KEY", "").strip()
        free_model = os.getenv("JEV_FREE_MODEL", "").strip()
        self.chat = bool(free_model) and not direct
        if self.chat:
            if not gateway:
                raise JudgeError("no AI_GATEWAY_API_KEY in .env")
            self.url, self.key, self.model = CHAT_URL, gateway, free_model
        elif direct:
            self.url, self.key, self.model = JEV_DIRECT_URL, direct, "jev-latest"
        elif gateway:
            self.url, self.key, self.model = JEV_GATEWAY_URL, gateway, "typesafe-ai/jev"
        else:
            raise JudgeError("no AI_GATEWAY_API_KEY or TYPESAFE_API_KEY in .env")

    def ask(self, state, questions, timeout=20.0, retries=6):
        t0 = time.monotonic()
        if self.chat:
            data = self._ask_chat(state, questions, timeout, retries)
        else:
            body = {"state": state, "model": self.model, "questions": questions}
            data = _post(self.url, self.key, body, timeout, retries)
        ms = (time.monotonic() - t0) * 1000
        try:
            answers = normalise(questions, data.get("answers", data))
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            if not self.chat:
                raise
            raise JudgeError(f"free model gave an unreadable answer: {str(exc)[:80]}") from exc
        return answers, {"judge": self.name, "model": data.get("model", self.model), "latency_ms": round(ms)}

    def _ask_chat(self, state, questions, timeout, retries) -> dict:
        """Free mode: ask a chat model the same questions and get Jev-shaped answers back."""
        lines = []
        for qid, q in questions.items():
            if q["type"] == "choice":
                lines.append(f'- "{qid}" ({q.get("instructions", "")}): pick one of {list(q["criteria"])}. '
                             f'Answer {{"choice": <option>, "probabilities": {{<option>: <0-1>, ...}}}}')
            elif q["type"] == "score":
                lines.append(f'- "{qid}" ({q.get("instructions", "")}): levels low to high {list(q["criteria"])}. '
                             f'Answer {{"score": <level name>, "probabilities": {{<level name>: <0-1>, ...}}}}')
            else:
                lines.append(f'- "{qid}" ({q.get("instructions", "")}): yes or no. Answer {{"p": <probability of yes, 0-1>}}')
        prompt = ("You are a fast judge for a trading bot. Read the state, answer every question, and give honest "
                  "probabilities (they should sum to 1 per question).\n\nState:\n" + json.dumps(state, indent=1, default=str)
                  + "\n\nQuestions:\n" + "\n".join(lines)
                  + "\n\nReply with ONLY a JSON object keyed by question id, nothing else.")
        body = {"model": self.model, "temperature": 0, "max_tokens": 2000,
                "messages": [{"role": "user", "content": prompt}]}
        data = _post(self.url, self.key, body, timeout, retries)
        try:
            text = data["choices"][0]["message"]["content"] or ""
            found = re.search(r"\{.*\}", text, re.S)
            if not found:
                raise ValueError("no JSON in the reply (the model may have run out of room)")
            return json.loads(found.group(0))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise JudgeError(f"free model gave an unreadable answer: {str(exc)[:80]}") from exc
