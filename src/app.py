# app.py
from verifier import get_account_id_map
from agent import app
import database as db
from config import SECURITY_RULES
import streamlit as st
from langchain_core.messages import HumanMessage, AIMessage


st.set_page_config(layout="wide")

st.title("🛡️ SentinelVerifier Demo")
st.caption(
    "A runtime verification system for AI agents that polices actions and responses.")

# --- Main Chat Interface ---
col1, col2 = st.columns([2, 1])

with col1:
    st.header("Chat with the Finance Agent")

    # Initialize session state
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "thread_id" not in st.session_state:
        st.session_state.thread_id = {"configurable": {"thread_id": "1"}}

    # Display all existing messages
    for msg in st.session_state.messages:
        role = "user" if isinstance(msg, HumanMessage) else "assistant"
        st.chat_message(role).write(msg.content)

    # Check the current state for a pending confirmation
    thread_state = app.get_state(st.session_state.thread_id)
    pending_tool_call = thread_state.values.get(
        "pending_tool_call") if thread_state else None

    # --- Confirmation UI ---
    if pending_tool_call:
        st.info("A transaction is awaiting your approval.")
        st.markdown("##### Unforgeable Transaction Parameters:")
        st.json(pending_tool_call)

        col_confirm, col_cancel = st.columns(2)
        with col_confirm:
            if st.button("✅ Confirm Transaction", use_container_width=True):
                st.session_state.messages.append(
                    HumanMessage(content="CONFIRM"))
                # Re-run the graph to execute the confirmed action
                events = app.stream(
                    {"messages": [HumanMessage(content="CONFIRM")]},
                    st.session_state.thread_id,
                )
                # Consume the stream to get the final result
                for event in events:
                    if "talker" in event:
                        final_event = event

                response_message = final_event["talker"]["messages"][-1]
                if isinstance(response_message, AIMessage):
                    st.session_state.messages.append(response_message)
                st.rerun()

        with col_cancel:
            if st.button("❌ Cancel Transaction", use_container_width=True):
                st.session_state.messages.append(
                    HumanMessage(content="CANCEL"))
                # Re-run the graph to handle the cancellation
                events = app.stream(
                    {"messages": [HumanMessage(content="CANCEL")]},
                    st.session_state.thread_id,
                )
                for event in events:
                    if "talker" in event:
                        final_event = event

                response_message = final_event["talker"]["messages"][-1]
                if isinstance(response_message, AIMessage):
                    st.session_state.messages.append(response_message)
                st.rerun()

    # --- Standard Chat Input ---
    else:
        if prompt := st.chat_input("Ask the agent to transfer money or check balances..."):
            st.session_state.messages.append(HumanMessage(content=prompt))

            # Run the agent graph, now passing the entire message history
            events = app.stream(
                {"messages": st.session_state.messages},
                st.session_state.thread_id,
            )

            # The last message might be the talker's response or a halt
            # We just need to find the final state to see if a confirmation is needed
            final_state = None
            for event in events:
                if event.get("doer") or event.get("guardian") or event.get("talker"):
                    final_state = event

            # If the flow ended with the talker, it means a response was generated
            if final_state and "talker" in final_state:
                response_message = final_state["talker"]["messages"][-1]
                if isinstance(response_message, AIMessage):
                    st.session_state.messages.append(response_message)

            st.rerun()


# --- Sidebar for System State and Logs ---
with col2:
    st.header("System Monitor")

    st.subheader("Live Account Balances")
    st.json({acc['id']: f"${acc['balance']:,}" for acc in db.get_all_accounts()})

    st.subheader("System Rules")
    st.markdown(
        f"- **Transaction Limit:** ${SECURITY_RULES.get('max_amount'):,}")
    st.markdown(
        f"- **Blacklisted Accounts:** `{', '.join(db.get_all_blacklisted_accounts())}`")

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

                        ACCOUNT_ID_MAP = get_account_id_map()
                        # Check if account exists before showing Z3 proof
                        if dest in ACCOUNT_ID_MAP:
                            dest_id = ACCOUNT_ID_MAP[dest]
                            user_acct_id = ACCOUNT_ID_MAP.get(
                                'USER_ACCOUNT', 0)
                            high_value_threshold = SECURITY_RULES.get(
                                "high_value_threshold", 8000)
                            high_value_dest_acct_name = SECURITY_RULES.get(
                                "high_value_destination_account", "Account_D")

                            st.code(f"""
# Z3 Solver Input
# Security Invariant: Sender must be USER_ACCOUNT
solver.add(sender == {user_acct_id})
# Amount constraints
solver.add(amount > 0)
solver.add(amount <= {SECURITY_RULES.get('max_amount')})
# Policy: High-value transfers must go to {high_value_dest_acct_name}
solver.add(Implies(amount > {high_value_threshold}, destination == {ACCOUNT_ID_MAP.get(high_value_dest_acct_name, 'N/A')}))
# Proposed action
solver.add(amount == {amount})
solver.add(destination == {dest_id})
solver.add(sender == {user_acct_id})
                            """, language="python")

                            st.markdown("##### Z3 Solver Output")
                            if status == "BLOCKED" and any(keyword in reason for keyword in ["Authorization Violation", "Policy Violation", "Limit Exceeded", "Invalid Amount", "Verification Failed"]):
                                st.error(
                                    f"UNSATISFIABLE\n\n**Reason:** {reason}")
                            elif status in ["APPROVED", "SUCCESSFULLY_EXECUTED"]:
                                st.success(
                                    "SATISFIABLE\n\nAll invariants satisfied. Transaction approved.")
                            else:
                                st.warning(
                                    f"NOT CHECKED BY Z3\n\n**Reason:** {reason}")
                        else:
                            # Account doesn't exist - show a clear message instead of a broken proof
                            st.info(
                                "**Pre-Verification Check Failed**\n\nThe destination account does not exist, so the Z3 proof was not executed.")
                            st.error(f"**Blocked:** {reason}")
                else:
                    st.markdown(summary)

    except Exception as e:
        st.error(
            f"Could not retrieve execution log. Start a new chat. Error: {e}")
