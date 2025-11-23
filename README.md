# SentinelVerifier 🛡️

**"We built the first Guardian AI that doesn't just *guess* if an action is safe—it *proves* it mathematically using runtime formal verification."**

SentinelVerifier is an MVP demonstrating a small provable AI agent security architecture. Instead of relying on probabilistic LLM-based safety filters, this project implements a deterministic **Execution Guardrail** using a Satisfiability Modulo Theories (SMT) solver (Microsoft's Z3) to formally verify agent actions against a set of inviolable rules *before* they are executed.

## Key Features & Innovations

1.  **Neuro-Symbolic Architecture:** This project moves beyond pure LLM chaining. It combines a generative AI (for understanding user intent) with a symbolic AI (Z3, for rigid, provable logic), representing a state-of-the-art hybrid approach to AI safety.
2.  **Runtime Formal Verification:** We use the Z3 solver to construct mathematical proofs on-the-fly. The system doesn't just check if a transaction is "less than $10,000"; it formally proves that the proposed action satisfies the logical invariant `amount <= 10000`.
3.  **Complex Logical Invariants:** The verifier goes beyond simple bounds checking. It enforces complex, conditional rules, such as: `Implies(amount > 8000, destination == "Account_D")`. This proves the system's ability to handle sophisticated, real-world business logic.
4.  **LLM Hallucination & Disobedience Defense:** The system implements a second security layer: a **Response Guardrail**. A dedicated "auditor" LLM cross-references the agent's final text response against an immutable execution log to prevent the agent from lying to or misleading the user after an action has been blocked.
5.  **Transparent Proof Visualization:** The UI includes a "System Monitor" that provides a live log of every attempted action. For each transaction, the user can see the exact logical proof that was submitted to the Z3 solver and its `SATISFIABLE` or `UNSATISFIABLE` result.

## Tech Stack

-   **Orchestration:** `langgraph`
-   **Agent LLM:** OpenRouter-compatible models (e.g., `qwen/qwen3-next-80b-a3b-instruct`) via `langchain-openai`
-   **Formal Verification (Symbolic AI):** `z3-solver`
-   **UI & Visualization:** `streamlit`
-   **State Management:** In-memory simulation (`account_state.py`)

## How to Run

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/peti12352/sentinel_verfier.git
    cd sentinel_verfier
    ```

2.  **Set up the environment:**
    ```bash
    # Create and activate a virtual environment
    python -m venv venv
    .\venv\Scripts\Activate.ps1
    
    # Install dependencies
    pip install -r requirements.txt
    ```

3.  **Configure API Keys:**
    -   Create a file named `.env` in the project root.
    -   Add your OpenRouter API key and other settings:
        ```ini
        OPENROUTER_API_KEY="your-key-here"
        OPENROUTER_BASE_URL="https://openrouter.ai/api/v1"
        OPENROUTER_MODEL="qwen/qwen3-next-80b-a3b-instruct"
        ```

4.  **Run the application:**
    ```bash
    streamlit run app.py
    ```

-   **The Problem:** Standard AI agents are black boxes. Their safety is based on "fuzzy" prompting, which fails under adversarial attacks. You can't *prove* they are safe.
-   **Our Solution:** A hybrid, neuro-symbolic architecture that separates understanding from verification. We use an LLM for what it's good at (language) and a formal solver for what it's good at (unbreakable logic).
-   **The Differentiator:** We are demonstrating the "Zelkova for Agents"—just as AWS uses SMT solvers to verify IAM policies, we use them to verify AI agent actions in real-time. This isn't just another chatbot; it's a blueprint for building provably safe autonomous systems.
