from app.services.essay_answers import draft_answers

questions = [
    "Why do you want to work at Discord?",
    "Please tell us about your experience leveraging Machine Learning for "
    "abuse/fraud detection, content classification, or other Trust & Safety "
    "related purposes!",
]

results = draft_answers(
    company="Discord",
    title="Machine Learning Engineer, Trust & Safety",
    description="Build ML systems that detect abuse and fraud across Discord, "
                "classify harmful content, and keep communities safe at scale.",
    resume_text=(
        "Arsh Bajaj. Software engineer. Built a FastAPI + React job-search "
        "tool with LLM-based matching using embeddings and Chroma. Built "
        "REST APIs, SQL databases, and Python data pipelines. Skills: "
        "Python, FastAPI, React, SQL, embeddings, LLM APIs."
    ),
    cover_letter="",
    questions=questions,
)

for r in results:
    print("\nQ:", r["question"])
    print("Direct experience:", r["has_direct_experience"])
    print("A:", r["answer"])