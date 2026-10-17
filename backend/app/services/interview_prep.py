import json
import re
from app.llm import generate_json

VALID_TYPES = {"hr", "behavioral", "technical", "resume"}

TYPE_GUIDANCE = {
    "hr": (
        "HR/recruiter screening-round questions: tell me about yourself, why this company "
        "and role, career motivation, strengths and weaknesses, why you're leaving or looking, "
        "salary expectations, notice period or availability, where you see yourself in a few "
        "years, and questions the candidate may have for the interviewer. Tailor them to this "
        "company and the candidate's background, not generic."
        "Include some interview ending questions HR might ask, like 'Do you have any questions for us?' or 'Is there anything else you'd like to share?'etc."
    ),
    "behavioral": "Behavioral questions (STAR-style) about teamwork, conflict, ownership, failure, and leadership, tied to the role's responsibilities.",
    "technical": "Technical questions on the skills, tools, and problem types the job description emphasizes. Mix conceptual questions with practical/design scenarios.",
    "resume": (
    "Strictly resume-based questions. Every question must be anchored to a specific item that "
    "actually appears on the candidate's resume (a named company, project, technology, date range, "
    "or metric) and must be impossible to answer well without having done that work. "
    "Do NOT ask generic behavioral, HR, or textbook technical questions, and do NOT reference "
    "anything that is not on the resume. "
    "Spread the questions across different roles, projects, and sections instead of clustering on one. "
    "Order and mix them as follows: "
    "(1) Opening: 1-2 questions asking the candidate to walk through their most relevant project or role "
    "and their specific contribution; "
    "(2) Depth probes: the majority of questions, drilling into execution details behind specific bullet "
    "points, such as design decisions, tradeoffs, what went wrong, how a metric was measured, and what "
    "they personally owned versus the team; "
    "(3) Claim verification: questions that test whether listed skills, tools, or metrics hold up "
    "under scrutiny, prioritizing the ones the job description requires; "
    "(4) Gaps and risks: 1-2 questions on required skills from the job description that are missing or "
    "thin on the resume, and, only if they genuinely exist, employment gaps, short tenures, or "
    "inconsistencies in the timeline. If none exist, skip this and ask another depth probe instead."
    ),
}


def _coerce_to_dict(result) -> dict:
    """generate_json may return a dict, a JSON string, or a list. Normalize to a dict."""
    if isinstance(result, dict):
        return result
    if isinstance(result, list):
        return {"questions": result}
    if isinstance(result, str):
        text = result.strip()
        # strip ```json ... ``` fences if the model added them
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
        parsed = json.loads(text)
        return _coerce_to_dict(parsed)
    raise ValueError(f"Unexpected LLM result type: {type(result).__name__}")


def generate_questions(job, resume_text: str, interview_type: str, count: int = 15) -> list[str]:
    if interview_type not in VALID_TYPES:
        raise ValueError(f"interview_type must be one of {sorted(VALID_TYPES)}")

    prompt = f"""You are an experienced interviewer preparing a mock interview.

Company: {job.company}
Role: {job.title}

Job description:
{job.description}

Candidate's resume (as submitted for this application):
{resume_text}

Interview type: {interview_type}
Guidance: {TYPE_GUIDANCE[interview_type]}

Write exactly {count} interview questions, ordered as a real interview would flow
(easier warm-up first, harder later). Each question must be specific to this
company/role/candidate, not generic.

Respond with ONLY valid JSON in this shape:
{{"questions": ["question 1", "question 2"]}}
"""

    result = _coerce_to_dict(generate_json(prompt))
    questions = result.get("questions", [])
    questions = [q.strip() for q in questions if isinstance(q, str) and q.strip()]
    if not questions:
        raise ValueError(f"LLM returned no questions. Raw result: {result}")
    return questions


EVAL_GUIDANCE = {
    "hr": (
        "Judge as an HR screen: concise and honest answers, clear motivation for this specific "
        "company and role, consistency with the resume, sensible logistics (salary, notice period), "
        "professional tone. Penalize rambling, generic answers, and negativity about past employers."
    ),
    "behavioral": (
        "Judge against the STAR structure (Situation, Task, Action, Result). Reward specific "
        "examples, clear personal ownership ('I' vs 'we'), and measurable results. Penalize vague "
        "or hypothetical answers, missing results, and stories with no reflection or learning."
    ),
    "technical": (
        "Judge technical correctness, depth, awareness of tradeoffs, and clarity of explanation. "
        "Point out any factual errors explicitly. Reward concrete examples and sound reasoning."
    ),
    "resume": (
        "Judge whether the candidate can convincingly defend what is on their resume: specific "
        "execution details, personal ownership, how metrics were measured, and consistency with "
        "the written claims. Penalize vague answers that suggest the work was shallow or exaggerated."
    ),
}

# Follow-up limits (tune these to make interviews shorter/longer)
FOLLOWUP_SCORE_THRESHOLD = 6      # only probe if the first answer scored <= this
MAX_FOLLOWUPS_PER_SESSION = 9


