

import os
from dotenv import load_dotenv
from typing import TypedDict, List, Dict, Any
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import BaseMessage, ToolMessage, AIMessage, SystemMessage, HumanMessage
from langgraph.prebuilt import ToolNode
import json
import copy
import database as db
from tools import transfer_funds, get_balance, list_available_accounts, get_transaction_rules
from verifier import guardian_check

load_dotenv()


def get_config(key: str, default: str = None) -> str:
    try:
        import streamlit as st
        if hasattr(st, 'secrets') and key in st.secrets:
            return st.secrets[key]
    except (ImportError, RuntimeError):
        pass
    except Exception as e:
        if "StreamlitAPIException" in str(type(e)) or "StreamlitSecretNotFoundError" in str(type(e)):
            pass
        else:
            raise e
    value = os.getenv(key, default)
    if value is None:
        raise ValueError(f"Configuration key '{key}' not found. Please set it in .env or Streamlit secrets.")
    return value


class AgentState(TypedDict):
    messages: List[BaseMessage]
    execution_history: List[dict]
    pending_tool_call: Dict[str, Any] | None


def entry_router(state: AgentState) -> str:
    """The entry point router. Decides if we are starting a new flow or handling a confirmation."""
    if state.get("pending_tool_call"):
        # If we have a pending tool call, the user is either confirming or canceling
        return "confirmation_router"
    else:
        # Otherwise, this is a new user request
        return "doer"


def doer_node(state: AgentState):
    system_prompt = (
        "You are a specialized parsing AI. Your task is to analyze the user's most recent request and translate it into a single, valid tool call based on the available tools. "
        "You must determine which tool is most appropriate and extract the necessary parameters. "
        "If the user's request is ambiguous or does not map to a specific tool, do not ask for clarification. Instead, call the 'no_op' tool. "
        "Do not generate any conversational text. Your output must be a single tool call."
    )
    last_user_message = state["messages"][-1]
    tools_with_no_op = tools + [no_op]
    llm_with_doer_tools = llm.bind_tools(tools_with_no_op)
    result = llm_with_doer_tools.invoke([SystemMessage(content=system_prompt), last_user_message])
    return {"messages": state["messages"] + [result]}


def guardian_node(state: AgentState):
    last_message = state["messages"][-1]
    tool_call = last_message.tool_calls[0]

    # If the Doer decided no action was needed, we just record that.
    if tool_call['name'] == 'no_op':
        history_entry = {"tool_name": "no_op", "status": "SKIPPED"}
        return {
            "messages": state["messages"],
            "execution_history": state.get("execution_history", []) + [history_entry]
        }

    if tool_call['name'] == 'transfer_funds':
        original_args = tool_call['args']
        normalized_args = original_args.copy()
        
        destination = normalized_args.get('destination', '')
        destination_lower = destination.lower()

        # Create a lowercase-to-canonical mapping of account names
        accounts = db.get_all_accounts()
        canonical_map = {acc['id'].lower(): acc['id'] for acc in accounts}

        # Try a few normalization strategies
        normalized_destination = None
        if destination_lower in canonical_map:
            # Strategy 1: Direct match (e.g., "account_c" -> "Account_C")
            normalized_destination = canonical_map[destination_lower]
        elif f"account_{destination_lower}" in canonical_map:
            # Strategy 2: Single-letter match (e.g., "c" -> "account_c" -> "Account_C")
            normalized_destination = canonical_map[f"account_{destination_lower}"]

        if normalized_destination:
            normalized_args['destination'] = normalized_destination
            # Update the tool call with the corrected arguments before verification
            tool_call['args'] = normalized_args

    is_safe, reason = guardian_check(tool_call)
    history_entry = {"tool_name": tool_call['name'], "tool_args": tool_call['args']}

    if is_safe:
        history_entry["status"] = "AWAITING_CONFIRMATION"
        history_entry["reason"] = "All checks passed. Awaiting user confirmation."
        # Halt and wait for confirmation by storing the tool call
        return {
            "messages": state["messages"],
            "execution_history": state.get("execution_history", []) + [history_entry],
            "pending_tool_call": tool_call,
        }
    else:
        history_entry["status"] = "BLOCKED"
        history_entry["reason"] = reason
        return {
            "messages": state["messages"],
            "execution_history": state.get("execution_history", []) + [history_entry],
            "pending_tool_call": None,
        }


def confirmation_router(state: AgentState) -> str:
    """Handles the user's response to a confirmation request."""
    user_response = state["messages"][-1].content.strip().upper()
    if user_response == "CONFIRM":
        return "tool_node"
    else: # Any other response (e.g., "CANCEL") is treated as a cancellation
        # Update the history to show the user cancelled
        last_event = state["execution_history"][-1]
        last_event["status"] = "CANCELLED_BY_USER"
        last_event["reason"] = "User rejected the proposed transaction."
        return "talker"


