"""
Evaluator Agent - FastAPI service

Scores a completed OSCE-style encounter (patient interview + written notes +
oral-exam answers) against a structured rubric and writes a short review.

READ THIS BEFORE TRUSTING THE NUMBERS
  * The rubric below is a DRAFT. It is loosely organised around the domains of
    the Calgary-Cambridge guide, but the items are NOT the official instrument
    and have NOT been reviewed by faculty. Replace it with your faculty's real
    rubric before any validation study.
  * Scores come from a small (8B) open-weight model acting as judge. LLM judges
    tend to be lenient, so this service enforces one rule in code: any credit
    above zero must be backed by evidence that can be CHECKED
        - interview items: the number of a Student turn in the transcript
        - notes items:     a notes section that is actually non-empty
        - viva items:      each key point marked as covered needs a quote that really appears
                           in the student's answer; the 0/1/2 score is then computed by code
    If the model cites no valid evidence, the score is reset to 0 and flagged.
    The model's original score is kept as `llm_score` so you can measure
    leniency later (useful for the "does the judge over-score?" question).
  * The viva "expected key points" were drafted by the same small model in the
    Examiner service and are not clinically verified.

Run with:
    uvicorn evaluator_service:app --host 0.0.0.0 --port 8200

Expects:
  - vLLM at http://localhost:8734/v1/chat/completions
  - ./sessions/<patient_session_id>.json       (written by patient_twin_service_v2.py)
  - ./examiner_results/<exam_id>.json          (written by examiner_service.py /finish)
"""

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# ---------------- CONFIG ----------------
VLLM_URL = "http://localhost:8734/v1/chat/completions"
MODEL_NAME = "meta-llama/Llama-3.1-8B-Instruct"
BASE_DIR = Path(__file__).parent
SESSIONS_DIR = BASE_DIR / "sessions"
EXAMINER_RESULTS_DIR = BASE_DIR / "examiner_results"
EVALUATOR_RESULTS_DIR = BASE_DIR / "evaluator_results"
EVALUATOR_RESULTS_DIR.mkdir(exist_ok=True)

RUBRIC_VERSION = "draft-0.1"
JUDGE_TEMPERATURE = 0.1
MAX_TRANSCRIPT_CHARS = 14000  # keeps prompt + output inside an 8192-token context
DISCLAIMER = (
    "This is an AI-generated assessment based on a draft rubric. It has not been "
    "validated against faculty grading and is intended for research and practice only."
)
# -----------------------------------------

# Score scale used everywhere: 0 = not done, 1 = partly done, 2 = clearly done
RUBRIC = {
    "history_taking": {
        "label": "Information gathering",
        "items": [
            {"id": "H1", "text": "Elicited the presenting complaint with open-ended questions",
             "guide": "Counts: a question that invites a free-text answer, such as 'What brought you in?' or 'How are you feeling?'. Does not count: only yes/no questions."},
            {"id": "H2", "text": "Explored onset, duration and character of the main symptom",
             "guide": "Counts: asking when it started, how long it has lasted, or what it feels like."},
            {"id": "H3", "text": "Asked about associated symptoms",
             "guide": "Counts ONLY if the Student asked about other symptoms (for example 'any fever or nausea?'). Does NOT count if the patient mentioned other symptoms without being asked."},
            {"id": "H4", "text": "Asked about relevant past medical history",
             "guide": "Counts: asking about past illnesses, operations or long-term conditions."},
            {"id": "H5", "text": "Asked about current medications and/or allergies",
             "guide": "Counts: asking about medications OR allergies."},
            {"id": "H6", "text": "Asked about relevant social history or risk factors",
             "guide": "Counts: asking about smoking, alcohol, occupation, living situation, travel or other risk factors."},
            {"id": "H7", "text": "Asked about relevant family history",
             "guide": "Counts: asking about illnesses that run in the family."},
        ],
    },
    "communication": {
        "label": "Communication",
        "items": [
            {"id": "C1", "text": "Greeted the patient and established rapport",
             "guide": "Counts: a greeting, introducing themselves, or a friendly opening."},
            {"id": "C2", "text": "Used clear, jargon-free language",
             "evidence": "all_student_turns",
             "guide": "Counts if the Student's own lines avoid medical jargon. This item judges all of the Student's lines together, so cite any Student turn."},
            {"id": "C3", "text": "Acknowledged the patient's feelings or concerns",
             "guide": "Counts: an empathic statement such as 'I'm sorry you're going through this'. A purely clinical question does not count."},
            {"id": "C4", "text": "Summarised or checked understanding with the patient",
             "guide": "Counts: restating the patient's story in the Student's own words, or asking 'have I understood correctly?'."},
        ],
    },
    "clinical_reasoning": {
        "label": "Clinical reasoning (written notes)",
        "items": [
            {"id": "R1", "text": "Notes accurately record the key findings the patient reported",
             "guide": "Counts: the HISTORY section lists the main symptoms the patient reported, without major errors."},
            {"id": "R2", "text": "Notes include a reasonable differential diagnosis",
             "guide": "Counts: the ASSESSMENT section names at least one plausible diagnosis; stronger if it lists alternatives."},
            {"id": "R3", "text": "Notes include sensible next steps (investigations or management)",
             "guide": "Counts: the ASSESSMENT section lists investigations or management steps."},
        ],
    },
}
VIVA_LABEL = "Oral examination"

