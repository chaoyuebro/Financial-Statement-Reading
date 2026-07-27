ALTER TABLE reports
  ADD COLUMN IF NOT EXISTS disclosure_time TIMESTAMPTZ;

ALTER TABLE disclosures
  ADD COLUMN IF NOT EXISTS disclosure_time TIMESTAMPTZ;

UPDATE reports
SET disclosure_time = disclosure_date::timestamp AT TIME ZONE 'Asia/Shanghai'
WHERE disclosure_time IS NULL AND disclosure_date IS NOT NULL;

UPDATE disclosures
SET disclosure_time = disclosure_date::timestamp AT TIME ZONE 'Asia/Shanghai'
WHERE disclosure_time IS NULL AND disclosure_date IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_reports_disclosure_time
  ON reports(disclosure_time DESC, id);
