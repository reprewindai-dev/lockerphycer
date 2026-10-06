"""Add authority_keys

Revision ID: a1b2c3d4e5f6
Revises: 
Create Date: 2026-09-21 08:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'authority_keys',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('holder_id', sa.String(length=160), nullable=False),
        sa.Column('lineage_id', sa.String(length=160), nullable=False),
        sa.Column('algorithm', sa.String(length=40), nullable=False),
        sa.Column('public_key', sa.String(length=128), nullable=False),
        sa.Column('encrypted_private_key', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=40), nullable=False),
        sa.Column('generation', sa.Integer(), nullable=False),
        sa.Column('rotation_parent_key_id', sa.String(length=36), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('activated_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['rotation_parent_key_id'], ['authority_keys.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_authority_keys_holder_id'), 'authority_keys', ['holder_id'], unique=False)
    op.create_index(op.f('ix_authority_keys_lineage_id'), 'authority_keys', ['lineage_id'], unique=False)
    op.create_index(op.f('ix_authority_keys_status'), 'authority_keys', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_authority_keys_status'), table_name='authority_keys')
    op.drop_index(op.f('ix_authority_keys_lineage_id'), table_name='authority_keys')
    op.drop_index(op.f('ix_authority_keys_holder_id'), table_name='authority_keys')
    op.drop_table('authority_keys')
