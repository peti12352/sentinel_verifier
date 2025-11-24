import os
from dotenv import load_dotenv
from typing import TypedDict, List
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import BaseMessage, ToolMessage, AIMessage, SystemMessage
from langgraph.prebuilt import ToolNode
import json
import copy
import account_state  # Import the state to access the canonical account names

from tools import transfer_funds, get_balance, list_available_accounts, get_transaction_rules
from verifier import guardian_check

# Load environment variables from .env file (for local development)
load_dotenv()


def get_config(key: str, default: str = None) -> str:
    """
    Safely retrieves configuration values from Streamlit secrets (for cloud)
    or environment variables (for local development).
    """
    try:
        import streamlit as st
        # Try to get from Streamlit secrets first (for Streamlit Cloud)
        if hasattr(st, 'secrets') and key in st.secrets:
            return st.secrets[key]
    except (ImportError, RuntimeError):
        # Streamlit not available or not in Streamlit context
        pass

    # Fall back to environment variables (for local development)
    return os.getenv(key, default)


class AgentState(TypedDict):
    messages: List[BaseMessage]
    execution_history: List[dict]


def agent_node(state: AgentState):
    """
    The agent's node. It now operates under a strict system prompt.
    """
    system_prompt = (
        "You are a direct and efficient financial assistant. Your primary goal is to execute user commands by calling the appropriate tool. "
        "When a user asks to perform an action (e.g., 'transfer X to Y'), you MUST call the tool directly with the extracted parameters. "
        "Do NOT ask for confirmation. Do NOT summarize the checks you think will pass. Do NOT engage in conversational pleasantries before acting. "
        "Directly attempt the action and let the system's guardian and validator handle the outcome. Relay the final result, whether success or a system block, back to the user."
    )

    # Prepend the system prompt to the message history to enforce behavior
    messages_with_prompt = [SystemMessage(
        content=system_prompt)] + state["messages"]

    # The agent's response is now provisional until validated
    result = llm_with_tools.invoke(messages_with_prompt)
    return {"messages": state["messages"] + [result]}


def guardian_node(state: AgentState):
    last_message = state["messages"][-1]
    tool_call = last_message.tool_calls[0]

    # --- Intelligent Pre-processing Step ---
    # If the tool is a transfer, try to normalize the destination account name.
    if tool_call['name'] == 'transfer_funds':
        original_args = tool_call['args']
        normalized_args = original_args.copy()
        destination = normalized_args.get('destination', '')

        # Create a lowercase-to-canonical mapping of account names
        canonical_map = {name.lower(): name for name in account_state.ACCOUNTS}

        # If the lowercase version of the destination exists in our map, snap it to the correct name
        if destination.lower() in canonical_map:
            normalized_destination = canonical_map[destination.lower()]
            normalized_args['destination'] = normalized_destination

            # Update the tool call with the corrected arguments before verification
            tool_call['args'] = normalized_args
    # --- End Pre-processing ---

    is_safe, reason = guardian_check(tool_call)

    current_history = state.get("execution_history", [])
    history_entry = {
        "tool_name": tool_call['name'],
        "tool_args": tool_call['args'],
    }

    if is_safe:
        history_entry["status"] = "APPROVED"
        history_entry["reason"] = "All checks passed."
        return {
            "messages": state["messages"],  # Pass tool call through
            "execution_history": current_history + [history_entry]
        }
    else:
        history_entry["status"] = "BLOCKED"
        history_entry["reason"] = reason
        error_message = ToolMessage(
            content=f"Error: Action blocked by SentinelVerifier. Reason: {reason}",
            tool_call_id=tool_call["id"],
        )
        # Return the error message to the agent to inform its final response
        return {
            "messages": state["messages"] + [error_message],
            "execution_history": current_history + [history_entry]
        }


def tool_node(state: AgentState):
    """
    This node now only runs if the guardian approved the action.
    It executes the tool, correctly unpacks the result, and updates the history.
    """
    # The ToolNode returns a dict with a 'messages' key
    tool_result_dict = tool_node_executor.invoke(state)

    # Extract the ToolMessage and its content
    tool_message = tool_result_dict['messages'][0]
    tool_output = tool_message.content

    # Create a deep copy to avoid mutating the original state during processing
    new_history = copy.deepcopy(state.get("execution_history", []))

    # Find the corresponding entry in history and mark it as executed
    last_approved_call_index = -1
    for i in range(len(new_history) - 1, -1, -1):
        if new_history[i].get("status") == "APPROVED":
            last_approved_call_index = i
            break

    if last_approved_call_index != -1:
        new_history[last_approved_call_index]["status"] = "SUCCESSFULLY_EXECUTED"
        new_history[last_approved_call_index]["result"] = tool_output

    return {
        "messages": state["messages"] + [tool_message],
        "execution_history": new_history
    }


