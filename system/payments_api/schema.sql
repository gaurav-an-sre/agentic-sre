CREATE TABLE IF NOT EXISTS accounts (
  account_id TEXT PRIMARY KEY,
  balance    NUMERIC(14,2) NOT NULL,
  currency   TEXT NOT NULL DEFAULT 'SGD'
);
CREATE TABLE IF NOT EXISTS transfers (
  transfer_id  TEXT PRIMARY KEY,
  from_account TEXT NOT NULL REFERENCES accounts(account_id),
  to_account   TEXT NOT NULL REFERENCES accounts(account_id),
  amount       NUMERIC(14,2) NOT NULL,
  currency     TEXT NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO accounts(account_id, balance)
SELECT 'acc_' || lpad(g::text, 4, '0'), 1000000.00 FROM generate_series(1, 200) g
ON CONFLICT (account_id) DO NOTHING;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO payments;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE ON TABLES TO payments;
