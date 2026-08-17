# Career OS — Implementation Plan (Personal Build)

**Based on:** Career OS PRD v1.0
**Scope:** Single-user, local, non-production. Optimized for fastest path to a usable tool, not for scale/robustness.
**Estimated total time:** ~3–4 weeks part-time (evenings/weekends) or ~10–12 focused days full-time.

---

## 0. Ground Rules for Keeping This Fast

Compared to the PRD's "recommended" stack, cut these for v1 — add back later only if you actually feel the pain:

| PRD suggested | Cut to | Why |
|---|---|---|
| Celery + Redis | **APScheduler**, or just a manual "Run Search" button | You're one user triggering things yourself; a job queue is overkill. |
| MongoDB | **Skip it** — store raw job postings and company briefs as JSON columns in Postgres | One database is easier to run and back up than two. |
| Pinecone (managed vector DB) | **Chroma, local, embedded** | Zero setup, no external account, works fully offline except for LLM calls. |
| Docker Compose multi-service | **Just run Postgres via Docker, everything else as local Python/Node processes** | Faster iteration loop, less to debug. |
| Auth system | **None** — it's `localhost` only | Not needed for a single-user local tool. |
| Full ATS coverage (LinkedIn, Greenhouse, Lever, Indeed...) | **Pick ONE job source to start** (whichever you use most) | Every new source is its own scraping/mapping project — don't parallelize this. |

**Also cut/simplify from the PRD's 11 modules for v1:**
- Module 4 (Auto-Fill Agent) and Module 5 (Learning) are the highest-effort, highest-risk pieces — build them **last**, and it's fine if v1 ships without them (you manually fill and submit; the tool still saves you huge time on search/match/tailor/track).
- Module 9 (Company Research) can start as "one good LLM prompt," not a separate pipeline.
- Module 11 (Dashboard) can be a single page for v1, not three polished sections.

---

## 1. Environment Setup (Day 0 — ~2–3 hrs)

- [ ] `docker run` a local Postgres container (or use SQLite if you want zero infra — fine for single-user; switch to Postgres later only if needed).
- [ ] Python project: FastAPI, SQLAlchemy (or SQLModel), Pydantic, `anthropic` SDK, `chromadb`, `playwright`.
- [ ] `playwright install` (browsers).
- [ ] React app via Vite (`npm create vite@latest`).
- [ ] `.env` for `GEMINI_API_KEY` and DB connection string — add to `.gitignore` immediately.
- [ ] One repo, two folders: `/backend`, `/frontend`. Keep it monolithic — no need for microservices.

**Definition of done:** FastAPI `/health` endpoint returns 200; React app renders "Hello Career OS"; both can talk to each other locally.

---

## 2. Phase 1 — Profile + Job Search (Days 1–3)

**Goal:** Get your profile/resume into the system, and get real jobs flowing into a database.

