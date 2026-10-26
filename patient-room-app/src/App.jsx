import React, { useState, useRef, useEffect } from 'react';

// ---------------- CONFIG ----------------
// One backend per agent. If you view this page through an SSH tunnel or VS Code
// port forwarding, all three ports need to be forwarded.
const PATIENT_API = 'http://localhost:8000';   // patient_twin_service_v2.py
const EXAMINER_API = 'http://localhost:8100';  // examiner_service.py
const EVALUATOR_API = 'http://localhost:8200'; // evaluator_service.py
// -----------------------------------------

const C = {
  bg: '#F4F5F2',
  panel: '#FFFFFF',
  ink: '#1C2622',
  inkSoft: '#6B7A72',
  inkFaint: '#9AA79F',
  accent: '#2F5A4B',
  accentSoft: '#E4EEE8',
  line: '#E4E7E2',
  notesAccent: '#B07A3E',
  notesAccentSoft: '#FBF3E8',
  studentBubble: '#2F5A4B',
  patientBubble: '#EFF3F0',
  errorBg: '#FDEEEC',
  errorText: '#B4483A',
  shadow: '0 1px 2px rgba(28,38,34,0.04), 0 4px 16px rgba(28,38,34,0.06)',
};

const FONT_DISPLAY = "'Source Serif 4', Georgia, serif";
const FONT_BODY = "'Inter', -apple-system, BlinkMacSystemFont, sans-serif";
const FONT_MONO = "'IBM Plex Mono', ui-monospace, monospace";

const pctColor = (p) => (p == null ? C.inkFaint : p >= 70 ? C.accent : p >= 40 ? C.notesAccent : C.errorText);
const scoreColor = (s) => (s === 2 ? C.accent : s === 1 ? C.notesAccent : s === 0 ? C.errorText : C.inkFaint);

const FontImports = () => (
  <style>{`
    @import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,400;8..60,500;8..60,600&family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: ${FONT_BODY}; background: ${C.bg}; }
    ::-webkit-scrollbar { width: 8px; height: 8px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: ${C.line}; border-radius: 8px; }
    textarea:focus, input:focus, button:focus-visible, summary:focus-visible {
      outline: 2px solid ${C.accent}; outline-offset: 1px;
    }
    @keyframes pulse-dot { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }
    @keyframes spin { to { transform: rotate(360deg); } }
    @keyframes fadeUp { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
    @keyframes dotBounce { 0%,80%,100% { transform: translateY(0); opacity: 0.4; } 40% { transform: translateY(-4px); opacity: 1; } }
    @media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; } }
  `}</style>
);

function Spinner({ size = 24, color = C.accent }) {
  return (
    <div
      style={{
        width: size, height: size, borderRadius: '50%',
        border: `2.5px solid ${color}22`, borderTopColor: color,
        animation: 'spin 0.8s linear infinite',
      }}
    />
  );
}

function TypingDots() {
  return (
    <div style={{ display: 'flex', gap: 4, padding: '2px 4px' }}>
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          style={{
            width: 6, height: 6, borderRadius: '50%', background: C.inkFaint,
            animation: `dotBounce 1.2s ${i * 0.15}s ease-in-out infinite`,
          }}
        />
      ))}
    </div>
  );
}

function ScorePill({ score, max = 2 }) {
  const color = scoreColor(score);
  return (
    <span
      style={{
        fontFamily: FONT_MONO, fontSize: 12, fontWeight: 500, color,
        background: `${color}14`, border: `1px solid ${color}33`, borderRadius: 999,
        padding: '3px 9px', whiteSpace: 'nowrap', flexShrink: 0,
      }}
    >
      {score == null ? 'n/a' : `${score}/${max}`}
    </span>
  );
}

function Bar({ percent }) {
  return (
    <div style={{ height: 6, borderRadius: 6, background: C.line, overflow: 'hidden' }}>
      <div
        style={{
          height: '100%', width: `${percent ?? 0}%`, background: pctColor(percent),
          borderRadius: 6, transition: 'width 0.5s ease',
        }}
      />
    </div>
  );
}

