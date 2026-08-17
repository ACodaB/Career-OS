# Career OS — Product Requirements Document

**Version:** 1.0
**Date:** August 12, 2026
**Author:** Product/Engineering Draft
**Status:** Draft for Review

---

## 1. Overview

### 1.1 Product Summary
Career OS is a personal AI-powered system that automates the repetitive parts of job searching and applying, while keeping the user in control of every important decision and final submission. It runs the full loop: **find → analyze → match → prioritize → prepare → auto-fill → review → submit → track → interview-prep.**

### 1.2 Problem Statement
Job searching at scale is repetitive and time-consuming: manually scanning boards, rewriting resumes per role, retyping the same information into dozens of application forms, and tracking status across scattered emails and spreadsheets. This kills momentum and causes qualified candidates to apply to fewer, less-targeted roles.

### 1.3 Goal
Make the user's job search dramatically faster by finding the right jobs, preparing a tailored application package for each one, automating repetitive form-filling, learning from the user's corrections over time, and providing realistic interview preparation — without ever submitting anything without explicit user confirmation.

### 1.4 Target User
A single user (personal-use tool, not multi-tenant SaaS) — technical/professional job seeker applying to multiple roles concurrently and wanting to preserve application quality at volume.

---

## 2. Goals & Non-Goals

### 2.1 Goals
- Reduce time-to-apply per job from ~30–45 minutes (manual) to a few minutes of review.
- Ensure every application is tailored, never generic or fabricated.
- Keep the user as the final approver of every submission.
- Improve personalization over time via stored user corrections, not model retraining.
- Provide interview prep that is specific to the job, company, and resume — not generic question banks.

### 2.2 Non-Goals (explicitly out of scope for v1)
- Career analytics / skill-gap analytics platforms
- Recruiter CRM or networking management
- Salary intelligence platform
- Generic career coaching
- Large-scale, long-horizon career planning
- Complex follow-up/reminder management beyond basic status tracking
- Multi-user / team support

---

## 3. Recommended Tech Stack

Chosen to match your current skill set (Python, React/HTML-JS, SQL + NoSQL + Vector DB, light LLM API experience, Playwright) so you can build this without adopting an entirely new stack.

| Layer | Technology | Rationale |
|---|---|---|
| Backend / API | **Python + FastAPI** | You know Python; FastAPI gives async support (important for scraping + LLM calls + browser automation running concurrently), automatic OpenAPI docs, and pairs well with Pydantic for strict data schemas (job records, application records). |
| Task orchestration | **Celery + Redis**, or simpler: **APScheduler** for v1 | Job search runs on schedules/triggers; application prep and auto-fill are long-running async tasks that shouldn't block the API. Start with APScheduler for simplicity, move to Celery if volume grows. |
| Relational DB | **PostgreSQL** | System of record for user profile, job postings, applications, statuses, preferences. Relational integrity matters here (applications reference jobs reference companies). |
| Vector DB | **Chroma** (local/self-hosted) or **Pinecone** (managed) | Embeddings for resume bullets, job descriptions, and past application answers — powers semantic matching (Module 2) and retrieval for resume tailoring (Module 3). Chroma is simplest to self-host for a personal tool; Pinecone if you want managed infra. |
| Document/unstructured store | **MongoDB** (optional) | Useful for storing raw scraped job postings pre-normalization, and flexible fields like company research briefs and interview transcripts, where schema varies. |
| LLM layer | **Anthropic API (Claude) via Python SDK** | Powers job analysis/matching, resume tailoring, cover letter generation, company research synthesis, and the interview agent. Use structured JSON outputs (Pydantic-validated) for anything downstream (match scores, field mappings). |
| Job sourcing | **Job board APIs where available (e.g. LinkedIn, Greenhouse, Lever, Indeed) + Playwright for scraping where no API exists** | Prefer official/structured APIs first; fall back to scraping only where necessary and permitted by ToS. |
| Application automation | **Playwright (Python)** | You already know it — ideal for the Application Agent (Module 4): identifying form fields, filling known data, and stopping for user review before submission. |
| Frontend | **React + Vite, TypeScript optional** | Dashboard, review screens, application board, interview UI. You know React; start with plain component state, add a lightweight state manager (Zustand or React Query for server state) only if needed. |
| Auth / secrets | **Local single-user auth (simple session or none) + a secrets manager (.env / OS keychain)** | Since this is single-user, avoid building multi-tenant auth complexity — but keep API keys and PII out of source control. |
| Deployment | **Local-first (Docker Compose: FastAPI + Postgres + Chroma + Redis)**, optionally deployed to a small VPS later | Personal tool — no need for cloud-native complexity in v1. |

**Note:** This stack is a recommendation, not a requirement — every module below is described in terms of behavior/data flow so it stays portable if you change tools later.

---

## 4. System Architecture (High-Level)