def _load(session):
    """Load questions + transcript. Adds q_index to older entries that lack it."""
    questions = json.loads(session.questions)
    raw = json.loads(session.transcript or "[]")
    transcript = []
    current_q = -1
    next_q = 0
    for t in raw:
        t = dict(t)
        if "q_index" not in t:
            if t.get("kind") == "question":
                t["q_index"] = next_q
                next_q += 1
            else:
                t["q_index"] = current_q
        current_q = t["q_index"]
        next_q = max(next_q, current_q + 1)
        transcript.append(t)
    return questions, transcript


def _last_turn_index(transcript):
    """Index of the last interviewer/candidate entry (ignores 'skipped' markers)."""
    for i in range(len(transcript) - 1, -1, -1):
        if transcript[i]["role"] != "system":
            return i
    return None


def _question_statuses(questions, transcript):
    statuses = []
    for i, q in enumerate(questions):
        answers = [t for t in transcript if t["role"] == "candidate" and t["q_index"] == i]
        skipped = any(t.get("kind") == "skipped" and t["q_index"] == i for t in transcript)
        if answers:
            status = "answered"
        elif skipped:
            status = "skipped"
        else:
            status = "pending"
        statuses.append({
            "index": i,
            "question": q,
            "status": status,
            "score": answers[0]["score"] if answers else None,
        })
    return statuses


def get_state(session) -> dict:
    questions, transcript = _load(session)
    statuses = _question_statuses(questions, transcript)
    idx = _last_turn_index(transcript)
    last = transcript[idx] if idx is not None else None
    active = last is not None and last["role"] == "interviewer"
    return {
        "session_id": session.id,
        "interview_type": session.interview_type,
        "status": session.status,
        "total_questions": len(questions),
        "answered_count": sum(1 for s in statuses if s["status"] == "answered"),
        "questions": statuses,
        "active_question_index": last["q_index"] if active else None,
        "current_kind": last.get("kind") if active else None,
        "transcript": transcript,
        "evaluation": json.loads(session.evaluation) if session.evaluation else None,
    }


def start_question(session, index: int) -> dict:
    questions, transcript = _load(session)
    if not isinstance(index, int) or not 0 <= index < len(questions):
        raise ValueError("Invalid question index")
    if _question_statuses(questions, transcript)[index]["status"] == "answered":
        raise ValueError("That question is already answered")

    idx = _last_turn_index(transcript)
    if idx is not None and transcript[idx]["role"] == "interviewer":
        last = transcript[idx]
        if last["q_index"] == index:
            return get_state(session)  # already the active question
        if last["kind"] == "question":
            transcript.pop(idx)  # drop an unanswered question we're switching away from

    transcript.append({
        "role": "interviewer", "kind": "question",
        "q_index": index, "content": questions[index],
    })
    session.transcript = json.dumps(transcript)
    return get_state(session)


def skip_question(session, index: int) -> dict:
    questions, transcript = _load(session)
    if not isinstance(index, int) or not 0 <= index < len(questions):
        raise ValueError("Invalid question index")
    if _question_statuses(questions, transcript)[index]["status"] != "pending":
        raise ValueError("Only unanswered, unskipped questions can be skipped")

    idx = _last_turn_index(transcript)
    if idx is not None:
        last = transcript[idx]
        if last["role"] == "interviewer" and last["kind"] == "question" and last["q_index"] == index:
            transcript.pop(idx)  # skipping the question that was active

    transcript.append({
        "role": "system", "kind": "skipped",
        "q_index": index, "content": questions[index],
    })
    session.transcript = json.dumps(transcript)
    return get_state(session)


