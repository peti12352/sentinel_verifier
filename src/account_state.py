# account_state.py
"""
This file simulates a simple database for the agent's world state.
In a real application, this would be a proper database.
"""

ACCOUNTS = {
    "USER_ACCOUNT": {"balance": 25000},
    "Account_A": {"balance": 1000},
    "Account_B": {"balance": 5000},
    "Account_C": {"balance": 0},
    "Account_D": {"balance": 100000},
}

# These are system-level rules and constants
BLACKLISTED_ACCOUNTS = {"Account_X", "Account_Y", "ILLEGAL_ACCOUNT"}
TRANSACTION_LIMIT = 10000