```
┌────────────┐     ┌──────────────┐     ┌───────────────────┐
│  React UI  │◄───►│  FastAPI     │◄───►│ PostgreSQL         │
│ (Dashboard,│     │  Backend     │     │ (jobs, apps, users)│
│  Review,   │     │              │     └───────────────────┘
│  Interview)│     │              │     ┌───────────────────┐
└────────────┘     │              │◄───►│ Vector DB (Chroma) │
                    │              │     │ (embeddings)       │
                    │              │     └───────────────────┘
                    │              │     ┌───────────────────┐
                    │              │◄───►│ Claude API (LLM)   │
                    │              │     └───────────────────┘
                    │              │     ┌───────────────────┐
                    │              │◄───►│ Playwright Workers │
                    │              │     │ (auto-fill, scrape)│
                    │              │     └───────────────────┘
                    └──────────────┘
                    Task Scheduler (APScheduler/Celery)
```

---

## 5. Functional Requirements by Module

### Module 1 — Job Search
**FR1.1** User can configure search preferences: roles, locations, experience level, employment type, remote/onsite/hybrid, other filters.
**FR1.2** User can trigger a manual search or enable scheduled automatic searches.
**FR1.3** System collects jobs from configured sources (APIs first, scraping fallback), cleans, normalizes, and deduplicates them before storage.
**FR1.4** Each stored job record includes: company, role, location, job description, salary (if available), application URL, posting date, source.

### Module 2 — Job Analysis & Matching
**FR2.1** System compares each job against the user's profile/resume (via embeddings + LLM reasoning) with no user action required by default.
**FR2.2** System outputs: match percentage, priority rating, strong matches, partial matches, missing/weak requirements, and a recommendation (Apply / Consider / Skip).
**FR2.3** User can act on each analyzed job: Skip, Save, or Apply.

### Module 3 — Application Preparation
**FR3.1** On "Apply," system generates a tailored resume by reprioritizing existing experience, skills, and projects — **never fabricating** experience, skills, education, or achievements. System also shows the skills which are not included in resume and required for the job role to which user can click and choose what more of them to be included on the resume
**FR3.2** System generates a personalized cover letter using job + company + user profile + relevant experience.
**FR3.3** System generates a company research brief (what they do, products, industry, relevant tech, role/team context, recent relevant news).
**FR3.4** Output is an "Application Package": tailored resume, cover letter, company brief, job summary, application info — all held for review, not submitted.

### Module 4 — Application Agent (Auto-Fill)
**FR4.1** On first use, user provides/confirms recurring information (contact info, education, work authorization, relocation, sponsorship, etc.).
**FR4.2** For each new application, system identifies form fields (via Playwright), matches them to known user data, auto-fills known fields, and generates draft answers for open-ended questions.
**FR4.3** System flags uncertain, high-stakes, or unmapped fields (e.g., sponsorship, salary expectation, custom essay questions) for mandatory user review.
**FR4.4** System **always stops before submission** and hands off to Module 6 (Review & Submission) — never submits autonomously.

### Module 5 — Application Learning
**FR5.1** When the user corrects an AI suggestion (e.g., relocation answer, which experience bullet to use), the system stores this as a persistent preference.
**FR5.2** Stored preferences are applied to future applications automatically.
**FR5.3** Learning is implemented via a structured, queryable preference store — not via fine-tuning or retraining the LLM.

### Module 6 — Application Review & Submission
**FR6.1** User sees a review screen per application: resume, cover letter, application answers, and a list of flagged potential issues.
**FR6.2** User can Edit any field or Confirm & Submit.
**FR6.3** On confirmation, system submits automatically where technically supported; where auto-submission isn't feasible/appropriate, system opens the prepared application for the user to submit manually.
**FR6.4** On submission, system creates a permanent application record (company, role, date, resume used, cover letter used, answers, status = Submitted).

### Module 7 — Application History
**FR7.1** Applications are shown in a **side-by-side status board** (columns, not a single list): Submitted, OA Pending, Interview Pending, Rejected, etc.
**FR7.2** Each record retains: company, role, JD, application URL, date applied, resume used, cover letter used, answers, current status, notes.
**FR7.3** Status transitions are supported: Submitted → OA Pending → Interview Pending → Interview Scheduled → Interview Completed → Offer, or Submitted → Rejected (and other realistic paths).

### Module 8 — Interview Status
**FR8.1** From any application, user can mark it as "Interview Pending" or "Interview Scheduled," optionally with date/time.
**FR8.2** Status change surfaces the application in the Interviews section of the daily dashboard.

### Module 9 — Company Research
**FR9.1** User can trigger "Research Company" from a job, application, or interview context.
**FR9.2** Output: company brief covering what they do, products, industry, relevant technology, role/team context, and other relevant current information.
**FR9.3** Company brief is reused by both Module 3 (cover letter) and Module 10 (interview prep) — not a separate standalone system.

