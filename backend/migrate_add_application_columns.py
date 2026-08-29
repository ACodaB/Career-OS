"""
One-off migration: adds the Phase 3 application-prep columns to the existing
`jobs` table in career_os.db, in place — no data is deleted.

Safe to run more than once: it checks which columns already exist and only
adds the ones that are missing.

Usage (from the backend/ folder, with your venv active):
    python migrate_add_application_columns.py
"""
import sqlite3

DB_PATH = "career_os.db"

NEW_COLUMNS = {
    "tailored_resume": "TEXT DEFAULT ''",
    "tailored_cover_letter": "TEXT DEFAULT ''",
    "application_generated_at": "DATETIME",
}


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("PRAGMA table_info(jobs);")
    existing_columns = {row[1] for row in cur.fetchall()}

    added = []
    skipped = []

    for col_name, col_def in NEW_COLUMNS.items():
        if col_name in existing_columns:
            skipped.append(col_name)
            continue
        cur.execute(f"ALTER TABLE jobs ADD COLUMN {col_name} {col_def};")
        added.append(col_name)

    conn.commit()
    conn.close()

    if added:
        print(f"Added columns: {', '.join(added)}")
    if skipped:
        print(f"Already present, skipped: {', '.join(skipped)}")
    if not added and not skipped:
        print("No columns processed — check that career_os.db is in this folder.")


if __name__ == "__main__":
    main()
