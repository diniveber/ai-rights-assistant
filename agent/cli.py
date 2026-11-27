"""Interactive CLI for the AI Rights Assistant."""

import argparse
import os
import sys
import traceback
import uuid
from pathlib import Path

import openai
from langchain_core.messages import HumanMessage

from agent import __version__, config
from agent.graph import build_graph, run_turn
from agent.llm import ConfigError, LLMOutputError

HELP = """
מדריך שימוש – עוזר הזכויות
──────────────────────────
כתוב בחופשיות על המצב שלך (עבודה, משפחה, בריאות, מילואים, עלייה...) ושאל אילו זכויות מגיעות לך.
העוזר ישאל שאלות המשך במידת הצורך, יציג זכויות רלוונטיות עם קישורים למקור, וימנע ממענה בנושאים אחרים.

פקודות:
  help  או  ?                  מדריך זה
  /file <נתיב> [שאלה]          צירוף קובץ מקומי (txt, md, pdf, docx) – יידרש אישור [Y/N]
  /summary                     יצירת תקציר שיחה ושמירתו לקובץ – יידרש אישור [Y/N]
  /cost                        עלות ושימוש מצטברים בסשן
  /models                      רשימת המודלים המוגדרים
  /reset                       התחלת שיחה חדשה
  /exit                        יציאה

דוגמאות:
  פוטרתי אחרי 3 שנות עבודה, מה מגיע לי?
  /file "C:\\Users\\me\\Documents\\מכתב ביטוח לאומי.pdf" מה המשמעות של המכתב?
"""

YES = {"y", "yes", "כן", "ט", "כ"}
NO = {"n", "no", "לא", "מ", "ל"}


class Session:
    def __init__(self, model: str, verbose: bool, debug: bool):
        self.model = model
        self.verbose = verbose
        self.debug = debug
        self.app = build_graph()
        self.thread_id = str(uuid.uuid4())
        self.totals = {"input_tokens": 0, "output_tokens": 0, "cost": 0.0, "theoretical_cost": 0.0}

    def reset(self):
        self.thread_id = str(uuid.uuid4())


# ---------------------------------------------------------------- helpers


COLOR = sys.stdout.isatty()


def c(code: str) -> str:
    return f"\033[{code}m" if COLOR else ""


def info(msg: str) -> None:
    print(f"{c('2')}[INFO] {msg}{c('0')}")


def error(msg: str) -> None:
    print(f"{c('91')}[ERROR] {msg}{c('0')}")


