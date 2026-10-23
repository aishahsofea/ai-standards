from app.users import connect, find_by_email


def make_db():
    db = connect(":memory:")
    db.execute("CREATE TABLE users (id INTEGER, name TEXT, email TEXT)")
    db.execute("INSERT INTO users VALUES (1, 'Ana', 'ana@example.com')")
    return db


def test_find_by_email_returns_the_matching_user():
    assert find_by_email(make_db(), "ana@example.com") == (1, "Ana", "ana@example.com")


def test_find_by_email_returns_none_when_missing():
    assert find_by_email(make_db(), "bob@example.com") is None
