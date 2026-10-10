"""Additive schema for the web console; client tables and contracts stay intact."""

EXTRA_COLUMNS = {
    'users': {'note': "TEXT NOT NULL DEFAULT ''", 'member_version': 'INTEGER NOT NULL DEFAULT 0'},
    'app_releases': {'portable_url': "TEXT NOT NULL DEFAULT ''", 'portable_sha256': "TEXT NOT NULL DEFAULT ''"},
    'app_release_history': {'portable_url': "TEXT NOT NULL DEFAULT ''", 'portable_sha256': "TEXT NOT NULL DEFAULT ''"},
}


def migrate(conn, now):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS admin_operations (
            operation_id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL,
            payload TEXT NOT NULL, result TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS code_batches (
            id TEXT PRIMARY KEY, plan TEXT, custom_days INTEGER, quantity INTEGER NOT NULL,
            expires_at TEXT, note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS site_settings (
            id INTEGER PRIMARY KEY CHECK (id=1), content TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_codes_order ON redeem_codes(created_at DESC,code DESC);
        CREATE INDEX IF NOT EXISTS idx_codes_state_order ON redeem_codes(used_by,is_disabled,created_at DESC,code DESC,expires_at);
        CREATE INDEX IF NOT EXISTS idx_codes_batch_order ON redeem_codes(batch_id,created_at DESC,code DESC);
        CREATE INDEX IF NOT EXISTS idx_users_member_expiry ON users(member_expires_at,id) WHERE is_member=1 AND plan!='permanent';
        CREATE TRIGGER IF NOT EXISTS users_membership_revision
        AFTER UPDATE OF is_member,plan,member_expires_at,is_banned,device_id,device_rebind_cooldown_until,note ON users
        BEGIN
            UPDATE users SET member_version=OLD.member_version+1 WHERE id=NEW.id;
        END;
        INSERT OR IGNORE INTO code_batches(id,plan,custom_days,quantity,expires_at,note,created_at)
        SELECT batch_id,MIN(plan),MIN(custom_days),COUNT(*),MAX(expires_at),MAX(COALESCE(note,'')),MIN(created_at)
        FROM redeem_codes GROUP BY batch_id;
    ''')
    conn.execute("INSERT OR IGNORE INTO schema_migrations(name,applied_at) VALUES('005_web_console',?)", (now,))
