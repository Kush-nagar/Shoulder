"""Player practice uploads and on-demand AI coach suggestions (ADR 0021).

Video bytes never pass through the API: the browser PUTs to one presigned URL
and `complete` reads the stored size and type back from storage. The AI coach
receives only aggregate features and the player's active goal title; its
output is filtered by `services.api.ai_coach` and re-validated here before a
row is written. Any upstream failure stores nothing.
"""

import logging
from collections.abc import Callable, Coroutine
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from fastapi.routing import APIRoute
from sqlalchemy.exc import DBAPIError

from services.api import ai_coach, storage
from services.api.auth import authenticated_identity
from services.api.db import user_transaction
from services.api.practice_service import (
    active_goal,
    consume_feedback_quota,
    feedback_model,
    insert_feedback,
    insert_video,
    load_video,
    mark_deleted,
    mark_ready,
    new_video_id,
    own_player_id,
    own_videos,
    video_feedback,
    video_model,
)
from services.api.problems import Problem
from services.api.routes import PRIVATE, unavailable
from services.api.schemas import (
    AiCoachFeedback,
    AiCoachResult,
    PracticeFeatures,
    PracticeUploadSession,
    PracticeVideo,
    PracticeVideoComplete,
    PracticeVideoCreate,
    PracticeVideoDetail,
)
from services.api.video import storage_unavailable

logger = logging.getLogger("shoulder.practice")
BODY_MAX_BYTES = 4096


class BoundedBodyRoute(APIRoute):
    """Refuse an oversized body before FastAPI reads or parses it.

    FastAPI reads the whole body before running dependencies, so the bound has
    to wrap the route handler itself. Every practice request body is small.
    """

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def bounded(request: Request) -> Response:
            too_large = Problem(413, "Those practice features are too large.")
            declared = request.headers.get("content-length")
            if declared is not None and (
                not declared.isdigit() or int(declared) > BODY_MAX_BYTES
            ):
                raise too_large
            body = b""
            async for chunk in request.stream():
                body += chunk
                if len(body) > BODY_MAX_BYTES:
                    raise too_large
            request._body = body  # Starlette's cache; the handler reads it.
            return await handler(request)

        return bounded


router = APIRouter(prefix="/v1/player/practice-videos", route_class=BoundedBodyRoute)


def _not_ready() -> Problem:
    return Problem(409, "That practice video has not finished uploading.")


