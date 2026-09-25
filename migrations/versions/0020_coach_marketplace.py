"""Coach marketplace phases 2-3: adults only, test mode (Block 10M)

Revision ID: 0020_coach_marketplace
Revises: 0019_team_leaderboard

Independent coaches create a profile, upload a background-check document, and
wait for a platform admin to verify them. Adults (a birth-year attestation of
18+) browse verified coaches through definer functions that return public
columns only, and book a slot. Every state transition that matters (verify,
book, confirm, cancel, expire) runs inside a definer function that locks the
slot before the booking, so two bookings of one slot cannot both win. Every
status change appends to `marketplace_audit`, which nobody may update or
delete. The whole surface is inert unless the API sets `MARKETPLACE_ENABLED`.
"""

# ruff: noqa: E501 -- SQL stays aligned with the reviewed database statements.

from alembic import op

revision = "0020_coach_marketplace"
down_revision = "0019_team_leaderboard"
branch_labels = None
depends_on = None

MIGRATION_ROLE = "shoulder_migration"
API_ROLE = "shoulder_api"
WORKER_ROLE = "shoulder_worker"
OPERATOR_ROLE = "shoulder_operator"

TABLES = (
    "platform_admin",
    "age_attestation",
    "coach_profile",
    "coach_document",
    "coach_slot",
    "coach_booking",
    "marketplace_report",
    "marketplace_audit",
)
# signature -> roles granted EXECUTE (none: trigger functions)
FUNCTIONS: dict[str, tuple[str, ...]] = {
    "private.is_platform_admin()": (API_ROLE,),
    "private.is_adult()": (API_ROLE,),
    "private.attest_age(integer)": (API_ROLE,),
    "private.marketplace_coaches(text,text)": (API_ROLE,),
    "private.marketplace_coach_slots(uuid)": (API_ROLE,),
    "private.write_marketplace_audit(text,text,uuid,jsonb)": (API_ROLE,),
    "private.audit_marketplace_status()": (),
    "private.coach_profile_rereview()": (),
    "private.set_coach_profile_status(uuid,text,text)": (API_ROLE,),
    "private.set_coach_charges_enabled(text,boolean)": (API_ROLE,),
    "private.expire_marketplace_holds()": (API_ROLE, WORKER_ROLE),
    "private.book_coach_slot(uuid,text)": (API_ROLE,),
    "private.attach_booking_checkout(uuid,text)": (API_ROLE,),
    "private.confirm_booking_payment(text,text)": (API_ROLE,),
    "private.expire_booking_checkout(text)": (API_ROLE,),
    "private.cancel_coach_booking(uuid,integer)": (API_ROLE,),
    "private.player_booking_list()": (API_ROLE,),
    "private.coach_booking_list()": (API_ROLE,),
}

