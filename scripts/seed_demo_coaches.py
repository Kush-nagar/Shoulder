"""Seed four synthetic marketplace coaches for the 18+ pilot (Block 10M).

Usage, with the same owner URL Alembic uses:

    MIGRATION_DATABASE_URL=postgresql+psycopg://... \\
        uv run python -m scripts.seed_demo_coaches
    MIGRATION_DATABASE_URL=... uv run python -m scripts.seed_demo_coaches --remove

Each coach is an auth user with an `@shoulder.invalid` address that never
signs in, an adult age attestation, and a `verified` coach profile with
`charges_enabled` and a fake `acct_demo_<n>` Stripe account, so it lists in
`/coaching` without admin review or Stripe onboarding. Bios start with
"Demo coach profile." and hold no contact details; in-person venues are public
places. Booking one still runs Stripe Checkout, which fails for a fake account
in test mode, so these profiles are for browsing only.

Idempotent: existing coaches are kept, and a coach with fewer than six open
future slots gets up to seven fresh ones over the next 14 days, so a rerun
refreshes an expired calendar. Every seed and removal writes a
`marketplace_audit` row. `--remove` deletes the four accounts; the cascade
removes their profiles, slots, and any bookings made against them.
"""

import argparse
import json
import os
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import Connection, create_engine, text

COACHES = [
    {
        "name": "Alex Rivera (demo)",
        "city": "Austin",
        "specialties": ["first_touch", "passing", "scanning"],
        "formats": ["in_person", "online"],
        "rate_cents": 6000,
        "venues": ["Zilker Park Field 3", "Mueller Lake Park Pitch"],
        "hour": 16,
        "bio": "Demo coach profile. Former college midfielder. Sessions work on "
        "receiving under pressure, checking your shoulder before the ball "
        "arrives, and playing forward quickly.",
    },
    {
        "name": "Jordan Blake (demo)",
        "city": "Denver",
        "specialties": ["finishing", "dribbling"],
        "formats": ["in_person"],
        "rate_cents": 7500,
        "venues": ["Washington Park Field 1", "City Park Pitch 4"],
        "hour": 17,
        "bio": "Demo coach profile. Striker coach for adult amateur players. "
        "Lots of repetitions: finishing with both feet, first-time shots, and "
        "beating a defender one against one.",
    },
    {
        "name": "Sam Okafor (demo)",
        "city": "Portland",
        "specialties": ["goalkeeping", "fitness"],
        "formats": ["in_person", "online"],
        "rate_cents": 5000,
        "venues": ["Laurelhurst Park Field", "Riverside Park Field 2"],
        "hour": 15,
        "bio": "Demo coach profile. Goalkeeper coach. Handling, footwork, "
        "distribution and match fitness, planned around your own schedule and "
        "level.",
    },
    {
        "name": "Casey Morgan (demo)",
        "city": "Chicago",
        "specialties": ["tactics", "defending", "scanning"],
        "formats": ["online"],
        "rate_cents": 4000,
        "venues": [],
        "hour": 18,
        "bio": "Demo coach profile. Video sessions on positioning, defending "
        "as a unit, and reading the game. Bring footage from your own matches "
        "to talk through.",
    },
]


def email(number: int) -> str:
    return f"marketplace-demo-{number}@shoulder.invalid"


def audit(
    connection: Connection, action: str, subject_id: object, detail: dict[str, object]
) -> None:
    connection.execute(
        text("""
            INSERT INTO app.marketplace_audit (action, subject_type, subject_id, detail)
            VALUES (:action, 'coach_profile', :id, CAST(:detail AS jsonb))
        """),
        {"action": action, "id": subject_id, "detail": json.dumps(detail)},
    )


def slot_times(number: int, now: datetime) -> list[tuple[datetime, datetime]]:
    """Seven slots across days 1..14, varying hour and length per coach."""
    day = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    hour = COACHES[number - 1]["hour"]
    assert isinstance(hour, int)
    times = []
    for index in range(7):
        start = day + timedelta(days=2 * index + number % 2, hours=hour + index % 2)
        times.append((start, start + timedelta(minutes=60 if index % 3 else 90)))
    return times


