import { useState, useEffect, useRef } from 'react'

const TYPES = [
  { value: 'hr', label: 'HR screen' },
  { value: 'behavioral', label: 'Behavioral' },
  { value: 'technical', label: 'Technical' },
  { value: 'resume', label: 'Resume-based' },
]
const typeLabel = (v) => TYPES.find((t) => t.value === v)?.label || v

const box = { border: '1px solid #444', borderRadius: 8, padding: 12, marginBottom: 12 }
const field = { color: '#111', background: '#fff', border: '1px solid #888', borderRadius: 6, padding: 8 }
const btn = { padding: '8px 16px', borderRadius: 6, border: '1px solid #888', cursor: 'pointer' }
const smallBtn = { ...btn, padding: '4px 10px', fontSize: 13 }

export default function InterviewPage({ applications, apiBase }) {
  const [appId, setAppId] = useState('')
  const [type, setType] = useState('behavioral')
  const [history, setHistory] = useState([])
  const [session, setSession] = useState(null)
  const [report, setReport] = useState(null)
  const [answer, setAnswer] = useState('')
  const [loading, setLoading] = useState('') // '' | 'starting' | 'opening' | 'answering' | 'finishing' | 'switching'
  const [error, setError] = useState('')
  const bottomRef = useRef(null)

  const call = async (path, options) => {
    const res = await fetch(`${apiBase}${path}`, options)
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`)
    return data
  }
  const post = (path, body) =>
    call(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })

  const loadHistory = async () => {
    try {
      setHistory(await call('/interview-sessions'))
    } catch (e) {
      // history is a convenience; ignore failures
    }
  }

  // Refresh history whenever we're on the setup screen
  useEffect(() => {
    if (!session) loadHistory()
  }, [session])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [session?.transcript?.length, report])

  // Browser back button -> setup screen (application + type picker)
  const inSession = session !== null
  useEffect(() => {
    if (!inSession) return
    window.history.pushState({ interview: true }, '')
    const onPop = () => {
      setSession(null)
      setReport(null)
      setAnswer('')
      setError('')
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [inSession])

  const goBack = () => window.history.back()

  // ---------- actions ----------
  const start = async () => {
    setError('')
    setLoading('starting')
    try {
      const prep = await post(`/applications/${appId}/interview-prep`, { interview_type: type })
      setSession(await call(`/interview-sessions/${prep.session_id}`))
      setReport(null)
      setAnswer('')
    } catch (e) {
      setError(e.message)
    }
    setLoading('')
  }

  const openSession = async (id) => {
    setError('')
    setLoading('opening')
    try {
      const state = await call(`/interview-sessions/${id}`)
      setSession(state)
      setReport(state.evaluation || null)
      setAnswer('')
    } catch (e) {
      setError(e.message)
    }
    setLoading('')
  }

  const deleteSession = async (id) => {
    if (!window.confirm('Delete this interview session and its transcript? This cannot be undone.')) return setError('')
    try {
      await call(`/interview-sessions/${id}`, { method: 'DELETE' })
      await loadHistory()
    } 
    catch (e) {
      setError(e.message)
    }
  }

  const pickQuestion = async (i) => {
    setError('')
    setLoading('switching')
    try {
      setSession(await post(`/interview-sessions/${session.session_id}/start-question`, { question_index: i }))
      setAnswer('')
    } catch (e) {
      setError(e.message)
    }
    setLoading('')
  }

  const skipQuestion = async (i) => {
    setError('')
    setLoading('switching')
    try {
      setSession(await post(`/interview-sessions/${session.session_id}/skip-question`, { question_index: i }))
      setAnswer('')
    } catch (e) {
      setError(e.message)
    }
    setLoading('')
  }

  const submitAnswer = async () => {
    if (!answer.trim()) return
    setError('')
    setLoading('answering')
    try {
      setSession(await post(`/interview-sessions/${session.session_id}/answer`, { answer }))
      setAnswer('')
    } catch (e) {
      setError(e.message)
    }
    setLoading('')
  }

  const finish = async () => {
    setError('')
    setLoading('finishing')
    try {
      setReport(await post(`/interview-sessions/${session.session_id}/finish`))
    } catch (e) {
      setError(e.message)
    }
    setLoading('')
  }

  const busy = loading !== ''

  // ---------- Setup screen ----------
  if (!session) {
    return (
      <div style={{ maxWidth: 700 }}>
        <h2>Mock Interview</h2>
        {applications.length === 0 ? (
          <p>No tracked applications yet. Mark a job as submitted from the Jobs tab first.</p>
        ) : (
          <>
            <div style={{ marginBottom: 12 }}>
              <label>Application<br />
                <select style={{ ...field, width: '100%' }} value={appId} onChange={(e) => setAppId(e.target.value)}>
                  <option value="">Select an application...</option>
                  {applications.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.company} — {a.title} ({a.status})
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div style={{ marginBottom: 12 }}>
              <label>Interview type<br />
                <select style={{ ...field, width: '100%' }} value={type} onChange={(e) => setType(e.target.value)}>
                  {TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                </select>
              </label>
            </div>
            <button style={btn} disabled={!appId || busy} onClick={start}>
              {loading === 'starting' ? 'Generating questions...' : 'Start new interview'}
            </button>
          </>
        )}
        {error && <p style={{ color: '#e5484d' }}>{error}</p>}

        {history.length > 0 && (
          <div style={{ marginTop: 32 }}>
            <h3>Past & in-progress interviews</h3>
            {history.map((h) => (
              <div key={h.session_id} style={{ ...box, display: 'flex', alignItems: 'center', gap: 12 }}>
                <div style={{ flex: 1 }}>
                  <strong>{h.company} — {h.title}</strong>
                  <div style={{ fontSize: 13, opacity: 0.8 }}>
                    {typeLabel(h.interview_type)} · {h.answered_count}/{h.total_questions} answered ·{' '}
                    {h.status === 'completed' ? '✅ Completed' : '⏳ In progress'}
                    {h.updated_at && ` · ${new Date(h.updated_at + 'Z').toLocaleString()}`}
                  </div>
                </div>
                <button style={btn} disabled={busy} onClick={() => openSession(h.session_id)}>
                  {h.status === 'completed' ? 'View' : 'Resume'}
                </button>
                <button style={btn} disabled={busy} onClick={() => deleteSession(h.session_id)}>
                  Delete
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    )
  }

  // ---------- Session screen ----------
  const locked = !!report
  const active = session.active_question_index
  const nextPending = session.questions.find((q) => q.status === 'pending')
  const canFinish = session.answered_count > 0 && !locked

  const finishButton = canFinish && (
    <button style={btn} disabled={busy} onClick={finish}>
      {loading === 'finishing' ? 'Building report...' : 'Finish & get report'}
    </button>
  )

  return (
    <div style={{ maxWidth: 800 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button style={btn} onClick={goBack}>← Back</button>
          <h2 style={{ margin: 0 }}>{typeLabel(session.interview_type)} interview</h2>
        </div>
        <span>{session.answered_count} / {session.total_questions} answered</span>
      </div>

      {/* Question list */}
      <details open={active === null && !locked} style={{ ...box, marginTop: 16 }}>
        <summary style={{ cursor: 'pointer', fontWeight: 600 }}>Questions</summary>
        <div style={{ marginTop: 8 }}>
          {session.questions.map((q) => {
            const isActive = active === q.index
            return (
              <div
                key={q.index}
                style={{
                  display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px', marginBottom: 6,
                  border: `1px solid ${isActive ? '#3b82f6' : '#444'}`, borderRadius: 6,
                  opacity: q.status === 'skipped' ? 0.6 : 1,
                }}
              >
                <span style={{ width: 22 }}>
                  {q.status === 'answered' ? '✅' : q.status === 'skipped' ? '⏭️' : '○'}
                </span>
                <span style={{ flex: 1 }}>{q.index + 1}. {q.question}</span>
                {q.status === 'answered' && <span>{q.score}/10</span>}
                {!locked && q.status !== 'answered' && !isActive && (
                  <button style={smallBtn} disabled={busy} onClick={() => pickQuestion(q.index)}>Practice</button>
                )}
                {!locked && q.status === 'pending' && (
                  <button style={smallBtn} disabled={busy} onClick={() => skipQuestion(q.index)}>Skip</button>
                )}
                {isActive && <span style={{ fontSize: 12 }}>in progress</span>}
              </div>
            )
          })}
        </div>
      </details>

      {/* Transcript */}
      <div style={{ marginTop: 16 }}>
        {session.transcript.map((t, i) => {
          if (t.role === 'system') {
            return (
              <div key={i} style={{ fontSize: 13, opacity: 0.6, marginBottom: 12 }}>
                ⏭️ Skipped Q{t.q_index + 1}
              </div>
            )
          }
          if (t.role === 'interviewer') {
            return (
              <div key={i} style={{ ...box, borderColor: '#3b82f6' }}>
                <strong>{t.kind === 'followup' ? `Follow-up (Q${t.q_index + 1})` : `Q${t.q_index + 1} · Interviewer`}</strong>
                <p style={{ margin: '6px 0 0', whiteSpace: 'pre-wrap' }}>{t.content}</p>
              </div>
            )
          }
          return (
            <div key={i} style={{ marginLeft: 40, marginBottom: 12 }}>
              <div style={{ ...box, marginBottom: 6 }}>
                <strong>You</strong>
                <p style={{ margin: '6px 0 0', whiteSpace: 'pre-wrap' }}>{t.content}</p>
              </div>
              <div style={{ ...box, borderColor: '#22c55e' }}>
                <strong>Score: {t.score}/10</strong>
                <p style={{ margin: '6px 0' }}>{t.feedback}</p>
                {t.strengths?.length > 0 && <div>✅ {t.strengths.join(' • ')}</div>}
                {t.weak_areas?.length > 0 && <div>⚠️ {t.weak_areas.join(' • ')}</div>}
                {t.answer_structure?.length > 0 && (
                  <div style={{ marginTop: 8 }}>
                    <strong>💡 Suggested answer structure</strong>
                    <ol style={{ margin: '4px 0 0', paddingLeft: 20 }}>
                      {t.answer_structure.map((s, k) => <li key={k}>{s}</li>)}
                    </ol>
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {/* Answer box */}
      {!locked && active !== null && (
        <div>
          <textarea
            style={{ ...field, width: '100%', minHeight: 120, boxSizing: 'border-box' }}
            placeholder="Type your answer..."
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            disabled={loading === 'answering'}
          />
          <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
            <button style={btn} disabled={busy || !answer.trim()} onClick={submitAnswer}>
              {loading === 'answering' ? 'Evaluating...' : 'Submit answer'}
            </button>
            {finishButton}
          </div>
        </div>
      )}

      {/* No active question */}
      {!locked && active === null && (
        <div style={box}>
          {nextPending ? (
            <p style={{ marginTop: 0 }}>
              Pick a question from the list above, or continue in order.
            </p>
          ) : (
            <p style={{ marginTop: 0 }}>You've gone through every question.</p>
          )}
          <div style={{ display: 'flex', gap: 8 }}>
            {nextPending && (
              <button style={btn} disabled={busy} onClick={() => pickQuestion(nextPending.index)}>
                Next question →
              </button>
            )}
            {finishButton}
          </div>
        </div>
      )}

      {error && <p style={{ color: '#e5484d' }}>{error}</p>}

      {/* Final report */}
      {report && (
        <div style={{ ...box, borderColor: '#f59e0b', marginTop: 16 }}>
          <h3 style={{ marginTop: 0 }}>Final report</h3>
          <p>
            <strong>Average score: {report.average_score}/10</strong> across {report.questions_answered} answers
            {report.questions_skipped > 0 && ` (${report.questions_skipped} skipped)`}
            {' · '}Readiness: <strong>{report.readiness}</strong>
          </p>
          <p>{report.overall_summary}</p>
          {report.top_weak_areas?.length > 0 && (
            <>
              <h4>Recurring weak areas</h4>
              <ul>{report.top_weak_areas.map((w, i) => <li key={i}>{w.area} (×{w.count})</li>)}</ul>
            </>
          )}
          <h4>Strengths</h4>
          <ul>{report.strengths.map((s, i) => <li key={i}>{s}</li>)}</ul>
          <h4>Improvements</h4>
          <ul>{report.improvements.map((s, i) => <li key={i}>{s}</li>)}</ul>
          <h4>Practice plan for tonight</h4>
          <ul>{report.practice_plan.map((s, i) => <li key={i}>{s}</li>)}</ul>
          <button style={btn} onClick={goBack}>Back to interviews</button>
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  )
}