# tools.py
from langchain_core.tools import tool
from pydantic import BaseModel, Field
import database as db

from config import SECURITY_RULES

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
    
    if not db.account_exists(sender) or not db.account_exists(destination):
        return "Error: Sender or destination account not found."

    sender_balance = db.get_account_balance(sender)
    destination_balance = db.get_account_balance(destination)

    db.update_account_balance(sender, sender_balance - amount)
    db.update_account_balance(destination, destination_balance + amount)
    
    return f"Success: Transferred ${amount} from {sender} to {destination}."


class BalanceSchema(BaseModel):
    account_id: str = Field(description="The account ID to check the balance of.")

@tool(args_schema=BalanceSchema)
def get_balance(account_id: str) -> str:
    """Checks the balance of a specified account."""
    balance = db.get_account_balance(account_id)
    if balance is not None:
        return f"The balance of {account_id} is ${balance}."
    else:
        return f"Error: Account '{account_id}' not found."

@tool
def list_available_accounts() -> dict:
    """Lists all non-blacklisted accounts that can be transacted with."""
    accounts = db.get_all_accounts()
    valid_accounts = [acc['id'] for acc in accounts]
    return {"available_accounts": valid_accounts}

@tool
def get_transaction_rules() -> dict:
    """Returns the system's transaction rules, like the maximum transfer amount."""
    blacklisted_accounts = db.get_all_blacklisted_accounts()
    return {
        "max_transfer_amount": SECURITY_RULES.get("max_amount"),
        "blacklisted_accounts": blacklisted_accounts
    }
