-- Optional PostgreSQL + pgvector. Требует CREATE EXTENSION vector;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS knowledge_chunks (
  id TEXT PRIMARY KEY,
  competency TEXT NOT NULL,
  topic TEXT NOT NULL,
  level TEXT NOT NULL,
  body TEXT NOT NULL,
  source_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
  review_status TEXT NOT NULL,
  embedding vector(1536) NOT NULL
);
-- Для 4-25 карточек индексы HNSW/IVFFlat НЕ нужны. Поиск exact корректен.
-- При масштабировании и измеренной необходимости можно добавить:
-- CREATE INDEX knowledge_chunks_embedding_hnsw ON knowledge_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS knowledge_chunks_competency_level ON knowledge_chunks(competency, level);
