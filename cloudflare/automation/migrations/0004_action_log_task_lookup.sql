CREATE INDEX IF NOT EXISTS idx_action_log_task_lookup
  ON action_log(action_type, status, action_key COLLATE NOCASE);
