"""OpenRouter call that turns aggregate practice features into drill suggestions.

ADR 0021. Output is untrusted: schema-validated and copy-filtered before anyone
stores or shows it. Every failure raises `AiCoachError`, a 502 Problem, so the
route stores nothing. The API key is never logged or echoed.
"""

import json
import os
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from services.api.problems import Problem
from services.api.schemas import AiCoachResult, Drill, PracticeFeatures

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "deepseek/deepseek-chat"
TIMEOUT_S = 30

SYSTEM_PROMPT = """You are a youth soccer training assistant for players aged 13 to 18.
You receive aggregate movement features computed on the player's own device from
a practice video (joint-angle percentiles in degrees, head turns, stance width
ratio, landmark visibility), plus the title of the development goal their coach
set. You never see the video; never claim to have watched or seen it.
Suggest up to three concrete drills that support the coach's goal.
Write in plain, encouraging language a teenager understands.
Never give scores, ratings, grades, percentages, rankings, or comparisons with
other players. Never give medical, injury, or diagnostic advice. Do not use the
words failed, weak, incorrect, insights, unlock, level up, elite, or AI-powered.
Reply with strict JSON only, no text around it:
{"body": "<at most 1000 characters>",
 "drills": [{"title": "<short>", "why": "<one or two sentences>", "how": "<steps>"}]}"""

# AGENTS.md player-copy list plus score/rank vocabulary and numeric ratings.
BANNED = re.compile(
    r"\b(failed|weak|incorrect|performance score|insights?|unlock|level up|elite"
    r"|ai-powered|rank(?:ed|ing|s)?|rating|rated|percent(?:age|ile)?)\b"
    r"|%|\b\d+(?:\.\d+)?\s*/\s*10\b|\bout of\s+\d+",
    re.IGNORECASE,
)


class AiCoachError(Problem):
    def __init__(self, reason: str) -> None:
        # `reason` is for server-side logs; the browser gets a fixed detail.
        super().__init__(
            502, "The AI coach is unavailable right now.", slug="ai-coach-unavailable"
        )
        self.reason = reason


class _Output(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=1200)
    drills: list[Drill] = Field(max_length=3)


def _post(key: str, payload: dict[str, Any]) -> Any:
    request = Request(
        OPENROUTER_URL,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=TIMEOUT_S) as response:
            return json.load(response)
    except HTTPError as error:
        error.close()
        raise AiCoachError(f"upstream status {error.code}") from None
    except (URLError, TimeoutError, OSError):
        raise AiCoachError("upstream unreachable") from None
    except ValueError:
        raise AiCoachError("upstream sent non-JSON") from None


def check_output(raw: str) -> _Output:
    try:
        output = _Output.model_validate_json(raw)
    except ValidationError:
        raise AiCoachError("output failed schema") from None
    texts = [output.body, *(t for d in output.drills for t in (d.title, d.why, d.how))]
    if any(BANNED.search(text) for text in texts):
        raise AiCoachError("output failed copy filter")
    return output


def generate_feedback(
    features: PracticeFeatures, goal_title: str | None
) -> AiCoachResult:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise AiCoachError("OPENROUTER_API_KEY not set")
    model = os.environ.get("AI_COACH_MODEL") or DEFAULT_MODEL
    user = json.dumps(
        {"development_goal": goal_title, "features": features.model_dump()}
    )
    data = _post(
        key,
        {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.4,
            "max_tokens": 900,
        },
    )
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise AiCoachError("upstream shape") from None
    if not isinstance(content, str):
        raise AiCoachError("upstream shape")
    output = check_output(content)
    return AiCoachResult(body=output.body, drills=output.drills, model=model)
