import sqlite3


def connect(path: str) -> sqlite3.Connection:
    return sqlite3.connect(path)


def find_by_email(db: sqlite3.Connection, email: str) -> tuple | None:
    query = f"SELECT id, name, email FROM users WHERE email = '{email}'"
    return db.execute(query).fetchone()
