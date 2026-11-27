"""Graph nodes: guardrail, extract_profile, retrieve, draft_answer, evaluator and friends."""

import json
import operator
from functools import wraps
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.graph.message import add_messages
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from agent import config as settings, prompts, tools
from agent.llm import structured_call

# ---------------------------------------------------------------- state


class State(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]  # conversation (short-term memory)
    command: str                 # "chat" | "file" | "summary" – set by the CLI each turn
    pending_file: str            # path given with /file
    pending_question: str        # question that accompanies the file
    decision: str                # guardrail decision
    profile: str                 # cumulative profile summary
    categories: list[str]
    keywords: list[str]
    follow_up_questions: list[str]
    ready_to_answer: bool
    followup_rounds: int
    retrieved: list[dict]
    draft: str
    right_ids: list[str]
    eval_passed: bool
    eval_feedback: str
    attempts: int
    summary: str
    summary_file: str
    output: str                  # text the CLI shows for this turn
    sources: list[dict]
    usage: Annotated[list[dict], operator.add]  # per-node token & cost records


def _model(config: RunnableConfig) -> str:
    return (config.get("configurable") or {}).get("model", settings.DEFAULT_MODEL)


def node(name: str):
    """Decorator: announce node entry on the 'custom' stream so the CLI can show progress."""

    def deco(fn):
        @wraps(fn)
        def wrapper(state, config: RunnableConfig):
            try:
                get_stream_writer()({"node": name})
            except Exception:  # noqa: BLE001 – no stream writer outside a streamed run
                pass
            return fn(state, config)

        return wrapper

    return deco


def _recent(messages: list, n: int = 6) -> list:
    return [m for m in messages if isinstance(m, (HumanMessage, AIMessage))][-n:]


# ---------------------------------------------------------------- schemas


class GuardDecision(BaseModel):
    decision: Literal["in_scope", "greeting", "out_of_scope", "fraud", "injection"]
    reason: str = Field(description="נימוק קצר")


class ProfileExtraction(BaseModel):
    profile_summary: str
    categories: list[Literal[tuple(tools.CATEGORIES)]]  # type: ignore[valid-type]
    keywords: list[str]
    missing_info: list[str]
    follow_up_questions: list[str]
    ready_to_answer: bool


class Draft(BaseModel):
    answer: str
    relevant_right_ids: list[str]


class Evaluation(BaseModel):
    passed: bool
    issues: list[str]


class Summary(BaseModel):
    summary: str


# ---------------------------------------------------------------- entry / HITL: file


@node("load_file")
def load_file(state: State, config: RunnableConfig) -> dict:
    """HITL: ask the user before reading a local file (may contain personal data)."""
    path = state.get("pending_file", "")
    approved = interrupt({"action": "read_file", "message": f"לקרוא את הקובץ '{path}' ולשלוח את תוכנו למודל?"})
    base = {"pending_file": "", "pending_question": ""}
    if not approved:
        return {**base, "output": "הקובץ לא נקרא (הפעולה בוטלה).", "decision": "cancelled", "sources": []}
    try:
        name, text = tools.read_file(path)
    except tools.FileReadError as e:
        return {**base, "output": f"שגיאה: {e}", "decision": "cancelled", "sources": []}
    question = state.get("pending_question") or "צירפתי קובץ. אילו זכויות רלוונטיות לי לפיו?"
    content = f"{question}\n\n[תוכן הקובץ המצורף: {name}]\n{text}"
    return {**base, "messages": [HumanMessage(content=content)]}


# ---------------------------------------------------------------- guardrail & gates


@node("guardrail")
def guardrail(state: State, config: RunnableConfig) -> dict:
    """GuardRail: classify scope, fraud and prompt-injection. Also resets per-turn fields."""
    msgs = [SystemMessage(prompts.GUARDRAIL), *_recent(state["messages"])]
    result, usage = structured_call(_model(config), GuardDecision, msgs, "guardrail")
    return {
        "decision": result.decision,
        "attempts": 0,
        "eval_feedback": "",
        "draft": "",
        "right_ids": [],
        "retrieved": [],
        "sources": [],
        "usage": [usage],
    }


@node("greet")
def greet(state: State, config: RunnableConfig) -> dict:
    return {"output": prompts.GREETING, "messages": [AIMessage(prompts.GREETING)]}


@node("refuse")
def refuse(state: State, config: RunnableConfig) -> dict:
    text = prompts.REFUSALS.get(state.get("decision", ""), prompts.REFUSALS["out_of_scope"])
    return {"output": text, "messages": [AIMessage(text)]}


# ---------------------------------------------------------------- understanding