def ask_approval(request: dict) -> bool:
    """HITL prompt in the terminal."""
    print(f"\n{c('93')}[HITL] {request.get('message', 'לאשר את הפעולה?')}{c('0')}")
    while True:
        try:
            answer = input("[Y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        if answer in YES:
            return True
        if answer in NO:
            return False
        print("נא להקליד Y או N")


def parse_file_command(arg: str) -> tuple[str, str]:
    """Split '/file <path> [question]'. Supports quoted paths and unquoted paths with spaces."""
    arg = arg.strip()
    if arg[:1] in "\"'":
        quote = arg[0]
        end = arg.find(quote, 1)
        if end > 0:
            return arg[1:end], arg[end + 1 :].strip()
    words = arg.split(" ")
    for i in range(len(words), 0, -1):  # longest prefix that is an existing file
        candidate = " ".join(words[:i])
        if Path(candidate).is_file():
            return candidate, " ".join(words[i:]).strip()
    return words[0], " ".join(words[1:]).strip()


def fmt_cost(actual: float, theoretical: float) -> str:
    if actual == 0 and theoretical > 0:
        return f"$0 (תיאורטי ${theoretical:.5f})"
    return f"${actual:.5f}"


def print_usage(session: Session, usage: list[dict]) -> None:
    if not usage:
        return
    print(f"\n{c('2')}── עלות ושימוש (הודעה זו) ─────────────────────")
    for u in usage:
        print(
            f"  {u['node']:<16} {u['input_tokens']:>6} in / {u['output_tokens']:>5} out"
            f"  {u['latency']:>5.1f}s  {fmt_cost(u['cost'], u['theoretical_cost'])}"
        )
    t_in = sum(u["input_tokens"] for u in usage)
    t_out = sum(u["output_tokens"] for u in usage)
    t_cost = sum(u["cost"] for u in usage)
    t_theo = sum(u["theoretical_cost"] for u in usage)
    label = 'סה"כ'
    print(f"  {label:<16} {t_in:>6} in / {t_out:>5} out          {fmt_cost(t_cost, t_theo)}")
    print(f"  מצטבר בסשן: {fmt_cost(session.totals['cost'], session.totals['theoretical_cost'])}{c('0')}")


def print_totals(session: Session) -> None:
    t = session.totals
    print(
        f"[{session.model}] סה\"כ בסשן: {t['input_tokens']} טוקני קלט / {t['output_tokens']} טוקני פלט · "
        f"עלות: {fmt_cost(t['cost'], t['theoretical_cost'])}"
    )


def describe_error(e: Exception) -> str:
    if isinstance(e, ConfigError):
        return str(e)
    if isinstance(e, openai.AuthenticationError):
        return "מפתח ה-API שגוי או לא בתוקף. בדוק את קובץ .env."
    if isinstance(e, openai.RateLimitError):
        return "חריגה ממגבלת הבקשות או מהיתרה בחשבון. המתן מעט ונסה שוב (במודלים חינמיים – יש מגבלה יומית)."
    if isinstance(e, openai.NotFoundError):
        return "המודל לא נמצא או אינו זמין בחשבון. בדוק את שם המודל (/models)."
    if isinstance(e, (openai.APIConnectionError, openai.APITimeoutError)):
        return "אין חיבור לשרת המודל. בדוק את חיבור האינטרנט ונסה שוב."
    if isinstance(e, openai.APIStatusError) and e.status_code == 418 and "NetFree" in str(e):
        return "הבקשה נחסמה על ידי סינון האינטרנט (NetFree) בגלל מילים בהודעה. נסה לנסח אחרת."
    if isinstance(e, openai.BadRequestError):
        return f"הבקשה נדחתה על ידי הספק: {getattr(e, 'message', e)}"
    if isinstance(e, LLMOutputError):
        return f"{e}. נסה שוב או בחר מודל אחר."
    return f"שגיאה לא צפויה ({type(e).__name__}): {e}"


# ---------------------------------------------------------------- turn


def handle(session: Session, payload: dict) -> None:
    last = {"node": None}

    def on_node(name: str) -> None:
        if session.verbose and name != last["node"]:  # a node resumed after HITL is announced once
            info(f"Entering Node: {name}...")
        last["node"] = name

    try:
        values, usage = run_turn(session.app, session.thread_id, payload, session.model, on_node, ask_approval)
    except Exception as e:  # noqa: BLE001 – every failure is shown as a clear message
        error(describe_error(e))
        if session.debug:
            traceback.print_exc()
        return

    for u in usage:
        for key in session.totals:
            session.totals[key] += u[key]

    print(f"\nעוזר: {values.get('output') or '(אין תשובה)'}")
    if values.get("sources"):
        print("\nמקורות:")
        for s in values["sources"]:
            print(f"  • {s['name']}: {s['url']}")
    print_usage(session, usage)
    print()


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    if not sys.stdin.isatty():  # piped/redirected input (e.g. scripted runs) is UTF-8, not the console codepage
        sys.stdin.reconfigure(encoding="utf-8")
    os.system("")  # enable ANSI colors on Windows consoles

    parser = argparse.ArgumentParser(prog="agent", description="AI Rights Assistant – עוזר זכויות והטבות (CLI)")
    parser.add_argument("--model", help=f"שם המודל (ברירת מחדל: {config.DEFAULT_MODEL})")
    parser.add_argument("--provider", choices=list(config.PROVIDERS), help="ספק: openai או openrouter")
    parser.add_argument("--quiet", action="store_true", help="הסתרת הודעות [INFO] על הנודים")
    parser.add_argument("--debug", action="store_true", help="הצגת traceback מלא בשגיאות")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args()

    model = args.model or (config.DEFAULT_MODELS[args.provider] if args.provider else config.DEFAULT_MODEL)
    provider = config.model_info(model)["provider"]
    key_env = config.PROVIDERS[provider]["api_key_env"]
    if not os.getenv(key_env):
        error(f"{key_env} חסר. צור קובץ .env לפי .env.example (בתיקייה הנוכחית או ליד agent.exe).")
        return 1

    session = Session(model, verbose=not args.quiet, debug=args.debug)
    tracing = os.getenv("LANGSMITH_TRACING", "").lower() == "true" and os.getenv("LANGSMITH_API_KEY")
    print(f"עוזר הזכויות v{__version__} 🇮🇱  ·  מודל: {model} ({provider})  ·  LangSmith: {'פעיל' if tracing else 'כבוי'}")
    print("הקלד help או ? למדריך שימוש.\n")

    while True:
        try:
            text = input("אתה: ").lstrip("﻿").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue

        lower = text.lower()
        if lower in ("help", "?", "/help"):
            print(HELP)
        elif lower in ("/exit", "/quit", "exit"):
            break
        elif lower == "/reset":
            session.reset()
            print("השיחה אופסה.\n")
        elif lower == "/cost":
            print_totals(session)
            print()
        elif lower == "/models":
            for name, m in config.MODELS.items():
                mark = "◀" if name == session.model else " "
                print(f" {mark} {name:<38} {m['provider']:<10} ${m['input']}/{m['output']} per 1M")
            print()
        elif lower == "/summary":
            handle(session, {"command": "summary"})
        elif lower.startswith("/file"):
            path, question = parse_file_command(text[5:])
            if not path:
                error("יש לציין נתיב לקובץ: /file <נתיב> [שאלה]")
                continue
            handle(session, {"command": "file", "pending_file": path, "pending_question": question})
        elif text.startswith("/"):
            error(f"פקודה לא מוכרת: {text.split()[0]} (הקלד help)")
        else:
            handle(session, {"command": "chat", "messages": [HumanMessage(text)]})

    print_totals(session)
    print("להתראות!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
