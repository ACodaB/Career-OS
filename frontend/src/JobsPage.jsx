import { useState, useEffect, useRef } from 'react'
import AutofillPanel from './AutofillPanel'

const API_BASE = 'http://localhost:8000'
const LAST_SEARCH_KEY = 'careerOS_lastSearchedCompanies'
const POLL_INTERVAL_MS = 5000
const HIDE_SUBMITTED_KEY = 'careerOS_hideSubmitted'

const RECOMMENDATION_LABELS = {
  strong_match: { label: 'Strong match', color: '#0a7d2c' },
  worth_applying: { label: 'Worth applying', color: '#b8860b' },
  weak_match: { label: 'Weak match', color: '#888' },
}

export default function JobsPage({ submittedJobIds, onApplicationChange }) {
  const [jobs, setJobs] = useState([])
  const [fetchingNow, setFetchingNow] = useState(false)
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

  // Phase 6 — which job's auto-fill panel is open
  const [autofillJobId, setAutofillJobId] = useState(null)

  
  // Keyword search + date filter + sort
  const [searchInput, setSearchInput] = useState('')
  const [searchQuery, setSearchQuery] = useState('') // the keyword currently applied
  const [searchScores, setSearchScores] = useState({}) // { [jobId]: { relevance, syntactic, semantic } }
  const [searchInfo, setSearchInfo] = useState(null) // semantic index progress from the backend
  const [searchLoading, setSearchLoading] = useState(false)
  const [searchError, setSearchError] = useState('')
  const [searchNotice, setSearchNotice] = useState('')
  const [searchCompany, setSearchCompany] = useState(null) // set when the search was a company name
  const [datePosted, setDatePosted] = useState('any') // any | 24h | 7d | 30d
  const [sortBy, setSortBy] = useState('relevance') // relevance | resume | newest

  // Closed-posting check
  const [closedCheck, setClosedCheck] = useState(null)

  // Hide jobs I've already submitted (remembered between visits)
  const [hideSubmitted, setHideSubmitted] = useState(
    () => localStorage.getItem(HIDE_SUBMITTED_KEY) === '1'
  )

  // Automatic fetching of new jobs (runs in the backend; this just shows and controls it)
  const [autoSync, setAutoSync] = useState(null)
  const [autoSyncSaving, setAutoSyncSaving] = useState(false)
  const lastAutoRunSeen = useRef(null)

  const [removedNotice, setRemovedNotice] = useState('')

  const handleJobRemoved = (message, jobId) => {
    setJobs((prev) => prev.filter((x) => x.id !== jobId))
    setAutofillJobId(null)
    setRemovedNotice(message)
    setTimeout(() => setRemovedNotice(''), 10000)
  }

  // The old per-company filter is gone; forget what it saved.
  useEffect(() => {
    localStorage.removeItem(LAST_SEARCH_KEY)
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

  // Fetch new jobs right now. The backend does the work (fetch + remove closed postings);
  // we just watch for it to finish. The backend also does this on a schedule when auto-fetch is on.
  const fetchBeforeRef = useRef('')
  const handleFetchNow = async () => {
    fetchBeforeRef.current = autoSync?.last_run || ''
    setFetchingNow(true)
    try {
      const res = await fetch(`${API_BASE}/auto-sync/run`, { method: 'POST' })
      if (!res.ok) setFetchingNow(false)
    } catch {
      setFetchingNow(false)
    }
  }

  // While a fetch runs, check on it every few seconds.
  useEffect(() => {
    if (!fetchingNow) return
    const started = Date.now()
    const timer = setInterval(async () => {
      try {
        const st = await (await fetch(`${API_BASE}/auto-sync`)).json()
        setAutoSync(st)
        const done = !st.busy && (st.last_run || '') !== fetchBeforeRef.current
        if (done || Date.now() - started > 15 * 60 * 1000) {
          lastAutoRunSeen.current = st.last_run || ''
          setFetchingNow(false)
          loadJobs()
        }
      } catch {
        /* keep polling */
      }
    }, 3000)
    return () => clearInterval(timer)
  }, [fetchingNow])

  const handleMatch = async (limit = null, companies = null) => {
    setMatching(true)
    setMatchError(null)

    pollRef.current = setInterval(loadJobs, POLL_INTERVAL_MS)

    try {
      const body = {}
      if (limit) body.limit = limit
      if (companies) body.companies = companies

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

  // ---- Keyword search ----
  const runSearch = async (q, keepNotice = false) => {
    const query = (q || '').trim()
    if (!query) return
    setSearchLoading(true)
    setSearchError('')
    if (!keepNotice) setSearchNotice('')
    try {
      const res = await fetch(`${API_BASE}/jobs/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query }),
      })
      const data = await res.json()
      if (!res.ok) {
        setSearchError(data.detail || 'Search failed.')
        return
      }
      const scores = {}
      data.results.forEach((r) => {
        scores[r.job_id] = r
      })
      setSearchScores(scores)
      setSearchQuery(query)
      setSearchInfo(data.semantic)
      setSearchCompany(data.company || null)

      // A company name we hadn't fetched yet: its jobs were just pulled in. Reload the list and
      // match them to your resume; the results re-rank live as the matches arrive.
      const fc = data.fetched_company
      if (fc) {
        if (fc.error) {
          setSearchNotice(`Found "${fc.token}" on Greenhouse but couldn't fetch it: ${fc.error}`)
        } else {
          setSearchNotice(`Fetched ${fc.added} new job(s) from ${fc.token}. Matching them to your resume...`)
          loadJobs()
          if (!matching) handleMatch(null, [fc.token])
        }
      }
    } catch {
      setSearchError('Search failed — is the backend running?')
    } finally {
      setSearchLoading(false)
    }
  }

  const clearSearch = () => {
    setSearchInput('')
    setSearchQuery('')
    setSearchScores({})
    setSearchInfo(null)
    setSearchError('')
    setSearchNotice('')
    setSearchCompany(null)
  }

  // While the semantic index is being built in the background, check on it and
  // refresh the results once it finishes.
  useEffect(() => {
    if (!searchQuery || !searchInfo?.indexing) return
    const timer = setInterval(async () => {
      try {
        const s = await (await fetch(`${API_BASE}/jobs/search/status`)).json()
        if (!s.running) {
          clearInterval(timer)
          runSearch(searchQuery, true)
        } else {
          setSearchInfo((p) => (p ? { ...p, indexed: s.indexed, total: s.total } : p))
        }
      } catch {
        /* keep polling */
      }
    }, 4000)
    return () => clearInterval(timer)
  }, [searchQuery, searchInfo?.indexing])

  // ---- Closed postings ----
  const handleCheckClosed = async () => {
    setClosedCheck({ loading: true })
    try {
      const res = await fetch(`${API_BASE}/jobs/closed/check`, { method: 'POST' })
      const data = await res.json()
      if (!res.ok) {
        setClosedCheck({ error: data.detail || 'Check failed.' })
        return
      }
      setClosedCheck(data)
    } catch {
      setClosedCheck({ error: 'Check failed — is the backend running?' })
    }
  }

  const handleRemoveClosed = async () => {
    const ids = closedCheck.closed.filter((c) => !c.tracked).map((c) => c.id)
    try {
      const res = await fetch(`${API_BASE}/jobs/closed/remove`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_ids: ids }),
      })
      const data = await res.json()
      if (!res.ok) {
        setClosedCheck({ error: data.detail || 'Remove failed.' })
        return
      }
      setClosedCheck({ done: `Removed ${data.removed} closed job(s).` })
      loadJobs()
    } catch {
      setClosedCheck({ error: 'Remove failed — is the backend running?' })
    }
  }

  // ---- Hide submitted ----
  const toggleHideSubmitted = (checked) => {
    setHideSubmitted(checked)
    localStorage.setItem(HIDE_SUBMITTED_KEY, checked ? '1' : '0')
  }

  // ---- Automatic job fetching ----
  const saveAutoSync = async (patch) => {
    const next = {
      enabled: autoSync?.enabled ?? false,
      interval_minutes: autoSync?.interval_minutes ?? 360,
      ...patch,
    }
    setAutoSyncSaving(true)
    try {
      const res = await fetch(`${API_BASE}/auto-sync`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(next),
      })
      if (res.ok) setAutoSync(await res.json())
    } catch {
      /* backend not reachable */
    } finally {
      setAutoSyncSaving(false)
    }
  }

  // Check the backend once a minute; when it has fetched, reload the job list.
  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const st = await (await fetch(`${API_BASE}/auto-sync`)).json()
        if (!alive) return
        setAutoSync(st)
        const seen = st.last_run || ''
        if (lastAutoRunSeen.current !== null && seen !== lastAutoRunSeen.current) loadJobs()
        lastAutoRunSeen.current = seen
      } catch {
        /* backend not reachable yet */
      }
    }
    tick()
    const timer = setInterval(tick, 60000)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [])

  // ---- Date posted, sort, and the visible list ----
  const DATE_WINDOWS = { '24h': 864e5, '7d': 7 * 864e5, '30d': 30 * 864e5 }
  const postedMs = (j) => {
    const t = Date.parse(j.posted_at)
    return Number.isNaN(t) ? null : t
  }
  const timeAgo = (ms) => {
    const days = Math.floor((Date.now() - ms) / 864e5)
    if (days < 1) return 'today'
    if (days === 1) return '1 day ago'
    if (days < 14) return `${days} days ago`
    if (days < 60) return `${Math.floor(days / 7)} weeks ago`
    return `${Math.floor(days / 30)} months ago`
  }
  // strong > worth applying > not matched yet > weak
  const tierRank = (j) =>
    j.match_recommendation === 'strong_match'
      ? 3
      : j.match_recommendation === 'worth_applying'
      ? 2
      : j.match_recommendation === 'weak_match'
      ? 0
      : 1
  const relOf = (j) => searchScores[j.id]?.relevance ?? 0

  const isSearching = searchQuery !== ''
  // A keyword search narrows the list to matching jobs; otherwise every synced job is listed.
  const poolJobs = isSearching ? jobs.filter((j) => searchScores[j.id]) : jobs
  const baseJobs = hideSubmitted ? poolJobs.filter((j) => !submittedJobIds.has(j.id)) : poolJobs
  const hiddenSubmittedCount = poolJobs.length - baseJobs.length
  const nowMs = Date.now()
  const dateFiltered =
    datePosted === 'any'
      ? baseJobs
      : baseJobs.filter((j) => {
          const t = postedMs(j)
          return t !== null && nowMs - t <= DATE_WINDOWS[datePosted]
        })
  const undatedCount = baseJobs.filter((j) => postedMs(j) === null).length

  const visibleJobs = [...dateFiltered].sort((a, b) => {
    if (sortBy === 'newest') return (postedMs(b) ?? 0) - (postedMs(a) ?? 0)
    const byResume = tierRank(b) - tierRank(a) || (b.match_percent || 0) - (a.match_percent || 0)
    if (sortBy === 'resume') return byResume || relOf(b) - relOf(a)
    if (!isSearching) return 0 // no keyword: keep the original order
    // keyword relevance in 5-point bands; inside a band, better resume matches come first
    return Math.floor(relOf(b) / 5) - Math.floor(relOf(a) / 5) || byResume || relOf(b) - relOf(a)
  })

  return (
    <div>
      <div style={{ background: '#f7f7f7', color: '#222', padding: 12, borderRadius: 8, marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', fontSize: 13 }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={!!autoSync?.enabled}
              disabled={autoSyncSaving || !autoSync}
              onChange={(e) => saveAutoSync({ enabled: e.target.checked })}
            />
            Fetch new jobs automatically every
          </label>
          <select
            value={autoSync?.interval_minutes ?? 360}
            disabled={autoSyncSaving || !autoSync}
            onChange={(e) => saveAutoSync({ interval_minutes: Number(e.target.value) })}
            style={{ padding: 2, background: '#fff', color: '#111' }}
          >
            <option value={60}>hour</option>
            <option value={180}>3 hours</option>
            <option value={360}>6 hours</option>
            <option value={720}>12 hours</option>
            <option value={1440}>24 hours</option>
          </select>
          <button onClick={handleFetchNow} disabled={fetchingNow || !!autoSync?.busy}>
            {fetchingNow || autoSync?.busy ? 'Fetching...' : 'Fetch now'}
          </button>
          <span style={{ color: '#666' }}>
            {autoSync?.last_run
              ? `Last fetch ${timeAgo(Date.parse(autoSync.last_run))}${
                  autoSync.last_added != null
                    ? ` (+${autoSync.last_added} new${
                        autoSync.last_removed ? `, ${autoSync.last_removed} closed removed` : ''
                      })`
                    : ''
                }`
              : autoSync?.enabled
              ? 'First fetch runs shortly'
              : 'Not fetched yet'}
          </span>
        </div>
        {autoSync?.last_error && (
          <p style={{ color: 'crimson', fontSize: 13, margin: '8px 0 0' }}>
            Last fetch problem: {autoSync.last_error}
          </p>
        )}
        <p style={{ fontSize: 12, color: '#666', margin: '8px 0 0' }}>
          Fetches the companies listed in your backend's .env (TARGET_COMPANIES). Postings that
          have been taken down are removed automatically after each fetch.
        </p>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <div>
          <h2 style={{ margin: 0 }}>
            Jobs ({visibleJobs.length}
            {visibleJobs.length !== jobs.length ? ` of ${jobs.length}` : ''})
          </h2>
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

      <div style={{ background: '#f7f7f7', color: '#222', padding: 12, borderRadius: 8, marginBottom: 16 }}>
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            style={{ flex: 1, padding: 8, background: '#fff', color: '#111', border: '1px solid #ccc', borderRadius: 4 }}
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') runSearch(searchInput)
            }}
            placeholder="Search by keyword or company name, e.g. machine learning engineer, or stripe"
          />
          <button onClick={() => runSearch(searchInput)} disabled={searchLoading || !searchInput.trim()}>
            {searchLoading ? 'Searching...' : 'Search'}
          </button>
          {isSearching && <button onClick={clearSearch}>Clear</button>}
        </div>
        {searchError && <p style={{ color: 'crimson', fontSize: 13, margin: '8px 0 0' }}>{searchError}</p>}
        {searchNotice && (
          <p style={{ color: '#0a7d2c', fontSize: 13, margin: '8px 0 0' }}>{searchNotice}</p>
        )}
        {isSearching && (
          <p style={{ fontSize: 13, margin: '8px 0 0' }}>
            {searchCompany
              ? `${Object.keys(searchScores).length} jobs at ${searchCompany}, best resume match first`
              : `${Object.keys(searchScores).length} jobs match “${searchQuery}” across all ${jobs.length} synced jobs`}
            {searchInfo && searchInfo.total > 0 && (
              <span style={{ color: '#666' }}>
                {' '}
                · semantic index {searchInfo.indexed}/{searchInfo.total}
                {searchInfo.indexing ? ' (building in the background, results refresh when done)' : ''}
              </span>
            )}
            {searchInfo?.error && <span style={{ color: 'crimson' }}> · {searchInfo.error}</span>}
          </p>
        )}

        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginTop: 12 }}>
          <span style={{ fontSize: 13, fontWeight: 'bold' }}>Date posted:</span>
          {[
            ['any', 'Any time'],
            ['24h', 'Past 24 hours'],
            ['7d', 'Past week'],
            ['30d', 'Past month'],
          ].map(([value, label]) => (
            <button
              key={value}
              onClick={() => setDatePosted(value)}
              style={{
                fontSize: 13,
                padding: '4px 10px',
                borderRadius: 14,
                cursor: 'pointer',
                border: '1px solid ' + (datePosted === value ? '#0a66c2' : '#bbb'),
                background: datePosted === value ? '#0a66c2' : '#fff',
                color: datePosted === value ? '#fff' : '#333',
              }}
            >
              {label}
            </button>
          ))}
          <span style={{ marginLeft: 'auto', fontSize: 13, fontWeight: 'bold' }}>Sort by:</span>
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            style={{ padding: 4, background: '#fff', color: '#111' }}
          >
            <option value="relevance">Keyword relevance</option>
            <option value="resume">Resume match</option>
            <option value="newest">Newest</option>
          </select>
        </div>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, marginTop: 10, cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={hideSubmitted}
            onChange={(e) => toggleHideSubmitted(e.target.checked)}
          />
          Hide jobs I've already submitted
          {hideSubmitted && hiddenSubmittedCount > 0 && (
            <span style={{ color: '#666' }}>({hiddenSubmittedCount} hidden)</span>
          )}
        </label>
        {datePosted !== 'any' && undatedCount > 0 && (
          <p style={{ fontSize: 12, color: '#666', margin: '8px 0 0' }}>
            {undatedCount} job(s) have no posting date and are hidden while a date filter is on.
          </p>
        )}

        <div style={{ marginTop: 12, borderTop: '1px solid #ddd', paddingTop: 10, fontSize: 13 }}>
          <button onClick={handleCheckClosed} disabled={closedCheck?.loading || jobs.length === 0}>
            {closedCheck?.loading ? 'Checking Greenhouse...' : 'Check for closed jobs'}
          </button>
          {closedCheck?.error && <span style={{ color: 'crimson', marginLeft: 8 }}>{closedCheck.error}</span>}
          {closedCheck?.done && <span style={{ marginLeft: 8 }}>{closedCheck.done}</span>}
          {closedCheck?.closed && (
            <div style={{ marginTop: 8 }}>
              <div>
                Checked {closedCheck.checked} jobs: {closedCheck.closed.length} no longer posted.
              </div>
              {closedCheck.closed.length > 0 && (
                <>
                  <ul style={{ margin: '6px 0', padding: '0 0 0 18px', maxHeight: 180, overflowY: 'auto' }}>
                    {closedCheck.closed.map((c) => (
                      <li key={c.id}>
                        {c.title} · {c.company}
                        {c.tracked ? ' (kept: tracked in Applications)' : ''}
                      </li>
                    ))}
                  </ul>
                  <button
                    onClick={handleRemoveClosed}
                    disabled={closedCheck.closed.every((c) => c.tracked)}
                  >
                    Remove {closedCheck.closed.filter((c) => !c.tracked).length} closed job(s)
                  </button>
                  <button onClick={() => setClosedCheck(null)} style={{ marginLeft: 8 }}>
                    Cancel
                  </button>
                </>
              )}
              {closedCheck.unverified?.length > 0 && (
                <div style={{ color: '#666', marginTop: 6 }}>
                  Couldn't verify: {closedCheck.unverified.map((u) => `${u.company} (${u.reason})`).join(', ')}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {removedNotice && (
        <p style={{ color: '#b8860b', fontSize: 14 }}>{removedNotice}</p>
      )}

      {visibleJobs.length === 0 ? (
        <p>
          {isSearching || datePosted !== 'any' || hideSubmitted
            ? 'No jobs match your keyword and filters.'
            : 'No jobs yet — run a search above to pull jobs from Greenhouse.'}
        </p>
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
                  <span style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    {isSearching && searchScores[j.id] && (
                      <span style={{ fontSize: 12, color: '#666' }}>
                        Relevance {Math.round(searchScores[j.id].relevance)}
                      </span>
                    )}
                    {j.match_percent > 0 && !(isSearching && j.match_recommendation === 'weak_match') && (
                      <span style={{ fontSize: 13, color: rec?.color || '#333' }}>
                        {rec ? `${rec.label} · ` : ''}{j.match_percent}%
                      </span>
                    )}
                  </span>
                </div>
                <div style={{ color: '#666', fontSize: 14 }}>
                  {j.company} {j.location && `· ${j.location}`}
                  {postedMs(j) !== null && ` · Posted ${timeAgo(postedMs(j))}`}
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
                  <button
                    onClick={() => setAutofillJobId(autofillJobId === j.id ? null : j.id)}
                    style={{ fontSize: 13 }}
                  >
                    {autofillJobId === j.id ? 'Hide auto-fill' : 'Auto-fill'}
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

                {autofillJobId === j.id && (
                  <AutofillPanel
                    jobId={j.id}
                    apiBase={API_BASE}
                    resumeText={editedResume[j.id] ?? j.tailored_resume}
                    coverLetterText={editedCoverLetter[j.id] ?? j.tailored_cover_letter}
                    autoStart
                    onClose={() => setAutofillJobId(null)}
                    onJobRemoved={handleJobRemoved}
                    onGenerated={loadJobs}
                    onSubmitted={onApplicationChange}
                    isSubmitted={isSubmitted}
                  />
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