OWNS_PROFILE = """EXISTS (
    SELECT 1 FROM app.coach_profile p
    WHERE p.id = coach_profile_id AND p.user_id = private.current_user_id()
)"""
SPECIALTIES = (
    "'scanning','first_touch','passing','finishing','dribbling','defending',"
    "'goalkeeping','fitness','tactics'"
)


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.platform_admin (
            user_id uuid PRIMARY KEY
                REFERENCES app.user_account (id) ON DELETE CASCADE,
            granted_at timestamptz NOT NULL DEFAULT now(),
            granted_by uuid
        )
    """)
    op.execute("""
        CREATE TABLE app.age_attestation (
            user_id uuid PRIMARY KEY
                REFERENCES app.user_account (id) ON DELETE CASCADE,
            birth_year integer NOT NULL
                CONSTRAINT age_attestation_birth_year CHECK (
                    birth_year BETWEEN 1900 AND extract(year FROM now())::integer
                ),
            attested_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(f"""
        CREATE TABLE app.coach_profile (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL UNIQUE
                REFERENCES app.user_account (id) ON DELETE CASCADE,
            display_name text NOT NULL
                CONSTRAINT coach_profile_display_name
                    CHECK (char_length(display_name) BETWEEN 2 AND 60),
            bio text NOT NULL DEFAULT ''
                CONSTRAINT coach_profile_bio CHECK (char_length(bio) <= 600),
            specialties text[] NOT NULL
                CONSTRAINT coach_profile_specialties CHECK (
                    cardinality(specialties) BETWEEN 1 AND 5
                    AND specialties <@ ARRAY[{SPECIALTIES}]::text[]
                ),
            city text NOT NULL
                CONSTRAINT coach_profile_city
                    CHECK (char_length(city) BETWEEN 2 AND 80),
            formats text[] NOT NULL
                CONSTRAINT coach_profile_formats CHECK (
                    cardinality(formats) >= 1
                    AND formats <@ ARRAY['in_person','online']::text[]
                ),
            rate_cents integer NOT NULL
                CONSTRAINT coach_profile_rate CHECK (rate_cents BETWEEN 1000 AND 50000),
            status text NOT NULL DEFAULT 'draft'
                CONSTRAINT coach_profile_status CHECK (
                    status IN ('draft','pending_review','verified','suspended','rejected')
                ),
            review_note text
                CONSTRAINT coach_profile_review_note CHECK (char_length(review_note) <= 500),
            verified_at timestamptz,
            verified_by uuid,
            stripe_account_id text,
            charges_enabled boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX coach_profile_status_idx ON app.coach_profile (status)")
    op.execute("""
        CREATE TABLE app.coach_document (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            coach_profile_id uuid NOT NULL
                REFERENCES app.coach_profile (id) ON DELETE CASCADE,
            kind text NOT NULL
                CONSTRAINT coach_document_kind
                    CHECK (kind IN ('background_check','id','certification')),
            object_key text NOT NULL UNIQUE,
            content_type text NOT NULL
                CONSTRAINT coach_document_content_type CHECK (
                    content_type IN ('application/pdf','image/jpeg','image/png')
                ),
            size_bytes integer NOT NULL
                CONSTRAINT coach_document_size CHECK (size_bytes BETWEEN 1 AND 10485760),
            uploaded_at timestamptz,
            status text NOT NULL DEFAULT 'uploading'
                CONSTRAINT coach_document_status CHECK (status IN ('uploading','ready')),
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX coach_document_profile_idx ON app.coach_document (coach_profile_id)"
    )
    op.execute("""
        CREATE TABLE app.coach_slot (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            coach_profile_id uuid NOT NULL
                REFERENCES app.coach_profile (id) ON DELETE CASCADE,
            starts_at timestamptz NOT NULL,
            ends_at timestamptz NOT NULL,
            format text NOT NULL
                CONSTRAINT coach_slot_format CHECK (format IN ('in_person','online')),
            venue text
                CONSTRAINT coach_slot_venue CHECK (char_length(venue) <= 120),
            status text NOT NULL DEFAULT 'open'
                CONSTRAINT coach_slot_status
                    CHECK (status IN ('open','held','booked','cancelled')),
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT coach_slot_duration CHECK (
                ends_at > starts_at
                AND ends_at - starts_at BETWEEN interval '30 minutes' AND interval '3 hours'
            ),
            -- In person needs a public venue named up front; never a home.
            CONSTRAINT coach_slot_venue_required
                CHECK (format = 'online' OR char_length(venue) >= 2)
        )
    """)
    op.execute(
        "CREATE INDEX coach_slot_profile_idx"
        " ON app.coach_slot (coach_profile_id, starts_at)"
    )
    op.execute("""
        CREATE TABLE app.coach_booking (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            slot_id uuid NOT NULL UNIQUE
                REFERENCES app.coach_slot (id) ON DELETE CASCADE,
            coach_profile_id uuid NOT NULL
                REFERENCES app.coach_profile (id) ON DELETE CASCADE,
            player_user_id uuid NOT NULL
                REFERENCES app.user_account (id) ON DELETE CASCADE,
            status text NOT NULL DEFAULT 'pending_payment'
                CONSTRAINT coach_booking_status CHECK (status IN (
                    'pending_payment','confirmed','cancelled_by_player',
                    'cancelled_by_coach','expired','completed'
                )),
            price_cents integer NOT NULL
                CONSTRAINT coach_booking_price CHECK (price_cents > 0),
            platform_fee_cents integer NOT NULL
                CONSTRAINT coach_booking_fee
                    CHECK (platform_fee_cents BETWEEN 0 AND price_cents),
            refund_cents integer NOT NULL DEFAULT 0
                CONSTRAINT coach_booking_refund
                    CHECK (refund_cents BETWEEN 0 AND price_cents),
            note text
                CONSTRAINT coach_booking_note CHECK (char_length(note) <= 280),
            stripe_checkout_session_id text UNIQUE,
            stripe_payment_intent_id text,
            hold_expires_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            cancelled_at timestamptz
        )
    """)
    op.execute(
        "CREATE INDEX coach_booking_profile_idx ON app.coach_booking (coach_profile_id)"
    )
    op.execute(
        "CREATE INDEX coach_booking_player_idx ON app.coach_booking (player_user_id)"
    )
    op.execute(
        "CREATE INDEX coach_booking_hold_idx ON app.coach_booking (hold_expires_at)"
        " WHERE status = 'pending_payment'"
    )
    op.execute("""
        CREATE TABLE app.marketplace_report (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            reporter_user_id uuid NOT NULL
                REFERENCES app.user_account (id) ON DELETE CASCADE,
            coach_profile_id uuid NOT NULL
                REFERENCES app.coach_profile (id) ON DELETE CASCADE,
            booking_id uuid REFERENCES app.coach_booking (id) ON DELETE SET NULL,
            reason text NOT NULL
                CONSTRAINT marketplace_report_reason
                    CHECK (char_length(reason) BETWEEN 10 AND 1000),
            status text NOT NULL DEFAULT 'open'
                CONSTRAINT marketplace_report_status CHECK (status IN ('open','resolved')),
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX marketplace_report_reporter_idx"
        " ON app.marketplace_report (reporter_user_id)"
    )
    op.execute(
        "CREATE INDEX marketplace_report_profile_idx"
        " ON app.marketplace_report (coach_profile_id, status)"
    )
    op.execute(
        "CREATE INDEX marketplace_report_booking_idx ON app.marketplace_report (booking_id)"
    )
    op.execute("""
        CREATE TABLE app.marketplace_audit (
            id bigserial PRIMARY KEY,
            actor_user_id uuid,
            action text NOT NULL,
            subject_type text,
            subject_id uuid,
            detail jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX marketplace_audit_subject_idx"
        " ON app.marketplace_audit (subject_id, created_at)"
    )

    for table in TABLES:
        op.execute(f"ALTER TABLE app.{table} OWNER TO {MIGRATION_ROLE}")
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_owner_maintenance ON app.{table}
                FOR ALL TO {MIGRATION_ROLE} USING (true) WITH CHECK (true)
        """)
        # Reads only; every write below is either a narrow column grant under
        # a policy, or a definer function.
        op.execute(f"GRANT SELECT ON app.{table} TO {API_ROLE}")
    op.execute(
        f"ALTER SEQUENCE app.marketplace_audit_id_seq OWNER TO {MIGRATION_ROLE}"
    )

    # The definer helpers the policies are written in terms of come first.
    op.execute("""
        CREATE FUNCTION private.is_platform_admin() RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT EXISTS (
                SELECT 1 FROM app.platform_admin a
                WHERE a.user_id = private.current_user_id()
            )
        $$
    """)
    # ponytail: year-only attestation, as frozen. Someone born late in the
    # cut-off year passes a few months early; a date of birth closes that.
    op.execute("""
        CREATE FUNCTION private.is_adult() RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT EXISTS (
                SELECT 1 FROM app.age_attestation a
                WHERE a.user_id = private.current_user_id()
                  AND a.birth_year <= extract(year FROM now())::integer - 18
            )
        $$
    """)

    def policy(table: str, suffix: str, verb: str, using: str | None, check: str | None) -> None:
        clauses = (f" USING ({using})" if using else "") + (
            f" WITH CHECK ({check})" if check else ""
        )
        op.execute(
            f"CREATE POLICY {table}_{suffix} ON app.{table}"
            f" FOR {verb} TO {API_ROLE}{clauses}"
        )

    me = "private.current_user_id()"
    admin = "private.is_platform_admin()"
    policy("platform_admin", "self_select", "SELECT", f"user_id = {me}", None)
    policy("age_attestation", "self_select", "SELECT", f"user_id = {me}", None)

    policy("coach_profile", "owner_select", "SELECT", f"user_id = {me}", None)
    policy("coach_profile", "admin_select", "SELECT", admin, None)
    # Only adults may coach. A new row is always a draft: status, review and
    # Stripe columns are not in the insert grant and keep their defaults.
    policy(
        "coach_profile", "owner_insert", "INSERT", None,
        f"user_id = {me} AND private.is_adult()",
    )  # fmt: skip
    policy("coach_profile", "owner_update", "UPDATE", f"user_id = {me}", f"user_id = {me}")
    op.execute(
        "GRANT INSERT (user_id, display_name, bio, specialties, city, formats,"
        f" rate_cents) ON app.coach_profile TO {API_ROLE}"
    )
    # Status, review, and charges_enabled change only in definer functions.
    op.execute(
        "GRANT UPDATE (display_name, bio, specialties, city, formats, rate_cents,"
        f" stripe_account_id, updated_at) ON app.coach_profile TO {API_ROLE}"
    )

    policy("coach_document", "owner_select", "SELECT", OWNS_PROFILE, None)
    policy("coach_document", "admin_select", "SELECT", admin, None)
    policy("coach_document", "owner_insert", "INSERT", None, f"{OWNS_PROFILE} AND status = 'uploading'")
    policy("coach_document", "owner_update", "UPDATE", OWNS_PROFILE, OWNS_PROFILE)
    policy("coach_document", "owner_delete", "DELETE", OWNS_PROFILE, None)
    op.execute(
        "GRANT INSERT (id, coach_profile_id, kind, object_key, content_type,"
        f" size_bytes) ON app.coach_document TO {API_ROLE}"
    )
    op.execute(f"GRANT UPDATE (status, uploaded_at) ON app.coach_document TO {API_ROLE}")
    op.execute(f"GRANT DELETE ON app.coach_document TO {API_ROLE}")

    policy("coach_slot", "owner_select", "SELECT", OWNS_PROFILE, None)
    policy("coach_slot", "owner_insert", "INSERT", None, f"{OWNS_PROFILE} AND status = 'open'")
    # The one direct slot transition: an open slot is withdrawn. Held and
    # booked slots move only with their booking, inside definer functions.
    policy(
        "coach_slot", "owner_update", "UPDATE",
        f"{OWNS_PROFILE} AND status = 'open'",
        f"{OWNS_PROFILE} AND status IN ('open', 'cancelled')",
    )  # fmt: skip
    op.execute(
        "GRANT INSERT (coach_profile_id, starts_at, ends_at, format, venue)"
        f" ON app.coach_slot TO {API_ROLE}"
    )
    op.execute(f"GRANT UPDATE (status) ON app.coach_slot TO {API_ROLE}")

    # Bookings are read-only to the runtime role; players read their own, a
    # coach reads those on their profile, an admin reads all.
    policy("coach_booking", "player_select", "SELECT", f"player_user_id = {me}", None)
    policy("coach_booking", "coach_select", "SELECT", OWNS_PROFILE, None)
    policy("coach_booking", "admin_select", "SELECT", admin, None)

    policy("marketplace_report", "reporter_select", "SELECT", f"reporter_user_id = {me}", None)
    policy("marketplace_report", "admin_select", "SELECT", admin, None)
    # A report may cite only the reporter's own booking with that coach.
    policy(
        "marketplace_report", "reporter_insert", "INSERT", None,
        f"""reporter_user_id = {me} AND private.is_adult() AND (
            booking_id IS NULL OR EXISTS (
                SELECT 1 FROM app.coach_booking b
                WHERE b.id = booking_id AND b.player_user_id = {me}
                  AND b.coach_profile_id = marketplace_report.coach_profile_id
            )
        )""",
    )  # fmt: skip
    policy("marketplace_report", "admin_update", "UPDATE", admin, admin)
    op.execute(
        "GRANT INSERT (reporter_user_id, coach_profile_id, booking_id, reason)"
        f" ON app.marketplace_report TO {API_ROLE}"
    )
    op.execute(f"GRANT UPDATE (status) ON app.marketplace_report TO {API_ROLE}")

    # Append-only: admins read; inserts come from definer helpers only.
    policy("marketplace_audit", "admin_select", "SELECT", admin, None)

    op.execute("""
        CREATE FUNCTION private.write_marketplace_audit(
            p_action text, p_subject_type text, p_subject_id uuid, p_detail jsonb
        ) RETURNS void
        LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = '' AS $$
            INSERT INTO app.marketplace_audit
                (actor_user_id, action, subject_type, subject_id, detail)
            VALUES (private.current_user_id(), p_action, p_subject_type,
                    p_subject_id, p_detail)
        $$
    """)
    op.execute("""
        CREATE FUNCTION private.audit_marketplace_status() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        BEGIN
            IF TG_OP = 'INSERT' OR NEW.status IS DISTINCT FROM OLD.status THEN
                PERFORM private.write_marketplace_audit(
                    TG_TABLE_NAME || '.' || NEW.status, TG_TABLE_NAME, NEW.id,
                    pg_catalog.jsonb_build_object(
                        'from', CASE WHEN TG_OP = 'UPDATE' THEN OLD.status END,
                        'to', NEW.status
                    )
                );
            END IF;
            RETURN NULL;
        END $$
    """)
    for table in ("coach_profile", "coach_slot", "coach_booking", "marketplace_report"):
        op.execute(f"""
            CREATE TRIGGER {table}_audit_status
                AFTER INSERT OR UPDATE ON app.{table}
                FOR EACH ROW EXECUTE FUNCTION private.audit_marketplace_status()
        """)

    # A verified coach who changes what players pay for or read goes back to
    # review. A trigger, so no code path can skip it.
    op.execute("""
        CREATE FUNCTION private.coach_profile_rereview() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        BEGIN
            IF OLD.status = 'verified' AND (
                NEW.rate_cents IS DISTINCT FROM OLD.rate_cents
                OR NEW.specialties IS DISTINCT FROM OLD.specialties
                OR NEW.bio IS DISTINCT FROM OLD.bio
            ) THEN
                NEW.status := 'pending_review';
            END IF;
            NEW.updated_at := now();
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER coach_profile_rereview
            BEFORE UPDATE ON app.coach_profile
            FOR EACH ROW EXECUTE FUNCTION private.coach_profile_rereview()
    """)

    # Once set, an attestation may not make the account older: a minor cannot
    # re-attest their way into the adult marketplace. Younger is allowed.
    op.execute("""
        CREATE FUNCTION private.attest_age(p_birth_year integer) RETURNS integer
        LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = '' AS $$
        DECLARE
            v_user uuid := private.current_user_id();
            v_year integer;
        BEGIN
            IF v_user IS NULL THEN
                RAISE EXCEPTION 'no identity' USING ERRCODE = '42501';
            END IF;
            SELECT birth_year INTO v_year FROM app.age_attestation
            WHERE user_id = v_user FOR UPDATE;
            IF FOUND AND p_birth_year < v_year THEN
                RAISE EXCEPTION 'age cannot be raised' USING ERRCODE = '55000';
            END IF;
            INSERT INTO app.age_attestation (user_id, birth_year) VALUES (v_user, p_birth_year)
            ON CONFLICT (user_id) DO UPDATE
                SET birth_year = excluded.birth_year, attested_at = now();
            PERFORM private.write_marketplace_audit(
                'age_attestation.set', 'user_account', v_user,
                pg_catalog.jsonb_build_object('birth_year', p_birth_year)
            );
            RETURN p_birth_year;
        END $$
    """)

    # Browsing: adults only; verified, Stripe-ready coaches with no open
    # report. Public columns only: never user_id, email, Stripe ids, notes.
    listed = """
        cp.status = 'verified' AND cp.charges_enabled
        AND cp.stripe_account_id IS NOT NULL
        AND NOT EXISTS (
            SELECT 1 FROM app.marketplace_report r
            WHERE r.coach_profile_id = cp.id AND r.status = 'open'
        )
        AND private.is_adult()
    """
    op.execute(f"""
        CREATE FUNCTION private.marketplace_coaches(p_specialty text, p_city text)
        RETURNS TABLE (
            id uuid, display_name text, bio text, specialties text[], city text,
            formats text[], rate_cents integer, verified_at timestamptz
        )
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT cp.id, cp.display_name, cp.bio, cp.specialties, cp.city,
                   cp.formats, cp.rate_cents, cp.verified_at
            FROM app.coach_profile cp
            WHERE {listed}
              AND (p_specialty IS NULL OR p_specialty = ANY (cp.specialties))
              AND (p_city IS NULL OR lower(cp.city) = lower(btrim(p_city)))
            ORDER BY cp.verified_at DESC, cp.id
        $$
    """)
    op.execute(f"""
        CREATE FUNCTION private.marketplace_coach_slots(p_coach_profile_id uuid)
        RETURNS TABLE (
            id uuid, starts_at timestamptz, ends_at timestamptz, format text, venue text
        )
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT s.id, s.starts_at, s.ends_at, s.format, s.venue
            FROM app.coach_slot s
            JOIN app.coach_profile cp ON cp.id = s.coach_profile_id
            WHERE cp.id = p_coach_profile_id AND {listed}
              AND s.status = 'open' AND s.starts_at > now()
            ORDER BY s.starts_at, s.id
        $$
    """)

    # Admin: approve/reject a pending profile, suspend/reinstate a verified
    # one. Owner: submit a draft or rejected profile once a background check
    # is ready. Anything else is refused.
    op.execute("""
        CREATE FUNCTION private.set_coach_profile_status(
            p_profile_id uuid, p_status text, p_note text
        ) RETURNS text
        LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = '' AS $$
        DECLARE
            v_user uuid := private.current_user_id();
            v_profile app.coach_profile%ROWTYPE;
        BEGIN
            SELECT * INTO v_profile FROM app.coach_profile
            WHERE id = p_profile_id FOR UPDATE;
            IF NOT FOUND OR v_user IS NULL THEN
                RAISE EXCEPTION 'no such profile' USING ERRCODE = 'P0002';
            END IF;
            IF private.is_platform_admin() AND v_profile.user_id <> v_user THEN
                IF NOT (
                    (v_profile.status = 'pending_review' AND p_status IN ('verified', 'rejected'))
                    OR (v_profile.status = 'verified' AND p_status = 'suspended')
                    OR (v_profile.status = 'suspended' AND p_status = 'verified')
                ) THEN
                    RAISE EXCEPTION 'transition refused' USING ERRCODE = '55000';
                END IF;
                UPDATE app.coach_profile SET
                    status = p_status,
                    review_note = p_note,
                    verified_at = CASE WHEN p_status = 'verified' THEN now() ELSE verified_at END,
                    verified_by = CASE WHEN p_status = 'verified' THEN v_user ELSE verified_by END
                WHERE id = p_profile_id;
                PERFORM private.write_marketplace_audit(
                    'coach_profile.decision', 'coach_profile', p_profile_id,
                    pg_catalog.jsonb_build_object('to', p_status, 'note', p_note)
                );
            ELSIF v_profile.user_id = v_user THEN
                IF p_status <> 'pending_review' OR v_profile.status NOT IN ('draft', 'rejected') THEN
                    RAISE EXCEPTION 'transition refused' USING ERRCODE = '55000';
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM app.coach_document d
                    WHERE d.coach_profile_id = p_profile_id
                      AND d.kind = 'background_check' AND d.status = 'ready'
                ) THEN
                    RAISE EXCEPTION 'background check required' USING ERRCODE = '23514';
                END IF;
                UPDATE app.coach_profile SET status = 'pending_review' WHERE id = p_profile_id;
            ELSE
                RAISE EXCEPTION 'no such profile' USING ERRCODE = 'P0002';
            END IF;
            RETURN p_status;
        END $$
    """)
    # Called only from a signature-verified Stripe `account.updated` event.
    op.execute("""
        CREATE FUNCTION private.set_coach_charges_enabled(p_account text, p_enabled boolean)
        RETURNS void
        LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = '' AS $$
            UPDATE app.coach_profile SET charges_enabled = p_enabled
            WHERE stripe_account_id = p_account AND charges_enabled <> p_enabled
        $$
    """)

    # Lock order everywhere: slot, then booking. SKIP LOCKED here, so the
    # sweep never waits on a booking in progress and cannot deadlock with it.
    op.execute("""
        CREATE FUNCTION private.expire_marketplace_holds() RETURNS integer
        LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = '' AS $$
        DECLARE
            v_count integer := 0;
            r record;
        BEGIN
            FOR r IN
                SELECT b.id AS booking_id, b.slot_id
                FROM app.coach_booking b JOIN app.coach_slot s ON s.id = b.slot_id
                WHERE b.status = 'pending_payment' AND b.hold_expires_at <= now()
                FOR UPDATE OF s, b SKIP LOCKED
            LOOP
                UPDATE app.coach_booking SET status = 'expired', updated_at = now()
                WHERE id = r.booking_id;
                UPDATE app.coach_slot SET status = 'open'
                WHERE id = r.slot_id AND status = 'held';
                v_count := v_count + 1;
            END LOOP;
            RETURN v_count;
        END $$
    """)

    # SQLSTATEs: 42501 not allowed (not adult, own slot), P0002 not bookable
    # (missing, past, cancelled, coach not listed), 23505 already taken.
    op.execute("""
        CREATE FUNCTION private.book_coach_slot(p_slot_id uuid, p_note text)
        RETURNS TABLE (
            booking_id uuid, price_cents integer, platform_fee_cents integer,
            stripe_account_id text, coach_display_name text,
            starts_at timestamptz, ends_at timestamptz
        )
        LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = '' AS $$
        #variable_conflict use_column
        DECLARE
            v_user uuid := private.current_user_id();
            v_slot app.coach_slot%ROWTYPE;
            v_coach app.coach_profile%ROWTYPE;
            v_price integer;
            v_fee integer;
            v_id uuid;
        BEGIN
            IF v_user IS NULL OR NOT private.is_adult() THEN
                RAISE EXCEPTION 'adults only' USING ERRCODE = '42501';
            END IF;
            PERFORM private.expire_marketplace_holds();
            SELECT * INTO v_slot FROM app.coach_slot s WHERE s.id = p_slot_id FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'not bookable' USING ERRCODE = 'P0002';
            END IF;
            SELECT * INTO v_coach FROM app.coach_profile cp WHERE cp.id = v_slot.coach_profile_id;
            IF v_coach.user_id = v_user THEN
                RAISE EXCEPTION 'own slot' USING ERRCODE = '42501';
            END IF;
            IF v_coach.status <> 'verified' OR NOT v_coach.charges_enabled
               OR v_coach.stripe_account_id IS NULL
               OR v_slot.status = 'cancelled' OR v_slot.starts_at <= now()
               OR EXISTS (
                   SELECT 1 FROM app.marketplace_report r
                   WHERE r.coach_profile_id = v_coach.id AND r.status = 'open'
               ) THEN
                RAISE EXCEPTION 'not bookable' USING ERRCODE = 'P0002';
            END IF;
            IF v_slot.status <> 'open' THEN
                RAISE EXCEPTION 'taken' USING ERRCODE = '23505';
            END IF;
            v_price := round(
                v_coach.rate_cents * extract(epoch FROM v_slot.ends_at - v_slot.starts_at) / 3600
            )::integer;
            v_fee := round(v_price * 0.10)::integer;
            -- slot_id is unique; an expired, never-paid hold is reused.
            INSERT INTO app.coach_booking AS b (
                slot_id, coach_profile_id, player_user_id, price_cents,
                platform_fee_cents, note, hold_expires_at
            ) VALUES (
                p_slot_id, v_coach.id, v_user, v_price, v_fee, p_note,
                now() + interval '15 minutes'
            )
            ON CONFLICT (slot_id) DO UPDATE SET
                player_user_id = excluded.player_user_id,
                status = 'pending_payment',
                price_cents = excluded.price_cents,
                platform_fee_cents = excluded.platform_fee_cents,
                refund_cents = 0,
                note = excluded.note,
                stripe_checkout_session_id = NULL,
                stripe_payment_intent_id = NULL,
                hold_expires_at = excluded.hold_expires_at,
                created_at = now(), updated_at = now(), cancelled_at = NULL
            WHERE b.status = 'expired'
            RETURNING b.id INTO v_id;
            IF v_id IS NULL THEN
                RAISE EXCEPTION 'taken' USING ERRCODE = '23505';
            END IF;
            UPDATE app.coach_slot SET status = 'held' WHERE id = p_slot_id;
            RETURN QUERY SELECT v_id, v_price, v_fee, v_coach.stripe_account_id,
                v_coach.display_name, v_slot.starts_at, v_slot.ends_at;
        END $$
    """)
    op.execute("""
        CREATE FUNCTION private.attach_booking_checkout(p_booking_id uuid, p_session text)
        RETURNS void
        LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = '' AS $$
        BEGIN
            UPDATE app.coach_booking SET stripe_checkout_session_id = p_session,
                updated_at = now()
            WHERE id = p_booking_id AND player_user_id = private.current_user_id()
              AND status = 'pending_payment' AND stripe_checkout_session_id IS NULL;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'no such hold' USING ERRCODE = 'P0002';
            END IF;
        END $$
    """)
    # Webhook `checkout.session.completed`. Returns 'confirmed' (now or
    # already), 'ignored' (paid, then cancelled with its own refund), or
    # 'refund' (nothing to confirm: late payment for a hold that lapsed and was
    # re-booked, or a coach cancelled during checkout). Idempotent.
    op.execute("""
        CREATE FUNCTION private.confirm_booking_payment(p_session text, p_payment_intent text)
        RETURNS text
        LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = '' AS $$
        DECLARE
            v_slot app.coach_slot%ROWTYPE;
            v_booking app.coach_booking%ROWTYPE;
        BEGIN
            SELECT s.* INTO v_slot FROM app.coach_slot s
            JOIN app.coach_booking b ON b.slot_id = s.id
            WHERE b.stripe_checkout_session_id = p_session
            FOR UPDATE OF s;
            IF NOT FOUND THEN RETURN 'refund'; END IF;
            SELECT * INTO v_booking FROM app.coach_booking
            WHERE slot_id = v_slot.id FOR UPDATE;
            IF v_booking.stripe_checkout_session_id IS DISTINCT FROM p_session THEN
                RETURN 'refund';
            END IF;
            IF v_booking.status IN ('confirmed', 'completed') THEN RETURN 'confirmed'; END IF;
            IF v_booking.status = 'pending_payment' OR (
                v_booking.status = 'expired' AND v_slot.status = 'open'
                AND v_slot.starts_at > now()
            ) THEN
                UPDATE app.coach_booking SET status = 'confirmed',
                    stripe_payment_intent_id = p_payment_intent, updated_at = now()
                WHERE id = v_booking.id;
                UPDATE app.coach_slot SET status = 'booked' WHERE id = v_slot.id;
                RETURN 'confirmed';
            END IF;
            IF v_booking.status LIKE 'cancelled_by_%'
               AND v_booking.stripe_payment_intent_id IS NOT NULL THEN
                RETURN 'ignored';
            END IF;
            UPDATE app.coach_booking SET stripe_payment_intent_id = p_payment_intent,
                updated_at = now()
            WHERE id = v_booking.id;
            RETURN 'refund';
        END $$
    """)
    op.execute("""
        CREATE FUNCTION private.expire_booking_checkout(p_session text) RETURNS void
        LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = '' AS $$
        DECLARE
            v_slot_id uuid;
        BEGIN
            SELECT s.id INTO v_slot_id FROM app.coach_slot s
            JOIN app.coach_booking b ON b.slot_id = s.id
            WHERE b.stripe_checkout_session_id = p_session
            FOR UPDATE OF s;
            IF NOT FOUND THEN RETURN; END IF;
            UPDATE app.coach_booking SET status = 'expired', updated_at = now()
            WHERE slot_id = v_slot_id AND stripe_checkout_session_id = p_session
              AND status = 'pending_payment';
            IF FOUND THEN
                UPDATE app.coach_slot SET status = 'open'
                WHERE id = v_slot_id AND status = 'held';
            END IF;
        END $$
    """)
    # The caller's role on the booking picks the status. The API computes the
    # refund under the 24-hour rule; this clamps it and returns what to refund.
    # An unpaid hold refunds nothing here; a payment that lands later is
    # refunded in full by the webhook. The slot is withdrawn either way.
    op.execute("""
        CREATE FUNCTION private.cancel_coach_booking(p_booking_id uuid, p_refund_cents integer)
        RETURNS TABLE (status text, refund_cents integer, stripe_payment_intent_id text)
        LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = '' AS $$
        #variable_conflict use_column
        DECLARE
            v_user uuid := private.current_user_id();
            v_slot app.coach_slot%ROWTYPE;
            v_booking app.coach_booking%ROWTYPE;
            v_status text;
            v_refund integer;
        BEGIN
            SELECT s.* INTO v_slot FROM app.coach_slot s
            JOIN app.coach_booking b ON b.slot_id = s.id
            WHERE b.id = p_booking_id FOR UPDATE OF s;
            IF NOT FOUND OR v_user IS NULL THEN
                RAISE EXCEPTION 'no such booking' USING ERRCODE = 'P0002';
            END IF;
            SELECT * INTO v_booking FROM app.coach_booking b
            WHERE b.id = p_booking_id FOR UPDATE;
            IF v_booking.player_user_id = v_user THEN
                v_status := 'cancelled_by_player';
            ELSIF EXISTS (
                SELECT 1 FROM app.coach_profile cp
                WHERE cp.id = v_booking.coach_profile_id AND cp.user_id = v_user
            ) THEN
                v_status := 'cancelled_by_coach';
            ELSE
                RAISE EXCEPTION 'no such booking' USING ERRCODE = 'P0002';
            END IF;
            IF v_booking.status NOT IN ('pending_payment', 'confirmed')
               OR v_slot.starts_at <= now() THEN
                RAISE EXCEPTION 'not cancellable' USING ERRCODE = '55000';
            END IF;
            v_refund := CASE WHEN v_booking.status = 'confirmed'
                THEN greatest(0, least(coalesce(p_refund_cents, 0), v_booking.price_cents))
                ELSE 0 END;
            UPDATE app.coach_booking b SET status = v_status, refund_cents = v_refund,
                cancelled_at = now(), updated_at = now()
            WHERE b.id = p_booking_id;
            UPDATE app.coach_slot s SET status = 'cancelled' WHERE s.id = v_slot.id;
            RETURN QUERY SELECT v_status, v_refund, v_booking.stripe_payment_intent_id;
        END $$
    """)
    booking_columns = """
        b.id, b.slot_id, b.status, b.price_cents, b.platform_fee_cents,
        b.refund_cents, b.note, b.hold_expires_at, b.created_at, b.cancelled_at,
        s.starts_at, s.ends_at, s.format, s.venue
    """
    op.execute(f"""
        CREATE FUNCTION private.player_booking_list()
        RETURNS TABLE (
            id uuid, slot_id uuid, status text, price_cents integer,
            platform_fee_cents integer, refund_cents integer, note text,
            hold_expires_at timestamptz, created_at timestamptz,
            cancelled_at timestamptz, starts_at timestamptz, ends_at timestamptz,
            format text, venue text, coach_profile_id uuid, coach_display_name text
        )
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT {booking_columns}, cp.id, cp.display_name
            FROM app.coach_booking b
            JOIN app.coach_slot s ON s.id = b.slot_id
            JOIN app.coach_profile cp ON cp.id = b.coach_profile_id
            WHERE b.player_user_id = private.current_user_id()
            ORDER BY s.starts_at DESC, b.id
        $$
    """)
    # The coach sees the player's first name only: no email, no user id.
    op.execute(f"""
        CREATE FUNCTION private.coach_booking_list()
        RETURNS TABLE (
            id uuid, slot_id uuid, status text, price_cents integer,
            platform_fee_cents integer, refund_cents integer, note text,
            hold_expires_at timestamptz, created_at timestamptz,
            cancelled_at timestamptz, starts_at timestamptz, ends_at timestamptz,
            format text, venue text, player_first_name text
        )
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
            SELECT {booking_columns},
                   coalesce(nullif(split_part(btrim(a.display_name), ' ', 1), ''), 'Player')
            FROM app.coach_booking b
            JOIN app.coach_slot s ON s.id = b.slot_id
            JOIN app.coach_profile cp ON cp.id = b.coach_profile_id
            JOIN app.user_account a ON a.id = b.player_user_id
            WHERE cp.user_id = private.current_user_id()
            ORDER BY s.starts_at DESC, b.id
        $$
    """)

    for signature, roles in FUNCTIONS.items():
        op.execute(f"ALTER FUNCTION {signature} OWNER TO {MIGRATION_ROLE}")
        op.execute(
            f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC, anon, authenticated,"
            f" {API_ROLE}, {WORKER_ROLE}, {OPERATOR_ROLE}"
        )
        for role in roles:
            op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {role}")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS app.{table} CASCADE")
    for signature in FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS {signature}")
