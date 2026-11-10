import { useState, useEffect, useRef } from 'react'

const DEFAULT_API = 'http://localhost:8000'

async function post(apiBase, path, body) {
  const res = await fetch(`${apiBase}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    let detail = ''
    let payload = null
    try {
      payload = await res.json()
      detail = typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail)
    } catch {
      /* ignore */
    }
    const err = new Error(detail || `Request failed (${res.status})`)
    err.status = res.status
    err.payload = payload
    throw err
  }
  return res.json()
}

const s = {
  box: { border: '1px solid #666', borderRadius: 8, padding: 12, marginTop: 12 },
  btn: {
    padding: '8px 14px',
    borderRadius: 6,
    border: '1px solid #888',
    cursor: 'pointer',
    fontSize: 14,
  },
  btnPrimary: { background: '#2563eb', color: '#fff', border: '1px solid #2563eb' },
  textarea: {
    width: '100%',
    minHeight: 130,
    padding: 8,
    borderRadius: 6,
    border: '1px solid #888',
    background: '#fff',
    color: '#111',
    fontSize: 14,
    boxSizing: 'border-box',
    fontFamily: 'inherit',
  },
  q: { fontWeight: 600, margin: '14px 0 6px' },
  warn: { color: '#e0a030', fontSize: 13, margin: '0 0 6px' },
  err: { color: '#ef4444', marginTop: 10, whiteSpace: 'pre-wrap' },
  muted: { fontSize: 13, opacity: 0.8 },
  list: { margin: '6px 0 0 18px', padding: 0, fontSize: 14 },
}

export default function AutofillPanel({
  jobId,
  apiBase = DEFAULT_API,
  autoStart = false,
  onClose,
  onJobRemoved,
  resumeText,
  coverLetterText,
  onSubmitted,
  isSubmitted,
  onGenerated
}) {
  // idle | scanning | drafting | review | launching | done
  const [phase, setPhase] = useState('idle')
  const [error, setError] = useState('')
  const [drafts, setDrafts] = useState([])
  const [result, setResult] = useState(null)
  const [submitState, setSubmitState] = useState('idle') // idle | saving | done
  const [notice, setNotice] = useState('')

  // Guard so React StrictMode's double-run in dev doesn't launch two scans
  const startedRef = useRef(false)
  useEffect(() => {
    if (autoStart && !startedRef.current) {
      startedRef.current = true
      startScan()
    }
  }, [])

  function reset() {
    setPhase('idle')
    setError('')
    setDrafts([])
    setResult(null)
    if (onClose) onClose()
  }

  async function startScan() {
    setError('')
    setNotice('')
    setResult(null)
    setPhase('scanning')
    let questions = []
    try {
      const scan = await post(apiBase, `/jobs/${jobId}/autofill/scan`)
      questions = scan.essay_questions || []
      if (scan.application_generated && onGenerated) onGenerated()
      if (scan.application_error) {
        setNotice(
          `Couldn't generate your tailored resume and cover letter (${scan.application_error}). Your base resume will be used.`
        )
      }
    } catch (e) {
      if (e.payload?.job_removed && onJobRemoved) {
        onJobRemoved(e.message, jobId)
        return
      }
      setError(e.message)
      setPhase('idle')
      return
    }

    if (questions.length === 0) {
      setDrafts([])
      setPhase('review')
      return
    }

    setPhase('drafting')
    try {
        const res = await post(apiBase, `/jobs/${jobId}/autofill/launch`, {
        essay_answers,
        resume_text: resumeText || null,
        cover_letter_text: coverLetterText || null,
      })
      setDrafts(res.drafts)
    } catch (e) {
      // Let the user write the answers themselves instead of losing the scan.
      setDrafts(questions.map((q) => ({ question: q, answer: '', has_direct_experience: true })))
      setError(`Drafting failed: ${e.message}\nYou can write the answers yourself or leave them blank.`)
    }
    setPhase('review')
  }

  function updateAnswer(index, value) {
    setDrafts((prev) => prev.map((d, i) => (i === index ? { ...d, answer: value } : d)))
  }

  async function launch() {
    setError('')
    setPhase('launching')
    const essay_answers = {}
    drafts.forEach((d) => {
      if (d.answer.trim()) essay_answers[d.question] = d.answer.trim()
    })
    try {
      const res = await post(apiBase, `/jobs/${jobId}/autofill/launch`, { essay_answers })
      setResult(res)
      setPhase('done')
    } catch (e) {
      if (e.payload?.job_removed && onJobRemoved) {
        onJobRemoved(e.message, jobId)
        return
      }
      setError(e.message)
      setPhase('review')
    }
  }
    async function markSubmitted() {
    setError('')
    setSubmitState('saving')
    try {
      await post(apiBase, `/jobs/${jobId}/submit-application`, {
        tailored_resume: resumeText || '',
        tailored_cover_letter: coverLetterText || '',
      })
      setSubmitState('done')
      if (onSubmitted) onSubmitted()
    } catch (e) {
      setError(e.message)
      setSubmitState('idle')
    }
  }
  const alreadyMarked = isSubmitted || submitState === 'done'
  const busy = phase === 'scanning' || phase === 'drafting' || phase === 'launching'
  const report = result?.report

  return (
    <div style={s.box}>
      <strong>Auto-fill application</strong>
      <p style={s.muted}>
        Opens the application form in Chrome and fills what it can. It never submits. You review
        and submit yourself.
      </p>

      {phase === 'idle' && (
        <button style={{ ...s.btn, ...s.btnPrimary }} onClick={startScan}>
          Auto-fill application
        </button>
      )}

      {phase === 'scanning' && (
        <p>Preparing your tailored resume and cover letter, then scanning the form... (up to a minute)</p>
      )}
      {phase === 'drafting' && <p>Drafting answers to the essay questions...</p>}
      {phase === 'launching' && (
        <p>Opening Chrome and filling the form... (up to a minute, keep this tab open)</p>
      )}

      {phase === 'review' && (
        <div>
          {drafts.length === 0 ? (
            <p>No free-text essay questions found on this form.</p>
          ) : (
            <>
              <p style={s.muted}>
                Review and edit each draft before it goes into the form. Empty answers are skipped.
              </p>
              {drafts.map((d, i) => (
                <div key={i}>
                  <div style={s.q}>{d.question}</div>
                  {!d.has_direct_experience && (
                    <p style={s.warn}>
                      Little direct experience in your resume for this one. Check it for honesty
                      and rewrite as needed.
                    </p>
                  )}
                  <textarea
                    style={s.textarea}
                    value={d.answer}
                    onChange={(e) => updateAnswer(i, e.target.value)}
                  />
                </div>
              ))}
            </>
          )}
          <div style={{ marginTop: 14, display: 'flex', gap: 8 }}>
            <button style={{ ...s.btn, ...s.btnPrimary }} onClick={launch}>
              Open form and fill
            </button>
            <button style={s.btn} onClick={reset}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {phase === 'done' && (
        <div>
          <p>
            <strong>Chrome is open.</strong> Finish the remaining fields there and submit it
            yourself. Close the window when you're done.
          </p>
          {result?.documents && (
            <div style={s.muted}>
              {result.documents.resume && <div>Resume uploaded: {result.documents.resume}</div>}
              {result.documents.cover_letter && (
                <div>Cover letter: {result.documents.cover_letter}</div>
              )}
            </div>
          )}
          {!report && <p style={s.muted}>{result?.note || 'No fill report received yet.'}</p>}
          {report && (
            <>
              <div>Filled: {report.filled?.join(', ') || 'nothing'}</div>
              {report.extras_filled?.length > 0 && (
                <div>Also filled: {report.extras_filled.join(', ')}</div>
              )}
              {report.fill_errors && Object.keys(report.fill_errors).length > 0 && (
                <>
                  <div style={{ marginTop: 6 }}>Couldn't fill:</div>
                  <ul style={s.list}>
                    {Object.entries(report.fill_errors).map(([field, why]) => (
                      <li key={field}>
                        {field}: {why}
                      </li>
                    ))}
                  </ul>
                </>
              )}
              {report.essays_filled?.length > 0 && (
                <div>Essays filled: {report.essays_filled.length}</div>
              )}
              {report.essays_not_filled?.length > 0 && (
                <>
                  <div style={{ marginTop: 8 }}>Essays I couldn't place (paste these yourself):</div>
                  <ul style={s.list}>
                    {report.essays_not_filled.map((q) => (
                      <li key={q}>{q}</li>
                    ))}
                  </ul>
                </>
              )}
              {report.needs_you?.length > 0 && (
                <>
                  <div style={{ marginTop: 8 }}>Still needs you:</div>
                  <ul style={s.list}>
                    {report.needs_you.map((f) => (
                      <li key={f}>{f}</li>
                    ))}
                  </ul>
                </>
              )}
            </>
          )}
                    <div style={{ marginTop: 12 }}>
            <p style={s.muted}>
              After you submit on the company's site, record it here so the job moves to your
              Applications tab.
            </p>
            <button
              style={
                alreadyMarked
                  ? { ...s.btn, color: '#0a7d2c', borderColor: '#0a7d2c' }
                  : { ...s.btn, ...s.btnPrimary }
              }
              onClick={markSubmitted}
              disabled={submitState === 'saving' || alreadyMarked}
            >
              {alreadyMarked
                ? '✓ Marked as submitted'
                : submitState === 'saving'
                ? 'Saving...'
                : "I've submitted it — mark as submitted"}
            </button>
          </div>
          <button style={{ ...s.btn, marginTop: 12 }} onClick={reset}>
            Done
          </button>
        </div>
      )}
      {notice && <div style={{ ...s.muted, marginTop: 8 }}>{notice}</div>}
      {error && <div style={s.err}>{error}</div>}
      {busy && <div style={{ ...s.muted, marginTop: 8 }}>Working...</div>}
    </div>
  )
}