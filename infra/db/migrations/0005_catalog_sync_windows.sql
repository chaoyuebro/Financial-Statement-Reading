CREATE TABLE IF NOT EXISTS catalog_sync_windows (
  kind          TEXT NOT NULL,
  date_from     DATE NOT NULL,
  date_to       DATE NOT NULL,
  status        TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'running', 'done', 'failed')),
  seen          INTEGER NOT NULL DEFAULT 0,
  synced        INTEGER NOT NULL DEFAULT 0,
  error         TEXT,
  started_at    TIMESTAMPTZ,
  completed_at  TIMESTAMPTZ,
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (kind, date_from, date_to)
);

