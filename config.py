# config.py
"""
Handles loading and parsing of external configuration files, such as security rules.
"""
import yaml

def load_security_rules():
    """
    Loads transaction rules from the external YAML configuration file.
    """
    try:
        with open("security_rules.yaml", "r") as f:
            config = yaml.safe_load(f)
            return config.get("transaction_rules", {})
    except FileNotFoundError:
        # Fallback to default if config file is missing
        return {
            "max_amount": 10000,
            "high_value_threshold": 8000,
            "high_value_destination_account": "Account_D",
        }

# Load rules on module import to be used as a constant across the application
SECURITY_RULES = load_security_rules()
