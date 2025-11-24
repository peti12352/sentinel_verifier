# verifier.py
from z3 import Int, Solver, sat, Implies
import database as db
from config import SECURITY_RULES

def get_account_id_map() -> dict[str, int]:
    """
    Generates a mapping from account ID strings to integer IDs for Z3 solver.
    Fetches the accounts directly from the database.
    """
    accounts = db.get_all_accounts()
    return {name['id']: i for i, name in enumerate(accounts)}

def verify_transaction_safety(amount_val: int, destination_val: str, sender_val: str = "USER_ACCOUNT"):
    """
    Uses Z3 to formally verify if a transaction meets all system invariants.
    This function mathematically proves that the sender is USER_ACCOUNT and all other rules are satisfied.
    """
    ACCOUNT_ID_MAP = get_account_id_map()
    # Pre-check: Ensure accounts exist before attempting proof
    if destination_val not in ACCOUNT_ID_MAP:
        return False, f"Invalid Destination: Account '{destination_val}' does not exist in the system."
    if sender_val not in ACCOUNT_ID_MAP:
        return False, f"Invalid Sender: Account '{sender_val}' does not exist in the system."
    
    amount = Int('amount')
    destination = Int('destination')
    sender = Int('sender')
    s = Solver()
    
    # --- Invariants (The Constitution) ---
    limit = SECURITY_RULES.get("max_amount", 10000)
    high_value_threshold = SECURITY_RULES.get("high_value_threshold", 8000)
    high_value_dest_acct_name = SECURITY_RULES.get("high_value_destination_account", "Account_D")
    
    user_account_id = ACCOUNT_ID_MAP["USER_ACCOUNT"]
    
    # 0. **CRITICAL SECURITY INVARIANT:** Sender MUST be USER_ACCOUNT (mathematically enforced)
    s.add(sender == user_account_id)
    
    # 1. Amount must be positive and within the overall transaction limit.
    s.add(amount > 0)
    s.add(amount <= limit)

    # 2. **Complex Rule:** If the amount is over the high-value threshold, it MUST go to the designated high-value account.
    if high_value_dest_acct_name in ACCOUNT_ID_MAP:
        high_value_acct_id = ACCOUNT_ID_MAP[high_value_dest_acct_name]
        s.add(Implies(amount > high_value_threshold, destination == high_value_acct_id))

    # --- Proposed Action (The "Attack") ---
    s.add(amount == amount_val)
    s.add(destination == ACCOUNT_ID_MAP[destination_val])
    s.add(sender == ACCOUNT_ID_MAP[sender_val])

    # --- Verification ---
    if s.check() == sat:
        return True, "Verified Safe: Transaction parameters conform to all symbolic invariants."
    else:
        # More detailed error checking for the user
        if sender_val != "USER_ACCOUNT":
            return False, f"Authorization Violation: Transfers can only be initiated from USER_ACCOUNT, not '{sender_val}'. This is mathematically enforced by the Z3 proof."
        if amount_val > high_value_threshold and destination_val != high_value_dest_acct_name:
            return False, f"Policy Violation: Transfers over ${high_value_threshold:,} must go to {high_value_dest_acct_name}, not '{destination_val}'."
        if amount_val <= 0:
            return False, "Invalid Amount: Transfer amount must be positive."
        if amount_val > limit:
            return False, f"Limit Exceeded: Amount ${amount_val:,} exceeds the maximum transaction limit of ${limit:,}."
        return False, "Verification Failed: Transaction does not satisfy system invariants."


def is_destination_blacklisted(destination: str):
    """
    Checks if the destination account is valid and not blacklisted.
    """
    if not db.account_exists(destination):
        all_accounts = [acc['id'] for acc in db.get_all_accounts()]
        return True, f"Invalid Account: Destination '{destination}' does not exist. Available accounts: {', '.join(all_accounts)}."
    if db.is_account_blacklisted(destination):
        return True, f"Blocked Account: Destination '{destination}' is on the security blacklist and cannot receive transfers."
    return False, "Destination OK."

def has_sufficient_funds(sender: str, amount: int):
    """
    Checks if the sender has enough funds for the transaction.
    """
    balance = db.get_account_balance(sender)
    if balance is not None and balance >= amount:
        return True, "Sufficient funds confirmed."
    else:
        return False, f"Heuristic Violation: Insufficient funds. Sender '{sender}' has ${balance}, but tried to send ${amount}."

def guardian_check(tool_call):
    """
    Main verification function that runs all checks based on the tool being called.
    """
    tool_name = tool_call.get('name')

    # Whitelist safe, read-only tools that don't need verification.
    if tool_name in ["get_balance", "list_available_accounts", "get_transaction_rules"]:
        return True, f"Tool '{tool_name}' is approved as a safe read-only operation."

    if tool_name == 'transfer_funds':
        args = tool_call['args']
        amount = args.get('amount')
        destination = args.get('destination')
        sender = "USER_ACCOUNT"  # Hard-coded: all transfers must come from the authenticated user

        # 1. Pre-check: Verify destination account exists (before attempting proof)
        is_blacklisted, reason = is_destination_blacklisted(destination)
        if is_blacklisted: return False, reason

        # 2. Symbolic Check (Z3) for complex logical invariants including sender authorization
        #    This mathematically proves that sender == USER_ACCOUNT
        is_safe, reason = verify_transaction_safety(amount, destination, sender)
        if not is_safe: return False, reason
        
        # 3. Heuristic Check for sufficient funds
        has_funds, reason = has_sufficient_funds(sender, amount)
        if not has_funds: return False, reason

        return True, "All transaction checks passed. Action is approved."
    
    # By default, deny any tool that isn't explicitly handled.
    return False, f"Tool '{tool_name}' is not recognized or not permitted."
