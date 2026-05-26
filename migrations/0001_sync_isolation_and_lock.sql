-- Adds per-account error tracking and item-level sync lock fields.
-- Apply with:  sqlite3 openfinance.db < migrations/0001_sync_isolation_and_lock.sql

BEGIN;

ALTER TABLE accountsync ADD COLUMN last_error VARCHAR;
ALTER TABLE accountsync ADD COLUMN last_error_at DATETIME;

ALTER TABLE item ADD COLUMN sync_started_at DATETIME;
ALTER TABLE item ADD COLUMN sync_finished_at DATETIME;
ALTER TABLE item ADD COLUMN last_sync_error VARCHAR;

COMMIT;