def response_validator_node(state: AgentState):
    """
    A powerful LLM-as-a-judge to check for hallucinations and contradictions.
    It verifies if the agent's final response is consistent with the execution history.
    """
    history = state.get("execution_history", [])
    last_message = state["messages"][-1]

    # Skip validation if no tools were called or agent is still using tools
    if not history or last_message.tool_calls:
        return state

    # Only validate if the last event was a tool call (not just any old event)
    # Check if there's a recent tool call in the message history
    recent_tool_call = False
    for msg in reversed(state["messages"][-5:]):  # Check last 5 messages
        if hasattr(msg, 'tool_calls') and msg.tool_calls:
            recent_tool_call = True
            break

    # If there's no recent tool call, this is just normal conversation - skip validation
    if not recent_tool_call:
        return state

    last_event = history[-1]

    # Only validate if the last event is actually a transfer_funds attempt
    # (we don't need to validate responses to read-only operations like get_balance)
    if last_event.get("tool_name") != "transfer_funds":
        return state

    prompt = f"""You are a strict, logical auditor AI. Your task is to determine if an agent's response is a truthful and direct representation of the last system event.

**Last System Event (Ground Truth):**
{json.dumps(last_event, indent=2)}

**Agent's Proposed Final Response:**
"{last_message.content}"

**Your Analysis:**
1.  Review the 'status' and 'reason' of the Last System Event. This is the immutable truth.
2.  Review the Agent's Proposed Final Response.
3.  Does the agent's response contradict, ignore, or downplay the ground truth? For example, if the status was 'BLOCKED', the agent MUST state that the action was blocked and explain why. It cannot ask for confirmation to proceed or imply the action is possible.
4.  If the status was 'BLOCKED', the agent's response is ONLY consistent if it clearly communicates the failure to the user.

Respond with a single JSON object with one key, "is_consistent": boolean.
- Set to false if the response contradicts the ground truth (e.g., it says 'all checks passed' when the status was 'BLOCKED').
- Set to true if the response accurately reflects the outcome in the ground truth OR if the response is about something completely unrelated to the last tool call.
"""

    # Use a separate, clean LLM instance for the audit
    auditor_llm = ChatOpenAI(
        model=get_config("OPENROUTER_MODEL",
                         "qwen/qwen3-next-80b-a3b-instruct"),
        temperature=0,
        base_url=get_config("OPENROUTER_BASE_URL"),
        api_key=get_config("OPENROUTER_API_KEY")
    )

    audit_result_str = auditor_llm.invoke(prompt).content

    try:
        audit_result = json.loads(audit_result_str)
        if not audit_result.get("is_consistent", True):
            # HALLUCINATION/CONTRADICTION DETECTED!
            hallucination_error = AIMessage(
                content=f"System Alert: Agent response was found to be inconsistent and has been blocked. The last action was BLOCKED. Reason: {last_event.get('reason')}"
            )
            # Replace the last message with our system alert
            state["messages"][-1] = hallucination_error
    except (json.JSONDecodeError, KeyError):
        # If the auditor fails, default to a safe state.
        safety_override = AIMessage(
            content="System Alert: Response validation failed. For security, the agent's last message has been withheld."
        )
        state["messages"][-1] = safety_override

    return state


# --- LLM and Tool Setup ---
llm = ChatOpenAI(
    model=get_config("OPENROUTER_MODEL", "qwen/qwen3-next-80b-a3b-instruct"),
    temperature=0,
    base_url=get_config("OPENROUTER_BASE_URL"),
    api_key=get_config("OPENROUTER_API_KEY")
)
tools = [transfer_funds, get_balance,
         list_available_accounts, get_transaction_rules]
llm_with_tools = llm.bind_tools(tools)
tool_node_executor = ToolNode(tools)


# --- Graph Definition ---
graph_builder = StateGraph(AgentState)
graph_builder.add_node("agent", agent_node)
graph_builder.add_node("guardian", guardian_node)
graph_builder.add_node("tools", tool_node)
graph_builder.add_node("validator", response_validator_node)

graph_builder.set_entry_point("agent")


def route_after_agent(state: AgentState):
    if state["messages"][-1].tool_calls:
        return "guardian"  # Agent wants to use a tool, verify first
    return "validator"  # Agent wants to talk to user, validate the response first


def route_after_guardian(state: AgentState):
    # This check is safer with .get
    last_history_entry = state.get("execution_history", [])[-1]
    if last_history_entry["status"] == "APPROVED":
        return "tools"  # Action is safe, execute it
    return "agent"  # Action is unsafe, inform the agent


# --- Graph Wiring ---
graph_builder.add_conditional_edges("agent", route_after_agent)
graph_builder.add_conditional_edges("guardian", route_after_guardian)
graph_builder.add_edge("tools", "agent")
graph_builder.add_edge("validator", END)


memory = MemorySaver()
# The initial state is now handled defensively in each node.
app = graph_builder.compile(checkpointer=memory)
