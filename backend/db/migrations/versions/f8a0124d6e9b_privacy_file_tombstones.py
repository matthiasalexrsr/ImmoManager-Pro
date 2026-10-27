"""Keep deleted file locators blocked independently of document metadata."""
import sqlalchemy as sa
from alembic import op

revision = 'f8a0124d6e9b'
down_revision = 'e7f9013c5d8a'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    column = next((item for item in sa.inspect(connection).get_columns('privacy_controls')
                   if item['name'] == 'file_keys_sha256'), None)
    if column:
        if not isinstance(column['type'], sa.JSON) or not column['nullable']:
            raise RuntimeError('Unexpected privacy file tombstone schema')
        return
    op.add_column('privacy_controls', sa.Column('file_keys_sha256', sa.JSON, nullable=True))


def downgrade():
    connection = op.get_bind()
    table = sa.Table('privacy_controls', sa.MetaData(), autoload_with=connection)
    if any(value for value in connection.scalars(sa.select(table.c.file_keys_sha256))):
        raise RuntimeError('Retained file tombstones must not be discarded; restore a verified pre-upgrade backup')
    with op.batch_alter_table('privacy_controls') as batch:
        batch.drop_column('file_keys_sha256')
