"""공동 계획의 은행별 복제본, 개인 재무 상태, 통신·실행 기록."""
from alembic import op

revision = "002_planner"
down_revision = "001_customer"


def upgrade():
    for statement in [
        """CREATE TABLE journey (
            id uuid PRIMARY KEY, shared jsonb NOT NULL, private jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now())""",
        """CREATE TABLE outgoing (
            seq bigserial PRIMARY KEY, message_id uuid UNIQUE NOT NULL,
            goal_id uuid NOT NULL, body jsonb NOT NULL, delivered boolean NOT NULL DEFAULT false,
            attempts integer NOT NULL DEFAULT 0, last_error text)""",
        "CREATE TABLE incoming (message_id uuid PRIMARY KEY, reply jsonb NOT NULL)",
        """CREATE TABLE bank_event (seq bigserial PRIMARY KEY, kind text NOT NULL,
            payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now())""",
        """CREATE TABLE appointment (id uuid PRIMARY KEY, title text NOT NULL,
            starts_at timestamptz NOT NULL, ends_at timestamptz NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(), CHECK (ends_at > starts_at))""",
        """CREATE TABLE chat_session (id uuid PRIMARY KEY, memory jsonb NOT NULL DEFAULT '{}',
            created_at timestamptz NOT NULL DEFAULT now())""",
        """CREATE TABLE chat_run (id uuid PRIMARY KEY, session_id uuid NOT NULL REFERENCES chat_session,
            prompt text NOT NULL, state text NOT NULL, answer text, created_at timestamptz NOT NULL DEFAULT now())""",
        """CREATE TABLE trace (seq bigserial PRIMARY KEY, session_id uuid NOT NULL,
            run_id uuid NOT NULL, kind text NOT NULL, payload jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now())""",
        "CREATE INDEX trace_by_session ON trace (session_id, seq)",
        "CREATE INDEX pending_messages ON outgoing (seq) WHERE NOT delivered",
    ]:
        op.execute(statement)


def downgrade():
    for name in ("trace", "chat_run", "chat_session", "appointment",
                 "bank_event", "incoming", "outgoing", "journey"):
        op.drop_table(name)
