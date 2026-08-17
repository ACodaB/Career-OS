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
GitHub: https://github.com/ACodaB | LeetCode: https://leetcode.com/u/arsh29bajaj/ | LinkedIn: https://www.linkedin.com/in/arsh-bajaj

EXPERIENCE:
AI Intern - Decimal Technologies Pvt. Ltd. (Jul 2026 - Aug 2026)
- Building intelligent document processing pipelines using Computer Vision and OCR techniques for automated information extraction.
- Developing OCR workflows by integrating YOLO-based text detection with PaddleOCR for structured text extraction and post-processing.
- Integrating AI models using FastAPI to develop scalable inference APIs for deployment.
- Working with modern NLP concepts including tokenization, word embeddings, ANNs, RNNs, LSTMs, GRUs, and Transformer architectures.
- Studying and implementing attention mechanisms, positional encoding, encoder-decoder architectures, and concepts from the Attention Is All You Need paper.
- Contributing to experimentation, evaluation, debugging, and optimization of AI models for production-oriented applications.

ML Content Intern - SmaranAI (Oct 2025 - Nov 2025)
- Created 20+ hands-on Machine Learning assignments covering supervised learning, NLP, feature engineering, and model evaluation.
- Developed structured educational resources and technical documentation for beginner and intermediate Machine Learning learners.
- Designed practical exercises and explanatory content to simplify complex ML concepts and improve learner engagement.
- Authored study material that improved learning efficiency by approximately 30% through well-structured examples and assignments.

SKILLS:
- Languages: Python, C/C++, SQL, JavaScript, Java, HTML, CSS
- ML & AI: Scikit-learn, Pandas, NumPy, Matplotlib, OpenCV, Hugging Face Transformers, PaddleOCR, Ultralytics YOLO, Gemini API, TensorFlow, PyTorch
- Tools: Git, GitHub, VS Code, Streamlit, Optuna, FASTAPI, Google Cloud, Kubernetes, Docker, MS Azure, Langchain, Langgraph, Django, Flask
- Concepts: Machine Learning, Deep Learning, NLP, Transformers, LLMs, Tokenization, Word Embeddings, Attention Mechanism, ANN, CNN, RNN, LSTM, GRU, OCR, Computer Vision, Feature Engineering, Hyperparameter Optimization, Model Deployment

PROJECTS:
AutoML Pipeline System | AI/ML Developer
- Built a modular AutoML pipeline automating preprocessing, feature engineering, feature selection, and model training.
- Reduced manual experimentation effort by 40-50% through workflow automation and Optuna-based hyperparameter tuning.
- Developed experiment tracking and deployment-ready prediction modules for reproducible ML workflows.
- Tech Stack: Python, Scikit-learn, Pandas, NumPy, Optuna, Streamlit
- GitHub: github.com/ACodaB/Automl-project

SkillForge - AI-powered Team & Skill Matching Platform | AI/ML Developer
- Designed an AI-powered compatibility scoring system for intelligent team formation using skill and preference analysis.
- Developed recommendation workflows tested with 20+ users, reducing manual team pairing time by 50%.
- Implemented backend APIs and collaborative workflow features for scalable multi-user coordination.
- Tech Stack: Python, NLP, Scikit-learn, Pandas, REST API, Node.js
- GitHub: github.com/AniAgg-5964/Skill-Forge

Smart India Hackathon (PS-25032) | AI/ML Developer
- Processed and analyzed 500+ tourist review entries using NLP preprocessing and sentiment classification techniques.
- Developed sentiment-based recommendation workflows for tourism itinerary optimization.
- Improved chatbot recommendations for promoting cultural and eco-tourism in Jharkhand.
- Tech Stack: Python, NLP, Scikit-learn, Pandas
- GitHub: github.com/RacTCode/Jharkhand-Tourism

EDUCATION:
- B.Tech in Computer Science and Engineering, USICT, GGSIPU (Expected May 2028 | CGPA: 8.97/10 till 4th semester)
- Senior Secondary (Class XII) - 96.4% | Class X - 89%

ACHIEVEMENTS & CERTIFICATIONS:
- HackCrux V2 - Hackathon Finalist (EchoLoop)
- Vedathon Ideathon - Top 10 Finalist among 2000+ participants (SkillForge)
- Anthropic Certifications: Building with Claude API, AI Fluency Framework & Foundations, Claude 101, Claude Code in Action
- Goldman Sachs Software Engineering Job Simulation
- Machine Learning with Python by Acmegrade under IIT Bombay`,
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