"""merge upstream migrations

Revision ID: 665e242be94b
Revises: 47a2ae6a4606, 8452d01d26d7
Create Date: 2026-02-06 16:26:09.924687

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import open_webui.internal.db


# revision identifiers, used by Alembic.
revision: str = '665e242be94b'
down_revision: Union[str, None] = ('47a2ae6a4606', '8452d01d26d7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
