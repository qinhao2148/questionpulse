"""Knowledge base services: parsing, chunking, embedding, vector search and RAG.

Generation always goes through the configured LLM API (DeepSeek). Embeddings
run in-process via fastembed and degrade to a deterministic hash embedder, so
the feature still works (with a visible degraded status) when the embedding
model cannot be loaded.
"""
