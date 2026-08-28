"""message usage: tokens spent and what they cost

Three nullable columns on `messages`. Nullable rather than defaulted to zero,
because every row written before this migration genuinely has no usage record,
and a zero there would read as "this answer was free" in any aggregate.

`cost_micro_usd` is an integer for the same reason the application counts in
micro-dollars: a thread's cost is a sum over dozens of rows whose interesting
digits sit at the fifth decimal place, which is exactly where a float drifts.

Revision ID: 0002_message_usage
Revises: 0001_initial
Create Date: 2026-08-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_message_usage"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("input_tokens", sa.Integer(), nullable=True))
    op.add_column("messages", sa.Column("output_tokens", sa.Integer(), nullable=True))
    op.add_column("messages", sa.Column("cost_micro_usd", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "cost_micro_usd")
    op.drop_column("messages", "output_tokens")
    op.drop_column("messages", "input_tokens")
