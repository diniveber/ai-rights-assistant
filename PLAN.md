# תוכנית עבודה – AI Rights Assistant (לפי מסמך הקורס)

> סמן `[x]` ליד כל משימה שהושלמה כדי לעקוב אחר ההתקדמות.
> מסמך מחייב: `פרויקט_סיום_LLMs.docx` (צ'קליסט נספח 7). ספק ברירת מחדל: OpenAI, עם אפשרות מעבר ל-OpenRouter.

---

## מטרה

אייג'נט CLI בפייתון, בנוי כ-Workflow ב-**LangGraph** ומנוטר ב-**LangSmith**, שמסייע לתושבי ישראל לזהות זכויות והטבות:
מבין הקשר, שואל שאלות המשך, שולף זכויות מבסיס ידע (RAG), מציג מקורות ונמנע ממענה מחוץ לתחום.

---

## מבנה הפרויקט (לפי הנדרש)

```
ai-rights-assistant/
├── agent/
│   ├── __init__.py
│   ├── config.py         # ספק, מודלים, מחירים
│   ├── llm.py            # יצירת מודל לפי ספק (OpenAI / OpenRouter) + מדידת עלות
│   ├── prompts.py        # פרומפטים לכל נוד
│   ├── graph.py          # הגדרת ה-LangGraph workflow
│   ├── nodes.py          # guardrail, extract, retrieve, draft, evaluator, refuse
│   ├── tools.py          # RAG (BM25 על rights.json), קריאת קובץ, ייצוא תקציר
│   ├── cli.py            # entrypoint של ה-CLI
│   └── data/rights.json  # בסיס הידע
├── evals/
│   ├── dataset.py        # שאלות מתויגות (בתחום / מחוץ לתחום)
│   ├── judge.py          # LLM-as-judge (מודל קבוע)
│   ├── compare_models.py # eval השוואת מודלים
│   ├── cost_eval.py      # eval עלויות
│   ├── scope_eval.py     # eval מקצועיות ואי-זליגה
│   ├── rubric.md         # rubric לשופט
│   └── results/          # פלטי CSV
├── manifest.json
├── requirements.txt
├── README.md
└── .env.example
```

---

## ארכיטקטורת הגרף

```
קלט → [guardrail] ──מחוץ לתחום / injection──→ [refuse] → סוף
            │ (Gate)
            ▼
      [extract_profile] ──חסר מידע──→ [ask_followup] → סוף
            │ (Gate)
            ▼
      [retrieve]  ← RAG על rights.json
            │
            ▼
      [draft_answer] → [evaluator] ──נכשל (ניסיון חוזר אחד)──→ [draft_answer]
                            │ עבר
                            ▼
                          סוף
```

| רכיב | מימוש |
|---|---|
| GuardRails | נוד `guardrail`: סיווג תחום + זיהוי prompt injection / בקשות מרמה |
| Gates | קצוות מותנים: מחוץ לתחום → סירוב; חסר מידע → שאלות המשך |
| Evaluator | נוד `evaluator`: בודק שהתשובה מבוססת על הזכויות שנשלפו ובפורמט הנכון |
| HITL | `interrupt` של LangGraph + אישור `[Y/N]` לפני קריאת קובץ אישי ולפני שמירת תקציר לדיסק |
| הרחבה | RAG: חיפוש BM25 מקומי בבסיס הידע (לא תלוי בספק) |
| ניטור | LangSmith – משתני סביבה בלבד |
| החלפת ספק | `LLM_PROVIDER=openai` / `openrouter` ב-`.env` |

---

## שלב 0 – הכנות

- [x] Python 3.10+ מותקן
- [x] סביבה וירטואלית `.venv` פעילה
- [x] מפתח OpenAI API ב-`.env`
- [x] GitHub CLI מותקן ומחובר
- [x] חשבון **LangSmith** + מפתח API ב-`.env`
- [x] חשבון **OpenRouter** (חינמי, ללא מנוי) + מפתח API ב-`.env`
- [ ] (מומלץ) בירור מול המרצה: האם מסמך הקורס מחייב, ומה לגבי OpenAI במקום OpenRouter

## שלב 1 – תשתית ✅ / עדכון

- [x] `requirements.txt`, `.env.example`, `.gitignore`, `config.py`, `check_setup.py`
- [x] הוספת תלויות: `langgraph`, `langchain-openai`, `langsmith`, `rank-bm25`, `pypdf`, `pyinstaller`
- [x] עדכון `.env.example`: `LLM_PROVIDER`, `OPENROUTER_API_KEY`, `LANGSMITH_*`
- [x] `agent/config.py` – ספקים, 3 מודלים (`gpt-5.4-nano`, `gpt-5.4-mini`, `nvidia/nemotron-3.5-super-vl:free`), מחירים + מחיר ייחוס לחינמי
- [x] `agent/llm.py` – יצירת מודל לפי ספק + חישוב עלות (כולל עלות תיאורטית למודלים חינמיים)
- [x] עדכון `check_setup.py` – בדיקת OpenAI, OpenRouter ו-LangSmith (כולם ✓)

## שלב 2 – בסיס ידע ✅

- [x] `rights.json` – 19 זכויות, כל הקישורים נבדקו
- [x] העברה ל-`agent/data/rights.json`
- [ ] **בדיקה (אתה):** מעבר מהיר על התוכן

## שלב 3 – הגרף (LangGraph)

- [x] `agent/prompts.py` – פרומפטים לכל נוד (מבוסס על הפרומפט הקיים)
- [x] `agent/tools.py` – `search_rights` (BM25 + קטגוריות), `read_file` (txt/md/pdf/docx), `export_summary`
- [x] `agent/nodes.py`:
  - [x] `guardrail` – סיווג: in_scope / greeting / out_of_scope / fraud / injection
  - [x] `refuse` – סירוב מנומס לפי סוג (ללא קריאה למודל), `greet` – ברכה
  - [x] `extract_profile` – חילוץ פרטים מצטבר + זיהוי מידע חסר
  - [x] `ask_followup` – שאלות המשך (עד 2 סבבים)
  - [x] `retrieve` – שליפת זכויות (RAG)
  - [x] `draft_answer` – ניסוח תשובה
  - [x] `evaluator` – בדיקת עיגון ופורמט, החזרה לניסוח פעם אחת אם נכשל
  - [x] `finalize` – מקורות + הסתייגות (דטרמיניסטי)
  - [x] `load_file`, `summarize`, `save_summary` – עם HITL (`interrupt`)
- [x] `agent/graph.py` – StateGraph, קצוות מותנים, checkpointer לשמירת הקשר, `run_turn` משותף ל-CLI ול-evals
- [x] מעקב עלות לכל נוד (tokens × תמחור)
- [x] מחיקת `agent.py` / `cli.py` / `config.py` הישנים מהשורש
- [x] בדיקה מקצה לקצה: 8 תרחישים (עמומה, פרטים, ברכה, מחוץ לתחום, injection, הונאה, קובץ, תקציר) – כולם עברו, $0.031

## שלב 4 – CLI

- [x] לולאת שיחה אינטראקטיבית (`python -m agent.cli`)
- [x] Streaming: `[INFO] Entering Node: retrieve...` בזמן אמת
- [x] `help` / `?` – מדריך שימוש קצר
- [x] `/file <נתיב> [שאלה]` – קריאת קובץ מקומי (txt/md/pdf/docx) עם אישור HITL `[Y/N]`
- [x] `/summary` – ייצוא תקציר שיחה לקובץ טקסט (`summaries/`), עם אישור HITL (בונוס)
- [x] `/cost` + הצגת עלות ושימוש בסוף כל הודעה (פירוט לפי נוד, כולל עלות תיאורטית)
- [x] `/reset`, `/models`, `/exit`, פרמטרים `--model`, `--provider`, `--quiet`, `--debug`, `--version`
- [x] הודעות שגיאה ברורות (מפתח חסר, מפתח שגוי, מודל לא זמין, rate limit, חיבור, קובץ לא נמצא)
- [ ] **בדיקה (אתה):** `python -m agent.cli` – שיחה עמומה, המשך שיחה, מחוץ לתחום, injection, קובץ, תקציר
- [ ] **בדיקה (אתה):** הריצה מופיעה ב-LangSmith

## שלב 5 – Evals Suite

- [x] `evals/dataset.py` – 10 שאלות בתחום (עם זכויות צפויות) + 10 מחוץ לתחום (כולל גבוליים ו-injection)
- [x] `evals/rubric.md` – ציון 1–5: רלוונטיות לתפקיד, דיוק עובדתי, שלמות, עמידה בפורמט, אמינות נתונים
- [x] `evals/judge.py` – שופט על מודל יחיד וקבוע
- [x] `evals/compare_models.py` – אותן שאלות על 3 מודלים (2 OpenAI בתשלום + 1 חינמי ב-OpenRouter):
  זמן, איכות, אמינות ואיכות נתונים → `results/compare_models.csv`
- [x] `evals/cost_eval.py` – משימות נפוצות, עלות לכל נוד ועלות כוללת, עלות בפועל + תיאורטית → `results/cost_eval.csv`
- [x] `evals/scope_eval.py` – refusal rate על שאלות מחוץ לתחום + סירובי-יתר בתחום → `results/scope_eval.csv`
- [ ] **בדיקה (אתה):** הרצת שלושת ה-evals ומעבר על ה-CSV

## שלב 6 – manifest.json ו-README

- [x] `manifest.json` לפי נספח 1: `name`, `version`, `description`, `creator_name`, `contact_information`,
  `release_date`, `repository_url`, `download_url`, `target_audience`, `professional_fields`,
  `tasks_capable_of_performing`, `examples_of_suitable_questions`, `technical_specifications`
- [x] **החלטה (אתה):** שם ופרטי קשר שיופיעו ב-manifest (הריפו ציבורי)
- [x] `README.md` – הסבר, תרשים ארכיטקטורה, התקנה, הרצה ב-CLI, פקודות, evals ותוצאות, מגבלות
- [x] הערה על תצוגת עברית בטרמינל ב-Windows

## שלב 7 – PyInstaller

- [x] `agent.spec` / פקודת בנייה הכוללת את `rights.json`
- [x] בניית `dist/agent.exe` (Console)
- [x] **בדיקה:** הרצת `agent.exe` בתיקייה נקייה עם `.env` בלבד

## שלב 8 – GitHub ו-Release

- [x] `git init`, קומיטים מסודרים
- [x] **וידוא שאין מפתחות** בקבצים או בהיסטוריה (`.env` מוחרג)
- [x] `gh repo create ai-rights-assistant --public --source . --push`
- [x] תג `v1.0.0` + `gh release create v1.0.0 dist/agent.exe`
- [x] עדכון `download_url` ב-manifest לפי הקישור בפועל

---

## צ'קליסט נספח 7

**ארכיטקטורה**
- [x] משימה ספציפית וממוקדת
- [x] Workflow ב-LangGraph (נודים וקצוות)
- [x] חיבור לספק LLM (OpenAI, עם אפשרות OpenRouter; מודלים בתשלום + חינמי)
- [x] GuardRails, Gates, Evaluator
- [x] HITL עם `[Y/N]` לפני פעולות רגישות
- [x] הרחבה אחת לפחות (RAG)
- [x] ניטור LangSmith

**CLI**
- [x] ממשק אינטראקטיבי
- [x] Streaming של הנוד הנוכחי
- [x] הצגת עלויות ושימוש בסיום משימה
- [x] שגיאות ברורות
- [x] `help` / `?`
- [x] עבודה עם קבצים לפי נתיב
- [ ] ~~MCP~~ (לא בשימוש)
- [x] [בונוס] ייצוא תקציר שיחה

**Evals**
- [x] פלט CSV לכל eval בקובץ נפרד
- [x] השוואת מודלים עם LLM-as-judge לפי rubric (המודל החינמי – ממתין לחידוש מכסה)
- [x] עלויות: מודל בתשלום, עלות לכל שלב ועלות כוללת, עלות תיאורטית לחינמי
- [x] אי-זליגה: ≥5 שאלות מחוץ לתחום, refusal rate ב-CSV

**הפצה**
- [x] `agent.exe` עם PyInstaller
- [x] ריפו GitHub מסודר
- [x] exe תחת Releases
- [x] `manifest.json` לפי נספח 1
- [x] `README.md` מפורט
- [x] `.env.example` ללא ערכים אמיתיים
- [x] מבנה תיקיות כנדרש

---

## לוח זמנים

| זמן | משימות |
|---|---|
| יום 1 · בוקר | שלב 0 (חשבונות), שלבים 1–3 (תשתית וגרף) |
| יום 1 · אחה"צ | שלב 4 (CLI) ובדיקות שיחה |
| יום 2 · בוקר | שלב 5 (Evals) |
| יום 2 · אחה"צ | שלבים 6–8 (manifest, README, exe, GitHub, Release) |
