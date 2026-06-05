"""merge upstream v0.9.6 + fork recovery chain

Revision ID: 7e66bdd43a43
Revises: 461111b60977, a2b3c4d5e6f7
Create Date: 2026-06-05 12:58:16.281344

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import open_webui.internal.db


# revision identifiers, used by Alembic.
revision: str = '7e66bdd43a43'
down_revision: Union[str, None] = ('461111b60977', 'a2b3c4d5e6f7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
