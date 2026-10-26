# Three-Agent OSCE Simulator

A training and assessment system for nursing and medical students, modelled on the OSCE (Objective Structured Clinical Examination). Three AI agents copy the three human roles in an OSCE station.

| Agent | Role | Service | Port |
|---|---|---|---|
| Patient | Talks with the student from a clinical case | `patient_twin_service_v2.py` | 8000 |
| Examiner | Reads the transcript and notes, then asks oral questions | `examiner_service.py` | 8100 |
| Evaluator | Scores a rubric using evidence that code verifies | `evaluator_service.py` | 8200 |
| Language model | Llama-3.1-8B-Instruct served by vLLM (OpenAI-compatible API) | vLLM | 8734 |
| Frontend | React + Vite web app | `patient-room-app/` | 5173 |

## Status

Research prototype. The pipeline runs end to end, but **nothing is validated yet**.

- The central research question, whether the Evaluator agrees with faculty as well as faculty agree with each other, has not been measured.
- The rubric is a draft and has not been reviewed by faculty.
- Demos use a scripted student, so scores show only that the pipeline reacts correctly to known inputs.
- Cases contain no physical-exam findings, so the system tests history-taking only.
- The examiner has no textbook corpus yet (retrieval is a stub).

## How it works

1. A random case is drawn from 170 patient profiles. Each has a persona: personality, language level, recall and dazed level.
2. The student takes a history and writes notes. The student speaks first.
3. On "Completed conversation", the session is saved and the Examiner generates oral questions from the gaps in the transcript and notes. Each question has expected key points.
4. The student answers the questions.
5. The Evaluator scores the rubric: information gathering, communication, written notes and the oral exam.

### Evidence-checked grading

The Evaluator does not simply trust the language model's score.

- **Interview items** must cite turn numbers. No valid turn gives no credit.
- **Notes items** must cite the notes section that supports them.
- **Oral exam items** must quote the student's answer for each key point. The code checks each quote and sets the 0, 1 or 2 score itself: none gives 0, at least two thirds of key points gives 2, otherwise 1.
- The model's own score is kept as `llm_score` so every override can be audited.

## Repository layout

```
patient_twin_service_v2.py   Patient agent (FastAPI)
examiner_service.py          Examiner agent (FastAPI)
evaluator_service.py         Evaluator agent (FastAPI)
patient-room-app/            React + Vite frontend (src/App.jsx)
```

Not in this repository (see `.gitignore`): `patient_profile.json`, `sessions/`, `examiner_results/`, `evaluator_results/`, `llm/`.

## Data and ethics

- Patient profiles come from **PatientSim**, which is derived from **MIMIC-IV**. MIMIC-IV is access-controlled (PhysioNet credentialing and a data use agreement). **This repository does not include the profiles.** Obtain them from the original sources under their own terms.
- Session transcripts and results can contain student data and are not committed.
- The system runs on a university server with an open-weight model, so no data is sent to outside AI services.
- Any study with students needs IRB approval first.

## Setup

Requires a GPU server, Python 3.11 and Node.js.

### 1. Environment

```bash
conda create -n patient_twin_env python=3.11 -y
conda activate patient_twin_env
pip install fastapi uvicorn httpx pydantic
# vLLM and its matching versions (tested combination):
pip install vllm==0.8.5 transformers==4.51.3
```

Check that the PyTorch build matches your GPU driver's CUDA version. A mismatch is the most common install failure.

### 2. Model

Llama-3.1-8B-Instruct is gated on Hugging Face. Request access, then log in:

```bash
huggingface-cli login
```

Never commit your token.

### 3. Start the services

Run each in its own tmux session so they survive disconnects.

```bash
# Language model
python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Llama-3.1-8B-Instruct --port 8734

# Agents (from the repository root)
uvicorn patient_twin_service_v2:app --host 0.0.0.0 --port 8000
uvicorn examiner_service:app --host 0.0.0.0 --port 8100
uvicorn evaluator_service:app --host 0.0.0.0 --port 8200

# Frontend
cd patient-room-app
npm install
npm run dev
```

Place `patient_profile.json` in the repository root before starting the patient service.

Check each service's configuration (model name, model URL, file paths) at the top of its Python file.

### 4. Use it from another computer

Open an SSH tunnel to the server so nothing is exposed to the network:

```bash
ssh -L 5173:localhost:5173 -L 8000:localhost:8000 \
    -L 8100:localhost:8100 -L 8200:localhost:8200 <user>@<server>
```

Then open `http://localhost:5173`.

## Known issues

- Patient sessions are held in memory, so restarting the patient service loses open sessions.
- CORS is open to all origins.
- Some `GET` endpoints for a session expose the diagnosis. Do not expose these services to students directly without locking them down.
- Judge consistency across repeated runs has not been measured.

## Planned work

- Faculty-reviewed, nursing-specific rubric.
- Textbook corpus for retrieval in the Examiner.
- Physical-exam findings in cases.
- Blind faculty scoring, with agreement measured by kappa or ICC.
- Crossover comparison with an actor-based station.
- Qualitative interviews and focus groups with students.
- A larger judge model and a per-key-point check that each quote supports its point.

## Research questions

1. Does the Evaluator agree with faculty as well as faculty agree with each other?
2. Does it score students higher or lower than faculty do?
3. Are transcript-aware examiner questions rated more relevant than a fixed question bank?
4. How do students perform here compared with an actor-based station?
