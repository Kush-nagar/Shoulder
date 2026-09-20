"""Task 20 email templates and Resend transport."""

import json
import unittest
from unittest.mock import patch
from uuid import uuid4

from services.worker import delivery


class _Response:
    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return b'{"id":"resend-message-id"}'


class EmailTemplateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.origin = "https://shoulder.example"
        self.publication = uuid4()
        self.goal = uuid4()
        self.game = uuid4()
        self.player = uuid4()

    def test_evidence_link_opens_the_exact_authenticated_goal_page(self) -> None:
        message = delivery.render_message(
            kind="evidence_ready",
            recipient="player@example.test",
            event_key=f"evidence-ready:{self.publication}",
            origin=self.origin,
            publication_id=self.publication,
            goal_id=self.goal,
        )
        target = (
            f"{self.origin}/player/goals/{self.goal}?publication={self.publication}"
        )
        self.assertEqual(message.target_url, target)
        self.assertIn(target, message.html)
        self.assertIn(target, message.text)

    def test_templates_use_only_fixed_content_free_subjects(self) -> None:
        private = "Player Secret vs Private Opponent: reflection words"
        messages = (
            delivery.render_message(
                kind="evidence_ready",
                recipient="player@example.test",
                event_key=f"evidence-ready:{self.publication}",
                origin=self.origin,
                publication_id=self.publication,
                goal_id=self.goal,
            ),
            delivery.render_message(
                kind="video_ready",
                recipient="coach@example.test",
                event_key=f"video-ready:{self.game}",
                origin=self.origin,
                game_id=self.game,
            ),
            delivery.render_message(
                kind="video_failed",
                recipient="coach@example.test",
                event_key=f"video-failed:{self.game}",
                origin=self.origin,
                game_id=self.game,
            ),
            delivery.render_message(
                kind="reflection_digest",
                recipient="coach@example.test",
                event_key=f"reflection-digest:{self.player}",
                origin=self.origin,
                player_id=self.player,
            ),
        )
        for message in messages:
            with self.subTest(subject=message.subject):
                self.assertNotIn(private, message.subject)
                self.assertNotIn("player", message.subject.lower())
                self.assertNotIn("reflection words", message.subject.lower())
                self.assertLessEqual(len(message.subject), 80)

    def test_rendering_rejects_unknown_or_incomplete_targets(self) -> None:
        with self.assertRaises(delivery.DeliveryError):
            delivery.render_message(
                kind="evidence_ready",
                recipient="player@example.test",
                event_key="evidence-ready:missing",
                origin=self.origin,
            )
        with self.assertRaises(delivery.DeliveryError):
            delivery.render_message(
                kind="unknown",
                recipient="player@example.test",
                event_key="unknown:event",
                origin=self.origin,
            )

    def test_origin_must_be_exact_https_or_explicit_loopback(self) -> None:
        self.assertEqual(
            delivery.verified_origin("https://shoulder.example"),
            "https://shoulder.example",
        )
        for unsafe in (
            "https://shoulder.example/path",
            "https://user@shoulder.example",
            "javascript:alert(1)",
            "http://shoulder.example",
        ):
            with self.subTest(origin=unsafe), self.assertRaises(delivery.DeliveryError):
                delivery.verified_origin(unsafe)
        self.assertEqual(
            delivery.verified_origin("http://127.0.0.1:3000", allow_local_http=True),
            "http://127.0.0.1:3000",
        )


class ResendTransportTests(unittest.TestCase):
    def test_mocked_send_uses_resend_payload_and_event_idempotency_key(self) -> None:
        message = delivery.render_message(
            kind="video_ready",
            recipient="coach@example.test",
            event_key=f"video-ready:{uuid4()}",
            origin="https://shoulder.example",
            game_id=uuid4(),
        )
        with patch(
            "services.worker.delivery.urlopen", return_value=_Response()
        ) as send:
            provider_id = delivery.send_with_resend(
                message,
                api_key="re_test_placeholder",
                sender="Shoulder <updates@shoulder.example>",
            )
        self.assertEqual(provider_id, "resend-message-id")
        request = send.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.resend.com/emails")
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.headers["Idempotency-key"], message.event_key)
        self.assertEqual(request.headers["Authorization"], "Bearer re_test_placeholder")
        payload = json.loads(request.data)
        self.assertEqual(payload["to"], ["coach@example.test"])
        self.assertEqual(payload["subject"], message.subject)
        self.assertEqual(payload["html"], message.html)
        self.assertEqual(payload["text"], message.text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
