"""merge ldap credential store

Revision ID: 6d45679bb23e
Revises: e7f8a9b0c1d2, ad192b50687b
Create Date: 2026-08-03 17:51:56.510679

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import open_webui.internal.db


# revision identifiers, used by Alembic.
revision: str = '6d45679bb23e'
down_revision: Union[str, None] = ('e7f8a9b0c1d2', 'ad192b50687b')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
