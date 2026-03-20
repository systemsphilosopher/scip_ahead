# SCIP Code Intelligence Database — Schema Reference

> **Purpose**: This document describes a SQLite database that stores [SCIP](https://sourcegraph.com/github.com/sourcegraph/scip) (Source Code Intelligence Protocol) index data. Use it to write SQL queries against this database for code navigation, symbol lookup, cross-referencing, and dependency analysis.

---

## Entity-Relationship Overview

```
repositories 1──* index_snapshots 1──* documents
                       │
                       └──* symbols 1──* occurrences ──* documents
                                  │
                                  └──* relationships (source ↔ target)
```

A **repository** has many **snapshots** (one per indexed commit). Each snapshot produces **documents** (source files) and **symbols** (named code entities). Symbols have **occurrences** (locations in documents where they appear) and **relationships** to other symbols.

---

## Tables

### `repositories`

Represents a source code repository.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `name` | TEXT NOT NULL | Repository name (e.g. `github.com/org/repo`) |
| `url` | TEXT | Clone URL or web URL |
| `created_at` | DATETIME | Default `CURRENT_TIMESTAMP` |

### `index_snapshots`

Each row is a single indexing run against a specific commit of a repository.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `repository_id` | INTEGER FK → `repositories.id` | CASCADE delete |
| `commit_sha` | TEXT NOT NULL | Full Git commit SHA |
| `indexed_at` | DATETIME | When the index was created |

**Unique constraint**: `(repository_id, commit_sha)` — one index per commit per repo.

### `documents`

A source file within an indexed snapshot.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `repository_id` | INTEGER FK → `repositories.id` | CASCADE delete |
| `snapshot_id` | INTEGER FK → `index_snapshots.id` | CASCADE delete |
| `path` | TEXT NOT NULL | Relative file path (e.g. `src/main.ts`) |
| `language` | TEXT | Language identifier (e.g. `typescript`, `python`, `go`) |
| `created_at` | DATETIME | |

**Unique constraint**: `(repository_id, path, snapshot_id)`

### `symbols`

A named code entity (function, class, variable, type, package, etc.) extracted by the SCIP indexer.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `scip_symbol` | TEXT NOT NULL | Full SCIP symbol string (globally unique, structured identifier — see below) |
| `symbol_name` | TEXT NOT NULL | Human-readable short name (e.g. `fetchUser`) |
| `kind` | TEXT | Symbol kind: `function`, `class`, `method`, `variable`, `interface`, `type`, `module`, `package`, `field`, `property`, `enum`, `constant`, etc. |
| `language` | TEXT | Language of the symbol |
| `signature` | TEXT | Type signature or function signature string |
| `documentation` | TEXT | Extracted doc comment / docstring |
| `repository_id` | INTEGER FK → `repositories.id` | CASCADE delete |
| `snapshot_id` | INTEGER FK → `index_snapshots.id` | CASCADE delete |
| `created_at` | DATETIME | |

**Unique constraint**: `(scip_symbol, snapshot_id)`

#### About `scip_symbol`

The `scip_symbol` field is the SCIP-standard structured identifier. It encodes scheme, package manager, package name, version, and descriptor path. Example:

```
scip-typescript npm @acme/utils 1.2.3 src/`helpers`.ts/fetchUser().
```

Use `symbol_name` for human-friendly searches and `scip_symbol` for exact cross-repo references.

### `occurrences`

A specific location in a document where a symbol appears (either its definition or a reference).

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `symbol_id` | INTEGER FK → `symbols.id` | CASCADE delete |
| `document_id` | INTEGER FK → `documents.id` | CASCADE delete |
| `start_line` | INTEGER NOT NULL | 0-indexed line number (start) |
| `end_line` | INTEGER NOT NULL | 0-indexed line number (end) |
| `start_character` | INTEGER NOT NULL | 0-indexed column (start) |
| `end_character` | INTEGER NOT NULL | 0-indexed column (end) |
| `syntax_kind` | TEXT | Optional syntax classification |
| `is_definition` | INTEGER | `1` = this occurrence is the symbol's definition site; `0` = reference |
| `created_at` | DATETIME | |

**Key insight**: To find where a symbol is **defined**, filter `is_definition = 1`. To find all **references** (usages), filter `is_definition = 0`.

### `relationships`

Directed edges between symbols expressing code-level relationships.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `source_symbol_id` | INTEGER FK → `symbols.id` | CASCADE delete |
| `target_symbol_id` | INTEGER FK → `symbols.id` | CASCADE delete |
| `relationship_type` | TEXT NOT NULL | See values below |
| `created_at` | DATETIME | |

Common `relationship_type` values:

| Value | Meaning |
|---|---|
| `implementation` | Source implements target (e.g. class implements interface) |
| `type_definition` | Source's type is defined by target |
| `reference` | Source references / depends on target |
| `inheritance` | Source inherits/extends target |

### `indexing_errors`

Diagnostic log for files that failed to index.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `repository_id` | INTEGER FK → `repositories.id` | Nullable |
| `document_path` | TEXT | File that caused the error |
| `error_message` | TEXT | Error details |
| `occurred_at` | DATETIME | |

---

## Indexes

| Index Name | Table | Column(s) | Purpose |
|---|---|---|---|
| `documents_snapshot_idx` | documents | `snapshot_id` | Filter files by snapshot |
| `symbols_repository_idx` | symbols | `repository_id` | Symbols per repo |
| `symbols_snapshot_idx` | symbols | `snapshot_id` | Symbols per snapshot |
| `symbols_name_idx` | symbols | `symbol_name` | Fast name search |
| `occurrences_symbol_idx` | occurrences | `symbol_id` | All occurrences of a symbol |
| `occurrences_document_idx` | occurrences | `document_id` | All symbols in a file |
| `occurrences_definition_idx` | occurrences | `is_definition` | Separate definitions from references |
| `relationships_source_idx` | relationships | `source_symbol_id` | Outbound edges |
| `relationships_target_idx` | relationships | `target_symbol_id` | Inbound edges |
| `relationships_type_idx` | relationships | `relationship_type` | Filter by relationship kind |
| `index_snapshots_repo_idx` | index_snapshots | `repository_id` | Snapshots per repo |
| `index_snapshots_commit_idx` | index_snapshots | `commit_sha` | Lookup by commit |

---

## Common Join Patterns

Most useful queries join through these paths:

```
-- Symbol → Definition location
symbols → occurrences (is_definition=1) → documents

-- Symbol → All references
symbols → occurrences (is_definition=0) → documents

-- File → All symbols used in it
documents → occurrences → symbols

-- Symbol → Related symbols
symbols → relationships (as source) → symbols
symbols → relationships (as target) → symbols

-- Scope to latest snapshot
index_snapshots → (ORDER BY indexed_at DESC LIMIT 1)
```

---

## Example Queries

### Find the latest snapshot for a repository

```sql
SELECT s.*
FROM index_snapshots s
JOIN repositories r ON r.id = s.repository_id
WHERE r.name = :repo_name
ORDER BY s.indexed_at DESC
LIMIT 1;
```

### Find where a symbol is defined

```sql
SELECT d.path, o.start_line, o.start_character
FROM occurrences o
JOIN documents d ON d.id = o.document_id
JOIN symbols s ON s.id = o.symbol_id
WHERE s.symbol_name = :name
  AND o.is_definition = 1
  AND s.snapshot_id = :snapshot_id;
```

### Find all references to a symbol

```sql
SELECT d.path, o.start_line, o.start_character, o.end_line, o.end_character
FROM occurrences o
JOIN documents d ON d.id = o.document_id
WHERE o.symbol_id = :symbol_id
  AND o.is_definition = 0;
```

### List all symbols in a file

```sql
SELECT s.symbol_name, s.kind, s.signature, o.start_line, o.is_definition
FROM occurrences o
JOIN symbols s ON s.id = o.symbol_id
JOIN documents d ON d.id = o.document_id
WHERE d.path = :file_path
  AND d.snapshot_id = :snapshot_id
ORDER BY o.start_line;
```

### Find all implementations of an interface

```sql
SELECT impl.symbol_name, impl.kind, impl.signature
FROM relationships r
JOIN symbols iface ON iface.id = r.target_symbol_id
JOIN symbols impl  ON impl.id  = r.source_symbol_id
WHERE iface.symbol_name = :interface_name
  AND r.relationship_type = 'implementation';
```

### Find the inheritance chain for a class

```sql
WITH RECURSIVE chain AS (
    SELECT s.id, s.symbol_name, s.kind, 0 AS depth
    FROM symbols s
    WHERE s.symbol_name = :class_name AND s.snapshot_id = :snapshot_id

    UNION ALL

    SELECT parent.id, parent.symbol_name, parent.kind, chain.depth + 1
    FROM chain
    JOIN relationships r ON r.source_symbol_id = chain.id
        AND r.relationship_type = 'inheritance'
    JOIN symbols parent ON parent.id = r.target_symbol_id
)
SELECT * FROM chain ORDER BY depth;
```

### Search symbols by name pattern

```sql
SELECT symbol_name, kind, language, signature
FROM symbols
WHERE symbol_name LIKE :pattern
  AND snapshot_id = :snapshot_id
ORDER BY symbol_name;
```

### Count symbols per language in a snapshot

```sql
SELECT language, kind, COUNT(*) AS count
FROM symbols
WHERE snapshot_id = :snapshot_id
GROUP BY language, kind
ORDER BY count DESC;
```

### Find cross-file dependencies (symbols defined in file A, referenced in file B)

```sql
SELECT DISTINCT
    def_doc.path  AS defined_in,
    ref_doc.path  AS referenced_from,
    s.symbol_name,
    s.kind
FROM symbols s
JOIN occurrences def_occ ON def_occ.symbol_id = s.id AND def_occ.is_definition = 1
JOIN documents def_doc   ON def_doc.id = def_occ.document_id
JOIN occurrences ref_occ ON ref_occ.symbol_id = s.id AND ref_occ.is_definition = 0
JOIN documents ref_doc   ON ref_doc.id = ref_occ.document_id
WHERE def_doc.path != ref_doc.path
  AND s.snapshot_id = :snapshot_id;
```

### Find unused symbols (defined but never referenced)

```sql
SELECT s.symbol_name, s.kind, d.path, o.start_line
FROM symbols s
JOIN occurrences o ON o.symbol_id = s.id AND o.is_definition = 1
JOIN documents d ON d.id = o.document_id
WHERE s.snapshot_id = :snapshot_id
  AND NOT EXISTS (
      SELECT 1 FROM occurrences ref
      WHERE ref.symbol_id = s.id AND ref.is_definition = 0
  );
```

---

## Query Writing Notes

- **Always scope to a `snapshot_id`** when querying symbols, documents, or occurrences to avoid mixing data from different indexing runs.
- **Line/column numbers are 0-indexed.**
- **`is_definition`** is an integer: use `= 1` / `= 0`, not boolean `TRUE`/`FALSE`.
- **`LIKE` with `%` wildcards** works on `symbol_name` for fuzzy search. The `symbols_name_idx` index supports prefix matching (`LIKE 'fetch%'`).
- **Foreign keys are enforced** (`PRAGMA foreign_keys = ON`) with `CASCADE` deletes — deleting a repository removes all its snapshots, documents, symbols, occurrences, and relationships.
- Use **`scip_symbol`** for exact cross-repository symbol matching; use **`symbol_name`** for human-readable searches.