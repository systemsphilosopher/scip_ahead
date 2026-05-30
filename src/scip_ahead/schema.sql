-- ============================================================================
-- SCIP Code Intelligence Database Schema (SQLite)
-- ============================================================================

PRAGMA foreign_keys = ON;

-- 1️⃣ Repositories
CREATE TABLE IF NOT EXISTS repositories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    url         TEXT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 2️⃣ Index Snapshots (tracks commits)
CREATE TABLE IF NOT EXISTS index_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    repository_id   INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    commit_sha      TEXT NOT NULL,
    indexed_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(repository_id, commit_sha)
);

-- 3️⃣ Documents (files)
CREATE TABLE IF NOT EXISTS documents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    repository_id   INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    snapshot_id     INTEGER NOT NULL REFERENCES index_snapshots(id) ON DELETE CASCADE,
    path            TEXT NOT NULL,
    language        TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(repository_id, path, snapshot_id)
);

-- 4️⃣ Symbols
CREATE TABLE IF NOT EXISTS symbols (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scip_symbol     TEXT NOT NULL,
    symbol_name     TEXT NOT NULL,
    kind            TEXT,
    language        TEXT,
    signature       TEXT,
    documentation   TEXT,
    repository_id   INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    snapshot_id     INTEGER NOT NULL REFERENCES index_snapshots(id) ON DELETE CASCADE,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(scip_symbol, snapshot_id)
);

-- 5️⃣ Occurrences
CREATE TABLE IF NOT EXISTS occurrences (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id       INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    document_id     INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    start_line      INTEGER NOT NULL,
    end_line        INTEGER NOT NULL,
    start_character INTEGER NOT NULL,
    end_character   INTEGER NOT NULL,
    -- (optional) Half-open range of the nearest enclosing AST node, same encoding
    -- as the range columns above. NULL when the indexer does not emit it
    -- (e.g. scip-dotnet). See Occurrence.enclosing_range in scip.proto.
    enclosing_start_line      INTEGER,
    enclosing_end_line        INTEGER,
    enclosing_start_character INTEGER,
    enclosing_end_character   INTEGER,
    syntax_kind     TEXT,
    is_definition   INTEGER DEFAULT 0,  -- 0 = false, 1 = true
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 6️⃣ Relationships
-- Boolean flags mirror SCIP's Relationship message (scip.proto): a single edge
-- can be any combination of reference / implementation / type-definition / definition.
CREATE TABLE IF NOT EXISTS relationships (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_symbol_id    INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    target_symbol_id    INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    is_reference        INTEGER DEFAULT 0,  -- 0 = false, 1 = true
    is_implementation   INTEGER DEFAULT 0,
    is_type_definition  INTEGER DEFAULT 0,
    is_definition       INTEGER DEFAULT 0,
    snapshot_id         INTEGER NOT NULL REFERENCES index_snapshots(id) ON DELETE CASCADE,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_symbol_id, target_symbol_id, snapshot_id)
);

-- 7️⃣ Indexing Errors (for debugging)
CREATE TABLE IF NOT EXISTS indexing_errors (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id     INTEGER REFERENCES index_snapshots(id) ON DELETE CASCADE,
    document_path   TEXT,
    scip_symbol     TEXT,
    error_message   TEXT,
    occurred_at     DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- INDEXES
-- ============================================================================

-- Documents
CREATE INDEX IF NOT EXISTS documents_snapshot_idx ON documents(snapshot_id);

-- Symbols
CREATE INDEX IF NOT EXISTS symbols_repository_idx ON symbols(repository_id);
CREATE INDEX IF NOT EXISTS symbols_snapshot_idx ON symbols(snapshot_id);
CREATE INDEX IF NOT EXISTS symbols_name_idx ON symbols(symbol_name);

-- Occurrences (critical for performance)
CREATE INDEX IF NOT EXISTS occurrences_symbol_idx ON occurrences(symbol_id);
CREATE INDEX IF NOT EXISTS occurrences_document_idx ON occurrences(document_id);
CREATE INDEX IF NOT EXISTS occurrences_definition_idx ON occurrences(is_definition);

-- Relationships
CREATE INDEX IF NOT EXISTS relationships_source_idx ON relationships(source_symbol_id);
CREATE INDEX IF NOT EXISTS relationships_target_idx ON relationships(target_symbol_id);
CREATE INDEX IF NOT EXISTS relationships_snapshot_idx ON relationships(snapshot_id);

-- Index Snapshots
CREATE INDEX IF NOT EXISTS index_snapshots_repo_idx ON index_snapshots(repository_id);
CREATE INDEX IF NOT EXISTS index_snapshots_commit_idx ON index_snapshots(commit_sha);