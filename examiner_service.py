"""
Knowledge/Examiner Agent — FastAPI service

Reads a COMPLETED patient-twin session (saved by patient_twin_service_v2.py's
/session/{id}/leave endpoint) and generates targeted oral-exam (viva) style
questions based on what the student covered or missed in their conversation.

CURRENT LIMITATION (be upfront about this, don't let it look like real RAG):
  This version has NO retrieval over a textbook/exam-question corpus yet.
  It generates questions purely from the LLM's own reasoning against the
  transcript + the hidden diagnosis. This is a placeholder for the planned
  RAG-grounded version - structured so a retrieval step can be inserted
  later (see the RETRIEVE_CONTEXT stub below) without restructuring the rest
  of the pipeline.

Run with:
    uvicorn examiner_service:app --host 0.0.0.0 --port 8100 --reload

Expects:
  - vLLM running at http://localhost:8734/v1/chat/completions
  - Completed session files in ./sessions/ (written by patient_twin_service_v2.py)
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ---------------- CONFIG ----------------
VLLM_URL = "http://localhost:8734/v1/chat/completions"
MODEL_NAME = "meta-llama/Llama-3.1-8B-Instruct"
SESSIONS_DIR = Path(__file__).parent / "sessions"
EXAMINER_RESULTS_DIR = Path(__file__).parent / "examiner_results"
EXAMINER_RESULTS_DIR.mkdir(exist_ok=True)
NUM_QUESTIONS = 4
# -----------------------------------------

app = FastAPI(title="Examiner Agent Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

EXAMS: dict[str, dict] = {}  # in-memory exam-session store, same pattern as the twin backend


def load_patient_session(session_id: str) -> dict:
    path = SESSIONS_DIR / f"{session_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Patient session not found or not yet completed")
    with open(path, "r") as f:
        return json.load(f)


def format_transcript(transcript: list[dict]) -> str:
    lines = []
    for turn in transcript:
        speaker = "Student" if turn["role"] == "user" else "Patient"
        lines.append(f"{speaker}: {turn['content']}")
    return "\n".join(lines)


def RETRIEVE_CONTEXT(diagnosis: str) -> str:
    """
    PLACEHOLDER for future RAG retrieval over a textbook/past-exam corpus.
    Currently returns nothing - the examiner prompt below works without it,
    but is structured so real retrieved chunks can be inserted here later
    (e.g. via embedding search over textbook chapters matching `diagnosis`).
    """
    return ""  # intentionally empty for now - see docstring above


def build_examiner_prompt(diagnosis: str, chief_complaint: str, transcript_text: str, notes: dict) -> str:
    retrieved_context = RETRIEVE_CONTEXT(diagnosis)
    context_block = f"\nREFERENCE MATERIAL:\n{retrieved_context}\n" if retrieved_context else ""

    notes_text = "\n".join(f"- {k}: {v}" for k, v in notes.items() if v.strip()) or "(student left notes blank)"

    prompt = f"""You are a clinical examiner conducting an oral exam (viva) with a medical/nursing student, immediately after they finished interviewing a simulated patient.

GROUND TRUTH (the student does NOT know this - this is for your use only):
Diagnosis: {diagnosis}
Presenting complaint: {chief_complaint}
{context_block}
FULL CONVERSATION TRANSCRIPT (what the student actually asked and learned):
{transcript_text}

STUDENT'S WRITTEN NOTES:
{notes_text}

YOUR TASK (do these in order):
STEP 1 - Gap analysis. Read ONLY the lines spoken by the Student in the transcript. List the clinical topics the student actually asked about ("covered_topics"). Then list important history, risk-factor, associated-symptom, or workup topics for this presentation that the student never asked about ("missed_topics"). Be strict: a topic counts as covered only if the student asked about it.

