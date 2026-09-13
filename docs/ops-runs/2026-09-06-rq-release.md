# CodeSense RQ release

- scope: latest `origin/main` plus durable ability-analysis and formal-submission RQ workers
- release mode: opt-in through `/var/www/codesense/.env`
- queue Redis: dedicated loopback Redis DB, separate from the application cache/session DB
- no database schema migration
- rollback: change both queue backends back to `thread`, stop the two worker services, and redeploy the previous commit if needed

## Verification

- RQ/worker/API targeted tests: 29 passed
- full pytest: 394 passed
- `compileall`: passed
- `node --check static/js/code_submission.js`: passed
- `git diff --check`: passed

## Runtime requirements

- Redis >=5
- `codesense-ability-worker.service`
- `codesense-submission-worker.service`
- both queue backends explicitly enabled in the production env file

The worker services only receive opaque database IDs through JSON-serialized RQ jobs; code, prompts, identities, provider responses and credentials are not stored in queue metadata.
