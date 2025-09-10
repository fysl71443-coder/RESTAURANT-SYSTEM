"""merge all migration heads

Revision ID: 76d4fbfc7862
Revises: 097c20248414, 20250909_03, 4539af27efad, 9fd032f321c7
Create Date: 2025-09-10 09:12:35.925936

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '76d4fbfc7862'
down_revision = ('097c20248414', '20250909_03', '4539af27efad', '9fd032f321c7')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