@router.post(
    "",
    response_model=PracticeUploadSession,
    status_code=201,
    dependencies=PRIVATE,
)
def create_practice_video(
    request: PracticeVideoCreate,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> PracticeUploadSession:
    try:
        with user_transaction(user_id) as connection:
            player_id = own_player_id(connection)
            video_id = new_video_id(connection)
            key = storage.practice_key(video_id, request.content_type)
            insert_video(
                connection,
                video_id=video_id,
                player_id=player_id,
                object_key=key,
                content_type=request.content_type,
                size_bytes=request.size_bytes,
                title=request.title,
            )
            url = storage.sign_put(key, request.content_type, request.size_bytes)
    except storage.StorageError:
        raise storage_unavailable() from None
    except DBAPIError:
        raise unavailable() from None
    return PracticeUploadSession(
        id=video_id,
        upload_url=url,
        content_type=request.content_type,
        expires_in_seconds=storage.PART_URL_SECONDS,
    )


@router.post("/{video_id}/complete", response_model=PracticeVideo, dependencies=PRIVATE)
def complete_practice_video(
    video_id: UUID,
    request: PracticeVideoComplete,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> PracticeVideo:
    try:
        with user_transaction(user_id) as connection:
            video = load_video(connection, video_id, lock=True)
            if video.status == "ready":
                return video_model(video)
            stored = storage.head_media(video.object_key)
            if stored is None:
                raise Problem(
                    409, "The upload has not arrived yet.", "upload-incomplete"
                )
            size, content_type = stored
            if size != video.size_bytes or content_type != video.content_type:
                # What arrived is not what was declared; keep none of it.
                storage.delete_object(video.object_key)
                mark_deleted(connection, video_id)
                mismatch = True
            else:
                mismatch = False
                video = mark_ready(connection, video_id, request.duration_ms)
    except storage.StorageError:
        raise storage_unavailable() from None
    except DBAPIError:
        raise unavailable() from None
    if mismatch:
        raise Problem(
            422,
            "The uploaded file does not match what was declared.",
            "upload-mismatch",
        )
    return video_model(video)


@router.get("", response_model=list[PracticeVideo], dependencies=PRIVATE)
def list_practice_videos(
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> list[PracticeVideo]:
    try:
        with user_transaction(user_id) as connection:
            rows = own_videos(connection, own_player_id(connection))
    except DBAPIError:
        raise unavailable() from None
    return [video_model(row) for row in rows]


@router.get("/{video_id}", response_model=PracticeVideoDetail, dependencies=PRIVATE)
def read_practice_video(
    video_id: UUID,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> PracticeVideoDetail:
    try:
        with user_transaction(user_id) as connection:
            video = load_video(connection, video_id)
        url = None
        if video.status == "ready":
            url = storage.sign_get(video.object_key, storage.PLAYER_GET_URL_SECONDS)
    except storage.StorageError:
        raise storage_unavailable() from None
    except DBAPIError:
        raise unavailable() from None
    return PracticeVideoDetail(
        **video_model(video).model_dump(),
        playback_url=url,
        playback_expires_in_seconds=storage.PLAYER_GET_URL_SECONDS if url else None,
    )


@router.delete("/{video_id}", status_code=204, dependencies=PRIVATE)
def delete_practice_video(
    video_id: UUID,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> Response:
    try:
        with user_transaction(user_id) as connection:
            video = load_video(connection, video_id, lock=True)
            # Object first: a storage failure leaves the row, so a retry can
            # still find the key. The row stays hidden as `deleted` until the
            # sweep re-deletes the key after any live PUT URL has expired.
            storage.delete_object(video.object_key)
            mark_deleted(connection, video_id)
    except storage.StorageError:
        raise storage_unavailable() from None
    except DBAPIError:
        raise unavailable() from None
    return Response(status_code=204)


@router.post(
    "/{video_id}/ai-feedback",
    response_model=AiCoachFeedback,
    status_code=201,
    dependencies=PRIVATE,
)
def request_ai_feedback(
    video_id: UUID,
    features: PracticeFeatures,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> AiCoachFeedback:
    try:
        with user_transaction(user_id) as connection:
            player_id = own_player_id(connection)
            video = load_video(connection, video_id)
            if video.status != "ready":
                raise _not_ready()
            goal = active_goal(connection, player_id)
        # Its own committed transaction, before the model runs: a request that
        # fails upstream still spends quota, so retries cannot bypass it.
        with user_transaction(user_id) as connection:
            consume_feedback_quota(connection, player_id)
    except DBAPIError:
        raise unavailable() from None

    # Outside any transaction: no connection is held while the model runs.
    try:
        generated = ai_coach.generate_feedback(features, goal.title if goal else None)
        result = AiCoachResult.model_validate(generated.model_dump())
    except Exception as error:  # noqa: BLE001 - any upstream failure is a 502
        # `reason` is a fixed internal string (never the key or model text).
        reason = getattr(error, "reason", type(error).__name__)
        logger.warning("ai coach failed: %s", reason)
        raise Problem(
            502, "The AI coach could not answer right now. Try again later."
        ) from None

    try:
        with user_transaction(user_id) as connection:
            row = insert_feedback(
                connection,
                video_id=load_video(connection, video_id).id,
                player_id=player_id,
                goal_id=goal.id if goal else None,
                features=features,
                result=result,
            )
    except DBAPIError:
        raise unavailable() from None
    return feedback_model(row)


@router.get(
    "/{video_id}/ai-feedback",
    response_model=list[AiCoachFeedback],
    dependencies=PRIVATE,
)
def list_ai_feedback(
    video_id: UUID,
    user_id: Annotated[str, Depends(authenticated_identity)],
) -> list[AiCoachFeedback]:
    try:
        with user_transaction(user_id) as connection:
            load_video(connection, video_id)
            rows = video_feedback(connection, video_id)
    except DBAPIError:
        raise unavailable() from None
    return [feedback_model(row) for row in rows]
