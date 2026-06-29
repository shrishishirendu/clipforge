"""add status to media_assets (pending/ready upload)

Revision ID: 9621c115a094
Revises: ba59b799bdd8
Create Date: 2026-06-29 13:13:37.700969

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9621c115a094'
down_revision: Union[str, None] = 'ba59b799bdd8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # op.add_column does not auto-create the Postgres ENUM type (unlike
    # create_table), so create it explicitly first.
    assetstatus = sa.Enum('PENDING', 'READY', name='assetstatus')
    assetstatus.create(op.get_bind(), checkfirst=True)
    # server_default backfills any existing rows so the NOT NULL add is safe;
    # the app sets status explicitly going forward (Python-side default).
    op.add_column('media_assets', sa.Column(
        'status',
        assetstatus,
        nullable=False,
        server_default='PENDING',  # enum stored by member name (codebase convention)
    ))


def downgrade() -> None:
    op.drop_column('media_assets', 'status')
    sa.Enum(name='assetstatus').drop(op.get_bind(), checkfirst=True)