def process_answer(session, job, resume_text: str, answer: str) -> dict:
    questions, transcript = _load(session)
    idx = _last_turn_index(transcript)
    if idx is None or transcript[idx]["role"] != "interviewer":
        raise ValueError("No active question")

    last = transcript[idx]
    q_index = last["q_index"]
    is_initial = last["kind"] == "question"
    current_question = last["content"]

    # Context: only the exchange for this question
    recent = "\n".join(
        f"{'Interviewer' if t['role'] == 'interviewer' else 'Candidate'}: {t['content']}"
        for t in transcript
        if t["role"] in ("interviewer", "candidate") and t["q_index"] == q_index
    )

    if is_initial:
        structure_rule = (
            '\nAlso provide "answer_structure": 3-4 very short steps (max ~10 words each) outlining how an '
            "ideal answer to THIS specific question should be structured, tailored to the question and "
            "the candidate's background, not just a framework name."
        )
        structure_shape = ', "answer_structure": ["<step 1>", "<step 2>", "<step 3>"]'
    else:
        structure_rule = ""
        structure_shape = ""

    prompt = f"""You are a strict but fair interviewer running a {session.interview_type} mock interview
for the role of {job.title} at {job.company}.

Job description:
{job.description}

Candidate's resume:
{resume_text}

Conversation on this question so far:
{recent}

The candidate just answered this question: "{current_question}"
Candidate's answer: "{answer}"

Evaluation criteria: {EVAL_GUIDANCE[session.interview_type]}

Evaluate the answer. Be specific and quote or reference what the candidate actually said.
If the answer is weak or vague, say exactly what was missing and how to improve it.
Only suggest a follow_up question if the answer left something genuinely worth probing; otherwise use null.{structure_rule}

Respond with ONLY valid JSON in this shape:
{{"score": <integer 1-10>, "feedback": "<2-4 sentences>", "strengths": ["..."], "weak_areas": ["short tag or phrase"], "follow_up": "<question or null>"{structure_shape}}}
"""

    result = _coerce_to_dict(generate_json(prompt))

    try:
        score = max(1, min(10, int(result.get("score", 5))))
    except (TypeError, ValueError):
        score = 5

    entry = {
        "role": "candidate",
        "q_index": q_index,
        "content": answer,
        "score": score,
        "feedback": str(result.get("feedback", "")).strip(),
        "strengths": [s for s in (result.get("strengths") or []) if isinstance(s, str)],
        "weak_areas": [w for w in (result.get("weak_areas") or []) if isinstance(w, str)],
    }
    if is_initial:
        entry["answer_structure"] = [s for s in (result.get("answer_structure") or []) if isinstance(s, str)]
    transcript.append(entry)

    # Follow-up only on weak first answers, capped per session
    follow_up = result.get("follow_up")
    followups_so_far = sum(1 for t in transcript if t.get("kind") == "followup")
    if (
        is_initial
        and score <= FOLLOWUP_SCORE_THRESHOLD
        and followups_so_far < MAX_FOLLOWUPS_PER_SESSION
        and isinstance(follow_up, str)
        and follow_up.strip()
        and follow_up.strip().lower() != "null"
    ):
        transcript.append({
            "role": "interviewer", "kind": "followup",
            "q_index": q_index, "content": follow_up.strip(),
        })

    session.transcript = json.dumps(transcript)
    return get_state(session) | {"last_evaluation": entry}


def finish_session(session, job) -> dict:
    # Idempotent: if already completed, return the stored report
    if session.status == "completed" and session.evaluation:
        return json.loads(session.evaluation)

    questions, transcript = _load(session)
    answers = [t for t in transcript if t["role"] == "candidate"]
    if not answers:
        raise ValueError("No answers submitted yet")

    statuses = _question_statuses(questions, transcript)
    skipped_count = sum(1 for s in statuses if s["status"] == "skipped")

    # Exact numbers computed in Python, not by the LLM
    scores = [a["score"] for a in answers if isinstance(a.get("score"), int)]
    average_score = round(sum(scores) / len(scores), 1) if scores else 0

    weak_counts: dict[str, int] = {}
    for a in answers:
        for w in a.get("weak_areas", []):
            key = w.strip().lower()
            if key:
                weak_counts[key] = weak_counts.get(key, 0) + 1
    top_weak_areas = [
        {"area": k, "count": v}
        for k, v in sorted(weak_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
    ]

    lines = []
    for t in transcript:
        if t["role"] == "interviewer":
            lines.append(f"Interviewer: {t['content']}")
        elif t["role"] == "candidate":
            lines.append(
                f"Candidate (scored {t.get('score', '?')}/10): {t['content']}\n"
                f"  Feedback given: {t.get('feedback', '')}"
            )
    transcript_text = "\n".join(lines)

    prompt = f"""You are a senior interview coach reviewing a {session.interview_type} mock interview
for the role of {job.title} at {job.company}. The candidate chose which questions to practice
and skipped {skipped_count} of {len(questions)} questions, so judge only what was answered.

Full transcript with per-answer scores and feedback:
{transcript_text}

Average score: {average_score}/10 across {len(answers)} answers.
Recurring weak areas (tag: times flagged): {top_weak_areas}

Evaluation criteria for this interview type: {EVAL_GUIDANCE[session.interview_type]}

Write a final report. Be specific: reference actual answers and moments from the transcript,
not generic advice.

Respond with ONLY valid JSON in this shape:
{{"overall_summary": "<3-5 sentences>", "strengths": ["..."], "improvements": ["..."], "practice_plan": ["<concrete thing to rehearse tonight>"], "readiness": "<one of: not ready, getting there, ready>"}}
"""

    result = _coerce_to_dict(generate_json(prompt))

    def _strs(key):
        return [s for s in (result.get(key) or []) if isinstance(s, str)]

    evaluation = {
        "interview_type": session.interview_type,
        "average_score": average_score,
        "questions_answered": len(answers),
        "questions_skipped": skipped_count,
        "total_questions": len(questions),
        "top_weak_areas": top_weak_areas,
        "overall_summary": str(result.get("overall_summary", "")).strip(),
        "strengths": _strs("strengths"),
        "improvements": _strs("improvements"),
        "practice_plan": _strs("practice_plan"),
        "readiness": str(result.get("readiness", "")).strip(),
    }

    session.evaluation = json.dumps(evaluation)
    session.status = "completed"
    return evaluation