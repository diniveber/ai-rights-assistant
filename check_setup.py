"""Setup check: API keys, model availability per provider, and LangSmith connection."""

import os
import sys

from agent import config
from agent.llm import get_llm


def check_models() -> bool:
    ok = True
    for model, info in config.MODELS.items():
        key_env = config.PROVIDERS[info["provider"]]["api_key_env"]
        if not os.getenv(key_env):
            print(f"✗ {model}: {key_env} חסר ב-.env")
            ok = False
            continue
        try:
            reply = get_llm(model).invoke("ענה במילה אחת: שלום")
            print(f"✓ {model} ({info['provider']}): {reply.content.strip()[:30]}")
        except Exception as e:  # noqa: BLE001
            print(f"✗ {model} ({info['provider']}): {type(e).__name__}: {str(e)[:120]}")
            ok = False
    return ok


def check_langsmith() -> bool:
    if os.getenv("LANGSMITH_TRACING", "").lower() != "true":
        print("– LangSmith: כבוי (LANGSMITH_TRACING אינו true)")
        return True
    try:
        from langsmith import Client

        list(Client().list_projects(limit=1))
        print(f"✓ LangSmith: מחובר (פרויקט: {os.getenv('LANGSMITH_PROJECT', 'default')})")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"✗ LangSmith: {type(e).__name__}: {str(e)[:120]}")
        return False


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"קובץ .env: {config.ENV_FILE or 'לא נמצא'} · ספק ברירת מחדל: {config.LLM_PROVIDER}\n")
    ok = check_models() & check_langsmith()
    print("\n✓ ההגדרה תקינה" if ok else "\n✗ יש בעיות בהגדרה – ראה למעלה")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
