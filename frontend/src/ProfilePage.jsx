import { useState, useEffect } from 'react'

const API_BASE = 'http://localhost:8000'

const userProfile = {
  name: 'Arsh Bajaj',
  email: 'arsh29bajaj@gmail.com',
  phone: '+91-8882856610',
  work_authorization: 'India, United States',
  education: 'B.Tech in Computer Science and Engineering, University School of Information, Communication & Technology (USICT), GGSIPU (Expected May 2028 | CGPA: 8.97/10)',
  skills: 'Python, C/C++, SQL, JavaScript, Java, HTML, CSS, Scikit-learn, Pandas, NumPy, Matplotlib, OpenCV, Hugging Face Transformers, PaddleOCR, Ultralytics YOLO, Gemini API, Git, GitHub, VS Code, Streamlit, Optuna, FastAPI, Langchain, Machine Learning, Deep Learning, NLP, Transformers, LLMs, Computer Vision, OCR',
  resume_text: `ARSH BAJAJ
Delhi, India | +91-8882856610 | arsh29bajaj@gmail.com
https://github.com/ACodaB | https://leetcode.com/u/arsh29bajaj/ | https://www.linkedin.com/in/arsh-bajaj
Experience
AI Intern – Decimal Technologies Pvt. Ltd. Jul 2026 – Aug 2026
• Automated Intelligent Document Processing: Engineered end-to-end vision OCR pipelines integrating
YOLOv8 text detection with PaddleOCR, reducing manual document data entry time by 65% while
boosting extraction accuracy to 94%.
• Scaled High-Throughput Inference APIs: Deployed containerized AI models using FastAPI and Docker,
improving API throughput by 40% and maintaining sub-200ms response latencies under concurrent work-
loads.
• Optimized Enterprise Knowledge Retrieval (RAG): Architected RAG workflows utilizing custom chunking,
vector indexing, and Google’s OKF structure, enhancing search retrieval precision by 35% over baseline
keyword search.
ML Content Intern – SmaranAI Oct 2025 – Nov 2025
• Authoring Hands-On Technical Resources: Designed 20+ practical Machine Learning assignments and
real-world project modules covering supervised learning, NLP, and model evaluation techniques.
• Accelerating Concept Comprehension: Developed structured learning pathways that improved learner
task completion speed by 30% and increased course retention rates among beginner and intermediate students.
Skills
Languages Python, C/C++, SQL, JavaScript, Java, HTML, CSS
ML & AI Scikit-learn, Pandas, NumPy, Matplotlib, OpenCV, Scikit- learn, Hugging Face Transformers,
PaddleOCR, Ultralytics YOLO, Gemini API, TensorFlow, PyTorch
Tools Git, GitHub, VS Code, Streamlit, Optuna, FASTAPI Google Cloud, Kubernetes, Docker, MS
Azure, Langchain, Langgraph, Django, Flask
Concepts Machine Learning, Deep Learning, NLP, Transformers, LLMs, Tokenization, Word Embeddings,
Attention Mechanism, ANN, CNN, RNN, LSTM, GRU, OCR, Computer Vision, Feature Engi-
neering, Hyperparameter Optimization, Model Deployment
Projects
AutoML Pipeline System AI/ML Developer
• Automated Hyperparameter Tuning: Architected an automated ML pipeline integrating automated fea-
ture engineering and Optuna optimization, cutting manual experimentation effort by 45% across tabular
datasets.
• Streamlined Workflow & Deployment: Developed reproducible experiment tracking and a Streamlit dash-
board, reducing model prototyping time from days to hours.
• Tech Stack: Python, Scikit-learn, Optuna, Pandas, NumPy, Streamlit
Tech Stack: Python, Scikit-learn, Pandas, NumPy, Optuna, Streamlit
GitHub: github.com/ACodaB/Automl-project
SkillForge – AI-powered Team & Skill Matching Platform AI/ML Developer
• Algorithmic Team Formation: Built an AI-driven compatibility scoring engine using candidate skill embed-
dings and semantic preference matching, reducing manual team pairing time by 50%.
• Scalable API Integration: Implemented RESTful backend services and multi-user coordination features eval-
uated across 20+ live test users with 90%+ matching satisfaction.
• Tech Stack: Python, NLP, Scikit-learn, REST APIs, Node.js
Tech Stack: Python, NLP, Scikit-learn, Pandas, REST API, Node.js
GitHub: github.com/AniAgg-5964/Skill-Forge
Smart India Hackathon (PS-25032) AI/ML Developer
• Tourism Review Analytics Pipeline: Processed and classified 500+ unstructured traveler reviews using NLP
sentiment techniques, improving recommendation relevance by 35% for eco-tourism itineraries.
• Tech Stack: Python, NLP, Scikit-learn, Text Preprocessing
Tech Stack: Python, NLP, Scikit-learn, Pandas
GitHub: github.com/RacTCode/Jharkhand-Tourism
Education
B.Tech in Computer Science and Engineering Expected May 2028
University School of Information, Communication & Technology (USICT), GGSIPU
CGPA: 8.97/10 (till 4th semester)
Relevant Coursework: Data Structures & Algorithms, Object-Oriented Programming, DBMS, Machine Learning and
Artificial Intelligence, Software Engineering, System Design, NLP
Senior Secondary March 2024
Class XII (96.4%) | 2nd rank in non-medical, school topper | Member of Prefectorial Board
Class X (89%)
Achievements
• Solved 120+ problems focusing on DSA on leetcode
• HackCrux V2 – Hackathon Finalist
Developed EchoLoop, an NLP-based digital reflection platform for emotional pattern analysis.
• Vedathon Ideathon – Top 10 Finalist among 2000+ participants
Presented SkillForge, an AI-powered team and skill matching platform.
Certifications
• Building with the Claude API by Anthropic
• Certificate of Completion: AI Fluency Framework & Foundations by Anthropic
• Certificate of completion: Claude 101 by Anthropic
• Claude Code in Action by Anthropic
• Goldman Sachs’s Software Engineering Job Simulation
• Machine Learning with Python by Acmegrade under IIT Bombay`,
}

