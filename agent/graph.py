"""LangGraph workflow for the AI Rights Assistant.

START ─┬─ chat ──────────────────────────────→ guardrail
       ├─ file ─→ load_file (HITL) ──approved─→ guardrail
       └─ summary → summarize → save_summary (HITL) → END

guardrail ─┬─ in_scope ─→ extract_profile ─┬─ ready ─→ retrieve → draft_answer → evaluator ─┬─ passed ─→ finalize → END
           ├─ greeting → greet → END        └─ missing info → ask_followup → END            └─ failed ─→ draft_answer (once)
           └─ out_of_scope / fraud / injection → refuse → END
"""

from collections.abc import Callable

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from agent import config
from agent.nodes import (
    State, ask_followup, draft_answer, evaluator, extract_profile, finalize, greet,
    guardrail, load_file, refuse, retrieve, save_summary, summarize,
)

# ---------------------------------------------------------------- gates


def route_entry(state: State) -> str:
    command = state.get("command", "chat")
    if command == "file":
        return "load_file"
    if command == "summary":
        return "summarize"
    return "guardrail"


def route_after_file(state: State) -> str:
    return END if state.get("decision") == "cancelled" else "guardrail"


def route_guardrail(state: State) -> str:
    decision = state.get("decision")
    if decision == "in_scope":
        return "extract_profile"
    if decision == "greeting":
        return "greet"
    return "refuse"


def route_profile(state: State) -> str:
    if state.get("ready_to_answer") or state.get("followup_rounds", 0) >= config.MAX_FOLLOWUP_ROUNDS:
        return "retrieve"
    return "ask_followup"


def route_evaluator(state: State) -> str:
    if state.get("eval_passed") or state.get("attempts", 0) >= config.MAX_DRAFT_ATTEMPTS:
        return "finalize"
    return "draft_answer"


def route_summary(state: State) -> str:
    return "save_summary" if state.get("summary") else END


# ---------------------------------------------------------------- build


def build_graph(checkpointer=None):
    g = StateGraph(State)
    for name, fn in [
        ("load_file", load_file), ("guardrail", guardrail), ("greet", greet), ("refuse", refuse),
        ("extract_profile", extract_profile), ("ask_followup", ask_followup), ("retrieve", retrieve),
        ("draft_answer", draft_answer), ("evaluator", evaluator), ("finalize", finalize),
        ("summarize", summarize), ("save_summary", save_summary),
    ]:
        g.add_node(name, fn)

    g.add_conditional_edges(START, route_entry, ["load_file", "guardrail", "summarize"])
    g.add_conditional_edges("load_file", route_after_file, ["guardrail", END])
    g.add_conditional_edges("guardrail", route_guardrail, ["extract_profile", "greet", "refuse"])
    g.add_conditional_edges("extract_profile", route_profile, ["retrieve", "ask_followup"])
    g.add_edge("retrieve", "draft_answer")
    g.add_edge("draft_answer", "evaluator")
    g.add_conditional_edges("evaluator", route_evaluator, ["finalize", "draft_answer"])
    g.add_conditional_edges("summarize", route_summary, ["save_summary", END])
    for terminal in ("greet", "refuse", "ask_followup", "finalize", "save_summary"):
        g.add_edge(terminal, END)

    return g.compile(checkpointer=checkpointer or InMemorySaver())


# ---------------------------------------------------------------- run one turn


def run_turn(
    app,
    thread_id: str,
    payload: dict,
    model: str,
    on_node: Callable[[str], None] | None = None,
    approve: Callable[[dict], bool] | None = None,
) -> tuple[dict, list[dict]]:
    """Stream one user turn through the graph, handling HITL interrupts.

    Returns (final_state_values, usage_records_for_this_turn).
    """
    cfg = {
        "configurable": {"thread_id": thread_id, "model": model},
        "run_name": "rights-assistant-turn",
        "tags": [model, payload.get("command", "chat")],
        "metadata": {"thread_id": thread_id, "model": model},
    }
    before = len(app.get_state(cfg).values.get("usage", []))
    current = {"output": "", "sources": [], **payload}
    while True:
        pending = None
        for mode, chunk in app.stream(current, cfg, stream_mode=["custom", "updates"]):
            if mode == "custom" and on_node and "node" in chunk:
                on_node(chunk["node"])
            elif mode == "updates" and "__interrupt__" in chunk:
                pending = chunk["__interrupt__"][0].value
        if pending is None:
            break
        current = Command(resume=bool(approve(pending)) if approve else False)

    values = app.get_state(cfg).values
    return values, values.get("usage", [])[before:]