- [ ] Data models: `UserProfile`, `Job` (per PRD Section 6).
- [ ] Simple form or JSON upload to seed your profile (name, contact, work auth, education, resume text, skills). Don't build a fancy resume parser — paste/paste resume text in, parse manually once.
- [ ] Pick **one** job source with a real API (e.g. a job board API, or an ATS like Greenhouse's public job API for companies you care about). Avoid scraping in Phase 1 — save that complexity for later if the API route doesn't cover enough.
- [ ] Ingestion endpoint/script: fetch → normalize → dedupe (by URL or company+title+date) → store in `Job` table.
- [ ] Trigger: a manual "Run Search" button/endpoint. No scheduler needed yet.

**Definition of done:** You can click one button and see real, deduped job postings land in Postgres, viewable via a simple `/jobs` list in the React app.

---

## 3. Phase 2 — Matching (Days 4–5)

**Goal:** Every stored job gets a match score against your profile automatically.

- [ ] Embed your resume/profile bullets and each job description using an embedding model (Claude API doesn't do embeddings — use a small local model like `sentence-transformers`, or OpenAI's embedding endpoint if you're open to a second API; either works, this is not an architecture-critical choice).
- [ ] Store embeddings in Chroma.
- [ ] On new job ingestion: compute similarity → pass top candidates + reasoning context to Claude → get back structured JSON: `match_percent`, `strengths`, `gaps`, `recommendation` (Apply/Consider/Skip). Use Pydantic to validate the LLM's JSON output.
- [ ] Store `Match` records; surface match % and recommendation in the `/jobs` list, sortable.

**Definition of done:** Every job in your list shows a match score and recommendation without you asking for it.

---

## 4. Phase 3 — Application Prep (Days 6–8)

**Goal:** One click on a job produces a tailored resume, cover letter, and company brief — all saved, none submitted.

- [ ] Resume tailoring prompt: give Claude your full resume content + the JD, ask it to **reorder/rephrase/select**, explicitly instructed never to invent content. Output structured (sections/bullets) so the UI can render it cleanly.
- [ ] **Add a guardrail check**: diff the tailored resume's factual claims against your source resume (even a simple LLM "does this contain any claim not present in the source resume?" check) — this directly addresses the PRD's #1 flagged risk (hallucination).
- [ ] Cover letter prompt: JD + company info + profile → draft letter.
- [ ] Company brief: one well-crafted Claude prompt (with web search if you want current info) → short structured brief. Don't over-engineer this into a separate pipeline yet.
- [ ] "Application Package" record tying job + tailored resume + cover letter + brief together, status = `Prepared`.

**Definition of done:** Clicking "Prepare Application" on a job produces a package you can read end-to-end and would actually be comfortable sending.

---

## 5. Phase 4 — Review, Submit (Manual), Track (Days 9–11)

**Goal:** A simple review screen, a way to mark applications submitted, and a status board.

- [ ] Review screen: shows resume/cover letter/brief for a package, editable text fields, "Confirm & Mark Submitted" button. **Skip auto-submission entirely in this phase** — you manually submit on the company site, then click "Mark Submitted" in your tool. This alone still saves the prep time, which is the bulk of the effort per application.
- [ ] On confirm: create permanent `Application` record (per PRD Module 7 data model), snapshot the exact resume/cover letter/answers used.
- [ ] Status board: simple Kanban-style columns (Submitted / OA Pending / Interview / Rejected) — a basic React grid grouping by status is enough, no need for drag-and-drop polish in v1 (a status dropdown per card is fine).

**Definition of done:** You can go from "job found" to "tracked in a status board" end-to-end, with real applications, without leaving the tool except to click Submit on the company's own site.

---

## 6. Phase 5 — Interview Prep (Days 12–14)

**Goal:** For any application marked "Interview Pending," generate a useful mock interview.

- [ ] Mark-as-interview action on an `Application` (simple status update).
- [ ] Interview prep endpoint: JD + resume + company brief + interview type (behavioral / technical / resume-based) → Claude generates a question set.
- [ ] Simple chat-style UI: system asks a question, you answer, Claude evaluates/follows up. This can literally be a Claude API loop with the transcript kept in state — no special "agent framework" needed.
- [ ] Store `InterviewSession` transcript + evaluation + flagged weak areas.

**Definition of done:** You can run a 15–20 minute mock interview through the tool the night before a real interview and get useful, specific feedback.

---

## 7. Phase 6 (Optional / Later) — Auto-Fill Agent & Learning

**Only build this once Phases 1–5 are working and you're actually feeling the pain of manual form-filling.** This is the highest-effort module — don't let it block getting value from the rest of the system.

- [ ] Playwright script: open application URL, extract form fields (labels/names/types).
- [ ] Field-mapping: match extracted fields to your stored profile data (start with a hardcoded mapping dict per ATS type — Greenhouse forms look different from Lever forms — expand as you encounter new ones).
- [ ] Auto-fill known fields; leave unmapped/high-stakes fields highlighted for you to fill.
- [ ] **Never auto-submit** — always hand off to the Phase 4 review screen.
- [ ] Preference store: a simple key-value table (`Preference`) that records your manual corrections and reuses them next time the same field/question type appears.

**Definition of done:** Applying to a job on a supported ATS requires you to fill in only the handful of fields the tool couldn't confidently map.

---

## 8. Suggested Timeline Summary

| Phase | Content | Est. time |
|---|---|---|
| 0 | Environment setup | 0.5 day |
| 1 | Profile + job search | 2–3 days |
| 2 | Matching | 1–2 days |
| 3 | Application prep (resume/cover letter/brief) | 2–3 days |
| 4 | Review, manual submit, tracking | 2–3 days |
| 5 | Interview prep | 2–3 days |
| **Core v1 total** | **Phases 0–5** | **~10–14 days** |
| 6 (optional) | Auto-fill agent + learning | +4–6 days, whenever you want it |

This gets you a genuinely useful personal tool (search → match → tailor → track → interview prep) in under two weeks part-time, without building the two hardest/most fragile pieces (browser automation, self-learning preferences) until you've confirmed the rest is worth the investment.

---

## 9. What to Explicitly Skip for v1 (Revisit Only If Needed)

- Multiple job sources / scraping fallback — one API source is enough to prove the loop works.
- Scheduled/automatic search runs — a manual button is fine.
- Fine-grained field-mapping learning system — a flat preference table is enough.
- Polished dashboard with 3 distinct sections — one page listing everything is enough.
- Docker Compose / deployment to a VPS — running locally on your machine is enough for personal use.
- Extensive test suite — spot-check outputs manually; this is a personal tool, not something with SLAs.
