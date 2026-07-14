"""merge upstream v0.10.2

Revision ID: e48721182479
Revises: 42e2978c7933, 7e66bdd43a43
Create Date: 2026-07-14 12:13:13.413054

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import open_webui.internal.db


# revision identifiers, used by Alembic.
revision: str = 'e48721182479'
down_revision: Union[str, None] = ('42e2978c7933', '7e66bdd43a43')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