def seed_one(connection: Connection, number: int, now: datetime) -> str:
    coach = COACHES[number - 1]
    user_id = connection.execute(
        text("SELECT id FROM auth.users WHERE email = :email"),
        {"email": email(number)},
    ).scalar_one_or_none()
    if user_id is None:
        # Mirrors scripts/seed_demo.py; the sync trigger makes user_account.
        user_id = connection.execute(
            text("""
                INSERT INTO auth.users
                    (id, instance_id, aud, role, email, raw_user_meta_data)
                VALUES (
                    gen_random_uuid(), '00000000-0000-0000-0000-000000000000',
                    'authenticated', 'authenticated', :email,
                    jsonb_build_object('display_name', CAST(:name AS text))
                )
                RETURNING id
            """),
            {"email": email(number), "name": coach["name"]},
        ).scalar_one()
    connection.execute(
        text("""
            INSERT INTO app.age_attestation (user_id, birth_year)
            VALUES (:id, :year) ON CONFLICT (user_id) DO NOTHING
        """),
        {"id": user_id, "year": 1980 + 2 * number},
    )
    profile_id = connection.execute(
        text("SELECT id FROM app.coach_profile WHERE user_id = :id"),
        {"id": user_id},
    ).scalar_one_or_none()
    if profile_id is None:
        profile_id = connection.execute(
            text("""
                INSERT INTO app.coach_profile
                    (user_id, display_name, bio, specialties, city, formats,
                     rate_cents, status, verified_at, stripe_account_id,
                     charges_enabled)
                VALUES (:id, :name, :bio, :specialties, :city, :formats, :rate,
                        'verified', now(), :account, true)
                RETURNING id
            """),
            {
                "id": user_id,
                "name": coach["name"],
                "bio": coach["bio"],
                "specialties": coach["specialties"],
                "city": coach["city"],
                "formats": coach["formats"],
                "rate": coach["rate_cents"],
                "account": f"acct_demo_{number}",
            },
        ).scalar_one()
        audit(connection, "coach_profile.demo_seeded", profile_id, {"demo": number})
    open_slots = connection.execute(
        text("""
            SELECT count(*) FROM app.coach_slot
            WHERE coach_profile_id = :profile AND status = 'open' AND starts_at > now()
        """),
        {"profile": profile_id},
    ).scalar_one()
    if open_slots < 6:
        formats = coach["formats"]
        venues = coach["venues"]
        assert isinstance(formats, list) and isinstance(venues, list)
        for index, (starts, ends) in enumerate(slot_times(number, now)):
            fmt = formats[index % len(formats)]
            connection.execute(
                text("""
                    INSERT INTO app.coach_slot
                        (coach_profile_id, starts_at, ends_at, format, venue)
                    SELECT :profile, :starts, :ends, :format, :venue
                    WHERE NOT EXISTS (
                        SELECT 1 FROM app.coach_slot
                        WHERE coach_profile_id = :profile AND starts_at = :starts
                    )
                """),
                {
                    "profile": profile_id,
                    "starts": starts,
                    "ends": ends,
                    "format": fmt,
                    "venue": venues[index % len(venues)]
                    if fmt == "in_person"
                    else None,
                },
            )
    return str(profile_id)


def seed(url: str) -> list[str]:
    engine = create_engine(url)
    now = datetime.now(UTC)
    try:
        with engine.connect() as connection, connection.begin():
            return [seed_one(connection, n, now) for n in range(1, len(COACHES) + 1)]
    finally:
        engine.dispose()


def remove(url: str) -> int:
    engine = create_engine(url)
    try:
        with engine.connect() as connection, connection.begin():
            emails = [email(n) for n in range(1, len(COACHES) + 1)]
            profiles = (
                connection.execute(
                    text("""
                    SELECT cp.id FROM app.coach_profile cp
                    JOIN app.user_account ua ON ua.id = cp.user_id
                    WHERE ua.email = ANY(:emails)
                """),
                    {"emails": emails},
                )
                .scalars()
                .all()
            )
            for profile_id in profiles:
                audit(connection, "coach_profile.demo_removed", profile_id, {})
            # auth.users -> user_account -> coach_profile -> slots, bookings.
            return connection.execute(
                text("DELETE FROM auth.users WHERE email = ANY(:emails)"),
                {"emails": emails},
            ).rowcount
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed demo marketplace coaches.")
    parser.add_argument("--remove", action="store_true", help="delete the demo coaches")
    arguments = parser.parse_args()
    url = os.environ.get("MIGRATION_DATABASE_URL")
    if not url:
        sys.exit("MIGRATION_DATABASE_URL is required")
    if arguments.remove:
        print(f"removed demo coach accounts: {remove(url)}")
    else:
        for profile_id in seed(url):
            print(f"demo coach profile: {profile_id}")


if __name__ == "__main__":
    main()
