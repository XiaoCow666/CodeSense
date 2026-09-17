CREATE TABLE IF NOT EXISTS action_log (
  action_key TEXT PRIMARY KEY,
  event_id TEXT NOT NULL,
  action_type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'running',
  response_json TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_action_log_event
  ON action_log(event_id, action_type);

CREATE INDEX IF NOT EXISTS idx_action_log_retry
  ON action_log(status, updated_at);

ALTER TABLE event_inbox ADD COLUMN action_status TEXT;
ALTER TABLE event_inbox ADD COLUMN action_result_json TEXT;