export default function ProfilePage() {
  const [profile, setProfile] = useState(userProfile)
  const [status, setStatus] = useState('')

  useEffect(() => {
    fetch(`${API_BASE}/profile`)
      .then((r) => r.json())
      .then((data) => {
        if (data) setProfile({ ...userProfile, ...data })
      })
      .catch(() => {})
  }, [])

  const handleChange = (field) => (e) => {
    setProfile({ ...profile, [field]: e.target.value })
  }

  const handleSave = async (e) => {
    e.preventDefault()
    setStatus('Saving...')
    try {
      const res = await fetch(`${API_BASE}/profile`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(profile),
      })
      if (!res.ok) throw new Error('Save failed')
      setStatus('Saved ✓')
      setTimeout(() => setStatus(''), 2000)
    } catch {
      setStatus('Save failed — is the backend running?')
    }
  }

  const inputStyle = { width: '100%', padding: 8, marginTop: 4, marginBottom: 16, boxSizing: 'border-box' }
  const labelStyle = { fontWeight: 'bold', fontSize: 14 }

  return (
    <div>
      <p style={{ color: '#666' }}>
        This is stored locally and used to tailor resumes/cover letters and score job matches later.
        Nothing here is sent anywhere except to the LLM when you explicitly trigger those actions.
      </p>
      <form onSubmit={handleSave}>
        <label style={labelStyle}>Name</label>
        <input style={inputStyle} value={profile.name} onChange={handleChange('name')} required />

        <label style={labelStyle}>Email</label>
        <input style={inputStyle} type="email" value={profile.email} onChange={handleChange('email')} required />

        <label style={labelStyle}>Phone</label>
        <input style={inputStyle} value={profile.phone} onChange={handleChange('phone')} />

        <label style={labelStyle}>Work Authorization</label>
        <input
          style={inputStyle}
          placeholder="e.g. US Citizen, requires H1-B sponsorship, etc."
          value={profile.work_authorization}
          onChange={handleChange('work_authorization')}
        />

        <label style={labelStyle}>Education</label>
        <textarea style={{ ...inputStyle, height: 80 }} value={profile.education} onChange={handleChange('education')} />

        <label style={labelStyle}>Skills (comma-separated)</label>
        <input
          style={inputStyle}
          placeholder="Python, React, PostgreSQL, ..."
          value={profile.skills}
          onChange={handleChange('skills')}
        />

        <label style={labelStyle}>Resume (paste full text)</label>
        <textarea
          style={{ ...inputStyle, height: 240, fontFamily: 'monospace', fontSize: 13 }}
          value={profile.resume_text}
          onChange={handleChange('resume_text')}
        />

        <button type="submit">Save Profile</button>
        {status && <span style={{ marginLeft: 12 }}>{status}</span>}
      </form>
    </div>
  )
}