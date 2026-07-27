UPDATE parse_jobs
SET id = report_id::text || '_' || stage
WHERE id <> report_id::text || '_' || stage;
