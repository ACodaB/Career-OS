import { useState } from 'react'
import ProfilePage from './ProfilePage'
import JobsPage from './JobsPage'
import './App.css'

function App() {
  const [tab, setTab] = useState('jobs')

  return (
    <div style={{ fontFamily: 'sans-serif', maxWidth: 800, margin: '40px auto', padding: '0 16px' }}>
      <h1>Career OS</h1>
      <nav style={{ display: 'flex', gap: 12, marginBottom: 24, borderBottom: '1px solid #ddd', paddingBottom: 12 }}>
        <button onClick={() => setTab('jobs')} style={{ fontWeight: tab === 'jobs' ? 'bold' : 'normal' }}>
          Jobs
        </button>
        <button onClick={() => setTab('profile')} style={{ fontWeight: tab === 'profile' ? 'bold' : 'normal' }}>
          Profile
        </button>
      </nav>
      {tab === 'jobs' ? <JobsPage /> : <ProfilePage />}
    </div>
  )
}

export default App
