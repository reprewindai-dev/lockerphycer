# Database Migrations

Run migrations in order against your PostgreSQL database.

## How to run

```bash
psql $DATABASE_URL < db/migrations/add_co2_readings.sql
```

## Migration list

| File | Description |
|---|---|
| `add_co2_readings.sql` | CO2 Router emissions tracking table — stores every reading with timestamp, CPU load, kg CO2/hr, baseline, and reduction delta |