STEP 2 - Generate exactly {NUM_QUESTIONS} oral exam questions. Rules:
1. At least one question must be built directly from an item in your missed_topics list (type "gap"), e.g. "You didn't ask about X - why might that matter for this patient?"
2. At least one question must test clinical reasoning (type "reasoning"), e.g. what is on the differential and what would distinguish the options.
3. Do NOT ask the student to simply repeat or summarise what the patient said or what is already in their own notes - ask them to reason, prioritise, or justify.
4. Every question must reference something specific from this transcript or a specific gap in it. No generic textbook questions.
5. Do not name or hint at the diagnosis. The questions should test whether the STUDENT can reason toward it.
6. Keep each question to one or two sentences.
7. For each question, give 2-4 "expected_key_points". Rules for key points: (a) base them on standard clinical knowledge about this presentation and the hidden diagnosis, NEVER on what the student wrote in their notes or said in the transcript; (b) each one must be a SINGLE specific clinical fact or action (for example a named test, drug class, mechanism, risk or complication) - not a restatement of the question and not a vague generalisation; (c) no two key points may say the same thing; (d) every key point must be something the student has to say to answer THIS question - no related but unasked facts, and if the question has two parts, cover both parts; (e) keep them clinically conservative, nothing beyond standard textbook knowledge.

Respond ONLY in this exact JSON format, no other text:
{{
  "covered_topics": ["..."],
  "missed_topics": ["..."],
  "questions": [
    {{
      "question": "...",
      "type": "gap" or "reasoning" or "knowledge",
      "targets_gap": "brief note on what this question probes, for internal review",
      "expected_key_points": ["...", "..."]
    }}
  ]
}}
"""
    return prompt


async def call_vllm(prompt: str, temperature: float = 0.6) -> str:
    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.post(
            VLLM_URL,
            json={
                "model": MODEL_NAME,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


def parse_llm_json(raw: str) -> dict:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {"_PARSE_FAILED_raw_output": raw}


# ---------------- REQUEST/RESPONSE MODELS ----------------
class AnswerIn(BaseModel):
    question_index: int
    answer: str


# ---------------- ENDPOINTS ----------------
@app.post("/examiner/start/{patient_session_id}")
async def start_examiner(patient_session_id: str):
    """Generate viva questions for a completed patient-twin session."""
    patient_session = load_patient_session(patient_session_id)

    transcript_text = format_transcript(patient_session["transcript"])
    prompt = build_examiner_prompt(
        diagnosis=patient_session["diagnosis"],
        chief_complaint=patient_session.get("chief_complaint") or "(not recorded for this session)",
        transcript_text=transcript_text,
        notes=patient_session["notes"],
    )

    raw_response = await call_vllm(prompt)
    parsed = parse_llm_json(raw_response)

    questions = parsed.get("questions", [])
    if not questions:
        raise HTTPException(status_code=502, detail="Examiner failed to generate valid questions. Raw output logged server-side.")

    exam_id = str(uuid.uuid4())
    EXAMS[exam_id] = {
        "patient_session_id": patient_session_id,
        "diagnosis": patient_session["diagnosis"],  # kept server-side, not returned to student
        "questions": questions,  # each includes type, targets_gap, expected_key_points (LLM-drafted, NOT clinically verified)
        "covered_topics": parsed.get("covered_topics", []),
        "missed_topics": parsed.get("missed_topics", []),
        "answers": {},  # question_index -> answer text
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "active",
    }

    return {
        "exam_id": exam_id,
        "questions": [q["question"] for q in questions],  # student sees ONLY the question text, not the internal gap notes
    }


@app.post("/examiner/{exam_id}/answer")
async def submit_answer(exam_id: str, body: AnswerIn):
    exam = EXAMS.get(exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam session not found")
    if body.question_index < 0 or body.question_index >= len(exam["questions"]):
        raise HTTPException(status_code=400, detail="Invalid question index")

    exam["answers"][str(body.question_index)] = body.answer
    return {"saved": True}


@app.post("/examiner/{exam_id}/finish")
async def finish_examiner(exam_id: str):
    exam = EXAMS.get(exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam session not found")

    exam["status"] = "completed"
    exam["ended_at"] = datetime.now(timezone.utc).isoformat()

    out_path = EXAMINER_RESULTS_DIR / f"{exam_id}.json"
    with open(out_path, "w") as f:
        json.dump(exam, f, indent=2)

    return {"status": "saved", "answered": len(exam["answers"]), "total_questions": len(exam["questions"]), "saved_to": str(out_path)}


@app.get("/examiner/{exam_id}")
async def get_exam(exam_id: str):
    exam = EXAMS.get(exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam session not found")
    return exam