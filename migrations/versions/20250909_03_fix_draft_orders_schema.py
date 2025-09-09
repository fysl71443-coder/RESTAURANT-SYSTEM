"""
Fix draft_orders schema: ensure table_number exists and backfill from table_no

Revision ID: 20250909_03
Revises: 20250908_02
Create Date: 2025-09-09
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20250909_03'
down_revision = '20250908_02'
branch_labels = None
depends_on = None

def column_exists(bind, table_name: str, column_name: str) -> bool:
    insp = sa.inspect(bind)
    try:
        cols = [c['name'] for c in insp.get_columns(table_name)]
        return column_name in cols
    except Exception:
        return False

def index_exists(bind, table_name: str, index_name: str) -> bool:
    insp = sa.inspect(bind)
    try:
        idx = [i['name'] for i in insp.get_indexes(table_name)]
        return index_name in idx
    except Exception:
        return False

def upgrade():
    bind = op.get_bind()

    # 1) Ensure table_number column exists (VARCHAR(50) NOT NULL DEFAULT '0')
    if not column_exists(bind, 'draft_orders', 'table_number'):
        try:
            with op.batch_alter_table('draft_orders', schema=None) as batch_op:
                batch_op.add_column(sa.Column('table_number', sa.String(length=50), nullable=True))
        except Exception:
            # Fallback for dialects without batch mode support
            op.add_column('draft_orders', sa.Column('table_number', sa.String(length=50), nullable=True))

        # Backfill from legacy table_no if present
        try:
            if column_exists(bind, 'draft_orders', 'table_no'):
                op.execute("""
                    UPDATE draft_orders
                    SET table_number = CASE
                        WHEN table_no IS NOT NULL THEN CAST(table_no AS VARCHAR(50))
                        ELSE '0'
                    END
                    WHERE table_number IS NULL
                """)
            else:
                op.execute("UPDATE draft_orders SET table_number = '0' WHERE table_number IS NULL")
        except Exception:
            # Best-effort: ensure not null later
            pass

        # Enforce NOT NULL and default
        try:
            with op.batch_alter_table('draft_orders', schema=None) as batch_op:
                batch_op.alter_column('table_number', existing_type=sa.String(length=50), nullable=False, server_default='0')
        except Exception:
            try:
                op.execute("UPDATE draft_orders SET table_number = '0' WHERE table_number IS NULL")
            except Exception:
                pass

    # 2) Ensure status column exists (default 'draft')
    if not column_exists(bind, 'draft_orders', 'status'):
        try:
            with op.batch_alter_table('draft_orders', schema=None) as batch_op:
                batch_op.add_column(sa.Column('status', sa.String(length=20), nullable=True))
        except Exception:
            op.add_column('draft_orders', sa.Column('status', sa.String(length=20), nullable=True))
        try:
            op.execute("UPDATE draft_orders SET status = 'draft' WHERE status IS NULL")
            with op.batch_alter_table('draft_orders', schema=None) as batch_op:
                batch_op.alter_column('status', existing_type=sa.String(length=20), nullable=False, server_default='draft')
        except Exception:
            pass

    # 3) Add performance index on (branch_code, status)
    if not index_exists(bind, 'draft_orders', 'ix_draft_orders_branch_status'):
        try:
            op.create_index('ix_draft_orders_branch_status', 'draft_orders', ['branch_code', 'status'], unique=False)
        except Exception:
            pass


def downgrade():
    # Non-destructive downgrade: drop index if exists
    bind = op.get_bind()
    try:
        if index_exists(bind, 'draft_orders', 'ix_draft_orders_branch_status'):
            op.drop_index('ix_draft_orders_branch_status', table_name='draft_orders')
    except Exception:
        pass

