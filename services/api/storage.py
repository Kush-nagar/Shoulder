"""The only module in this service that talks to object storage.

`docs/02-architecture.md` constraint 2: video bytes do not pass through
FastAPI. Nothing here reads or writes an object body. The service creates a
multipart upload, hands the browser one short-lived URL per part, reconciles
what storage actually received, and completes or aborts the upload.

Every signed URL names one object, one HTTP verb, and one expiry. Object keys
are derived from the generated `video.id` and a fixed extension allowlist; a
caller's filename never reaches a key, a path, or a command.
"""

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any
from uuid import UUID

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mypy_boto3_s3.client import S3Client

# `docs/02-architecture.md` fixes the 32 MiB part size; `docs/00-decisions.md`
# leaves it open for Task 8 measurement, so it stays one constant to revise.
PART_SIZE_BYTES = 32 * 1024 * 1024
MAX_UPLOAD_BYTES = 8 * 1024 * 1024 * 1024
MAX_PARTS = MAX_UPLOAD_BYTES // PART_SIZE_BYTES
# S3 rejects any part but the last below 5 MiB, so the part size is also the
# floor for a resumed part; nothing here may sign a smaller one.
MIN_PART_SIZE_BYTES = 5 * 1024 * 1024
# The coach ceiling in `docs/10-security-privacy.md`. Player clip signing is
# five minutes and belongs to Task 18.
PART_URL_SECONDS = 900
GET_URL_SECONDS = 900

# Extension -> stored extension and accepted browser content type. The browser
# MIME is a hint only; `docs/04-api.md` requires probing before trusting it,
# which Task 11 does with ffprobe.
ALLOWED_MEDIA: dict[str, tuple[str, frozenset[str]]] = {
    "mp4": ("mp4", frozenset({"video/mp4"})),
    "m4v": ("m4v", frozenset({"video/x-m4v", "video/mp4"})),
    "mov": ("mov", frozenset({"video/quicktime"})),
}


class StorageError(Exception):
    """Object storage refused or could not answer. Never carries provider text."""


@dataclass(frozen=True)
class StoredPart:
    """One part storage confirms it holds."""

    part_number: int
    etag: str
    size_bytes: int


def original_key(video_id: UUID, extension: str) -> str:
    """`originals/{video_id}/source.{ext}` from `docs/02-architecture.md`.

    The extension comes from `ALLOWED_MEDIA`, not from the request, so the key
    is fully determined by a server-generated UUID.
    """
    if extension not in ALLOWED_MEDIA:
        raise StorageError("unsupported media extension")
    return f"originals/{video_id}/source.{ALLOWED_MEDIA[extension][0]}"


def part_count(size_bytes: int) -> int:
    """Number of 32 MiB parts a file of this size needs, last part shorter."""
    return (size_bytes + PART_SIZE_BYTES - 1) // PART_SIZE_BYTES


def expected_part_size(size_bytes: int, part_number: int) -> int:
    """Byte length the client must PUT for this part number."""
    total = part_count(size_bytes)
    if not 1 <= part_number <= total:
        raise StorageError("part number is outside this upload")
    if part_number < total:
        return PART_SIZE_BYTES
    return size_bytes - PART_SIZE_BYTES * (total - 1)


def bucket() -> str:
    name = os.environ.get("R2_BUCKET")
    if not name:
        raise StorageError("object storage is not configured")
    return name


@lru_cache
def get_client() -> "S3Client":
    """One signing client for the process.

    `signature_version='s3v4'` is explicit because a presigned URL signed any
    other way would not be object-and-verb specific on R2.
    """
    endpoint = os.environ.get("R2_ENDPOINT_URL")
    access_key = os.environ.get("R2_ACCESS_KEY_ID")
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
    if not (endpoint and access_key and secret_key):
        raise StorageError("object storage is not configured")
    client: S3Client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=os.environ.get("R2_REGION", "auto"),
        config=Config(
            signature_version="s3v4",
            # R2 and MinIO both address a bucket by path; a virtual-host style
            # URL would need per-bucket DNS that neither local setup has.
            s3={"addressing_style": "path"},
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=5,
            read_timeout=30,
        ),
    )
    return client


