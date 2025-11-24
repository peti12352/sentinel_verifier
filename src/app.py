# app.py
import streamlit as st
from langchain_core.messages import HumanMessage, AIMessage
from agent import app
import account_state
from verifier import ACCOUNT_ID_MAP

st.set_page_config(layout="wide")

st.title("🛡️ SentinelVerifier Demo")
st.caption("A runtime verification system for AI agents that polices actions and responses.")

# --- Main Chat Interface ---
col1, col2 = st.columns([2, 1])

with col1:
    st.header("Chat with the Finance Agent")
    
    if "messages" not in st.session_state:
        st.session_state.messages = []
    
    if "thread_id" not in st.session_state:
        st.session_state.thread_id = {"configurable": {"thread_id": "1"}}

    for msg in st.session_state.messages:
        st.chat_message(msg.type).write(msg.content)

    if prompt := st.chat_input("Ask the agent to transfer money or check balances..."):
        st.session_state.messages.append(HumanMessage(content=prompt))
        st.chat_message("human").write(prompt)
        
        # Stream the agent's response
        events = app.stream(
            {"messages": [HumanMessage(content=prompt)]},
            st.session_state.thread_id
        )
        
        response = ""
        with st.chat_message("ai").empty():
            for event in events:
                if "messages" in event.get("validator", {}):
                    msg = event["validator"]["messages"][-1]
                    if msg.content:
                        response += msg.content
                        st.write(response)
            
            if response:
                st.session_state.messages.append(AIMessage(content=response))
        
        # Force a rerun to update the sidebar with the latest execution log
        st.rerun()


# --- Sidebar for System State and Logs ---
with col2:
    st.header("System Monitor")

    st.subheader("Live Account Balances")
    st.json({acc: f"${data['balance']:,}" for acc, data in account_state.ACCOUNTS.items()})

    st.subheader("System Rules")
    st.markdown(f"- **Transaction Limit:** ${account_state.TRANSACTION_LIMIT:,}")
    st.markdown(f"- **Blacklisted Accounts:** `{', '.join(account_state.BLACKLISTED_ACCOUNTS)}`")

    st.subheader("Execution Log")
    try:
        thread_state = app.get_state(st.session_state.thread_id)
        history = []
        
        if thread_state and hasattr(thread_state, 'values') and isinstance(thread_state.values, dict):
            history = thread_state.values.get('execution_history', [])

        if not history:
            st.info("No tool calls have been attempted yet.")
        else:
            # Display each log entry, with an interactive expander for proof visualization
            for i, event in enumerate(reversed(history)):
                tool_name = event.get("tool_name", "N/A")
                status = event.get("status", "UNKNOWN")

                summary = f"**{len(history) - i}:** {tool_name} — **{status}**"
                
                # Make an expander for every transfer_funds attempt
                if tool_name == "transfer_funds":
                    with st.expander(summary):
                        st.json(event)
                        st.markdown("---")
                        st.markdown("##### Proof Visualization")
                        
                        args = event.get("tool_args", {})
                        amount = args.get("amount", "N/A")
                        dest = args.get("destination", "N/A")
                        reason = event.get("reason", "")
                        
                        # Check if account exists before showing Z3 proof
                        if dest in ACCOUNT_ID_MAP:
                            dest_id = ACCOUNT_ID_MAP[dest]
                            user_acct_id = ACCOUNT_ID_MAP.get('USER_ACCOUNT', 0)
                            st.code(f"""
# Z3 Solver Input
# Security Invariant: Sender must be USER_ACCOUNT
solver.add(sender == {user_acct_id})
# Amount constraints
solver.add(amount > 0)
solver.add(amount <= {account_state.TRANSACTION_LIMIT})
# Policy: High-value transfers must go to Account_D
solver.add(Implies(amount > 8000, destination == {ACCOUNT_ID_MAP.get('Account_D', 'N/A')}))
# Proposed action
solver.add(amount == {amount})
solver.add(destination == {dest_id})
solver.add(sender == {user_acct_id})
                            """, language="python")

                            st.markdown("##### Z3 Solver Output")
                            if status == "BLOCKED" and any(keyword in reason for keyword in ["Authorization Violation", "Policy Violation", "Limit Exceeded", "Invalid Amount", "Verification Failed"]):
                                st.error(f"UNSATISFIABLE\n\n**Reason:** {reason}")
                            elif status in ["APPROVED", "SUCCESSFULLY_EXECUTED"]:
                                st.success("SATISFIABLE\n\nAll invariants satisfied. Transaction approved.")
                            else:
                                st.warning(f"NOT CHECKED BY Z3\n\n**Reason:** {reason}")
                        else:
                            # Account doesn't exist - show a clear message instead of a broken proof
                            st.info("**Pre-Verification Check Failed**\n\nThe destination account does not exist, so the Z3 proof was not executed.")
                            st.error(f"**Blocked:** {reason}")
                else:
                    st.markdown(summary)

    except Exception as e:
        st.error(f"Could not retrieve execution log. Start a new chat. Error: {e}")
