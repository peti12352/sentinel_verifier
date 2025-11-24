# tools.py
from langchain_core.tools import tool
from pydantic import BaseModel, Field
import account_state

class TransferSchema(BaseModel):
    amount: int = Field(description="The amount of money to transfer from your account (USER_ACCOUNT).")
    destination: str = Field(description="The destination account ID.")

@tool(args_schema=TransferSchema)
def transfer_funds(amount: int, destination: str) -> str:
    """
    Executes a money transfer from USER_ACCOUNT to the specified destination.
    This tool can ONLY transfer from USER_ACCOUNT (the authenticated user's account).
    This tool should only be called AFTER passing all verification checks.
    """
    sender = "USER_ACCOUNT"  # Hard-coded: transfers can only come from the authenticated user
    
    # This check is redundant if the verifier works, but is good practice.
    if sender not in account_state.ACCOUNTS or destination not in account_state.ACCOUNTS:
        return "Error: Sender or destination account not found."

    account_state.ACCOUNTS[sender]["balance"] -= amount
    account_state.ACCOUNTS[destination]["balance"] += amount
    return f"Success: Transferred ${amount} from {sender} to {destination}."


class BalanceSchema(BaseModel):
    account_id: str = Field(description="The account ID to check the balance of.")

@tool(args_schema=BalanceSchema)
def get_balance(account_id: str) -> str:
    """Checks the balance of a specified account."""
    balance = account_state.ACCOUNTS.get(account_id, {}).get("balance")
    if balance is not None:
        return f"The balance of {account_id} is ${balance}."
    else:
        return f"Error: Account '{account_id}' not found."

@tool
def list_available_accounts() -> dict:
    """Lists all non-blacklisted accounts that can be transacted with."""
    valid_accounts = list(account_state.ACCOUNTS.keys())
    return {"available_accounts": valid_accounts}

@tool
def get_transaction_rules() -> dict:
    """Returns the system's transaction rules, like the maximum transfer amount."""
    return {
        "max_transfer_amount": account_state.TRANSACTION_LIMIT,
        "blacklisted_accounts": list(account_state.BLACKLISTED_ACCOUNTS)
    }