app = FastAPI(title="Evaluator Agent Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------- LOADING ----------------
def _check_id(value: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", value or ""):
        raise HTTPException(status_code=400, detail="Invalid id format")
    return value


def load_json(path: Path, missing_msg: str) -> dict:
    if not path.exists():
        raise HTTPException(status_code=404, detail=missing_msg)
    with open(path, "r") as f:
        return json.load(f)


# ---------------- TRANSCRIPT FORMATTING ----------------
def format_transcript(transcript: list[dict]) -> list[tuple[int, str]]:
    lines = []
    for i, turn in enumerate(transcript):
        speaker = "Student" if turn.get("role") == "user" else "Patient"
        lines.append((i, f"[{i}] {speaker}: {turn.get('content', '')}"))
    return lines


def clip_transcript(lines: list[tuple[int, str]]) -> str:
    """Keep original turn numbers. If too long, keep the first 4 turns and the most recent ones."""
    total = sum(len(text) for _, text in lines)
    if total <= MAX_TRANSCRIPT_CHARS:
        return "\n".join(text for _, text in lines)
    head = lines[:4]
    used = sum(len(text) for _, text in head)
    tail = []
    for item in reversed(lines[4:]):
        if used + len(item[1]) > MAX_TRANSCRIPT_CHARS:
            break
        tail.append(item)
        used += len(item[1])
    tail.reverse()
    return "\n".join([t for _, t in head] + ["[... some middle turns omitted for length ...]"] + [t for _, t in tail])


# ---------------- MODEL CALLS ----------------
async def call_llm(prompt: str, temperature: float = JUDGE_TEMPERATURE) -> str:
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            VLLM_URL,
            json={
                "model": MODEL_NAME,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": 1800,
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


def _repair_json(text: str) -> str:
    """Fixes two slips small models make: a key with no value (e.g. {"n": 3, "quote"}) and trailing commas."""
    text = re.sub(r'([{,]\s*)"(quote|evidence|feedback|evidence_section)"(\s*[,}])', r'\1"\2": ""\3', text)
    text = re.sub(r',(\s*[}\]])', r'\1', text)
    return text


def parse_llm_json(raw: str):
    """Tolerant parser. Handles code fences, text around the JSON, small repairs (see _repair_json), several JSON
    objects in a row (some models emit one object per item), and truncated output (keeps the complete items)."""
    text = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        span = text[start : end + 1]
        for candidate in (span, _repair_json(span)):
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
    text = _repair_json(text)
    decoder = json.JSONDecoder()
    objects, i = [], 0
    while True:
        start = text.find("{", i)
        if start == -1:
            break
        try:
            obj, stop = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            i = start + 1
            continue
        objects.append(obj)
        i = stop
    if not objects:
        return None
    if len(objects) == 1:
        return objects[0]
    merged = []
    for obj in objects:
        if isinstance(obj, dict) and isinstance(obj.get("items"), list):
            merged.extend(obj["items"])
    if not merged:
        merged = [o for o in objects if isinstance(o, dict) and "id" in o]
    return {"items": merged} if merged else objects[0]


RETRY_NOTE = (
    "\n\nYour previous reply was not valid JSON. Reply again with valid JSON only: every key must have a value "
    '(use "" for an empty string), no comments, and no text outside the JSON.'
)


async def call_json(prompt: str):
    """Returns (parsed_or_None, raw_text). On unparseable output, retries once at temperature 0 and says what was wrong."""
    raw = None
    for attempt in range(2):
        try:
            raw = await call_llm(
                prompt if attempt == 0 else prompt + RETRY_NOTE,
                temperature=JUDGE_TEMPERATURE if attempt == 0 else 0.0,
            )
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Model service error: {e}")
        parsed = parse_llm_json(raw)
        if parsed is not None:
            return parsed, raw
    return None, raw


# ---------------- PROMPTS ----------------
SCALE_TEXT = """SCORING SCALE for each item:
0 = not done at all
1 = partly done (attempted but incomplete, or only indirectly)
2 = clearly and adequately done"""


def _item_block(items: list[dict]) -> str:
    return "\n".join(f"{i['id']}: {i['text']}\n   How to judge: {i.get('guide', '')}" for i in items)


def build_transcript_prompt(transcript_text: str, items: list[dict], student_turns: list[int]) -> str:
    turn_list = ", ".join(str(t) for t in student_turns)
    return f"""You are scoring a medical/nursing student's simulated patient interview against a rubric. Use ONLY the transcript below as evidence.

TRANSCRIPT (turn numbers in square brackets):
{transcript_text}

The Student's turns are numbered: {turn_list}. Only these numbers can be cited as evidence. Patient turns are context only.

RUBRIC ITEMS:
{_item_block(items)}

{SCALE_TEXT}

STRICT RULES:
- Judge ONLY what the Student said. Information the patient volunteered without being asked does NOT count as the student asking for it.
- Any score above 0 MUST cite at least one Student turn number in "evidence_turns", written as plain integers, for example [0, 2]. If you cannot cite a Student turn, the score must be 0.
- Be strict. When unsure between two scores, choose the lower one.
- "feedback" is ONE short sentence to the student about what they actually said or did not say. Do not just repeat the rubric wording.

Respond ONLY with ONE JSON object in exactly this shape, with an entry for every rubric item:
{{"items": [{{"id": "H1", "score": 0, "evidence_turns": [], "feedback": "..."}}]}}"""


def build_notes_prompt(sections: dict, transcript_text: str, diagnosis: str, items: list[dict]) -> str:
    return f"""You are scoring the written notes a student wrote after interviewing a simulated patient.

The correct diagnosis for this case (hidden from the student) is: {diagnosis}.
Give credit for a differential that includes it, but do not penalise other reasonable options that fit the findings. Do not reveal the diagnosis in your feedback.

WHAT THE PATIENT ACTUALLY SAID (for checking that the notes are accurate):
{transcript_text}

STUDENT NOTES:
HISTORY: {sections['history'] or '(blank)'}
EXAM: {sections['exam'] or '(blank)'}
ASSESSMENT AND PLAN: {sections['assessment'] or '(blank)'}

RUBRIC ITEMS:
{_item_block(items)}

{SCALE_TEXT}

STRICT RULES:
- Judge ONLY what is written in the notes.
- Any score above 0 MUST name the notes section it relies on in "evidence_section". The only valid values are exactly "history", "exam" or "assessment". The differential diagnosis and the plan are both in the "assessment" section. The section must contain text.
- Be strict. When unsure between two scores, choose the lower one.
- "feedback" is ONE short sentence to the student about what their notes actually contain or lack. Do not just repeat the rubric wording.

Respond ONLY with ONE JSON object in exactly this shape, with an entry for every rubric item:
{{"items": [{{"id": "R1", "score": 0, "evidence_section": "history", "feedback": "..."}}]}}"""


def build_viva_prompt(recs: list[dict]) -> str:
    blocks = []
    for r in recs:
        kps = "\n".join(f"  {n}. {kp}" for n, kp in enumerate(r["expected_key_points"], start=1))
        blocks.append(f"{r['id']}: {r['text']}\nKey points:\n{kps}\nStudent answer: {r['student_answer']}")
    joined = "\n\n".join(blocks)
    return f"""You are scoring a student's oral-exam answers. For each question you get numbered key points and the student's answer.

{joined}

For EACH key point, decide whether the student's answer covers it.

STRICT RULES:
- A key point is covered only if the answer actually states that idea, in any wording. Being on the same general topic is not enough. Do not reward length.
- A key point made of several parts is covered only if the answer addresses ALL of its parts.
- For every key point you mark covered, copy a short phrase (3 to 15 words) EXACTLY as the student wrote it into "quote". The phrase must come from THAT question's own answer, not from another question's answer. If you cannot quote the answer, mark the key point as not covered.
- For a key point that is not covered, write only {{"n": 2, "covered": false}} and leave "quote" out.
- "feedback" is ONE short sentence to the student about what their answer did or did not cover.

Return ONE JSON object whose "items" list has an entry for EVERY question above, each listing EVERY key point. Do not output several separate JSON objects. Exactly this shape:
{{"items": [{{"id": "V1", "key_points": [{{"n": 1, "covered": true, "quote": "words copied from this answer"}}, {{"n": 2, "covered": false}}], "feedback": "..."}}]}}"""


def build_review_prompt(domains: dict) -> str:
    lines = []
    for d in domains.values():
        pct = "not scored" if d["percent"] is None else f"{d['percent']}%"
        lines.append(f"{d['label']}: {pct}")
        for it in d["items"]:
            # an item whose credit could not be verified says nothing reliable about the student, so the review must not
            if it["score"] is not None and not str(it.get("flag") or "").startswith("reset"):
                note = it["feedback"] or "not demonstrated in the conversation"
                lines.append(f"  - ({it['score']}/2) {it['text']} -- {note}")
    results = "\n".join(lines)
    return f"""Write a short, supportive written review for a medical/nursing student, based ONLY on the scored results below. Do not invent findings, do not mention any diagnosis, and do not mention scores that are not listed. Only praise areas scored 70% or above; describe areas below 50% as needing work.

RESULTS:
{results}

Respond ONLY with JSON in exactly this shape:
{{"summary": "2-3 sentences", "strengths": ["up to 3 short points"], "improvements": ["up to 3 short, actionable points"]}}"""


# ---------------- VALIDATION (the part that keeps the judge honest) ----------------
def _norm_score(value):
    try:
        v = int(value)
    except (TypeError, ValueError):
        return None
    return v if v in (0, 1, 2) else None


def _int_list(value) -> list[int]:
    """Accepts [4], ["4"], ["[4]"], "turn 4", "[0, 2]" ... and returns plain ints."""
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    out = []
    for x in items:
        if isinstance(x, bool):
            continue
        if isinstance(x, int):
            out.append(x)
        elif isinstance(x, float) and x.is_integer():
            out.append(int(x))
        elif isinstance(x, str):
            out.extend(int(n) for n in re.findall(r"\d+", x))
    return out


def normalize_section(value):
    """Maps what the model calls a notes section onto history / exam / assessment, or None."""
    t = str(value or "").strip().lower()
    if not t:
        return None
    if "histor" in t or t in ("hx", "subjective"):
        return "history"
    if "exam" in t or "objective" in t:
        return "exam"
    if any(w in t for w in ("assess", "differential", "plan", "diagnos", "impression")):
        return "assessment"
    return None


def _items_by_id(parsed) -> dict:
    if isinstance(parsed, dict) and "id" in parsed and "items" not in parsed:
        return {str(parsed["id"]): parsed}  # a single bare item
    items = parsed.get("items") if isinstance(parsed, dict) else None
    if not isinstance(items, list):
        return {}
    return {str(it["id"]): it for it in items if isinstance(it, dict) and "id" in it}


def _blank_record(item: dict) -> dict:
    return {
        "id": item["id"],
        "text": item["text"],
        "score": None,        # the score actually used
        "llm_score": None,    # what the model originally said (kept for auditing leniency)
        "feedback": "",
        "llm_feedback": "",   # model's wording, kept in the saved record only
        "flag": None,
    }


def _reset(rec: dict) -> None:
    """Credit claimed without checkable evidence -> 0. The model's feedback would now contradict the score, so it is blanked."""
    rec["score"] = 0
    rec["flag"] = "reset_no_valid_evidence"
    rec["llm_feedback"] = rec["feedback"]
    rec["feedback"] = ""


def deterministic_zero(items: list[dict], message: str) -> list[dict]:
    out = []
    for item in items:
        rec = _blank_record(item)
        rec.update(score=0, feedback=message, flag="deterministic_zero")
        out.append(rec)
    return out


def validate_transcript_items(parsed, items: list[dict], student_turns: set[int]) -> list[dict]:
    by_id = _items_by_id(parsed)
    results = []
    for item in items:
        rec = _blank_record(item)
        rec["evidence_turns"] = []
        raw = by_id.get(item["id"])
        if raw is None:
            rec["flag"] = "not_scored_no_model_output"
        else:
            llm_score = _norm_score(raw.get("score"))
            rec["llm_score"] = llm_score
            rec["feedback"] = str(raw.get("feedback", ""))[:300]
            if llm_score is None:
                rec["flag"] = "not_scored_invalid_score"
            else:
                turns = [t for t in _int_list(raw.get("evidence_turns")) if t in student_turns]
                if not turns and item.get("evidence") == "all_student_turns":
                    # "absence" items (e.g. no jargon) have no single line to point at - the evidence is every Student line
                    turns = sorted(student_turns)
                rec["evidence_turns"] = turns
                if llm_score > 0 and not turns:
                    _reset(rec)
                else:
                    rec["score"] = llm_score
        results.append(rec)
    return results


def validate_notes_items(parsed, items: list[dict], nonblank_sections: set[str]) -> list[dict]:
    by_id = _items_by_id(parsed)
    results = []
    for item in items:
        rec = _blank_record(item)
        rec["evidence_section"] = None
        raw = by_id.get(item["id"])
        if raw is None:
            rec["flag"] = "not_scored_no_model_output"
        else:
            llm_score = _norm_score(raw.get("score"))
            rec["llm_score"] = llm_score
            rec["feedback"] = str(raw.get("feedback", ""))[:300]
            section = normalize_section(raw.get("evidence_section"))
            if llm_score is None:
                rec["flag"] = "not_scored_invalid_score"
            else:
                if section in nonblank_sections:
                    rec["evidence_section"] = section
                if llm_score > 0 and rec["evidence_section"] is None:
                    _reset(rec)
                else:
                    rec["score"] = llm_score
        results.append(rec)
    return results


STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with", "is", "are", "was", "were",
    "be", "it", "that", "this", "as", "at", "by", "i", "would", "can", "may",
}


def _norm_text(text) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def quote_supported(quote: str, answer: str) -> bool:
    """True only if the quoted phrase really comes from the student's answer.
    Needs >= 3 words (unless the whole answer is that short); exact match, or >= 80% of its content words present."""
    q, a = _norm_text(quote), _norm_text(answer)
    if not q or not a:
        return False
    if len(q.split()) < 3 and len(a.split()) > 3:
        return False
    if q in a:
        return True
    words = [w for w in q.split() if w not in STOPWORDS]
    if len(words) < 2:
        return False
    answer_words = set(a.split())
    return sum(w in answer_words for w in words) / len(words) >= 0.8


def viva_score(verified: int, total: int) -> int:
    """Computed by code, not by the model: none -> 0, at least two thirds -> 2, otherwise 1."""
    if total <= 0 or verified <= 0:
        return 0
    return 2 if verified * 3 >= total * 2 else 1


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "yes", "covered", "1")


def apply_viva_scores(parsed, recs: list[dict]) -> None:
    by_id = _items_by_id(parsed)
    for rec in recs:
        raw = by_id.get(rec["id"])
        if raw is None:
            rec["flag"] = "not_scored_no_model_output"
            continue
        entries = raw.get("key_points")
        if not isinstance(entries, list):
            rec["flag"] = "not_scored_invalid_format"  # never silently zero a student for a formatting slip
            continue
        n = len(rec["expected_key_points"])
        claims = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            nums = _int_list(entry.get("n"))
            if len(nums) == 1 and 1 <= nums[0] <= n and _truthy(entry.get("covered")):
                claims[nums[0]] = str(entry.get("quote") or "")
        verified = {k: q for k, q in claims.items() if quote_supported(q, rec["student_answer"])}
        rec["feedback"] = str(raw.get("feedback", ""))[:300]
        rec["llm_score"] = viva_score(len(claims), n)      # what the model's own claims would have earned
        rec["score"] = viva_score(len(verified), n)        # what the verified claims earn
        rec["key_points_hit"] = sorted(verified)
        rec["key_point_evidence"] = {str(k): q for k, q in sorted(verified.items())}
        if claims and not verified:
            _reset(rec)
        elif len(verified) < len(claims):
            rec["llm_feedback"] = rec["feedback"]
            rec["feedback"] = f"Covered {len(verified)} of {n} expected points."
            rec["flag"] = "partial_unverified"


# ---------------- SUMMARIES ----------------
def summarize_domain(label: str, items: list[dict]) -> dict:
    scored = [i for i in items if i["score"] is not None]
    max_points = 2 * len(scored)
    points = sum(i["score"] for i in scored)
    return {
        "label": label,
        "points": points,
        "max_points": max_points,
        "percent": round(100 * points / max_points) if max_points else None,
        "unscored_items": len(items) - len(scored),
        "items": items,
    }


def fallback_review(domains: dict) -> dict:
    strengths, improvements = [], []
    for d in domains.values():
        for it in d["items"]:
            if it["score"] == 2:
                strengths.append(f"Done well: {it['text']}")
            elif it["score"] == 0:
                improvements.append(f"Missed or incomplete: {it['text']}")
    return {
        "summary": "The written review could not be generated automatically. See the item-by-item results below.",
        "strengths": strengths[:3],
        "improvements": improvements[:3],
        "source": "deterministic_fallback",
    }


def public_view(record: dict) -> dict:
    domains = {}
    for key, d in record["domains"].items():
        items = [{k: v for k, v in it.items() if k != "llm_feedback"} for it in d["items"]]
        domains[key] = {**d, "items": items}
    return {
        "exam_id": record["exam_id"],
        "rubric_version": record["rubric_version"],
        "judge_model": record["judge_model"],
        "case_diagnosis": record["diagnosis"],
        "overall": record["overall"],
        "domains": domains,
        "review": record["review"],
        "disclaimer": DISCLAIMER,
    }


# ---------------- ENDPOINTS ----------------
@app.post("/evaluator/run/{exam_id}")
async def run_evaluation(exam_id: str):
    _check_id(exam_id)
    exam = load_json(
        EXAMINER_RESULTS_DIR / f"{exam_id}.json",
        "Examiner results not found - finish the oral exam first",
    )
    patient = load_json(
        SESSIONS_DIR / f"{_check_id(exam['patient_session_id'])}.json",
        "Patient session not found",
    )

    transcript = patient.get("transcript", [])
    notes = patient.get("notes") or {}
    diagnosis = patient.get("diagnosis") or exam.get("diagnosis") or "unknown"

    student_turns = {i for i, t in enumerate(transcript) if t.get("role") == "user"}
    transcript_text = clip_transcript(format_transcript(transcript))

    interview_items = RUBRIC["history_taking"]["items"] + RUBRIC["communication"]["items"]
    reasoning_items = RUBRIC["clinical_reasoning"]["items"]
    sections = {k: (notes.get(k) or "").strip() for k in ("history", "exam", "assessment")}
    nonblank = {k for k, v in sections.items() if v}
    viva_questions = exam.get("questions", [])
    answers = exam.get("answers", {})

    async def score_interview():
        if not student_turns:
            return deterministic_zero(interview_items, "No questions were asked of the patient."), None
        parsed, raw = await call_json(build_transcript_prompt(transcript_text, interview_items, sorted(student_turns)))
        return validate_transcript_items(parsed, interview_items, student_turns), raw

    async def score_notes():
        if not nonblank:
            return deterministic_zero(reasoning_items, "No notes were written."), None
        parsed, raw = await call_json(build_notes_prompt(sections, transcript_text, diagnosis, reasoning_items))
        return validate_notes_items(parsed, reasoning_items, nonblank), raw

    async def score_viva():
        recs, to_judge = [], []
        for i, q in enumerate(viva_questions):
            key_points = [str(k) for k in (q.get("expected_key_points") or [])]
            answer = (answers.get(str(i)) or "").strip()
            rec = _blank_record({"id": f"V{i + 1}", "text": q.get("question", "")})
            rec.update(student_answer=answer, expected_key_points=key_points, key_points_hit=[], key_point_evidence={})
            if not key_points:
                rec.update(flag="not_scored_no_key_points", feedback="No reference points were available for this question.")
            elif not answer:
                rec.update(score=0, flag="deterministic_zero", feedback="No answer was given.")
            else:
                to_judge.append(rec)
            recs.append(rec)
        raw = None
        if to_judge:
            parsed, raw = await call_json(build_viva_prompt(to_judge))
            apply_viva_scores(parsed, to_judge)
        return recs, raw

    (interview_res, interview_raw), (notes_res, notes_raw), (viva_res, viva_raw) = await asyncio.gather(
        score_interview(), score_notes(), score_viva()
    )

    domains = {
        "history_taking": summarize_domain(RUBRIC["history_taking"]["label"], [r for r in interview_res if r["id"].startswith("H")]),
        "communication": summarize_domain(RUBRIC["communication"]["label"], [r for r in interview_res if r["id"].startswith("C")]),
        "clinical_reasoning": summarize_domain(RUBRIC["clinical_reasoning"]["label"], notes_res),
        "viva": summarize_domain(VIVA_LABEL, viva_res),
    }
    total_points = sum(d["points"] for d in domains.values())
    total_max = sum(d["max_points"] for d in domains.values())
    overall = {
        "points": total_points,
        "max_points": total_max,
        "percent": round(100 * total_points / total_max) if total_max else None,
    }

    review_parsed, review_raw = await call_json(build_review_prompt(domains))
    if isinstance(review_parsed, dict) and review_parsed.get("summary"):
        review = {
            "summary": str(review_parsed.get("summary", ""))[:700],
            "strengths": [str(s)[:200] for s in (review_parsed.get("strengths") or [])][:3],
            "improvements": [str(s)[:200] for s in (review_parsed.get("improvements") or [])][:3],
            "source": "model",
        }
    else:
        review = fallback_review(domains)

    record = {
        "exam_id": exam_id,
        "patient_session_id": exam["patient_session_id"],
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "rubric_version": RUBRIC_VERSION,
        "judge_model": MODEL_NAME,
        "judge_temperature": JUDGE_TEMPERATURE,
        "rubric": RUBRIC,
        "diagnosis": diagnosis,
        "overall": overall,
        "domains": domains,
        "review": review,
        "raw_model_outputs": {
            "interview": interview_raw,
            "notes": notes_raw,
            "viva": viva_raw,
            "review": review_raw,
        },
    }
    with open(EVALUATOR_RESULTS_DIR / f"{exam_id}.json", "w") as f:
        json.dump(record, f, indent=2)

    return public_view(record)


@app.get("/evaluator/{exam_id}")
async def get_evaluation(exam_id: str):
    _check_id(exam_id)
    record = load_json(EVALUATOR_RESULTS_DIR / f"{exam_id}.json", "Evaluation not found")
    return public_view(record)