### Module 10 — Interview Preparation
**FR10.1** Interview agent combines job description, resume, company research, and interview type to generate a personalized session; it must behave like an experienced HR interviewer + technical hiring manager, not a generic question generator.
**FR10.2** **Behavioral interview:** questions grounded in the user's actual experience; challenges vague answers with follow-ups.
**FR10.3** **Technical interview:** questions grounded primarily in actual job requirements; evaluates answers and asks follow-ups.
**FR10.4** **Resume-based interview:** deep-dives into specific resume claims (why this approach, failure cases, evaluation method, what you'd change today) to test genuine understanding.
**FR10.5** Output includes: question sets by category, answer evaluations, identified weak areas, topics to revise, and a mock interview transcript.

### Module 11 — Daily Workflow (Dashboard)
**FR11.1** Dashboard has three sections: Review, Applications, Interviews.
**FR11.2** **Review** shows prepared-but-unapproved applications with readiness indicators (resume/cover letter/application status).
**FR11.3** **Applications** shows summary counts (Submitted, OA Pending, Interview, Rejected) with a link to the full status board.
**FR11.4** **Interviews** shows applications flagged for interview prep with quick actions: Research Company, Prepare for Interview.

---

## 6. Core Data Model (Draft)

- **User Profile**: contact info, work authorization, education, resume(s), skills, preferences, recurring application answers.
- **Job**: company, role, location, description, salary, URL, posting date, source, normalized skill tags.
- **Match**: job_id, user_id, match %, strengths, gaps, recommendation.
- **Application**: job_id, resume_version, cover_letter, answers[], status, dates, notes.
- **Preference**: key, value, source (learned from correction), confidence/last-updated.
- **CompanyBrief**: company_id, summary, products, industry, tech stack, recency timestamp.
- **InterviewSession**: application_id, type (behavioral/technical/resume-based), transcript, evaluation, weak areas.

---

## 7. Non-Functional Requirements

- **User control:** No application is ever submitted without explicit confirmation. This is a hard constraint, not a preference.
- **No fabrication:** Resume/cover letter generation must never invent experience, skills, education, or achievements — only reorganize/rephrase real user-provided content.
- **Personalization without retraining:** All learning happens via structured preference storage, not model fine-tuning.
- **Auditability:** Every application record must retain exactly what was submitted (resume version, cover letter, answers) for future reference.
- **Resilience to source changes:** Scraping/automation logic (job boards, ATS forms) will break as sites change — design for graceful degradation and easy field-mapping updates, not a fully static automation.
- **Privacy:** All personal data (resume, application answers, contact info) stored locally/self-hosted by default given single-user, sensitive-data nature of the product.
- **Latency:** Job analysis/matching and application prep should run asynchronously; user shouldn't block on LLM/scraping calls in the UI thread.

---

## 8. Risks & Open Questions

| Risk | Notes |
|---|---|
| ATS/job-board ToS and anti-bot measures | Playwright-based auto-fill and scraping may violate some platforms' terms of service; needs a per-site policy (some sites: auto-fill + auto-submit; others: prepare only, manual submit). |
| LLM hallucination in resume tailoring | Needs strict prompting + validation step (e.g., diff-check tailored resume against source resume to catch invented content) given your "used LLM APIs a little" experience — this is the highest-risk module to get right. |
| Job source coverage | Which job boards/ATSs are must-have for v1 (LinkedIn, Greenhouse, Lever, Indeed, company career pages)? |
| Field-mapping brittleness | Application forms vary widely; how much manual mapping work is acceptable per new ATS before the "learning" system pays off? |
| Scope of v1 | Suggest building Modules 1–3 and 6–7 first (search → match → prepare → review/submit → track) before Module 4 (auto-fill) and Module 10 (interview agent), since auto-fill and interview simulation are the most technically complex and highest-risk pieces. |

---

## 9. Suggested Build Phasing

1. **Phase 1 — Foundation:** User profile + resume storage, job search/collection/normalization (Module 1), basic dashboard shell.
2. **Phase 2 — Intelligence:** Job analysis & matching (Module 2) with embeddings + LLM scoring.
3. **Phase 3 — Application Prep:** Resume tailoring, cover letter, company research (Modules 3, 9).
4. **Phase 4 — Review & Tracking:** Review/submission flow and application history board (Modules 6, 7) — can initially require fully manual submission.
5. **Phase 5 — Automation:** Application Agent auto-fill via Playwright (Module 4), Application Learning (Module 5).
6. **Phase 6 — Interview Prep:** Interview status (Module 8) and the interview agent (Module 10).
7. **Phase 7 — Polish:** Full daily workflow dashboard (Module 11), preference tuning, reliability hardening.

---

## 10. Success Metrics

- Time from "job found" to "application submitted" (target: under 5 minutes of active user time per application).
- % of applications requiring zero manual field correction after Module 5 learning matures.
- Match-score accuracy (user agreement rate with system's Apply/Skip recommendation over time).
- Interview prep usage rate before scheduled interviews.
- Zero incidents of fabricated resume/cover-letter content.