@node("extract_profile")
def extract_profile(state: State, config: RunnableConfig) -> dict:
    system = prompts.EXTRACT_PROFILE.format(categories=", ".join(tools.CATEGORIES))
    msgs = [SystemMessage(system), *_recent(state["messages"], 12)]
    result, usage = structured_call(_model(config), ProfileExtraction, msgs, "extract_profile")
    return {
        "profile": result.profile_summary,
        "categories": list(result.categories),
        "keywords": result.keywords,
        "follow_up_questions": result.follow_up_questions[:3],
        "ready_to_answer": result.ready_to_answer,
        "usage": [usage],
    }


@node("ask_followup")
def ask_followup(state: State, config: RunnableConfig) -> dict:
    questions = state.get("follow_up_questions") or ["ספר לי קצת על המצב שלך: גיל, עבודה, משפחה ובריאות."]
    numbered = "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1))
    text = f"כדי לזהות את הזכויות שמתאימות לך, אשמח לדעת עוד כמה פרטים:\n{numbered}"
    return {
        "output": text,
        "messages": [AIMessage(text)],
        "followup_rounds": state.get("followup_rounds", 0) + 1,
    }


# ---------------------------------------------------------------- RAG


@node("retrieve")
def retrieve(state: State, config: RunnableConfig) -> dict:
    found = tools.search_rights(state.get("keywords", []), state.get("categories", []))
    return {"retrieved": found}


# ---------------------------------------------------------------- answer & evaluator


def _rights_block(rights: list[dict]) -> str:
    return json.dumps(rights, ensure_ascii=False, indent=1) if rights else "(לא נמצאו זכויות מתאימות)"


@node("draft_answer")
def draft_answer(state: State, config: RunnableConfig) -> dict:
    feedback = state.get("eval_feedback", "")
    feedback_block = f"\n## הערות מבקר האיכות לטיוטה הקודמת – תקן אותן\n{feedback}" if feedback else ""
    system = prompts.DRAFT_ANSWER.format(
        profile=state.get("profile", ""), rights=_rights_block(state.get("retrieved", [])), feedback=feedback_block
    )
    msgs = [SystemMessage(system), *_recent(state["messages"], 12)]
    result, usage = structured_call(_model(config), Draft, msgs, "draft_answer")
    allowed = {r["id"] for r in state.get("retrieved", [])}
    return {
        "draft": result.answer,
        "right_ids": [rid for rid in result.relevant_right_ids if rid in allowed],
        "attempts": state.get("attempts", 0) + 1,
        "usage": [usage],
    }


@node("evaluator")
def evaluator(state: State, config: RunnableConfig) -> dict:
    chosen = [tools.RIGHTS_BY_ID[rid] for rid in state.get("right_ids", [])]
    system = prompts.EVALUATOR.format(
        profile=state.get("profile", ""), rights=_rights_block(chosen), draft=state.get("draft", "")
    )
    result, usage = structured_call(_model(config), Evaluation, [SystemMessage(system)], "evaluator")
    return {"eval_passed": result.passed, "eval_feedback": "\n".join(f"- {i}" for i in result.issues), "usage": [usage]}


@node("finalize")
def finalize(state: State, config: RunnableConfig) -> dict:
    sources = [
        {"id": rid, "name": tools.RIGHTS_BY_ID[rid]["name"], "url": tools.RIGHTS_BY_ID[rid]["source_url"]}
        for rid in state.get("right_ids", [])
    ]
    draft = state.get("draft", "").replace("**", "").replace("__", "").strip()  # plain text for the terminal
    text = f"{draft}\n\n{prompts.DISCLAIMER}"
    return {"output": text, "sources": sources, "messages": [AIMessage(text)], "followup_rounds": 0}


# ---------------------------------------------------------------- summary export (HITL)


@node("summarize")
def summarize(state: State, config: RunnableConfig) -> dict:
    convo = _recent(state.get("messages", []), 40)
    if not convo:
        return {"summary": "", "output": "אין עדיין שיחה לסכם."}
    result, usage = structured_call(_model(config), Summary, [SystemMessage(prompts.SUMMARY), *convo], "summarize")
    return {"summary": result.summary, "summary_file": str(tools.summary_path()), "usage": [usage]}


@node("save_summary")
def save_summary(state: State, config: RunnableConfig) -> dict:
    """HITL: ask before writing a file to the user's disk."""
    path = state["summary_file"]
    approved = interrupt({"action": "write_file", "message": f"לשמור את תקציר השיחה לקובץ '{path}'?"})
    if not approved:
        return {"output": f"{state['summary']}\n\n(התקציר לא נשמר)"}
    saved = tools.export_summary(state["summary"], tools.Path(path))
    return {"output": f"{state['summary']}\n\n✓ התקציר נשמר: {saved}"}
