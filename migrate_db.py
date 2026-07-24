import sqlite3

conn = sqlite3.connect("bots.db")
cursor = conn.cursor()

cursor.execute("PRAGMA table_info(user_bots)")
existing_cols = {row[1] for row in cursor.fetchall()}

new_columns = {
    "description": "TEXT",
    "creator_str": "TEXT",
    "has_media": "INTEGER DEFAULT 0",
    "media_type": "TEXT",
}

for col_name, col_type in new_columns.items():
    if col_name not in existing_cols:
        print(f"Adding column: {col_name}")
        cursor.execute(f"ALTER TABLE user_bots ADD COLUMN {col_name} {col_type}")
    else:
        print(f"Column already exists, skipping: {col_name}")

# Also make sure the user_visits table exists (new in this version)
cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_visits (
        user_id INTEGER,
        bot_db_id INTEGER,
        PRIMARY KEY (user_id, bot_db_id)
    )
""")

conn.commit()
conn.close()
print("Migration complete.")
