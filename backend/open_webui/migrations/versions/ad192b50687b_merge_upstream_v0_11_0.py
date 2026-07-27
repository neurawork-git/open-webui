"""merge upstream v0.11.0

Revision ID: ad192b50687b
Revises: e48721182479, f0bd01a18a3d
Create Date: 2026-07-27 16:56:14.479626

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import open_webui.internal.db


# revision identifiers, used by Alembic.
revision: str = 'ad192b50687b'
down_revision: Union[str, None] = ('e48721182479', 'f0bd01a18a3d')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