function DomainCard({ domain, isViva }) {
  return (
    <div style={{ background: C.panel, border: `1px solid ${C.line}`, borderRadius: 16, padding: 22, boxShadow: C.shadow }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
        <h3 style={{ fontFamily: FONT_DISPLAY, fontSize: 17, fontWeight: 500, color: C.ink }}>{domain.label}</h3>
        <span style={{ fontFamily: FONT_MONO, fontSize: 13, color: pctColor(domain.percent) }}>
          {domain.percent == null ? 'not scored' : `${domain.percent}%`}
        </span>
      </div>
      <Bar percent={domain.percent} />
      <div style={{ marginTop: 18, display: 'flex', flexDirection: 'column', gap: 16 }}>
        {domain.items.length === 0 && (
          <p style={{ fontSize: 13, color: C.inkFaint }}>Nothing to score in this section.</p>
        )}
        {domain.items.map((item) => (
          <div key={item.id}>
            <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start', justifyContent: 'space-between' }}>
              <p style={{ fontSize: 13.5, color: C.ink, lineHeight: 1.5 }}>{item.text}</p>
              <ScorePill score={item.score} />
            </div>
            {item.feedback && (
              <p style={{ fontSize: 12.5, color: C.inkSoft, marginTop: 4, lineHeight: 1.5 }}>{item.feedback}</p>
            )}
            {item.flag && String(item.flag).startsWith('reset') && (
              <p style={{ fontSize: 12, color: C.notesAccent, marginTop: 4 }}>
                No supporting evidence was found, so no credit was given.
              </p>
            )}
            {item.flag && String(item.flag).startsWith('not_scored') && (
              <p style={{ fontSize: 12, color: C.inkFaint, marginTop: 4 }}>
                This item could not be scored automatically and is excluded from the total.
              </p>
            )}
            {isViva && (
              <details style={{ marginTop: 8 }}>
                <summary style={{ cursor: 'pointer', fontSize: 12.5, color: C.accent }}>
                  Your answer and the expected points
                </summary>
                <div style={{ marginTop: 8, padding: 12, background: C.bg, borderRadius: 10, fontSize: 12.5, color: C.inkSoft, lineHeight: 1.6 }}>
                  <p>
                    <strong style={{ color: C.ink }}>Your answer: </strong>
                    {item.student_answer || '(no answer)'}
                  </p>
                  {item.expected_key_points && item.expected_key_points.length > 0 && (
                    <ul style={{ marginTop: 8, paddingLeft: 18 }}>
                      {item.expected_key_points.map((kp, n) => {
                        const hit = (item.key_points_hit || []).includes(n + 1);
                        return (
                          <li key={n} style={{ color: hit ? C.accent : C.inkSoft }}>
                            {hit ? '✓ ' : '○ '}
                            {kp}
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </div>
              </details>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function App() {
  const [sessionId, setSessionId] = useState(null);
  const [patientInfo, setPatientInfo] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [isLoadingRoom, setIsLoadingRoom] = useState(true);
  const [error, setError] = useState(null);
  const [notesOpen, setNotesOpen] = useState({ history: true, exam: false, assessment: false });
  const [notes, setNotes] = useState({ history: '', exam: '', assessment: '' });
  const [confirmingComplete, setConfirmingComplete] = useState(false);
  const [isWide, setIsWide] = useState(window.innerWidth > 860);

  // phase: room -> viva_loading -> viva -> evaluating -> results (plus *_error states)
  const [phase, setPhase] = useState('room');
  const [examId, setExamId] = useState(null);
  const [vivaQuestions, setVivaQuestions] = useState([]);
  const [vivaIndex, setVivaIndex] = useState(0);
  const [vivaDone, setVivaDone] = useState(false);
  const [answering, setAnswering] = useState(false);
  const [evaluation, setEvaluation] = useState(null);
  const scrollRef = useRef(null);

  useEffect(() => {
    startSession();
    const onResize = () => setIsWide(window.innerWidth > 860);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, isTyping, vivaDone]);

  // ---------------- PATIENT CONVERSATION ----------------
  async function startSession() {
    setIsLoadingRoom(true);
    setError(null);
    try {
      const res = await fetch(`${PATIENT_API}/session/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      if (!res.ok) throw new Error(`Failed to start session (${res.status})`);
      const data = await res.json();
      setSessionId(data.session_id);
      setPatientInfo(data.patient);
      setMessages([]); // the patient waits for the student to speak first
    } catch (e) {
      setError(`Couldn't connect to the patient service at ${PATIENT_API}. Make sure the backend is running.`);
    } finally {
      setIsLoadingRoom(false);
    }
  }

  async function sendMessage() {
    if (!input.trim() || !sessionId || isTyping) return;
    const text = input.trim();
    setMessages((m) => [...m, { role: 'student', text }]);
    setInput('');
    setIsTyping(true);
    setError(null);
    try {
      const res = await fetch(`${PATIENT_API}/session/${sessionId}/message`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: text }),
      });
      if (!res.ok) throw new Error(`Message failed (${res.status})`);
      const data = await res.json();
      setMessages((m) => [...m, { role: 'patient', text: data.reply }]);
    } catch (e) {
      setError("The patient didn't respond — the model service may be unreachable.");
    } finally {
      setIsTyping(false);
    }
  }

  // ---------------- COMPLETE CONVERSATION -> ORAL EXAM ----------------
  async function handleCompleteConfirmed() {
    setConfirmingComplete(false);
    if (!sessionId) return;
    setError(null);
    setPhase('viva_loading');
    try {
      const res = await fetch(`${PATIENT_API}/session/${sessionId}/leave`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ notes }),
      });
      if (!res.ok) throw new Error(`Failed to save (${res.status})`);
    } catch (e) {
      setPhase('room');
      setError("Couldn't save your conversation — check the backend connection and try again.");
      return;
    }
    await loadViva();
  }

  async function loadViva() {
    setPhase('viva_loading');
    setError(null);
    try {
      const res = await fetch(`${EXAMINER_API}/examiner/start/${sessionId}`, { method: 'POST' });
      if (!res.ok) throw new Error(`Examiner failed (${res.status})`);
      const data = await res.json();
      if (!data.questions || data.questions.length === 0) throw new Error('No questions returned');
      setExamId(data.exam_id);
      setVivaQuestions(data.questions);
      setVivaIndex(0);
      setVivaDone(false);
      setMessages((m) => [
        ...m,
        { role: 'divider', text: 'Oral examination' },
        { role: 'examiner', text: data.questions[0] },
      ]);
      setPhase('viva');
    } catch (e) {
      setPhase('viva_error');
    }
  }

  // ---------------- ORAL EXAM ----------------
  async function submitAnswer() {
    if (!input.trim() || !examId || answering || isTyping) return;
    const text = input.trim();
    const idx = vivaIndex;
    setMessages((m) => [...m, { role: 'student', text }]);
    setInput('');
    setAnswering(true);
    setError(null);
    try {
      const res = await fetch(`${EXAMINER_API}/examiner/${examId}/answer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question_index: idx, answer: text }),
      });
      if (!res.ok) throw new Error(`Answer failed (${res.status})`);
    } catch (e) {
      setMessages((m) => m.slice(0, -1)); // undo the optimistic message
      setInput(text);
      setAnswering(false);
      setError("Couldn't save that answer — please send it again.");
      return;
    }
    const next = idx + 1;
    if (next < vivaQuestions.length) {
      setIsTyping(true);
      setTimeout(() => {
        setMessages((m) => [...m, { role: 'examiner', text: vivaQuestions[next] }]);
        setVivaIndex(next);
        setIsTyping(false);
        setAnswering(false);
      }, 500);
    } else {
      setVivaDone(true);
      setAnswering(false);
    }
  }

  // ---------------- EVALUATION ----------------
  async function runEvaluation() {
    setPhase('evaluating');
    setError(null);
    try {
      const fin = await fetch(`${EXAMINER_API}/examiner/${examId}/finish`, { method: 'POST' });
      if (!fin.ok) throw new Error('finish failed');
      const res = await fetch(`${EVALUATOR_API}/evaluator/run/${examId}`, { method: 'POST' });
      if (!res.ok) throw new Error('evaluation failed');
      setEvaluation(await res.json());
      setPhase('results');
    } catch (e) {
      setPhase('eval_error');
    }
  }

  const inViva = phase === 'viva';
  const onSend = () => (inViva ? submitAnswer() : sendMessage());
  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  };
  const toggleSection = (key) => setNotesOpen((s) => ({ ...s, [key]: !s[key] }));

  const screenStyle = {
    background: C.bg, fontFamily: FONT_BODY, width: '100%', minHeight: '100vh',
    display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
  };

  const busyScreen = (text, sub) => (
    <div style={screenStyle}>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 14, textAlign: 'center' }}>
        <Spinner size={30} />
        <p style={{ color: C.ink, fontSize: 14.5, fontWeight: 500 }}>{text}</p>
        {sub && <p style={{ color: C.inkSoft, fontSize: 13, maxWidth: 320, lineHeight: 1.6 }}>{sub}</p>}
      </div>
    </div>
  );

  const errorScreen = (message, onRetry) => (
    <div style={screenStyle}>
      <div
        style={{
          background: C.errorBg, border: `1px solid ${C.errorText}33`, borderRadius: 14,
          padding: 28, maxWidth: 440, textAlign: 'center', boxShadow: C.shadow,
        }}
      >
        <p style={{ color: C.errorText, fontSize: 14, lineHeight: 1.6, marginBottom: 18 }}>{message}</p>
        <button
          onClick={onRetry}
          style={{
            background: C.accent, color: '#fff', border: 'none', borderRadius: 10,
            padding: '10px 20px', fontSize: 14, fontWeight: 500, cursor: 'pointer', fontFamily: FONT_BODY,
          }}
        >
          Try again
        </button>
      </div>
    </div>
  );

  // ---------------- RESULTS SCREEN ----------------
  const resultsScreen = () => {
    const ev = evaluation;
    const entries = Object.entries(ev.domains);
    return (
      <div style={{ background: C.bg, fontFamily: FONT_BODY, minHeight: '100vh', padding: '36px 20px 60px' }}>
        <div style={{ maxWidth: 860, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 18, animation: 'fadeUp 0.35s ease-out' }}>
          <div>
            <h1 style={{ fontFamily: FONT_DISPLAY, fontSize: 28, fontWeight: 500, color: C.ink }}>Your OSCE evaluation</h1>
            <p style={{ color: C.inkSoft, fontSize: 14, marginTop: 6 }}>
              The patient's diagnosis in this case was{' '}
              <strong style={{ color: C.ink }}>{ev.case_diagnosis}</strong>.
            </p>
          </div>

          {/* Overall */}
          <div
            style={{
              background: C.panel, border: `1px solid ${C.line}`, borderRadius: 18, padding: 28,
              display: 'flex', flexWrap: 'wrap', gap: 32, boxShadow: C.shadow,
            }}
          >
            <div style={{ minWidth: 170 }}>
              <p style={{ fontSize: 11.5, letterSpacing: '0.08em', textTransform: 'uppercase', color: C.inkFaint, fontWeight: 600 }}>Overall</p>
              <div style={{ fontFamily: FONT_DISPLAY, fontSize: 58, lineHeight: 1.05, color: pctColor(ev.overall.percent), marginTop: 6 }}>
                {ev.overall.percent == null ? '–' : ev.overall.percent}
                {ev.overall.percent != null && <span style={{ fontSize: 24 }}>%</span>}
              </div>
              <p style={{ fontFamily: FONT_MONO, fontSize: 12.5, color: C.inkSoft, marginTop: 6 }}>
                {ev.overall.points} / {ev.overall.max_points} points
              </p>
              {entries.filter(([, d]) => d.percent == null && d.items.length > 0).length > 0 && (
                <p style={{ fontSize: 12, color: C.notesAccent, marginTop: 8, lineHeight: 1.5, maxWidth: 200 }}>
                  Not included in this total:{' '}
                  {entries.filter(([, d]) => d.percent == null && d.items.length > 0).map(([, d]) => d.label).join(', ')}{' '}
                  (could not be scored).
                </p>
              )}
            </div>
            <div style={{ flex: 1, minWidth: 240, display: 'flex', flexDirection: 'column', gap: 14, justifyContent: 'center' }}>
              {entries.map(([key, d]) => (
                <div key={key}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, color: C.inkSoft, marginBottom: 6 }}>
                    <span>{d.label}</span>
                    <span style={{ fontFamily: FONT_MONO }}>{d.percent == null ? '–' : `${d.percent}%`}</span>
                  </div>
                  <Bar percent={d.percent} />
                </div>
              ))}
            </div>
          </div>

          {/* Written review */}
          <div style={{ background: C.panel, border: `1px solid ${C.line}`, borderRadius: 16, padding: 24, boxShadow: C.shadow }}>
            <h3 style={{ fontFamily: FONT_DISPLAY, fontSize: 17, fontWeight: 500, color: C.ink, marginBottom: 10 }}>Examiner's review</h3>
            <p style={{ fontSize: 14, color: C.ink, lineHeight: 1.65 }}>{ev.review.summary}</p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24, marginTop: 18 }}>
              {ev.review.strengths && ev.review.strengths.length > 0 && (
                <div style={{ flex: 1, minWidth: 240 }}>
                  <p style={{ fontSize: 11.5, letterSpacing: '0.08em', textTransform: 'uppercase', color: C.accent, fontWeight: 600, marginBottom: 8 }}>Strengths</p>
                  <ul style={{ paddingLeft: 18, fontSize: 13.5, color: C.ink, lineHeight: 1.65 }}>
                    {ev.review.strengths.map((s, i) => <li key={i}>{s}</li>)}
                  </ul>
                </div>
              )}
              {ev.review.improvements && ev.review.improvements.length > 0 && (
                <div style={{ flex: 1, minWidth: 240 }}>
                  <p style={{ fontSize: 11.5, letterSpacing: '0.08em', textTransform: 'uppercase', color: C.notesAccent, fontWeight: 600, marginBottom: 8 }}>To work on</p>
                  <ul style={{ paddingLeft: 18, fontSize: 13.5, color: C.ink, lineHeight: 1.65 }}>
                    {ev.review.improvements.map((s, i) => <li key={i}>{s}</li>)}
                  </ul>
                </div>
              )}
            </div>
          </div>

          {entries.map(([key, d]) => (
            <DomainCard key={key} domain={d} isViva={key === 'viva'} />
          ))}

          <p style={{ fontSize: 12, color: C.inkFaint, lineHeight: 1.6, textAlign: 'center', maxWidth: 560, margin: '6px auto 0' }}>
            {ev.disclaimer} Rubric version: {ev.rubric_version}.
          </p>
          <div style={{ textAlign: 'center' }}>
            <button
              onClick={() => window.location.reload()}
              style={{
                background: C.accent, color: '#fff', border: 'none', borderRadius: 10,
                padding: '11px 22px', fontSize: 14, fontWeight: 500, cursor: 'pointer', fontFamily: FONT_BODY,
              }}
            >
              Start a new case
            </button>
          </div>
        </div>
      </div>
    );
  };

  // ---------------- ROOM / VIVA SCREEN (shared layout) ----------------
  const roomScreen = () => {
    const genderSymbol = patientInfo?.gender === 'M' ? '♂' : patientInfo?.gender === 'F' ? '♀' : '?';
    const progress = vivaDone
      ? 'All questions answered'
      : `Question ${Math.min(vivaIndex + 1, vivaQuestions.length)} of ${vivaQuestions.length}`;

    return (
      <div style={{ background: C.bg, fontFamily: FONT_BODY, width: '100%', minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
        {/* HEADER */}
        <div
          style={{
            background: C.panel, borderBottom: `1px solid ${C.line}`, padding: '18px 28px',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 14,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <div
              style={{
                width: 46, height: 46, borderRadius: '50%', background: C.accentSoft, color: C.accent,
                display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 20, flexShrink: 0,
              }}
            >
              {genderSymbol}
            </div>
            <div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                <h1 style={{ fontFamily: FONT_DISPLAY, color: C.ink, fontSize: 19, fontWeight: 500 }}>New Patient</h1>
                <span style={{ color: C.inkFaint, fontFamily: FONT_MONO, fontSize: 12 }}>
                  {patientInfo?.age} · {patientInfo?.gender}
                </span>
              </div>
              <p style={{ color: C.inkSoft, fontSize: 12.5, marginTop: 2 }}>
                Presenting complaint: <span style={{ color: C.ink, fontWeight: 500 }}>{patientInfo?.presenting_complaint}</span>
              </p>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
            {inViva ? (
              <>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <div style={{ width: 7, height: 7, borderRadius: '50%', background: C.notesAccent }} />
                  <span style={{ color: C.inkSoft, fontSize: 12.5 }}>Oral exam · {progress}</span>
                </div>
              </>
            ) : (
              <>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <div style={{ width: 7, height: 7, borderRadius: '50%', background: C.accent, animation: 'pulse-dot 2s ease-in-out infinite' }} />
                  <span style={{ color: C.inkSoft, fontSize: 12.5 }}>In room</span>
                </div>
                <button
                  onClick={() => setConfirmingComplete(true)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 7, background: 'transparent',
                    border: `1px solid ${C.accent}`, color: C.accent, borderRadius: 9,
                    padding: '9px 15px', fontSize: 13.5, fontWeight: 500, cursor: 'pointer',
                    fontFamily: FONT_BODY, transition: 'background 0.15s',
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = C.accentSoft)}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                >
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" strokeLinecap="round" />
                    <path d="M22 4L12 14.01l-3-3" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  Completed conversation
                </button>
              </>
            )}
          </div>
        </div>

        {error && sessionId && (
          <div style={{ background: C.errorBg, color: C.errorText, padding: '9px 28px', fontSize: 12.5, textAlign: 'center' }}>
            {error}
          </div>
        )}

        {/* BODY */}
        <div style={{ flex: 1, display: 'flex', flexDirection: isWide ? 'row' : 'column', minHeight: 0, height: isWide ? 'calc(100vh - 82px)' : 'auto' }}>
          {/* CHAT PANEL */}
          <div
            style={{
              flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column',
              borderRight: isWide ? `1px solid ${C.line}` : 'none',
              borderBottom: isWide ? 'none' : `1px solid ${C.line}`,
              height: isWide ? '100%' : '60vh',
            }}
          >
            <div ref={scrollRef} style={{ flex: 1, overflowY: 'auto', padding: '22px 26px', display: 'flex', flexDirection: 'column', gap: 14 }}>
              {messages.length === 0 && !isTyping && (
                <div style={{ display: 'flex', flex: 1, alignItems: 'center', justifyContent: 'center', textAlign: 'center' }}>
                  <p style={{ color: C.inkFaint, fontSize: 13.5, maxWidth: 260, lineHeight: 1.6 }}>
                    The patient is waiting. Start the conversation whenever you're ready.
                  </p>
                </div>
              )}
              {messages.map((m, i) => {
                if (m.role === 'divider') {
                  return (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 12, margin: '8px 0' }}>
                      <div style={{ flex: 1, height: 1, background: C.line }} />
                      <span style={{ fontSize: 11.5, letterSpacing: '0.08em', textTransform: 'uppercase', color: C.inkFaint, fontWeight: 600 }}>
                        {m.text}
                      </span>
                      <div style={{ flex: 1, height: 1, background: C.line }} />
                    </div>
                  );
                }
                const isStudent = m.role === 'student';
                const isExaminer = m.role === 'examiner';
                return (
                  <div
                    key={i}
                    style={{
                      display: 'flex', flexDirection: 'column',
                      alignItems: isStudent ? 'flex-end' : 'flex-start', animation: 'fadeUp 0.25s ease-out',
                    }}
                  >
                    {isExaminer && (
                      <span style={{ fontSize: 11, color: C.notesAccent, fontWeight: 600, letterSpacing: '0.06em', marginBottom: 4, marginLeft: 4 }}>
                        EXAMINER
                      </span>
                    )}
                    <div
                      style={{
                        maxWidth: '72%', padding: '11px 16px', borderRadius: 16,
                        borderBottomRightRadius: isStudent ? 4 : 16,
                        borderBottomLeftRadius: isStudent ? 16 : 4,
                        background: isStudent ? C.studentBubble : isExaminer ? C.notesAccentSoft : C.patientBubble,
                        color: isStudent ? '#fff' : C.ink,
                        border: isExaminer ? `1px solid ${C.notesAccent}33` : 'none',
                        fontSize: 14.5, lineHeight: 1.55, whiteSpace: 'pre-wrap',
                        boxShadow: isStudent ? '0 2px 8px rgba(47,90,75,0.18)' : 'none',
                      }}
                    >
                      {m.text}
                    </div>
                  </div>
                );
              })}
              {isTyping && (
                <div style={{ display: 'flex', justifyContent: 'flex-start' }}>
                  <div
                    style={{
                      background: inViva ? C.notesAccentSoft : C.patientBubble,
                      borderRadius: 16, borderBottomLeftRadius: 4, padding: '13px 16px',
                    }}
                  >
                    <TypingDots />
                  </div>
                </div>
              )}
            </div>

            {inViva && vivaDone ? (
              <div
                style={{
                  borderTop: `1px solid ${C.line}`, padding: 16, background: C.panel, display: 'flex',
                  alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap',
                }}
              >
                <p style={{ fontSize: 13.5, color: C.inkSoft }}>All questions answered. Ready for your evaluation?</p>
                <button
                  onClick={runEvaluation}
                  style={{
                    background: C.accent, color: '#fff', border: 'none', borderRadius: 10,
                    padding: '10px 20px', fontSize: 14, fontWeight: 500, cursor: 'pointer', fontFamily: FONT_BODY,
                  }}
                >
                  Get my evaluation
                </button>
              </div>
            ) : (
              <div style={{ borderTop: `1px solid ${C.line}`, padding: 16, display: 'flex', gap: 10, background: C.panel }}>
                <input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={inViva ? 'Type your answer…' : 'Ask the patient a question…'}
                  disabled={isTyping || answering}
                  style={{
                    flex: 1, border: `1px solid ${C.line}`, borderRadius: 11, padding: '11px 15px',
                    fontSize: 14, color: C.ink, fontFamily: FONT_BODY, background: '#fff',
                  }}
                />
                <button
                  onClick={onSend}
                  disabled={isTyping || answering || !input.trim()}
                  style={{
                    background: C.accent, opacity: isTyping || answering || !input.trim() ? 0.45 : 1,
                    border: 'none', borderRadius: 11, width: 44, display: 'flex',
                    alignItems: 'center', justifyContent: 'center', cursor: 'pointer', flexShrink: 0,
                  }}
                  aria-label={inViva ? 'Send answer' : 'Send message'}
                >
                  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2">
                    <path d="M22 2L11 13" strokeLinecap="round" strokeLinejoin="round" />
                    <path d="M22 2l-7 20-4-9-9-4 20-7z" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </button>
              </div>
            )}
          </div>

          {/* NOTES PANEL */}
          <div style={{ width: isWide ? 350 : '100%', flexShrink: 0, background: C.panel, display: 'flex', flexDirection: 'column' }}>
            <div style={{ borderBottom: `1px solid ${C.line}`, padding: '18px 22px' }}>
              <h2 style={{ fontFamily: FONT_DISPLAY, color: C.ink, fontSize: 16, fontWeight: 500 }}>Your notes</h2>
              <p style={{ color: C.inkFaint, fontSize: 12, marginTop: 2 }}>
                {inViva ? 'Locked — saved when you completed the conversation' : 'Private — not visible to the patient'}
              </p>
            </div>

            <div style={{ flex: 1, overflowY: 'auto', padding: 18, display: 'flex', flexDirection: 'column', gap: 12 }}>
              {[
                { key: 'history', label: 'History', hint: 'Onset, character, associated symptoms…' },
                { key: 'exam', label: 'Exam findings', hint: 'What you observed or examined…' },
                { key: 'assessment', label: 'Assessment & plan', hint: 'Your working differential…' },
              ].map((section) => (
                <div key={section.key} style={{ border: `1px solid ${C.line}`, borderRadius: 11, overflow: 'hidden' }}>
                  <button
                    onClick={() => toggleSection(section.key)}
                    style={{
                      width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                      background: C.notesAccentSoft, border: 'none', padding: '11px 14px', cursor: 'pointer',
                      fontSize: 13.5, fontWeight: 500, color: C.ink, fontFamily: FONT_BODY,
                    }}
                  >
                    <span>{section.label}</span>
                    <svg
                      width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={C.notesAccent} strokeWidth="2.2"
                      style={{ transform: notesOpen[section.key] ? 'rotate(0deg)' : 'rotate(-90deg)', transition: 'transform 0.15s' }}
                    >
                      <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </button>
                  {notesOpen[section.key] && (
                    <textarea
                      value={notes[section.key]}
                      onChange={(e) => setNotes((n) => ({ ...n, [section.key]: e.target.value }))}
                      placeholder={section.hint}
                      readOnly={inViva}
                      rows={5}
                      style={{
                        width: '100%', border: 'none', padding: '12px 14px', fontSize: 13.5,
                        resize: 'vertical', fontFamily: FONT_BODY, display: 'block',
                        background: '#1C2622', color: '#F4F5F2', caretColor: '#F4F5F2',
                        opacity: inViva ? 0.75 : 1,
                      }}
                    />
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* COMPLETION MODAL */}
        {confirmingComplete && (
          <div
            style={{
              position: 'fixed', inset: 0, background: 'rgba(20,26,23,0.35)',
              display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24, zIndex: 20,
            }}
          >
            <div style={{ background: C.panel, borderRadius: 16, padding: 28, maxWidth: 400, width: '100%', boxShadow: C.shadow, animation: 'fadeUp 0.2s ease-out' }}>
              <h3 style={{ fontFamily: FONT_DISPLAY, color: C.ink, fontSize: 18, marginBottom: 8 }}>Complete this conversation?</h3>
              <p style={{ color: C.inkSoft, fontSize: 13.5, lineHeight: 1.6, marginBottom: 22 }}>
                Your conversation and notes will be saved and you won't be able to return to the patient. You'll move on to a short oral exam about this case, then get your evaluation.
              </p>
              <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
                <button
                  onClick={() => setConfirmingComplete(false)}
                  style={{
                    border: `1px solid ${C.line}`, background: 'transparent', color: C.inkSoft,
                    borderRadius: 9, padding: '9px 16px', fontSize: 13.5, cursor: 'pointer', fontFamily: FONT_BODY,
                  }}
                >
                  Keep talking
                </button>
                <button
                  onClick={handleCompleteConfirmed}
                  style={{
                    border: 'none', background: C.accent, color: '#fff', borderRadius: 9,
                    padding: '9px 18px', fontSize: 13.5, fontWeight: 500, cursor: 'pointer', fontFamily: FONT_BODY,
                  }}
                >
                  Complete & continue
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    );
  };

  // ---------------- PICK THE SCREEN ----------------
  let screen;
  if (isLoadingRoom) screen = busyScreen('Preparing the room…');
  else if (error && !sessionId) screen = errorScreen(error, startSession);
  else if (phase === 'viva_loading') screen = busyScreen('The examiner is reviewing your conversation…', 'This usually takes a few seconds.');
  else if (phase === 'viva_error') screen = errorScreen("Couldn't prepare your oral exam questions. Your conversation and notes are already saved.", loadViva);
  else if (phase === 'evaluating') screen = busyScreen('Scoring your encounter…', 'Your interview, notes and oral exam answers are being checked against the rubric. This can take up to a minute.');
  else if (phase === 'eval_error') screen = errorScreen("Couldn't complete the evaluation. Your answers are saved.", runEvaluation);
  else if (phase === 'results' && evaluation) screen = resultsScreen();
  else screen = roomScreen();

  return (
    <>
      <FontImports />
      {screen}
    </>
  );
}
