"""Standalone knowledge ingestion worker.

Run with ``uv run python -m app.workers.knowledge_worker``. Claims queued
ingestion jobs from MySQL and runs the parse/chunk/embed/publish pipeline.
The API process also attempts each job inline as a background task; the
queued -> running CAS makes the two safe to run side by side.
"""

from app.knowledge.ingestion import run_worker_loop

if __name__ == "__main__":
    run_worker_loop()
