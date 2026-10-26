import React, { useState, useRef, useEffect } from 'react';
import { Send, CheckCircle2, ChevronDown, ChevronRight, Circle, Loader2 } from 'lucide-react';

// ---------------- CONFIG ----------------
// Point this at wherever patient_twin_service_v2.py is running.
const API_BASE = 'http://localhost:8000';
// -----------------------------------------

const COLORS = {
  bg: '#F5F6F3',
  panel: '#FFFFFF',
  ink: '#1F2A24',
  inkSoft: '#5C6B62',
  accent: '#3D6B5C',
  accentSoft: '#E7EFEA',
  line: '#DDE3DE',
  notesAccent: '#A9713C',
  notesAccentSoft: '#F4ECE0',
  patientBubble: '#EFF2EE',
  errorBg: '#FCEEEC',
  errorText: '#A94A3D',
};

const FONTS = {
  display: "'Source Serif 4', Georgia, serif",
  body: "'Inter', -apple-system, sans-serif",
  mono: "'IBM Plex Mono', monospace",
};

export default function PatientRoom() {
  const [sessionId, setSessionId] = useState(null);
  const [patientInfo, setPatientInfo] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [isLoadingRoom, setIsLoadingRoom] = useState(true);
  const [error, setError] = useState(null);
  const [notesOpen, setNotesOpen] = useState({ history: true, exam: false, assessment: false });
  const [notes, setNotes] = useState({ history: '', exam: '', assessment: '' });
  const [completed, setCompleted] = useState(false);
  const [completionSummary, setCompletionSummary] = useState(null);
  const [confirmingComplete, setConfirmingComplete] = useState(false);
  const scrollRef = useRef(null);

  useEffect(() => {
    startSession();
  }, []);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isTyping]);

  async function startSession() {
    setIsLoadingRoom(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/session/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      if (!res.ok) throw new Error(`Failed to start session (${res.status})`);
      const data = await res.json();
      setSessionId(data.session_id);
      setPatientInfo(data.patient);
      setMessages([{ role: 'patient', text: data.opening_message }]);
    } catch (e) {
      setError(
        `Couldn't connect to the patient service. Make sure patient_twin_service_v2.py is running and reachable at ${API_BASE}.`
      );
    } finally {
      setIsLoadingRoom(false);
    }
  }

  async function sendMessage() {
    if (!input.trim() || !sessionId) return;
    const studentText = input.trim();
    setMessages((m) => [...m, { role: 'student', text: studentText }]);
    setInput('');
    setIsTyping(true);
    setError(null);

    try {
      const res = await fetch(`${API_BASE}/session/${sessionId}/message`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: studentText }),
      });
      if (!res.ok) throw new Error(`Message failed (${res.status})`);
      const data = await res.json();
      // The backend keeps full conversation memory server-side and re-sends
      // it to the model every turn, so the patient stays consistent across
      // the whole conversation without the frontend needing to manage that.
      setMessages((m) => [...m, { role: 'patient', text: data.reply }]);
    } catch (e) {
      setError("The patient didn't respond — the model service may be unreachable. Try again.");
    } finally {
      setIsTyping(false);
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const toggleSection = (key) => setNotesOpen((s) => ({ ...s, [key]: !s[key] }));

  async function handleCompleteConfirmed() {
    setConfirmingComplete(false);
    if (!sessionId) return;
    try {
      const res = await fetch(`${API_BASE}/session/${sessionId}/leave`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ notes }),
      });
      if (!res.ok) throw new Error(`Failed to save session (${res.status})`);
      const data = await res.json();
      setCompletionSummary(data);
      setCompleted(true);
    } catch (e) {
      setError("Couldn't save your session — check the backend connection and try again.");
    }
  }

  // ---------------- LOADING STATE ----------------
  if (isLoadingRoom) {
    return (
      <div style={{ background: COLORS.bg, fontFamily: FONTS.body }} className="w-full h-full flex items-center justify-center p-8">
        <style>{`
          @import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');
          @keyframes spin { to { transform: rotate(360deg); } }
          .animate-spin { animation: spin 1s linear infinite; }
        `}</style>
        <div className="flex flex-col items-center gap-3">
          <Loader2 size={28} color={COLORS.accent} className="animate-spin" />
          <p style={{ color: COLORS.inkSoft }} className="text-sm">Preparing the room…</p>
        </div>
      </div>
    );
  }

  // ---------------- CONNECTION ERROR (before session starts) ----------------
  if (error && !sessionId) {
    return (
      <div style={{ background: COLORS.bg, fontFamily: FONTS.body }} className="w-full h-full flex items-center justify-center p-8">
        <div style={{ background: COLORS.errorBg, borderColor: COLORS.errorText }} className="max-w-md border rounded-lg p-6 text-center">
          <p style={{ color: COLORS.errorText }} className="text-sm leading-relaxed mb-4">{error}</p>
          <button onClick={startSession} style={{ background: COLORS.accent }} className="rounded-md px-4 py-2 text-sm text-white">
            Try again
          </button>
        </div>
      </div>
    );
  }

  // ---------------- COMPLETED STATE ----------------
  if (completed) {
    return (
      <div style={{ background: COLORS.bg, fontFamily: FONTS.body, minHeight: '600px' }} className="w-full h-full flex items-center justify-center p-8">
        <div style={{ background: COLORS.panel, borderColor: COLORS.line }} className="max-w-md w-full border rounded-lg p-8 text-center">
          <div style={{ background: COLORS.accentSoft }} className="w-14 h-14 rounded-full flex items-center justify-center mx-auto mb-5">
            <CheckCircle2 size={26} color={COLORS.accent} strokeWidth={1.75} />
          </div>
          <h2 style={{ fontFamily: FONTS.display, color: COLORS.ink }} className="text-xl mb-2">
            Conversation completed
          </h2>
          <p style={{ color: COLORS.inkSoft }} className="text-sm leading-relaxed mb-6">
            Your conversation and notes have been saved.
          </p>
          <div style={{ borderColor: COLORS.line, color: COLORS.inkSoft }} className="border rounded-md p-3 text-xs text-left space-y-1">
            <div className="flex justify-between">
              <span>Messages exchanged</span>
              <span style={{ color: COLORS.ink, fontFamily: FONTS.mono }}>
                {completionSummary?.message_count ?? messages.length}
              </span>
            </div>
            <div className="flex justify-between">
              <span>Note sections completed</span>
              <span style={{ color: COLORS.ink, fontFamily: FONTS.mono }}>
                {Object.values(notes).filter((v) => v.trim()).length} / 3
              </span>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ---------------- MAIN ROOM ----------------
  return (
    <div style={{ background: COLORS.bg, fontFamily: FONTS.body }} className="w-full h-full flex flex-col">
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');
        ::-webkit-scrollbar { width: 8px; }
        ::-webkit-scrollbar-thumb { background: ${COLORS.line}; border-radius: 4px; }
        textarea:focus, input:focus { outline: 2px solid ${COLORS.accent}; outline-offset: -1px; }
        @media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; } }
        @keyframes pulse-dot { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
      `}</style>

      {/* Header — deliberately shows NO diagnosis, just what a student would actually know */}
      <div style={{ background: COLORS.panel, borderColor: COLORS.line }} className="border-b px-6 py-4 flex items-center justify-between flex-wrap gap-4">
        <div className="flex items-center gap-4">
          <div style={{ background: COLORS.accentSoft, color: COLORS.accent }} className="w-11 h-11 rounded-full flex items-center justify-center text-sm font-medium">
            {patientInfo?.gender === 'M' ? '♂' : patientInfo?.gender === 'F' ? '♀' : '?'}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 style={{ fontFamily: FONTS.display, color: COLORS.ink }} className="text-lg leading-tight">
                New Patient
              </h1>
              <span style={{ color: COLORS.inkSoft, fontFamily: FONTS.mono }} className="text-xs">
                {patientInfo?.age} · {patientInfo?.gender}
              </span>
            </div>
            <p style={{ color: COLORS.inkSoft }} className="text-xs mt-0.5">
              Presenting complaint: <span style={{ color: COLORS.ink }}>{patientInfo?.presenting_complaint}</span>
            </p>
          </div>
        </div>

        <div className="flex items-center gap-5">
          <div className="flex items-center gap-1.5">
            <Circle size={8} fill={COLORS.accent} color={COLORS.accent} style={{ animation: 'pulse-dot 2s ease-in-out infinite' }} />
            <span style={{ color: COLORS.inkSoft }} className="text-xs">In room</span>
          </div>
          <button
            onClick={() => setConfirmingComplete(true)}
            style={{ borderColor: COLORS.accent, color: COLORS.accent }}
            className="flex items-center gap-2 border rounded-md px-3.5 py-2 text-sm font-medium transition-colors"
            onMouseEnter={(e) => (e.currentTarget.style.background = COLORS.accentSoft)}
            onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
          >
            <CheckCircle2 size={15} strokeWidth={1.75} />
            Completed conversation
          </button>
        </div>
      </div>

      {error && sessionId && (
        <div style={{ background: COLORS.errorBg, color: COLORS.errorText }} className="px-6 py-2 text-xs text-center">
          {error}
        </div>
      )}

      <div className="flex-1 flex min-h-0">
        {/* Chat panel */}
        <div className="flex-1 flex flex-col min-w-0" style={{ borderRight: `1px solid ${COLORS.line}` }}>
          <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
            {messages.map((m, i) => (
              <div key={i} className={`flex ${m.role === 'student' ? 'justify-end' : 'justify-start'}`}>
                <div
                  style={{
                    background: m.role === 'student' ? COLORS.accent : COLORS.patientBubble,
                    color: m.role === 'student' ? '#FFFFFF' : COLORS.ink,
                  }}
                  className="max-w-[75%] rounded-lg px-4 py-2.5 text-sm leading-relaxed"
                >
                  {m.text}
                </div>
              </div>
            ))}
            {isTyping && (
              <div className="flex justify-start">
                <div style={{ background: COLORS.patientBubble, color: COLORS.inkSoft }} className="rounded-lg px-4 py-2.5 text-sm">
                  typing…
                </div>
              </div>
            )}
          </div>

          <div style={{ borderColor: COLORS.line }} className="border-t p-4 flex gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask the patient a question…"
              style={{ borderColor: COLORS.line, color: COLORS.ink }}
              className="flex-1 border rounded-md px-3.5 py-2.5 text-sm bg-white"
              disabled={isTyping}
            />
            <button
              onClick={sendMessage}
              disabled={isTyping || !input.trim()}
              style={{ background: COLORS.accent, opacity: isTyping || !input.trim() ? 0.5 : 1 }}
              className="rounded-md px-4 py-2.5 text-white flex items-center justify-center"
              aria-label="Send message"
            >
              <Send size={16} strokeWidth={2} />
            </button>
          </div>
        </div>

        {/* Notes panel */}
        <div style={{ background: COLORS.panel }} className="w-[340px] flex-shrink-0 flex flex-col">
          <div style={{ borderColor: COLORS.line }} className="border-b px-5 py-4">
            <h2 style={{ fontFamily: FONTS.display, color: COLORS.ink }} className="text-sm">Your notes</h2>
            <p style={{ color: COLORS.inkSoft }} className="text-xs mt-0.5">Private — not visible to the patient</p>
          </div>

          <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
            {[
              { key: 'history', label: 'History', hint: 'Onset, character, associated symptoms…' },
              { key: 'exam', label: 'Exam findings', hint: 'What you observed or examined…' },
              { key: 'assessment', label: 'Assessment & plan', hint: 'Your working differential…' },
            ].map((section) => (
              <div key={section.key} style={{ borderColor: COLORS.line }} className="border rounded-md overflow-hidden">
                <button
                  onClick={() => toggleSection(section.key)}
                  style={{ background: COLORS.notesAccentSoft, color: COLORS.ink }}
                  className="w-full flex items-center justify-between px-3 py-2 text-sm font-medium"
                >
                  <span>{section.label}</span>
                  {notesOpen[section.key] ? (
                    <ChevronDown size={15} color={COLORS.notesAccent} />
                  ) : (
                    <ChevronRight size={15} color={COLORS.notesAccent} />
                  )}
                </button>
                {notesOpen[section.key] && (
                  <textarea
                    value={notes[section.key]}
                    onChange={(e) => setNotes((n) => ({ ...n, [section.key]: e.target.value }))}
                    placeholder={section.hint}
                    rows={5}
                    style={{ color: COLORS.ink }}
                    className="w-full px-3 py-2.5 text-sm resize-none border-0"
                  />
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Completion confirmation modal */}
      {confirmingComplete && (
        <div className="fixed inset-0 bg-black bg-opacity-30 flex items-center justify-center p-6 z-10">
          <div style={{ background: COLORS.panel }} className="max-w-sm w-full rounded-lg p-6">
            <h3 style={{ fontFamily: FONTS.display, color: COLORS.ink }} className="text-lg mb-2">
              Complete this conversation?
            </h3>
            <p style={{ color: COLORS.inkSoft }} className="text-sm leading-relaxed mb-5">
              Your conversation and notes will be saved, and you won't be able to continue this encounter afterward.
            </p>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setConfirmingComplete(false)}
                style={{ color: COLORS.inkSoft, borderColor: COLORS.line }}
                className="border rounded-md px-4 py-2 text-sm"
              >
                Keep talking
              </button>
              <button onClick={handleCompleteConfirmed} style={{ background: COLORS.accent }} className="rounded-md px-4 py-2 text-sm text-white">
                Complete & save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
