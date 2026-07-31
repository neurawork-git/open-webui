"""Add user_credential table for the LDAP credential store (fork-local)

Holds the AD password of an LDAP-authenticated user, encrypted, so tools can reach
NTLM-only on-prem services as that user.

Downgrade drops the table. That is a requirement, not housekeeping: rolling back must
not leave secrets behind.

Revision ID: e7f8a9b0c1d2
Revises: e48721182479
Create Date: 2026-07-31 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from open_webui.migrations._fork_helpers import (
    create_table_if_missing,
    drop_table_if_exists,
)

# revision identifiers, used by Alembic.
revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, None] = "e48721182479"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    create_table_if_missing(
        "user_credential",
        # Primary key
        sa.Column("id", sa.Text(), primary_key=True),
        # Owner + system
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("realm", sa.Text(), nullable=False),
        # DOMAIN\user -- not a secret, stored in clear so the account can be shown
        sa.Column("account", sa.Text(), nullable=False),
        # base64(nonce + AES-256-GCM ciphertext); NULL when consent exists but no
        # password has been captured yet
        sa.Column("secret", sa.Text(), nullable=True),
        # Which key encrypted `secret` -- lets a rotated key be detected locally
        sa.Column("key_id", sa.Text(), nullable=True),
        # Storing is the default; this column only ever records an explicit refusal, which
        # has to survive so the next login does not undo a deletion.
        sa.Column("opted_in", sa.Boolean(), nullable=False, server_default=sa.true()),
        # Timing (BigInteger for epoch timestamps)
        sa.Column("expires_at", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("last_used_at", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        # One credential per user and realm
        sa.Index("idx_user_credential_user_realm", "user_id", "realm", unique=True),
        sa.Index("idx_user_credential_expires_at", "expires_at"),
    )


def downgrade() -> None:
    drop_table_if_exists("user_credential")
