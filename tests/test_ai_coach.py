import io
import json
import os
import unittest
from typing import Any
from unittest.mock import patch

from services.api import ai_coach
from services.api.ai_coach import AiCoachError, generate_feedback
from services.api.practice_schemas import PracticeFeatures

KEY = "sk-test-not-a-real-key"
FEATURES = PracticeFeatures.model_validate(
    {
        "frames_analyzed": 450,
        "fps": 15,
        "duration_ms": 30000,
        "knee_flexion_deg": {"p10": 12, "p50": 34, "p90": 61},
        "hip_flexion_deg": {"p10": 10, "p50": 25, "p90": 50},
        "trunk_lean_deg": {"p10": 2, "p50": 8, "p90": 20},
        "head_turns": 7,
        "head_turns_per_min": 14.0,
        "stance_width_ratio": {"p50": 1.2},
        "visibility_mean": 0.82,
    }
)
GOOD: dict[str, Any] = {
    "body": "Nice work staying low. Try checking your shoulder before you receive.",
    "drills": [
        {
            "title": "Shoulder check pass",
            "why": "Looking around before the ball arrives gives you more options.",
            "how": "A partner passes; glance over each shoulder before each touch.",
        }
    ],
}


def completion(content: Any) -> io.BytesIO:
    body = {"choices": [{"message": {"role": "assistant", "content": content}}]}
    return io.BytesIO(json.dumps(body).encode())


class AiCoachTests(unittest.TestCase):
    def setUp(self) -> None:
        env = patch.dict(os.environ, {"OPENROUTER_API_KEY": KEY}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("AI_COACH_MODEL", None)

    def call(self, response: Any) -> Any:
        with patch.object(ai_coach, "urlopen") as urlopen:
            if isinstance(response, BaseException):
                urlopen.side_effect = response
            else:
                urlopen.return_value.__enter__.return_value = response
            result = generate_feedback(FEATURES, "Scan before receiving")
            self.request = urlopen.call_args.args[0]
            self.timeout = urlopen.call_args.kwargs["timeout"]
            return result

    def test_happy_path(self) -> None:
        result = self.call(completion(json.dumps(GOOD)))
        self.assertEqual(result.body, GOOD["body"])
        self.assertEqual(result.drills[0].title, "Shoulder check pass")
        self.assertEqual(result.model, "deepseek/deepseek-chat")
        self.assertLessEqual(self.timeout, 30)
        sent = json.loads(self.request.data)
        self.assertEqual(sent["response_format"], {"type": "json_object"})
        self.assertIn("Scan before receiving", sent["messages"][1]["content"])
        self.assertNotIn(KEY, json.dumps(sent))
        self.assertEqual(self.request.get_header("Authorization"), f"Bearer {KEY}")

    def test_model_env_override(self) -> None:
        with patch.dict(os.environ, {"AI_COACH_MODEL": "x/y"}):
            result = self.call(completion(json.dumps(GOOD)))
        self.assertEqual(result.model, "x/y")

    def assert_rejected(self, response: Any) -> AiCoachError:
        with self.assertRaises(AiCoachError) as caught:
            self.call(response)
        self.assertEqual(caught.exception.status, 502)
        self.assertNotIn(KEY, str(caught.exception) + caught.exception.reason)
        return caught.exception

    def test_bad_json(self) -> None:
        self.assert_rejected(completion("here are drills: {not json"))
        self.assert_rejected(io.BytesIO(b"<html>oops"))
        self.assert_rejected(
            completion(json.dumps({"body": "x", "drills": [GOOD["drills"][0]] * 4}))
        )
        self.assert_rejected(completion(json.dumps({**GOOD, "body": "a" * 1201})))

    def test_banned_word(self) -> None:
        for text in ("Your elite touch", "Some insights", "You failed the turn"):
            self.assert_rejected(completion(json.dumps({**GOOD, "body": text})))

    def test_percent_and_ratings(self) -> None:
        for text in ("You bent 80% of the time", "I'd give that 7/10", "8 out of 10"):
            self.assert_rejected(completion(json.dumps({**GOOD, "body": text})))
        drill = {**GOOD["drills"][0], "how": "Aim for 90 percent accuracy"}
        self.assert_rejected(completion(json.dumps({**GOOD, "drills": [drill]})))

    def test_timeout(self) -> None:
        self.assert_rejected(TimeoutError("timed out"))

    def test_missing_key(self) -> None:
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
            with patch.object(ai_coach, "urlopen") as urlopen:
                with self.assertRaises(AiCoachError):
                    generate_feedback(FEATURES, None)
                urlopen.assert_not_called()

    def test_features_reject_landmarks(self) -> None:
        with self.assertRaises(ValueError):
            PracticeFeatures.model_validate(
                {**FEATURES.model_dump(), "landmarks": [[0.1, 0.2]]}
            )


if __name__ == "__main__":
    unittest.main()
