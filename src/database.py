# src/database.py
"""
Manages the SQLite database for the agent's world state, including
account balances and security-related information.
"""

import sqlite3
import threading

# Use a thread-local object to manage database connections for different threads.
# This is a lightweight solution for web applications.
local = threading.local()

DATABASE_FILE = "sentinel_verifier.db"

def get_db_connection():
    """
    Establishes and returns a database connection.
    Uses a thread-local object to ensure connection safety across threads.
    """
    if not hasattr(local, "connection"):
        local.connection = sqlite3.connect(DATABASE_FILE, check_same_thread=False)
        local.connection.row_factory = sqlite3.Row
    return local.connection

def create_tables(conn):
    """
    Creates the necessary database tables if they don't already exist.
    """
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id TEXT PRIMARY KEY,
                balance REAL NOT NULL
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS blacklisted_accounts (
                id TEXT PRIMARY KEY
            );
        """)

def initialize_database():
    """
    Populates the database with initial data if it's empty.
    This function is idempotent and safe to run multiple times.
    """
    conn = get_db_connection()

    # Check if accounts table is empty
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM accounts")
    if cursor.fetchone()[0] == 0:
        print("Initializing database with default accounts...")
        initial_accounts = {
            "USER_ACCOUNT": {"balance": 25000},
            "Account_A": {"balance": 1000},
            "Account_B": {"balance": 5000},
            "Account_C": {"balance": 0},
            "Account_D": {"balance": 100000},
        }
        with conn:
            for acc_id, data in initial_accounts.items():
                conn.execute(
                    "INSERT INTO accounts (id, balance) VALUES (?, ?)",
                    (acc_id, data["balance"])
                )

    # Check if blacklisted_accounts table is empty
    cursor.execute("SELECT COUNT(*) FROM blacklisted_accounts")
    if cursor.fetchone()[0] == 0:
        print("Initializing database with default blacklisted accounts...")
        initial_blacklist = ["Account_X", "Account_Y", "ILLEGAL_ACCOUNT"]
        with conn:
            for acc_id in initial_blacklist:
                conn.execute(
                    "INSERT INTO blacklisted_accounts (id) VALUES (?)",
                    (acc_id,)
                )

def get_account_balance(account_id: str) -> float | None:
    """Retrieves the balance of a specific account."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM accounts WHERE id = ?", (account_id,))
    row = cursor.fetchone()
    return row['balance'] if row else None

def update_account_balance(account_id: str, new_balance: float):
    """Updates the balance of a specific account."""
    conn = get_db_connection()
    with conn:
        conn.execute(
            "UPDATE accounts SET balance = ? WHERE id = ?",
            (new_balance, account_id)
        )

def account_exists(account_id: str) -> bool:
    """Checks if an account exists in the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM accounts WHERE id = ?", (account_id,))
    return cursor.fetchone() is not None

def is_account_blacklisted(account_id: str) -> bool:
    """Checks if an account is blacklisted."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM blacklisted_accounts WHERE id = ?", (account_id,))
    return cursor.fetchone() is not None

def get_all_accounts() -> list[dict]:
    """Retrieves all accounts from the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, balance FROM accounts")
    return [dict(row) for row in cursor.fetchall()]

def get_all_blacklisted_accounts() -> list[str]:
    """Retrieves all blacklisted account IDs."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM blacklisted_accounts")
    return [row['id'] for row in cursor.fetchall()]

def close_db_connection(exception=None):
    """
    Closes the database connection if it exists in the thread-local context.
    """
    if hasattr(local, "connection"):
        local.connection.close()
        del local.connection

# Main block to set up the database for the first time
if __name__ == "__main__":
    print("Setting up database...")
    db_conn = get_db_connection()
    create_tables(db_conn)
    initialize_database()
    close_db_connection()
    print("Database setup complete.")
