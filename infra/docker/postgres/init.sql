-- Veklom / Lockerphycer — PostgreSQL init
-- Runs once when the postgres container is first created

-- Ensure the database exists (created by POSTGRES_DB env var, this is a safety net)
SELECT 'CREATE DATABASE lockerphycer_production'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'lockerphycer_production')\gexec

-- Extensions
\c lockerphycer_production
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "btree_gin";
