CREATE TABLE IF NOT EXISTS report_analyses (
  report_id    UUID PRIMARY KEY REFERENCES reports(id) ON DELETE CASCADE,
  version_tag  TEXT NOT NULL,
  points       JSONB NOT NULL,
  model        TEXT,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_report_analyses_version
  ON report_analyses(version_tag);