def _call(operation: str, **arguments: Any) -> Any:
    """Run one storage call and reduce any failure to `StorageError`.

    A provider message can name a bucket, a key, or a credential, and
    `docs/10-security-privacy.md` forbids all three in a response or a log.
    """
    try:
        return getattr(get_client(), operation)(**arguments)
    except (ClientError, BotoCoreError) as error:
        raise StorageError(f"storage {operation} failed") from error


def create_multipart(key: str, content_type: str) -> str:
    response = _call(
        "create_multipart_upload",
        Bucket=bucket(),
        Key=key,
        ContentType=content_type,
    )
    upload_id = response.get("UploadId")
    if not upload_id:
        raise StorageError("storage did not return an upload id")
    return str(upload_id)


def sign_part(key: str, upload_id: str, part_number: int) -> str:
    """A presigned PUT for exactly one part of one upload of one object."""
    if not 1 <= part_number <= MAX_PARTS:
        raise StorageError("part number is outside this upload")
    url = _call(
        "generate_presigned_url",
        ClientMethod="upload_part",
        Params={
            "Bucket": bucket(),
            "Key": key,
            "UploadId": upload_id,
            "PartNumber": part_number,
        },
        ExpiresIn=PART_URL_SECONDS,
    )
    return str(url)


def sign_get(key: str, seconds: int = GET_URL_SECONDS) -> str:
    """A presigned GET for exactly one object.

    Capped at the fifteen-minute coach ceiling in
    `docs/10-security-privacy.md`; a caller cannot ask for longer.
    """
    if not 1 <= seconds <= GET_URL_SECONDS:
        raise StorageError("signing lifetime is outside the allowed range")
    url = _call(
        "generate_presigned_url",
        ClientMethod="get_object",
        Params={"Bucket": bucket(), "Key": key},
        ExpiresIn=seconds,
    )
    return str(url)


def list_parts(key: str, upload_id: str) -> list[StoredPart]:
    """What storage actually holds, which is the only trustworthy part list."""
    parts: list[StoredPart] = []
    marker = 0
    while True:
        response = _call(
            "list_parts",
            Bucket=bucket(),
            Key=key,
            UploadId=upload_id,
            PartNumberMarker=marker,
            MaxParts=1000,
        )
        for part in response.get("Parts", []):
            parts.append(
                StoredPart(
                    part_number=int(part["PartNumber"]),
                    etag=str(part["ETag"]).strip('"'),
                    size_bytes=int(part["Size"]),
                )
            )
        if not response.get("IsTruncated"):
            break
        marker = int(response["NextPartNumberMarker"])
    parts.sort(key=lambda part: part.part_number)
    return parts


def complete_multipart(key: str, upload_id: str, parts: list[StoredPart]) -> None:
    _call(
        "complete_multipart_upload",
        Bucket=bucket(),
        Key=key,
        UploadId=upload_id,
        MultipartUpload={
            "Parts": [
                {"PartNumber": part.part_number, "ETag": f'"{part.etag}"'}
                for part in parts
            ]
        },
    )


def abort_multipart(key: str, upload_id: str) -> None:
    """Abort, tolerating an upload storage has already discarded.

    Abort must be safe to repeat: `docs/10-security-privacy.md` schedules
    abandoned uploads for automatic abort, so a coach's abort and a sweeper's
    abort can race.
    """
    try:
        _call("abort_multipart_upload", Bucket=bucket(), Key=key, UploadId=upload_id)
    except StorageError:
        if head_object(key) is not None:
            raise


def head_object(key: str) -> int | None:
    """Stored byte length, or None when the object is absent."""
    try:
        response = getattr(get_client(), "head_object")(Bucket=bucket(), Key=key)
    except ClientError as error:
        status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if status in (403, 404):
            return None
        raise StorageError("storage head_object failed") from error
    except BotoCoreError as error:
        raise StorageError("storage head_object failed") from error
    return int(response["ContentLength"])
