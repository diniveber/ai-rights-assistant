"""LLM-as-judge: scores an agent answer 1–5 per criterion using evals/rubric.md, on one fixed model."""

import json
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from agent import config, tools
from agent.llm import structured_call

RUBRIC = (Path(__file__).resolve().parent / "rubric.md").read_text(encoding="utf-8")
CRITERIA = ["relevance", "accuracy", "completeness", "format", "reliability"]

JUDGE_PROMPT = f"""אתה שופט מקצועי והוגן שמעריך תשובות של אייג'נט זכויות והטבות בישראל.
דרג את התשובה לפי ה-rubric הבא בלבד. היה מחמיר ועקבי; אל תתגמל אורך לשמו.

{RUBRIC}

החזר ציון שלם 1–5 לכל קריטריון, ונימוק קצר (rationale) בעברית."""


class JudgeScores(BaseModel):
    relevance: int
    accuracy: int
    completeness: int
    format: int
    reliability: int
    rationale: str


def judge(question: str, answer: str, cited_ids: list[str], expected_ids: list[str]) -> tuple[dict, dict]:
    """Return (scores_dict incl. overall, usage_record)."""
    reference_ids = list(dict.fromkeys(expected_ids + cited_ids))
    reference = [tools.RIGHTS_BY_ID[rid] for rid in reference_ids if rid in tools.RIGHTS_BY_ID]
    content = (
        f"## שאלת המשתמש\n{question}\n\n"
        f"## הזכויות המרכזיות הצפויות (מזהים)\n{expected_ids}\n\n"
        f"## הזכויות שהאייג'נט ציין (מזהים)\n{cited_ids}\n\n"
        f"## עובדות מבסיס הידע\n{json.dumps(reference, ensure_ascii=False, indent=1)}\n\n"
        f"## תשובת האייג'נט\n{answer}"
    )
    result, usage = structured_call(
        config.JUDGE_MODEL, JudgeScores, [SystemMessage(JUDGE_PROMPT), HumanMessage(content)], "judge"
    )
    scores = {c: min(5, max(1, getattr(result, c))) for c in CRITERIA}
    scores["judge_overall"] = round(sum(scores.values()) / len(CRITERIA), 2)
    scores["judge_rationale"] = result.rationale
    return scores, usage
