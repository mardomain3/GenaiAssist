import sqlite3
import hashlib
import os

DB_NAME = "users.db" 

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            hashed_password TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    hashed = hashlib.sha256((password + salt).encode()).hexdigest()
    return f"{salt}${hashed}"

def verify_password(plain_password: str, stored_hash: str) -> bool:
    salt, hashed = stored_hash.split("$")
    return hashlib.sha256((plain_password + salt).encode()).hexdigest() == hashed

def create_user(username: str, password: str):
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (username, hashed_password) VALUES (?, ?)",
            (username, hash_password(password))
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # Username already exists
    finally:
        conn.close()

def get_user(username: str):
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE username = ?", (username,)
    ).fetchone()
    conn.close()
    return user