"""Block 08P practice/AI-coach shapes (frozen in project-08 contract).

Features are aggregate only: `extra="forbid"` rejects any landmark payload.
"""

from pydantic import BaseModel, ConfigDict, Field


class Percentiles(BaseModel):
    model_config = ConfigDict(extra="forbid")
    p10: float = Field(ge=0, le=180)
    p50: float = Field(ge=0, le=180)
    p90: float = Field(ge=0, le=180)


class StanceWidth(BaseModel):
    model_config = ConfigDict(extra="forbid")
    p50: float = Field(ge=0, le=10)


class PracticeFeatures(BaseModel):
    model_config = ConfigDict(extra="forbid")
    frames_analyzed: int = Field(ge=0, le=9000)  # 10 min at 15 fps
    fps: float = Field(ge=0, le=60)
    duration_ms: int = Field(ge=0, le=600_000)
    knee_flexion_deg: Percentiles
    hip_flexion_deg: Percentiles
    trunk_lean_deg: Percentiles
    head_turns: int = Field(ge=0, le=10_000)
    head_turns_per_min: float = Field(ge=0, le=600)
    stance_width_ratio: StanceWidth
    visibility_mean: float = Field(ge=0, le=1)


class Drill(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=80)
    why: str = Field(min_length=1, max_length=400)
    how: str = Field(min_length=1, max_length=600)


class AiCoachResult(BaseModel):
    body: str = Field(min_length=1, max_length=1200)
    drills: list[Drill] = Field(max_length=3)
    model: str