def tool_node(state: AgentState):
    """Executes the tool call that was previously verified and user-confirmed."""
    tool_call_to_execute = state.get("pending_tool_call")
    if not tool_call_to_execute:
        # This should not happen if the graph is wired correctly
        return state

    # The ToolNode requires the tool call to be in a message
    tool_input_message = AIMessage(content="", tool_calls=[tool_call_to_execute])
    tool_result_dict = tool_node_executor.invoke({"messages": [tool_input_message]})
    
    tool_output = tool_result_dict['messages'][0].content
    
    new_history = copy.deepcopy(state.get("execution_history", []))
    new_history[-1]["status"] = "SUCCESSFULLY_EXECUTED"
    new_history[-1]["result"] = tool_output
    
    return {
        "messages": state["messages"],
        "execution_history": new_history,
        "pending_tool_call": None, # Clear the pending call
    }


def talker_node(state: AgentState):
    """Generates a user-friendly response based on the final state."""
    history = state.get("execution_history")

    # Find the last human message for context
    last_human_message = ""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            last_human_message = msg.content
            break

    if not history or history[-1].get("tool_name") == "no_op":
         # This means the "Doer" chose no_op on the last turn
        final_response_prompt = (
            "You are a helpful and friendly financial assistant. The user's last request was ambiguous or not related to a financial action. "
            "Politely ask for clarification or try to help with their request. User's message: "
            f"'{last_human_message}'"
        )
    else:
        last_event = history[-1]
        status = last_event.get("status")
        if status == "AWAITING_CONFIRMATION":
            # This is a special case handled by the UI, but we provide a fallback message.
            final_response_prompt = "A transaction is awaiting your confirmation. Please respond with 'confirm' or 'cancel'."
        else:
             final_response_prompt = (
                "You are a helpful and friendly financial assistant. Your role is to communicate the result of a financial operation to the user. "
                "Based *only* on the following final system event, generate a clear and direct response. "
                "Do not add any information not present in the event summary."
                f"\n\n**Final System Event:**\n{json.dumps(last_event, indent=2)}"
            )

    talker_llm = ChatOpenAI(
        model=get_config("OPENROUTER_MODEL", "qwen/qwen3-next-80b-a3b-instruct"),
        temperature=0.7,
        base_url=get_config("OPENROUTER_BASE_URL"),
        api_key=get_config("OPENROUTER_API_KEY")
    )
    final_response = talker_llm.invoke(final_response_prompt).content
    return {"messages": state["messages"] + [AIMessage(content=final_response)]}


def route_after_doer(state: AgentState):
    last_message = state["messages"][-1]
    if not last_message.tool_calls or last_message.tool_calls[0]['name'] == 'no_op':
        return "talker"
    return "guardian"

def route_after_guardian(state: AgentState):
    last_history_entry = state["execution_history"][-1]
    if last_history_entry["status"] == "AWAITING_CONFIRMATION":
        # We halt the graph here. The UI will take over.
        return END
    # If blocked or any other status, go to the talker to report it
    return "talker"


# --- LLM and Tool Setup ---
llm = ChatOpenAI(
    model=get_config("OPENROUTER_MODEL", "qwen/qwen3-next-80b-a3b-instruct"),
    temperature=0,
    base_url=get_config("OPENROUTER_BASE_URL"),
    api_key=get_config("OPENROUTER_API_KEY")
)
def no_op():
    """Call this tool when the user's request is ambiguous or does not map to a specific action."""
    pass
tools = [transfer_funds, get_balance, list_available_accounts, get_transaction_rules]
tool_node_executor = ToolNode(tools)

# --- Graph Definition ---
graph_builder = StateGraph(AgentState)

# Add all the nodes
graph_builder.add_node("doer", doer_node)
graph_builder.add_node("guardian", guardian_node)
graph_builder.add_node("tool_node", tool_node)
graph_builder.add_node("talker", talker_node)
# Add dummy nodes to host the routers
graph_builder.add_node("entry_router_node", lambda state: state)
graph_builder.add_node("confirmation_router_node", lambda state: state)

graph_builder.set_entry_point("entry_router_node")

# --- Graph Wiring ---
graph_builder.add_conditional_edges(
    "entry_router_node",
    entry_router,
    {
        "confirmation_router": "confirmation_router_node",
        "doer": "doer"
    }
)
graph_builder.add_conditional_edges(
    "confirmation_router_node",
    confirmation_router,
    {
        "tool_node": "tool_node",
        "talker": "talker"
    }
)
graph_builder.add_conditional_edges(
    "doer", 
    route_after_doer,
    {
        "talker": "talker",
        "guardian": "guardian"
    }
)
graph_builder.add_conditional_edges(
    "guardian", 
    route_after_guardian,
    {
        END: END, # The graph can end here if confirmation is required
        "talker": "talker"
    }
)
graph_builder.add_edge("tool_node", "talker")
graph_builder.add_edge("talker", END)

memory = MemorySaver()
app = graph_builder.compile(checkpointer=memory)
