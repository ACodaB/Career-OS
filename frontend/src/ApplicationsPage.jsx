const API_BASE = 'http://localhost:8000'
const STATUSES = ['Submitted', 'OA Pending', 'Interview', 'Rejected']

export default function ApplicationsPage({ applications, setApplications }) {
  const handleStatusChange = async (applicationId, newStatus) => {
    const previous = applications
    setApplications((prev) =>
      prev.map((a) => (a.id === applicationId ? { ...a, status: newStatus } : a))
    )
    try {
      const res = await fetch(`${API_BASE}/applications/${applicationId}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus }),
      })
      if (!res.ok) {
        setApplications(previous)
      }
    } catch {
      setApplications(previous)
    }
  }

  const handleUndo = async (applicationId) => {
    const confirmed = window.confirm(
      'Remove this application from your tracker? This permanently deletes the saved resume/cover letter snapshot and cannot be undone.'
    )
    if (!confirmed) return

    const previous = applications
    setApplications((prev) => prev.filter((a) => a.id !== applicationId))
    try {
      const res = await fetch(`${API_BASE}/applications/${applicationId}`, {
        method: 'DELETE',
      })
      if (!res.ok) {
        setApplications(previous)
      }
    } catch {
      setApplications(previous)
    }
  }

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Applications ({applications.length})</h2>
      {applications.length === 0 ? (
        <p>No applications tracked yet — generate and submit one from the Jobs tab.</p>
      ) : (
        <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start', overflowX: 'auto' }}>
          {STATUSES.map((status) => {
            const columnApps = applications.filter((a) => a.status === status)
            return (
              <div key={status} style={{ flex: '1 0 220px', minWidth: 220 }}>
                <h3
                  style={{
                    fontSize: 14,
                    borderBottom: '2px solid #ddd',
                    paddingBottom: 6,
                    margin: 0,
                  }}
                >
                  {status} ({columnApps.length})
                </h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
                  {columnApps.map((app) => (
                    <div
                      key={app.id}
                      style={{ border: '1px solid #ddd', borderRadius: 6, padding: 8, fontSize: 13 }}
                    >
                      <strong>{app.title}</strong>
                      <div style={{ color: '#666' }}>{app.company}</div>
                      <div style={{ color: '#999', fontSize: 11, marginTop: 4 }}>
                        Submitted {new Date(app.submitted_at).toLocaleDateString()}
                      </div>
                      <select
                        value={app.status}
                        onChange={(e) => handleStatusChange(app.id, e.target.value)}
                        style={{ marginTop: 6, width: '100%', fontSize: 12 }}
                      >
                        {STATUSES.map((s) => (
                          <option key={s} value={s}>
                            {s}
                          </option>
                        ))}
                      </select>
                      <button
                        onClick={() => handleUndo(app.id)}
                        style={{
                          marginTop: 6,
                          width: '100%',
                          fontSize: 12,
                          background: 'none',
                          border: '1px solid #ddd',
                          borderRadius: 4,
                          color: '#b00',
                          cursor: 'pointer',
                          padding: '4px 0',
                        }}
                      >
                        Undo (remove from tracker)
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}