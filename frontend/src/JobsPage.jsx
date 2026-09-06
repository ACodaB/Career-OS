import { useState, useEffect, useRef } from 'react'

const API_BASE = 'http://localhost:8000'
const LAST_SEARCH_KEY = 'careerOS_lastSearchedCompanies'
const POLL_INTERVAL_MS = 5000

const RECOMMENDATION_LABELS = {
  strong_match: { label: 'Strong match', color: '#0a7d2c' },
  worth_applying: { label: 'Worth applying', color: '#b8860b' },
  weak_match: { label: 'Weak match', color: '#888' },
}

export default function JobsPage({ submittedJobIds, onApplicationChange }) {
  const [jobs, setJobs] = useState([])
  const [companies, setCompanies] = useState('')
  const [activeCompanies, setActiveCompanies] = useState(() => {
    const saved = localStorage.getItem(LAST_SEARCH_KEY)
    return saved ? JSON.parse(saved) : []
  })
  const [syncing, setSyncing] = useState(false)
  const [syncResult, setSyncResult] = useState(null)
  const [matching, setMatching] = useState(false)
  const [matchError, setMatchError] = useState(null)
  const pollRef = useRef(null)

  // Phase 3 — application generation state
  const [generatingJobId, setGeneratingJobId] = useState(null)
  const [generateErrors, setGenerateErrors] = useState({})
  const [expandedJobId, setExpandedJobId] = useState(null)
  const [copiedField, setCopiedField] = useState(null)

  // Phase 4 — editable review + submit state
  const [editedResume, setEditedResume] = useState({})       // { [jobId]: text }
  const [editedCoverLetter, setEditedCoverLetter] = useState({}) // { [jobId]: text }
  const [submittingJobId, setSubmittingJobId] = useState(null)
  const [submitErrors, setSubmitErrors] = useState({})

  useEffect(() => {
    if (activeCompanies.length > 0) {
      setCompanies(activeCompanies.join(', '))
    }
  }, [])

  const loadJobs = () => {
    fetch(`${API_BASE}/jobs`)
      .then((r) => r.json())
      .then(setJobs)
      .catch(() => setJobs([]))
  }

  useEffect(() => {
    loadJobs()
  }, [])

  // Stop polling if the component unmounts mid-match.
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [])

  const handleSync = async () => {
    setSyncing(true)
    setSyncResult(null)
    try {
      const board_tokens = companies
        .split(',')
        .map((c) => c.trim())
        .filter(Boolean)

      const res = await fetch(`${API_BASE}/jobs/sync`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(board_tokens.length ? { board_tokens } : {}),
      })
      const data = await res.json()
      setSyncResult(data)

      const lowered = board_tokens.map((t) => t.toLowerCase())
      setActiveCompanies(lowered)
      localStorage.setItem(LAST_SEARCH_KEY, JSON.stringify(lowered))

      loadJobs()
    } catch {
      setSyncResult({ error: 'Sync failed — is the backend running?' })
    } finally {
      setSyncing(false)
    }
  }

  const handleMatch = async (limit = null) => {
    setMatching(true)
    setMatchError(null)

    pollRef.current = setInterval(loadJobs, POLL_INTERVAL_MS)

    try {
      const body = {}
      if (limit) body.limit = limit
      if (activeCompanies.length > 0) body.companies = activeCompanies

      const res = await fetch(`${API_BASE}/jobs/match`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await res.json()
      if (!res.ok) {
        setMatchError(data.detail || 'Matching failed.')
      } else {
        loadJobs()
      }
    } catch {
      setMatchError('Matching failed — is the backend running?')
    } finally {
      clearInterval(pollRef.current)
      pollRef.current = null
      setMatching(false)
    }
  }

  const handleShowAll = () => {
    setActiveCompanies([])
    localStorage.removeItem(LAST_SEARCH_KEY)
  }

  // ---- Phase 3: generate tailored resume + cover letter ----

  const handleGenerateApplication = async (jobId) => {
    setGeneratingJobId(jobId)
    setGenerateErrors((prev) => {
      const next = { ...prev }
      delete next[jobId]
      return next
    })

    try {
      const res = await fetch(`${API_BASE}/jobs/${jobId}/generate-application`, {
        method: 'POST',
      })
      const data = await res.json()
      if (!res.ok) {
        setGenerateErrors((prev) => ({ ...prev, [jobId]: data.detail || 'Generation failed.' }))
      } else {
        // Regeneration should discard any in-progress edits for this job,
        // since the underlying generated content just changed.
        setEditedResume((prev) => {
          const next = { ...prev }
          delete next[jobId]
          return next
        })
        setEditedCoverLetter((prev) => {
          const next = { ...prev }
          delete next[jobId]
          return next
        })
        loadJobs()
        setExpandedJobId(jobId)
      }
    } catch {
      setGenerateErrors((prev) => ({
        ...prev,
        [jobId]: 'Generation failed — is the backend running?',
      }))
    } finally {
      setGeneratingJobId(null)
    }
  }

  const handleCopy = async (text, fieldKey) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopiedField(fieldKey)
      setTimeout(() => setCopiedField(null), 1500)
    } catch {
      // Clipboard API can fail on non-HTTPS/non-localhost contexts; silently ignore,
      // the text is still visible and selectable for manual copy.
    }
  }

  // ---- Phase 4: expand + edit + submit ----

  const handleToggleExpand = (job) => {
    if (expandedJobId === job.id) {
      setExpandedJobId(null)
      return
    }
    setExpandedJobId(job.id)
    setEditedResume((prev) =>
      prev[job.id] !== undefined ? prev : { ...prev, [job.id]: job.tailored_resume }
    )
    setEditedCoverLetter((prev) =>
      prev[job.id] !== undefined ? prev : { ...prev, [job.id]: job.tailored_cover_letter }
    )
  }

  const handleSubmitApplication = async (jobId) => {
    setSubmittingJobId(jobId)
    setSubmitErrors((prev) => {
      const next = { ...prev }
      delete next[jobId]
      return next
    })

    try {
      const res = await fetch(`${API_BASE}/jobs/${jobId}/submit-application`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tailored_resume: editedResume[jobId] ?? '',
          tailored_cover_letter: editedCoverLetter[jobId] ?? '',
        }),
      })
      const data = await res.json()
      if (!res.ok) {
        setSubmitErrors((prev) => ({ ...prev, [jobId]: data.detail || 'Submit failed.' }))
      } else {
        onApplicationChange() // tells App.jsx to refetch /applications, syncing both tabs
      }
    } catch {
      setSubmitErrors((prev) => ({
        ...prev,
        [jobId]: 'Submit failed — is the backend running?',
      }))
    } finally {
      setSubmittingJobId(null)
    }
  }

  const visibleJobs =
    activeCompanies.length === 0
      ? jobs
      : jobs.filter((j) =>
          activeCompanies.some(
            (token) =>
              j.company.toLowerCase().includes(token) ||
              token.includes(j.company.toLowerCase())
          )
        )

  return (
    <div>
      <div style={{ background: '#f7f7f7', padding: 16, borderRadius: 8, marginBottom: 24 }}>
        <label style={{ fontWeight: 'bold', fontSize: 14 }}>
          Greenhouse company board tokens (comma-separated, e.g. stripe, notion, airbnb)
        </label>
        <p style={{ fontSize: 13, color: '#666', margin: '4px 0 8px' }}>
          Find a company's token in their job board URL: boards.greenhouse.io/&lt;token&gt;.
          Leave blank to use the companies configured in your backend's .env (TARGET_COMPANIES).
        </p>
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            style={{ flex: 1, padding: 8 }}
            value={companies}
            onChange={(e) => setCompanies(e.target.value)}
            placeholder="stripe, notion, airbnb"
          />
          <button onClick={handleSync} disabled={syncing}>
            {syncing ? 'Syncing...' : 'Run Search'}
          </button>
        </div>
        {syncResult && (
          <div style={{ marginTop: 12, fontSize: 13 }}>
            {syncResult.error && <p style={{ color: 'crimson' }}>{syncResult.error}</p>}
            {syncResult.total_inserted !== undefined && (
              <p>
                Inserted <strong>{syncResult.total_inserted}</strong> new jobs, skipped{' '}
                {syncResult.total_skipped} already-seen ones.
              </p>
            )}
            {syncResult.errors && Object.keys(syncResult.errors).length > 0 && (
              <div style={{ color: 'crimson' }}>
                {Object.entries(syncResult.errors).map(([company, err]) => (
                  <p key={company}>
                    {company}: {err}
                  </p>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <div>
          <h2 style={{ margin: 0 }}>
            Jobs ({visibleJobs.length}
            {activeCompanies.length > 0 && visibleJobs.length !== jobs.length ? ` of ${jobs.length}` : ''})
          </h2>
          {activeCompanies.length > 0 && (
            <button
              onClick={handleShowAll}
              style={{ fontSize: 12, marginTop: 4, background: 'none', border: 'none', color: '#0645AD', cursor: 'pointer', padding: 0 }}
            >
              Show all {jobs.length} synced jobs
            </button>
          )}
        </div>
        <div style={{ textAlign: 'right' }}>
          <button onClick={() => handleMatch(5)} disabled={matching || jobs.length === 0} style={{ marginRight: 8 }}>
            Test Match (5)
          </button>
          <button onClick={() => handleMatch()} disabled={matching || jobs.length === 0}>
            {matching ? 'Matching... (updating live)' : 'Run Matching'}
          </button>
          {matchError && (
            <p style={{ color: 'crimson', fontSize: 13, margin: '4px 0 0' }}>{matchError}</p>
          )}
        </div>
      </div>

      {visibleJobs.length === 0 ? (
        <p>No jobs yet — run a search above to pull jobs from Greenhouse.</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {visibleJobs.map((j) => {
            const rec = RECOMMENDATION_LABELS[j.match_recommendation]
            const hasApplication = Boolean(j.application_generated_at)
            const isGenerating = generatingJobId === j.id
            const isExpanded = expandedJobId === j.id
            const genError = generateErrors[j.id]
            const isSubmitting = submittingJobId === j.id
            const submitError = submitErrors[j.id]
            const isSubmitted = submittedJobIds.has(j.id)

            return (
              <div key={j.id} style={{ border: '1px solid #ddd', borderRadius: 8, padding: 12 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <strong>{j.title}</strong>
                  {j.match_percent > 0 && (
                    <span style={{ fontSize: 13, color: rec?.color || '#333' }}>
                      {rec ? `${rec.label} · ` : ''}{j.match_percent}%
                    </span>
                  )}
                </div>
                <div style={{ color: '#666', fontSize: 14 }}>
                  {j.company} {j.location && `· ${j.location}`}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 8, flexWrap: 'wrap' }}>
                  <a href={j.url} target="_blank" rel="noreferrer" style={{ fontSize: 13 }}>
                    View posting →
                  </a>
                  <button
                    onClick={() => handleGenerateApplication(j.id)}
                    disabled={isGenerating}
                    style={{ fontSize: 13 }}
                  >
                    {isGenerating
                      ? 'Generating...'
                      : hasApplication
                      ? 'Regenerate Application'
                      : 'Generate Application'}
                  </button>
                  {hasApplication && (
                    <button
                      onClick={() => handleToggleExpand(j)}
                      style={{ fontSize: 13, background: 'none', border: 'none', color: '#0645AD', cursor: 'pointer', padding: 0 }}
                    >
                      {isExpanded ? 'Hide application' : 'View application'}
                    </button>
                  )}
                </div>

                {genError && (
                  <p style={{ color: 'crimson', fontSize: 13, marginTop: 6 }}>{genError}</p>
                )}

                {isExpanded && hasApplication && (
                  <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 16 }}>
                    <div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <h4 style={{ margin: '0 0 6px' }}>Tailored Resume (editable)</h4>
                        <button
                          onClick={() => handleCopy(editedResume[j.id] ?? '', `resume-${j.id}`)}
                          style={{ fontSize: 12 }}
                        >
                          {copiedField === `resume-${j.id}` ? 'Copied!' : 'Copy'}
                        </button>
                      </div>
                      <textarea
                        value={editedResume[j.id] ?? j.tailored_resume}
                        onChange={(e) =>
                          setEditedResume((prev) => ({ ...prev, [j.id]: e.target.value }))
                        }
                        style={{
                          width: '100%',
                          boxSizing: 'border-box',
                          background: '#fafafa',
                          color: '#111',
                          border: '1px solid #eee',
                          borderRadius: 6,
                          padding: 10,
                          fontSize: 13,
                          fontFamily: 'inherit',
                          minHeight: 220,
                          resize: 'vertical',
                        }}
                      />
                    </div>

                    <div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <h4 style={{ margin: '0 0 6px' }}>Cover Letter (editable)</h4>
                        <button
                          onClick={() => handleCopy(editedCoverLetter[j.id] ?? '', `cover-${j.id}`)}
                          style={{ fontSize: 12 }}
                        >
                          {copiedField === `cover-${j.id}` ? 'Copied!' : 'Copy'}
                        </button>
                      </div>
                      <textarea
                        value={editedCoverLetter[j.id] ?? j.tailored_cover_letter}
                        onChange={(e) =>
                          setEditedCoverLetter((prev) => ({ ...prev, [j.id]: e.target.value }))
                        }
                        style={{
                          width: '100%',
                          boxSizing: 'border-box',
                          background: '#fafafa',
                          color: '#111',
                          border: '1px solid #eee',
                          borderRadius: 6,
                          padding: 10,
                          fontSize: 13,
                          fontFamily: 'inherit',
                          minHeight: 220,
                          resize: 'vertical',
                        }}
                      />
                    </div>

                    <div>
                      <p style={{ fontSize: 12, color: '#666', margin: '0 0 6px' }}>
                        Submit the application yourself on the company's site first, using the
                        text above (edit it if you like), then confirm here to save it to your
                        tracker.
                      </p>
                      <button
                        onClick={() => handleSubmitApplication(j.id)}
                        disabled={isSubmitting || isSubmitted}
                        style={isSubmitted ? { color: '#0a7d2c', borderColor: '#0a7d2c' } : undefined}
                      >
                        {isSubmitting ? 'Saving...' : isSubmitted ? '✓ Submitted' : 'Confirm & Mark Submitted'}
                      </button>
                      {submitError && (
                        <p style={{ color: 'crimson', fontSize: 13, marginTop: 6 }}>{submitError}</p>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}