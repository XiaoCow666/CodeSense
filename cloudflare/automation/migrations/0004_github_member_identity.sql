CREATE TABLE IF NOT EXISTS github_member_identity (
  repository TEXT NOT NULL,
  github_login TEXT NOT NULL,
  assignee_open_id TEXT NOT NULL,
  assignee_name TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (repository, github_login)
);

CREATE INDEX IF NOT EXISTS idx_github_member_identity_assignee
  ON github_member_identity(repository, assignee_open_id);
