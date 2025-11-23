# verifier.py
from z3 import Int, Solver, sat, Implies
import account_state

# Map string account names to integer IDs for Z3 to reason about.
# This is a common practice when working with symbolic solvers.
ACCOUNT_ID_MAP = {name: i for i, name in enumerate(account_state.ACCOUNTS.keys())}

def verify_transaction_safety(amount_val: int, destination_val: str):
    """
    Uses Z3 to formally verify if a transaction meets all system invariants.
    """
    amount = Int('amount')
    destination = Int('destination')
    s = Solver()
    
    # --- Invariants (The Constitution) ---
    limit = account_state.TRANSACTION_LIMIT
    
    # 1. Amount must be positive and within the overall transaction limit.
    s.add(amount > 0)
    s.add(amount <= limit)

    # 2. **New Complex Rule:** If the amount is over $8,000, it MUST go to Account_D.
    #    We use Implies(condition, requirement) to model this.
    high_value_acct_id = ACCOUNT_ID_MAP["Account_D"]
    s.add(Implies(amount > 8000, destination == high_value_acct_id))

    # --- Proposed Action (The "Attack") ---
    s.add(amount == amount_val)
    # Convert the string destination to its integer ID for the proof.
    if destination_val in ACCOUNT_ID_MAP:
        s.add(destination == ACCOUNT_ID_MAP[destination_val])
    else:
        # If the destination doesn't exist, it can't be part of a valid proof.
        return False, "Invariant Violation: Destination account does not exist in the ID map."

    # --- Verification ---
    if s.check() == sat:
        return True, "Verified Safe: Transaction parameters conform to all symbolic invariants."
    else:
        # More detailed error checking for the user
        if amount_val > 8000 and destination_val != "Account_D":
            return False, f"Invariant Violation: Transfers over $8,000 must go to Account_D, not '{destination_val}'."
        if amount_val <= 0:
            return False, "Invariant Violation: Amount must be positive."
        if amount_val > limit:
            return False, f"Invariant Violation: Amount ${amount_val} exceeds the ${limit} limit."
        return False, "Invariant Violation: Transaction failed symbolic checks for an unknown reason."


def is_destination_blacklisted(destination: str):
    """
    Checks if the destination account is in the hard-coded blacklist.
    """
    if destination in account_state.BLACKLISTED_ACCOUNTS:
        return True, f"Heuristic Violation: Destination account '{destination}' is blacklisted."
    if destination not in account_state.ACCOUNTS:
        return True, f"Heuristic Violation: Destination account '{destination}' does not exist."
    return False, "Destination OK."

def has_sufficient_funds(sender: str, amount: int):
    """
    Checks if the sender has enough funds for the transaction.
    """
    balance = account_state.ACCOUNTS.get(sender, {}).get("balance", 0)
    if balance >= amount:
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
        sender = args.get('sender', 'USER_ACCOUNT')

        # 1. Symbolic Check (Z3) for complex logical invariants
        is_safe, reason = verify_transaction_safety(amount, destination)
        if not is_safe: return False, reason

        # 2. Heuristic Check for destination validity (blacklist)
        is_blacklisted, reason = is_destination_blacklisted(destination)
        if is_blacklisted: return False, reason
        
        # 3. Heuristic Check for sufficient funds
        has_funds, reason = has_sufficient_funds(sender, amount)
        if not has_funds: return False, reason

        return True, "All transaction checks passed. Action is approved."
    
    # By default, deny any tool that isn't explicitly handled.
    return False, f"Tool '{tool_name}' is not recognized or not permitted."
