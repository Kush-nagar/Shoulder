"""Replay content-free deletion markers before restored product access opens."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text

from services.api import storage
from services.api.db import operator_transaction

FIELDS = {
    "manifest_id",
    "kind",
    "team_id",
    "target_id",
    "requested_at",
    "backup_expires_at",
}
KINDS = {
    "player_erasure",
    "season_expiry",
    "video_source",
    "video_all",
    "export_cleanup",
    "reflection_erasure",
}


def validated(record: dict[str, Any], key: str) -> dict[str, Any]:
    if set(record) != FIELDS or record.get("kind") not in KINDS:
        raise ValueError("invalid deletion suppression record")
    manifest_id = UUID(str(record["manifest_id"]))
    team_id = UUID(str(record["team_id"]))
    target = record["target_id"]
    target_id = UUID(str(target)) if target is not None else None
    if record["kind"] == "season_expiry":
        if target_id is not None:
            raise ValueError("invalid deletion suppression record")
    elif target_id is None:
        raise ValueError("invalid deletion suppression record")
    requested_at = datetime.fromisoformat(str(record["requested_at"]))
    backup_expires_at = datetime.fromisoformat(str(record["backup_expires_at"]))
    if requested_at.tzinfo is None or backup_expires_at.tzinfo is None:
        raise ValueError("invalid deletion suppression record")
    if key != storage.deletion_ledger_key(manifest_id):
        raise ValueError("invalid deletion suppression record")
    return {
        "manifest_id": manifest_id,
        "kind": record["kind"],
        "team_id": team_id,
        "target_id": target_id,
        "requested_at": requested_at,
        "backup_expires_at": backup_expires_at,
    }


def main() -> int:
    replayed = 0
    for key in storage.list_deletion_suppressions():
        record = validated(storage.read_deletion_suppression(key), key)
        with operator_transaction() as connection:
            connection.execute(
                text("""
                    SELECT private.replay_deletion_suppression(
                        :manifest_id, :kind, :team_id, :target_id,
                        :requested_at, :backup_expires_at
                    )
                """),
                record,
            )
        replayed += 1
    print(f"Replayed {replayed} deletion suppression record(s).")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
