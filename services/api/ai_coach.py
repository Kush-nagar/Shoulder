"""AI coach client. Stub owned by W2 (Block 08P); W2 replaces the body."""

from services.api.schemas import AiCoachResult, Drill, PracticeFeatures

__all__ = ["AiCoachResult", "Drill", "PracticeFeatures", "generate_feedback"]


def generate_feedback(
    features: PracticeFeatures, goal_title: str | None
) -> AiCoachResult:
    raise NotImplementedError
