"""
Chroma vector store setup — Phase 2 (matching).

Persistent Chroma client backed by a local on-disk directory. No server to
run — fits the "no extra infra" rule from the implementation plan. This is
also what gives us embedding caching: job descriptions embedded once stay
in ./chroma_db until they change, so repeat match runs skip re-embedding
anything unchanged.
"""
import chromadb

_client = chromadb.PersistentClient(path="./chroma_db")

_jobs_collection = _client.get_or_create_collection(
    name="jobs",
    metadata={"hnsw:space": "cosine"},
)


def get_jobs_collection():
    return _jobs_collection
    