# AI Rights Assistant – עוזר זכויות והטבות

אייג'נט CLI בעברית שעוזר לתושבי ישראל לגלות זכויות והטבות שמגיעות להם. הוא מכסה ביטוח לאומי, דיני עבודה, מסים, הנחות ברשות המקומית וזכויות עולים.

האייג'נט בנוי כ-Workflow ב-**LangGraph** ומנוטר ב-**LangSmith**. הוא:
- מבין את המצב של המשתמש, ושואל שאלות המשך כשחסרים פרטים חשובים.
- שולף זכויות רלוונטיות מבסיס ידע מקומי (RAG), ומציג לכל אחת תנאי זכאות, דרך מימוש וקישור למקור רשמי.
- מסרב לשאלות מחוץ לתחום, לבקשות לרמות את המערכת ולניסיונות prompt injection.
- קורא קובץ מקומי (למשל מכתב פיטורים) ומייצא תקציר שיחה, בשני המקרים רק אחרי אישור `[Y/N]` מהמשתמש.

> ⚠️ האייג'נט מספק מידע כללי בלבד ואינו מחליף ייעוץ משפטי או פנייה לגורם המוסמך.

---

## הורדה והרצה מהירה (Windows)

1. מורידים את `agent.exe` מעמוד ה-[Releases](https://github.com/diniveber/ai-rights-assistant/releases).
2. באותה תיקייה יוצרים קובץ `.env` לפי [.env.example](.env.example). מספיק `OPENAI_API_KEY`, ומפתח LangSmith אופציונלי.
3. מריצים מתוך הטרמינל:
   ```
   agent.exe
   ```

---

## ארכיטקטורה

```
                        ┌──────────────┐
    /file ─────────────▶│  load_file   │──(HITL: Y/N)──┐
                        └──────────────┘               │
                                                       ▼
 הודעה ───────────────────────────────────────▶ ┌─────────────┐
                                                │  guardrail  │  GuardRail
                                                └─────────────┘
                     מחוץ לתחום / הונאה / injection │  ברכה  │  בתחום
                        ┌──────────────────────────┘    │    │
                        ▼                               ▼    ▼
                   ┌─────────┐                   ┌───────┐ ┌─────────────────┐
                   │ refuse  │                   │ greet │ │ extract_profile │  Gate
                   └─────────┘                   └───────┘ └─────────────────┘
                                                  חסר מידע │          │ מספיק מידע
                                                           ▼          ▼
                                                  ┌──────────────┐ ┌──────────┐
                                                  │ ask_followup │ │ retrieve │  RAG (BM25)
                                                  └──────────────┘ └──────────┘
                                                                        │
                                                                        ▼
                                                                ┌──────────────┐
                                                        ┌──────▶│ draft_answer │
                                                        │       └──────────────┘
                                                  נכשל  │               │
                                       (ניסיון חוזר אחד)│               ▼
                                                        │        ┌───────────┐
                                                        └────────│ evaluator │  Evaluator
                                                                 └───────────┘
                                                                       │ עבר
                                                                       ▼
                                                                 ┌──────────┐
                                                                 │ finalize │  מקורות + הסתייגות
                                                                 └──────────┘

 /summary ─▶ summarize ─(HITL: Y/N)─▶ save_summary
```

| רכיב | מימוש |
|---|---|
| **GuardRails** | הנוד `guardrail` מסווג כל הודעה לאחת הקטגוריות: `in_scope`, ‏`greeting`, ‏`out_of_scope`, ‏`fraud`, ‏`injection` |
| **Gates** | קצוות מותנים: בקשה מחוץ לתחום מגיעה לסירוב, וכשחסר מידע עוברים לשאלות המשך (עד 2 סבבים) |
| **Evaluator** | הנוד `evaluator` בודק שהתשובה מבוססת רק על הזכויות שנשלפו ושהיא בפורמט הנכון. אם הבדיקה נכשלת, התשובה חוזרת לניסוח פעם אחת |
| **HITL** | `interrupt` של LangGraph, עם אישור `[Y/N]` לפני קריאת קובץ אישי ולפני שמירת תקציר לדיסק |
| **הרחבה: RAG** | חיפוש BM25 מקומי בקובץ [agent/data/rights.json](agent/data/rights.json), שכולל 19 זכויות ב-9 קטגוריות, כל אחת עם קישור למקור |
| **זיכרון שיחה** | checkpointer של LangGraph. הפרטים שהמשתמש מסר נצברים לאורך השיחה |
| **ניטור** | LangSmith, דרך משתני סביבה. ריצות ה-evals נשמרות בפרויקט נפרד עם הסיומת `-evals` |
| **ספק LLM** | ‏OpenAI כברירת מחדל. אפשר לעבור ל-OpenRouter עם `LLM_PROVIDER=openrouter` או `--provider openrouter` |
| **עלויות** | כל קריאה למודל נמדדת לפי tokens × תמחור, ומוצגת לפי נוד. למודל חינמי מוצגת גם העלות התיאורטית |

### מבנה הפרויקט

```
ai-rights-assistant/
├── agent/
│   ├── __init__.py
│   ├── config.py         # ספקים, מודלים, תמחור
│   ├── llm.py            # יצירת מודל לפי ספק + מדידת עלות
│   ├── prompts.py        # פרומפטים לכל נוד
│   ├── graph.py          # הגדרת ה-LangGraph workflow
│   ├── nodes.py          # guardrail, extract, retrieve, draft, evaluator, refuse, HITL...
│   ├── tools.py          # RAG (BM25), קריאת קבצים, ייצוא תקציר
│   ├── cli.py            # entrypoint של ה-CLI
│   └── data/rights.json  # בסיס הידע
├── evals/
│   ├── dataset.py        # 10 שאלות בתחום + 10 מחוץ לתחום, מתויגות
│   ├── judge.py          # LLM-as-judge על מודל קבוע
│   ├── rubric.md         # rubric לשופט
│   ├── compare_models.py # eval 1 – השוואת מודלים
│   ├── cost_eval.py      # eval 2 – עלויות
│   ├── scope_eval.py     # eval 3 – מקצועיות ואי-זליגה
│   └── results/          # פלטי CSV
├── check_setup.py        # בדיקת מפתחות וחיבורים
├── manifest.json
├── requirements.txt
├── README.md
└── .env.example
```

---

## התקנה מקוד המקור

דרוש Python 3.10 ומעלה.

```bash
git clone https://github.com/diniveber/ai-rights-assistant.git
cd ai-rights-assistant
python -m venv .venv
.venv\Scripts\activate          # ב-Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # ממלאים את המפתחות
python check_setup.py           # בודק את OpenAI, ‏OpenRouter ו-LangSmith
```

### משתני סביבה (`.env`)

| משתנה | תיאור |
|---|---|
| `LLM_PROVIDER` | ‏`openai` (ברירת מחדל) או `openrouter` |
| `OPENAI_API_KEY` | מפתח OpenAI |
| `OPENROUTER_API_KEY` | מפתח OpenRouter (חשבון חינמי מספיק למודלים החינמיים) |
| `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` | ניטור ב-LangSmith |
| `RIGHTS_MODEL` | אופציונלי: מודל ברירת מחדל |

---

## שימוש ב-CLI

```bash
python -m agent.cli                                   # מקוד המקור
agent.exe                                             # מהקובץ המקומפל
agent.exe --provider openrouter                       # מודל חינמי דרך OpenRouter
agent.exe --model gpt-5.4-nano --quiet
```

| פקודה | תיאור |
|---|---|
| `help` או `?` | מדריך שימוש קצר |
| `/file <נתיב> [שאלה]` | צירוף קובץ מקומי (txt, ‏md, ‏pdf, ‏docx). דורש אישור `[Y/N]` |
| `/summary` | תקציר שיחה ושמירתו לקובץ טקסט בתיקייה `summaries/`. דורש אישור `[Y/N]` |
| `/cost` | עלות ושימוש מצטברים בסשן |
| `/models` | רשימת המודלים המוגדרים |
| `/reset` | התחלת שיחה חדשה |
| `/exit` | יציאה |

אפשרויות שורת פקודה: `--model`, ‏`--provider`, ‏`--quiet` (מסתיר את הודעות ה-INFO), ‏`--debug` (מציג traceback מלא), ‏`--version`.

### דוגמת שיחה

```
> פוטרתי
[INFO] Entering Node: guardrail...
[INFO] Entering Node: extract_profile...
[INFO] Entering Node: ask_followup...
כדי לבדוק אילו זכויות מגיעות לך, אשמח לדעת:
1. כמה זמן עבדת במקום העבודה?
2. האם עבדת במשרה מלאה, ומה היה השכר החודשי בערך?

> 3 שנים, משרה מלאה
[INFO] Entering Node: guardrail...
[INFO] Entering Node: extract_profile...
[INFO] Entering Node: retrieve...
[INFO] Entering Node: draft_answer...
[INFO] Entering Node: evaluator...
[INFO] Entering Node: finalize...
עוזר: ... פיצויי פיטורים, הודעה מוקדמת, דמי אבטלה ...

מקורות:
  • פיצויי פיטורים: https://...

── עלות ושימוש (הודעה זו) ─────────────────────
  guardrail           539 in /    63 out    1.9s  $0.00069
  extract_profile     830 in /   287 out    6.9s  $0.00191
  draft_answer       1980 in /   616 out    4.6s  $0.00426
  evaluator          1802 in /   142 out    2.4s  $0.00199
  סה"כ               5151 in /  1108 out          $0.00885
  מצטבר בסשן: $0.00885
```

(הדוגמה מקוצרת. המספרים לקוחים מהרצה אמיתית של gpt-5.4-mini ומשתנים בכל הרצה.)

השגיאות מוצגות בהודעות ברורות בעברית: מפתח חסר או שגוי, מודל לא זמין, חריגה ממגבלת קצב, בעיית חיבור או קובץ שלא נמצא.

---

## Evals

שלושה evals. כל אחד שומר CSV מפורט וקובץ `_summary.csv` בתיקייה [evals/results/](evals/results/).

```bash
python evals/compare_models.py     # השוואת מודלים (LLM-as-judge)
python evals/cost_eval.py          # עלויות
python evals/scope_eval.py         # מקצועיות ואי-זליגה
```

### 1. השוואת מודלים

אותן שאלות רצות על שלושה מודלים: שניים בתשלום ב-OpenAI ואחד חינמי ב-OpenRouter. המדדים:
- **זמן:** נמדד אוטומטית.
- **איכות ואמינות:** שופט LLM-as-judge נותן ציון 1–5 לפי [evals/rubric.md](evals/rubric.md), בחמישה קריטריונים: רלוונטיות, דיוק עובדתי, שלמות, פורמט ואמינות. השופט הוא מודל קבוע אחד לכל ההשוואות, **gpt-5.4**, שבכוונה לא נמצא בין המודלים שנבדקים, כדי למנוע הטיה לטובת עצמו.
- **איכות הנתונים:** precision, ‏recall ו-F1 של הזכויות שזוהו, מול הזכויות שתויגו מראש לכל שאלה.

| מודל | שאלות | ציון שופט | אמינות | F1 | זמן ממוצע | עלות לשאלה |
|---|---|---|---|---|---|---|
| gpt-5.4-mini | 10 | **4.86** | **5.0** | **1.00** | **10.1 שנ'** | $0.0087 |
| gpt-5.4-nano | 10 | 4.56 | 4.6 | 0.96 | 15.2 שנ' | **$0.0030** |
| nemotron-3.5-super-vl:free | 6 | 4.67 | 4.17 | **1.00** | 81.7 שנ' | ‏$0 (תיאורטית $0.0043) |

**מסקנה:**
- ‏**gpt-5.4-mini** הוא האיכותי והמהיר ביותר, ולכן הוא ברירת המחדל.
- ‏**gpt-5.4-nano** זול פי 3 בערך ואיכותו קרובה. החולשה שלו היא בשלמות התשובות, למשל בשאלה על אזרח ותיק.
- **המודל החינמי** זיהה את כל הזכויות הנכונות, אבל קיבל את ציון האמינות הנמוך ביותר. הוא גם איטי פי 8 בערך, ולכן לא מתאים לשימוש אינטראקטיבי.

> המודל החינמי נבדק על 6 שאלות בלבד, בגלל המכסה היומית של OpenRouter: ‏50 בקשות ביום. כדי להריץ רק אותו בלי לדרוס את שאר התוצאות:
> `python evals/compare_models.py --models nvidia/nemotron-3.5-super-vl:free --merge`

### 2. עלויות

שש משימות נפוצות: שאלה מפורטת, שאלה עמומה שמובילה לשאלות המשך, שיחה רב-שלבית, שאלה מחוץ לתחום, ניתוח קובץ מקומי, ושאלה עם תקציר שיחה. לכל משימה מחושבת עלות לכל נוד ועלות כוללת, לפי tokens × תמחור. למודל החינמי מוצגת עלות בפועל ($0) ולצידה עלות תיאורטית לפי תעריף שווה-ערך.

| מודל | קריאות LLM | עלות בפועל (6 משימות) | עלות תיאורטית | הערכה ל-1,000 משימות |
|---|---|---|---|---|
| gpt-5.4-nano | 20 | $0.0133 | $0.0133 | $2.21 |
| gpt-5.4-mini | 22 | $0.0465 | $0.0465 | $7.75 |
| nemotron-3.5-super-vl:free | 24 | $0.00 | $0.0223 | ‏$0 (תיאורטית $3.71) |

### 3. מקצועיות ואי-זליגה

10 שאלות מחוץ לתחום: מתכונים, קוד, מניות, ייעוץ רפואי, פוליטיקה, בקשות הונאה ו-prompt injection, כולל מקרים גבוליים. בנוסף רצות 10 שאלות בתחום, כדי לזהות סירובי-יתר.

| מודל | Refusal rate | זליגות | סירובי-יתר | דיוק כולל |
|---|---|---|---|---|
| gpt-5.4-nano | **100%** (10/10) | 0 | 0% | 100% |
| gpt-5.4-mini | **100%** (10/10) | 0 | 0% | 100% |
| nemotron-3.5-super-vl:free | **100%** (10/10) | 0 | 0% (0/2) | 100% |

כל המודלים סירבו לכל השאלות שמחוץ לתחום ולא ענו בטעות על אף אחת. הם גם לא סירבו לאף שאלה לגיטימית. ‏mini והמודל החינמי זיהו נכון את **סוג** הבעיה בכל 10 המקרים, כלומר הבחינו בין שאלה מחוץ לתחום, ניסיון הונאה ו-prompt injection. ‏nano זיהה נכון 9 מתוך 10.

> המודל החינמי רץ על כל 10 השאלות שמחוץ לתחום, אבל רק על 2 שאלות בתחום, בגלל המכסה היומית: `python evals/scope_eval.py --models nvidia/nemotron-3.5-super-vl:free --free-in-scope 2 --merge`

---

## בניית agent.exe

> ‏PyInstaller לא תומך ב-Python 3.10.0, בגלל באג במודול `dis`. לבנייה צריך Python ‏3.10.1 ומעלה. הקובץ שפורסם נבנה ב-Python 3.11.

```bash
py -3.11 -m venv .venv-build
.venv-build\Scripts\pip install -r requirements.txt
.venv-build\Scripts\pyinstaller --noconfirm agent.spec
```

הקובץ [agent.spec](agent.spec) בונה את [run_agent.py](run_agent.py) לקובץ exe יחיד מסוג Console. הוא כולל את `rights.json` ואת קבצי ה-metadata של ספריות LangChain. הבנייה ממנו שקולה לפקודה הזו:

```bash
pyinstaller --noconfirm --onefile --console --name agent ^
  --add-data "agent/data/rights.json;agent/data" --collect-data langchain_core ^
  --copy-metadata langsmith --copy-metadata langchain-core ^
  --copy-metadata langchain-openai --copy-metadata langgraph run_agent.py
```

הקובץ נוצר בנתיב `dist/agent.exe` ושוקל כ-35MB. כדי להריץ אותו, שמים לידו קובץ `.env`.

---

## מגבלות

- **בסיס הידע מוגבל:** 19 זכויות מרכזיות בלבד. סכומים ותנאים מתעדכנים מדי שנה, ולכן חשוב לבדוק תמיד בקישור הרשמי.
- **המודל החינמי:** ב-OpenRouter יש מכסה של 50 בקשות חינמיות ביום, וזמן התגובה ארוך. לכן הוא נבדק על מדגם קטן יותר.
- **השופט:** ‏gpt-5.4 הוא מאותה משפחה כמו המודלים שנבדקים. השופט היחיד מאפשר השוואה עקבית בין המודלים, אבל הוא לא מחליף בדיקה אנושית.
- **עברית בטרמינל של Windows:** ב-Windows Terminal ובטרמינל של VS Code העברית מוצגת היטב. ב-`cmd.exe` הישן היא עלולה להופיע הפוכה או כסימני שאלה. מומלץ להריץ ב-Windows Terminal.
- **פרטיות:** התקצירים נשמרים מקומית בתיקייה `summaries/`, שאינה נשמרת ב-git. אם LangSmith פעיל, ההודעות נשלחות לניטור. אפשר לכבות אותו עם `LANGSMITH_TRACING=false`.
