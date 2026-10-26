"""
Patient Digital Twin — FastAPI backend, built natively for PatientSim's
patient_profile.json format (170 clinician-validated MIMIC-derived profiles).

No schema transformation - reads PatientSim's fields directly.

Run with:
    uvicorn patient_twin_service_v2:app --host 0.0.0.0 --port 8000 --reload

Expects vLLM running at http://localhost:8734/v1/chat/completions
Expects patient_profile.json in the same directory.
"""

import json
import random
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
PROFILES_PATH = Path(__file__).parent / "patient_profile.json"
SESSIONS_DIR = Path(__file__).parent / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)
# -----------------------------------------

app = FastAPI(title="Patient Digital Twin Service v2 (PatientSim-native)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SESSIONS: dict[str, dict] = {}


def load_all_profiles() -> list[dict]:
    with open(PROFILES_PATH, "r") as f:
        return json.load(f)


def get_profile_by_hadm_id(hadm_id: str) -> dict:
    profiles = load_all_profiles()
    for p in profiles:
        if p["hadm_id"] == hadm_id:
            return p
    raise ValueError(f"No profile found with hadm_id={hadm_id}")


def get_random_profile(diagnosis_filter: str | None = None) -> dict:
    profiles = load_all_profiles()
    if diagnosis_filter:
        profiles = [p for p in profiles if diagnosis_filter.lower() in p["diagnosis"].lower()]
        if not profiles:
            raise ValueError(f"No profiles found with diagnosis containing '{diagnosis_filter}'")
    return random.choice(profiles)


# ---------------- PERSONA AXIS TRANSLATION ----------------
# PatientSim encodes behavior as short codes (personality, cefr, recall_level,
# dazed_level). This translates those codes into actual prompt instructions.

PERSONALITY_INSTRUCTIONS = {
    "distrust": "You are somewhat distrustful and guarded with the interviewer. You may hesitate before answering personal questions and sometimes ask why something needs to be known before answering.",
    "anxious": "You are anxious and worried about your condition. You may over-explain symptoms, seek reassurance, and ask the interviewer if what you're describing sounds serious.",
    "stoic": "You downplay your symptoms and tend to minimize how bad things are. You may need to be asked follow-up questions to reveal the full picture.",
    "cooperative": "You are open, cooperative, and straightforward in answering questions.",
    "irritable": "You are somewhat impatient or irritable, especially if questions feel repetitive or if you've been waiting. You may give short or slightly curt answers.",
}

CEFR_INSTRUCTIONS = {
    "A": "Use only very simple, basic everyday vocabulary. Avoid any advanced or uncommon words. Keep sentences short.",
    "B": "Use everyday conversational vocabulary. Avoid clinical, medical, or highly technical/academic words. You may use moderately varied vocabulary but nothing obscure or overly formal.",
    "C": "You can use fairly sophisticated vocabulary for a layperson, but you are still NOT a medical professional - never use actual clinical/medical terminology to describe your condition.",
}

RECALL_INSTRUCTIONS = {
    "low": "Your recall of medical history details is poor. You often say things like 'I don't really remember' or 'I'd have to check' when asked about past diagnoses, dates, or specific medical details. You may get some minor details slightly wrong or contradictory if pressed too hard on specifics.",
    "normal": "Your recall of your medical history is reasonably accurate and consistent.",
    "high": "You recall your medical history clearly and in detail, and can answer specific questions about past diagnoses, dates, and treatments accurately.",
}

DAZED_INSTRUCTIONS = {
    "normal": "You are fully alert, oriented, and able to engage normally in conversation.",
    "mild": "You are mildly foggy or slow to respond at times - you may need a question repeated occasionally, or pause before answering - but you are still coherent and able to hold a conversation.",
}


def build_behavioral_instructions(profile: dict) -> str:
    personality = PERSONALITY_INSTRUCTIONS.get(
        profile.get("personality", ""), "Respond naturally and realistically."
    )
    cefr_level = profile.get("cefr", "B")
    cefr = CEFR_INSTRUCTIONS.get(cefr_level, CEFR_INSTRUCTIONS["B"])
    recall = RECALL_INSTRUCTIONS.get(profile.get("recall_level", "normal"), RECALL_INSTRUCTIONS["normal"])
    dazed = DAZED_INSTRUCTIONS.get(profile.get("dazed_level", "normal"), DAZED_INSTRUCTIONS["normal"])

    return f"""PERSONALITY: {personality}
LANGUAGE LEVEL: {cefr}
MEMORY/RECALL: {recall}
ALERTNESS: {dazed}"""


def build_system_prompt(profile: dict) -> str:
    behavioral = build_behavioral_instructions(profile)

    prompt = f"""# ROLE
You are simulating a real patient being interviewed by a medical/nursing student for clinical training purposes. You are NOT an assistant — stay fully in character as the patient at all times.

# CASE FILE (ground truth — never reveal the diagnosis directly)
Age: {profile['age']}, Gender: {profile['gender']}, Race: {profile.get('race', 'not specified')}
Marital status: {profile.get('marital_status', 'not specified')}
Occupation: {profile.get('occupation', 'not specified')}
Living situation: {profile.get('living_situation', 'not specified')}
Children: {profile.get('children', 'not specified')}

Chief complaint: {profile['chiefcomplaint']}
Pain level (0-10): {profile.get('pain', 'not specified')}

History of present illness — POSITIVE findings (things you ARE experiencing, reveal only when asked relevant questions): {profile.get('present_illness_positive', 'none documented')}
History of present illness — NEGATIVE findings (things you are NOT experiencing, state these if specifically asked): {profile.get('present_illness_negative', 'none documented')}

Past medical history: {profile.get('medical_history', 'none documented')}
Current medications: {profile.get('medication', 'none documented')}
Allergies: {profile.get('allergies', 'none documented')}
Family medical history: {profile.get('family_medical_history', 'none documented')}

Social history:
- Exercise: {profile.get('exercise', 'not documented')}
- Tobacco: {profile.get('tobacco', 'not documented')}
- Alcohol: {profile.get('alcohol', 'not documented')}
- Illicit drug use: {profile.get('illicit_drug', 'not documented')}
- Sexual history: {profile.get('sexual_history', 'not documented')}

Diagnosis (HIDDEN — never state this or clinical terms related to it): {profile['diagnosis']}

# BEHAVIORAL PROFILE
{behavioral}

# RULES YOU MUST FOLLOW
1. Speak ONLY in first-person, plain everyday language matching your LANGUAGE LEVEL above — never use clinical/medical terminology.
2. NEVER volunteer the diagnosis or clinical terms unless the student specifically and appropriately asks.
3. Reveal information progressively. Answer only what was asked, in 1-3 short sentences. To a broad opening question (for example "how are you feeling?"), mention only your main complaint and at most ONE other detail, then stop and wait to be asked. Do not volunteer onset, associated symptoms, or medications unless asked. Do not repeat details you already gave unless asked again.
4. Stay consistent with your PERSONALITY, LANGUAGE LEVEL, MEMORY/RECALL, and ALERTNESS traits above throughout the ENTIRE conversation.
5. If asked something not in your case file, respond the way a real patient with your recall level would — do not break character to say information is missing.
6. If the student asks something clearly outside a patient's knowledge (e.g. lab values, clinical mechanisms), respond with realistic patient confusion, not a clinical answer.
7. Never contradict earlier answers in this conversation (unless your LOW recall level plausibly explains a minor inconsistency) — treat the case file as your memory, re-check it before every reply.
8. Physical exam findings are NOT documented for this case — if the student attempts to examine you, respond naturally to the physical action itself (e.g. wincing, describing a sensation) but do not state specific clinical exam findings (e.g. do not say "you'll hear crackles") since none are scripted; keep any such response vague and in plain patient language.
9. If the student is rude, unclear, or asks leading questions, react the way a real patient with your personality would.
10. Describe where it hurts in everyday words (my side, my back, my belly, my chest). Do not name internal organs or medical conditions unless your own case notes give that exact wording (for example a past diagnosis listed in your history).

# OUTPUT
Respond only as the patient would speak — no meta-commentary, no labels, no stage directions unless naturally part of speech.
"""
    return prompt


# ---------------- REQUEST/RESPONSE MODELS ----------------
class StartSessionIn(BaseModel):
    pass  # no fields - every session is a fully random draw from all 170 profiles,
          # by design, so the case can't be pre-selected or known in advance


class MessageIn(BaseModel):
    content: str


class NotesIn(BaseModel):
    history: str = ""
    exam: str = ""
    assessment: str = ""


class LeaveIn(BaseModel):
    notes: NotesIn


# ---------------- ENDPOINTS ----------------
@app.get("/profiles/diagnoses")
async def list_available_diagnoses():
    """Utility endpoint: see what diagnoses/counts are available."""
    profiles = load_all_profiles()
    counts: dict[str, int] = {}
    for p in profiles:
        counts[p["diagnosis"]] = counts.get(p["diagnosis"], 0) + 1
    return counts


@app.post("/session/start")
async def start_session(body: StartSessionIn = StartSessionIn()):
    """Creates a new session from a RANDOMLY selected PatientSim profile.
    The case is never chosen or known in advance - every call draws fresh
    from all 170 profiles, so the student encounters an unpredictable case,
    same as walking into a real, unknown patient's room."""
    profile = get_random_profile()

    session_id = str(uuid.uuid4())
    system_prompt = build_system_prompt(profile)

    SESSIONS[session_id] = {
        "hadm_id": profile["hadm_id"],
        "chief_complaint": profile["chiefcomplaint"],  # saved so the Examiner/Evaluator don't have to guess it from the transcript
        "diagnosis": profile["diagnosis"],  # kept server-side only, never sent to frontend
        "system_prompt": system_prompt,
        "messages": [],  # empty - patient says nothing until the student speaks first
        "notes": {"history": "", "exam": "", "assessment": ""},
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "active",
    }

    # No opening line generated here - the patient waits silently until the
    # student initiates, same as walking into a real exam room and the
    # patient waiting for the clinician to start the conversation.
    return {
        "session_id": session_id,
        "patient": {
            "age": profile["age"],
            "gender": profile["gender"],
            "presenting_complaint": profile["chiefcomplaint"],
            "hadm_id": profile["hadm_id"],
            # diagnosis deliberately NOT returned to the frontend
        },
    }


@app.post("/session/{session_id}/message")
async def send_message(session_id: str, body: MessageIn):
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["status"] != "active":
        raise HTTPException(status_code=400, detail="Session already ended")

    session["messages"].append({"role": "user", "content": body.content})
    reply = await call_vllm(session["system_prompt"], session["messages"])
    session["messages"].append({"role": "assistant", "content": reply})

    return {"reply": reply}


@app.patch("/session/{session_id}/notes")
async def update_notes(session_id: str, body: NotesIn):
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session["notes"] = body.model_dump()
    return {"saved": True}


@app.post("/session/{session_id}/leave")
async def leave_room(session_id: str, body: LeaveIn):
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session["notes"] = body.notes.model_dump()
    session["status"] = "completed"
    session["ended_at"] = datetime.now(timezone.utc).isoformat()

    record = {
        "session_id": session_id,
        "hadm_id": session["hadm_id"],
        "chief_complaint": session.get("chief_complaint", ""),
        "diagnosis": session["diagnosis"],  # saved for grading/research use, not shown to student live
        "started_at": session["started_at"],
        "ended_at": session["ended_at"],
        "transcript": session["messages"],
        "notes": session["notes"],
    }
    out_path = SESSIONS_DIR / f"{session_id}.json"
    with open(out_path, "w") as f:
        json.dump(record, f, indent=2)

    return {
        "status": "saved",
        "message_count": len(session["messages"]),
        "saved_to": str(out_path),
    }


@app.get("/session/{session_id}")
async def get_session(session_id: str):
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


# ---------------- VLLM CALL HELPER ----------------
async def call_vllm(system_prompt: str, conversation: list[dict]) -> str:
    messages = [{"role": "system", "content": system_prompt}] + conversation

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(
                VLLM_URL,
                json={
                    "model": MODEL_NAME,
                    "messages": messages,
                    "temperature": 0.7,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Model service error: {e}")