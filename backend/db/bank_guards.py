"""Original byte protection, including direct SQL writers."""


def install_bank_guards(connection):
    from sqlalchemy import inspect
    if not {'bank_imports', 'bank_source_links'}.issubset(inspect(connection).get_table_names()):
        return
    dialect = connection.dialect.name
    if dialect == 'sqlite':
        connection.exec_driver_sql('''CREATE TRIGGER IF NOT EXISTS bank_original_update
            BEFORE UPDATE ON bank_imports WHEN
            NEW.original_token IS NOT OLD.original_token OR NEW.source_sha256 IS NOT OLD.source_sha256 OR
            NEW.mapping_sha256 IS NOT OLD.mapping_sha256 OR NEW.account_id IS NOT OLD.account_id OR
            (OLD.state = 'confirmed' AND (NEW.manifest_token IS NOT OLD.manifest_token OR NEW.state IS NOT OLD.state))
            BEGIN SELECT RAISE(ABORT, 'Bank original is immutable'); END''')
        connection.exec_driver_sql('''CREATE TRIGGER IF NOT EXISTS bank_original_delete
            BEFORE DELETE ON bank_imports BEGIN SELECT RAISE(ABORT, 'Bank original is immutable'); END''')
        connection.exec_driver_sql('''CREATE TRIGGER IF NOT EXISTS bank_link_update
            BEFORE UPDATE ON bank_source_links BEGIN SELECT RAISE(ABORT, 'Bank source link is immutable'); END''')
        connection.exec_driver_sql('''CREATE TRIGGER IF NOT EXISTS bank_link_delete
            BEFORE DELETE ON bank_source_links BEGIN SELECT RAISE(ABORT, 'Bank source link is immutable'); END''')
    elif dialect == 'postgresql':
        connection.exec_driver_sql('''CREATE OR REPLACE FUNCTION protect_bank_original() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Bank original is immutable'; END IF;
            IF NEW.original_token IS DISTINCT FROM OLD.original_token OR NEW.source_sha256 IS DISTINCT FROM OLD.source_sha256
               OR NEW.mapping_sha256 IS DISTINCT FROM OLD.mapping_sha256 OR NEW.account_id IS DISTINCT FROM OLD.account_id
               OR (OLD.state = 'confirmed' AND (NEW.manifest_token IS DISTINCT FROM OLD.manifest_token OR NEW.state IS DISTINCT FROM OLD.state))
            THEN RAISE EXCEPTION 'Bank original is immutable'; END IF;
            RETURN NEW;
        END; $$ LANGUAGE plpgsql''')
        connection.exec_driver_sql('''CREATE OR REPLACE FUNCTION protect_bank_link() RETURNS trigger AS $$
            BEGIN RAISE EXCEPTION 'Bank source link is immutable'; END; $$ LANGUAGE plpgsql''')
        connection.exec_driver_sql('DROP TRIGGER IF EXISTS bank_original_guard ON bank_imports')
        connection.exec_driver_sql('CREATE TRIGGER bank_original_guard BEFORE UPDATE OR DELETE ON bank_imports FOR EACH ROW EXECUTE FUNCTION protect_bank_original()')
        connection.exec_driver_sql('DROP TRIGGER IF EXISTS bank_link_guard ON bank_source_links')
        connection.exec_driver_sql('CREATE TRIGGER bank_link_guard BEFORE UPDATE OR DELETE ON bank_source_links FOR EACH ROW EXECUTE FUNCTION protect_bank_link()')
