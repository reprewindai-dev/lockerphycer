-- CO2 Router emissions tracking table
-- Run: psql $DATABASE_URL < db/migrations/add_co2_readings.sql

CREATE TABLE IF NOT EXISTS co2_readings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    cpu_load_percent FLOAT NOT NULL,
    estimated_kg_co2_per_hr FLOAT NOT NULL,
    active_routes INTEGER NOT NULL DEFAULT 0,
    optimization_applied BOOLEAN NOT NULL DEFAULT FALSE,
    reduction_from_baseline_percent FLOAT,
    baseline_kg_co2_per_hr FLOAT
);

CREATE INDEX IF NOT EXISTS idx_co2_readings_timestamp ON co2_readings(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_co2_readings_optimization ON co2_readings(optimization_applied);
