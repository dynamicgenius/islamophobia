-- Islamophobia Pipeline v3 Schema

-- Sources table
CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    source_name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_weight REAL NOT NULL DEFAULT 0.5,
    url TEXT NOT NULL,
    country TEXT,
    region TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    last_fetched_at TEXT
);

-- Events table
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    event_name TEXT NOT NULL,
    event_type TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT,
    location_text TEXT,
    impact_window_days INTEGER NOT NULL DEFAULT 14,
    source_url TEXT
);

-- Incidents table
CREATE TABLE IF NOT EXISTS incidents (
    incident_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    source_incident_id TEXT,
    title TEXT,
    summary TEXT,
    content TEXT,
    incident_type TEXT,
    verified INTEGER NOT NULL DEFAULT 0,
    published_at TEXT,
    reported_at TEXT,
    location_text TEXT,
    location_norm TEXT,
    latitude REAL,
    longitude REAL,
    confidence REAL NOT NULL DEFAULT 0,
    relevance_score REAL NOT NULL DEFAULT 0,
    event_flag INTEGER NOT NULL DEFAULT 0,
    conflict_flag INTEGER NOT NULL DEFAULT 0,
    protest_flag INTEGER NOT NULL DEFAULT 0,
    far_right_flag INTEGER NOT NULL DEFAULT 0,
    offline_flag INTEGER NOT NULL DEFAULT 0,
    online_flag INTEGER NOT NULL DEFAULT 0,
    created_at TEXT,
    updated_at TEXT,
    FOREIGN KEY (source_id) REFERENCES sources(source_id)
);

-- Incident tags table
CREATE TABLE IF NOT EXISTS incident_tags (
    incident_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    value INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (incident_id, tag),
    FOREIGN KEY (incident_id) REFERENCES incidents(incident_id)
);

-- Daily metrics table
CREATE TABLE IF NOT EXISTS daily_metrics (
    day TEXT NOT NULL,
    source_id TEXT,
    total_items INTEGER NOT NULL DEFAULT 0,
    total_incidents INTEGER NOT NULL DEFAULT 0,
    verified_incidents INTEGER NOT NULL DEFAULT 0,
    avg_confidence REAL NOT NULL DEFAULT 0,
    avg_relevance REAL NOT NULL DEFAULT 0,
    online_share REAL NOT NULL DEFAULT 0,
    offline_share REAL NOT NULL DEFAULT 0,
    created_at TEXT,
    PRIMARY KEY (day, source_id)
);

-- Model runs table
CREATE TABLE IF NOT EXISTS model_runs (
    run_id TEXT PRIMARY KEY,
    model_name TEXT NOT NULL,
    train_start TEXT,
    train_end TEXT,
    test_start TEXT,
    test_end TEXT,
    features_json TEXT,
    metrics_json TEXT,
    created_at TEXT
);

-- Pipeline runs table
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_start TEXT,
    run_end TEXT,
    items_fetched INTEGER,
    new_items INTEGER,
    avg_relevance REAL,
    status TEXT
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_incidents_source_id ON incidents(source_id);
CREATE INDEX IF NOT EXISTS idx_incidents_published_at ON incidents(published_at);
CREATE INDEX IF NOT EXISTS idx_incidents_reported_at ON incidents(reported_at);
CREATE INDEX IF NOT EXISTS idx_incidents_location_norm ON incidents(location_norm);
CREATE INDEX IF NOT EXISTS idx_incidents_event_flag ON incidents(event_flag);
CREATE INDEX IF NOT EXISTS idx_incidents_relevance ON incidents(relevance_score);
CREATE INDEX IF NOT EXISTS idx_incidents_incident_type ON incidents(incident_type);
CREATE INDEX IF NOT EXISTS idx_incidents_verified ON incidents(verified);
