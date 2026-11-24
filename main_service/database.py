import sqlite3
from pathlib import Path
from contextlib import closing


def prepare_database(path):
    """При первом запуске переносим прежнюю базу в том и переводим рубли в копейки."""
    source = Path("/previous/expenses.db")
    with closing(sqlite3.connect(path)) as db:
        if source.is_file() and not db.execute("PRAGMA schema_version").fetchone()[0]:
            with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as old:
                old.backup(db)

        columns = [row[1] for row in db.execute("PRAGMA table_info(expenses)")]
        if "amount" not in columns:
            return

        with db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE converted_expenses (
                id INTEGER PRIMARY KEY,
                amount_kopecks INTEGER NOT NULL CHECK (amount_kopecks > 0),
                date DATE NOT NULL, description TEXT,
                category_id INTEGER NOT NULL REFERENCES categories(id)
            )""")
            db.execute("""INSERT INTO converted_expenses
                SELECT id, CAST(ROUND(amount * 100) AS INTEGER), date, description, category_id
                FROM expenses""")
            db.execute("DROP TABLE expenses")
            db.execute("ALTER TABLE converted_expenses RENAME TO expenses")
