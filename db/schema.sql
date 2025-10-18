-- PostgreSQL schema for Data Audit System

-- Ensure UUID extension is available (optional but useful)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Main audit table
CREATE TABLE IF NOT EXISTS file_audit (
    id SERIAL PRIMARY KEY,
    source TEXT NOT NULL CHECK (source IN ('fileserver', 'sharepoint')),
    file_path TEXT NOT NULL UNIQUE,
    last_modified TIMESTAMPTZ,
    last_accessed TIMESTAMPTZ,
    owner TEXT,
    checksum TEXT NOT NULL,
    archive_url TEXT,
    status TEXT NOT NULL DEFAULT 'Active' 
        CHECK (status IN ('Active', 'Archived', 'Deleted')),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Performance indexes
CREATE INDEX IF NOT EXISTS idx_file_audit_status ON file_audit (status);
CREATE INDEX IF NOT EXISTS idx_file_audit_last_accessed ON file_audit (last_accessed);
CREATE INDEX IF NOT EXISTS idx_file_audit_source ON file_audit (source);
CREATE INDEX IF NOT EXISTS idx_file_audit_path ON file_audit (file_path);

-- Auto-update updated_at column on row update
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE 'plpgsql';

DROP TRIGGER IF EXISTS trigger_update_updated_at ON file_audit;
CREATE TRIGGER trigger_update_updated_at
    BEFORE UPDATE ON file_audit
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();