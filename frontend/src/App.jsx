import { useState, useEffect } from 'react'
import ProfilePage from './ProfilePage'
import JobsPage from './JobsPage'
import ApplicationsPage from './ApplicationsPage'
import './App.css'

const API_BASE = 'http://localhost:8000'

function App() {
  const [tab, setTab] = useState('jobs')
  const [applications, setApplications] = useState([])

  const loadApplications = () => {
    fetch(`${API_BASE}/applications`)
      .then((r) => r.json())
      .then(setApplications)
      .catch(() => {})
  }

  useEffect(() => {
    loadApplications()
  }, [])

  const submittedJobIds = new Set(applications.map((a) => a.job_id))

  return (
    <div style={{ fontFamily: 'sans-serif', maxWidth: 800, margin: '40px auto', padding: '0 16px' }}>
      <h1>Career OS</h1>
      <nav style={{ display: 'flex', gap: 12, marginBottom: 24, borderBottom: '1px solid #ddd', paddingBottom: 12 }}>
        <button onClick={() => setTab('jobs')} style={{ fontWeight: tab === 'jobs' ? 'bold' : 'normal' }}>
          Jobs
        </button>
        <button onClick={() => setTab('applications')} style={{ fontWeight: tab === 'applications' ? 'bold' : 'normal' }}>
          Applications
        </button>
        <button onClick={() => setTab('profile')} style={{ fontWeight: tab === 'profile' ? 'bold' : 'normal' }}>
          Profile
        </button>
      </nav>
      {tab === 'jobs' && (
        <JobsPage submittedJobIds={submittedJobIds} onApplicationChange={loadApplications} />
      )}
      {tab === 'applications' && (
        <ApplicationsPage applications={applications} setApplications={setApplications} />
      )}
      {tab === 'profile' && <ProfilePage />}
    </div>
  )
}

export default App