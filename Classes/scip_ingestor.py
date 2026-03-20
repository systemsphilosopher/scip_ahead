import sqlite3
from Classes.scip_pb2 import Index

class SCIPIngestor:

    def ingest_scip(self, db_path: str, scip_path: str, commit_sha: str) -> None:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")

        index = Index()
        with open(scip_path, "rb") as f:
            index.ParseFromString(f.read())

        repository_id = self.upsert_repo(conn, index)

        snapshot_id = self.check_or_create_snapshot(conn, repository_id, commit_sha)
        if snapshot_id is None:
            return

        conn.execute("BEGIN")
        # transaction is now open — steps 4–9 continue here
        doc_ids = self.ingest_docs(conn, index, repository_id, snapshot_id)
        scip_symbol_to_id = self.ingest_symbols(conn, index, repository_id, snapshot_id)
        conn.commit()

    def ingest_docs(
        self,
        conn: sqlite3.Connection,
        index: Index,
        repository_id: int,
        snapshot_id: int,
    ) -> dict[str, int]:
        path_to_doc_id: dict[str, int] = {}

        for doc in index.documents:
            cursor = conn.execute(
                """
                INSERT INTO documents (repository_id, path, snapshot_id)
                VALUES (?, ?, ?)
                ON CONFLICT (repository_id, path, snapshot_id) DO UPDATE SET
                    path = excluded.path
                RETURNING id
                """,
                (repository_id, doc.relative_path, snapshot_id),
            )
            doc_id = cursor.fetchone()[0]
            path_to_doc_id[doc.relative_path] = doc_id

        return path_to_doc_id

    def upsert_repo(self, conn: sqlite3.Connection, index: Index) -> int:
        project_root = index.metadata.project_root
        repo_name = project_root.rstrip("/").split("/")[-1]

        row = conn.execute(
            "SELECT id FROM repositories WHERE name = ?", (repo_name,)
        ).fetchone()

        if row:
            return row[0]

        cursor = conn.execute(
            "INSERT INTO repositories (name) VALUES (?)", (repo_name,)
        )
        conn.commit()
        return cursor.lastrowid

    def check_or_create_snapshot(
        self, conn: sqlite3.Connection, repository_id: int, commit_sha: str
    ) -> int | None:
        existing = conn.execute(
            "SELECT id FROM index_snapshots WHERE repository_id = ? AND commit_sha = ?",
            (repository_id, commit_sha),
        ).fetchone()

        if existing:
            print(f"Snapshot already exists for repository_id={repository_id}, commit_sha={commit_sha!r} — skipping ingestion.")
            return None

        cursor = conn.execute(
            "INSERT INTO index_snapshots (repository_id, commit_sha) VALUES (?, ?)",
            (repository_id, commit_sha),
        )
        conn.commit()
        return cursor.lastrowid

    def ingest_symbols(
        self,
        conn: sqlite3.Connection,
        index: Index,
        repository_id: int,
        snapshot_id: int,
    ) -> dict[str, int]:
        scip_symbol_to_id: dict[str, int] = {}

        rows: list[tuple] = []

        # Collect from all documents
        for doc in index.documents:
            lang = doc.language if doc.language else None
            for sym_info in doc.symbols:
                rows.append((
                    sym_info.symbol,
                    sym_info.display_name or sym_info.symbol.split(".")[-1],
                    sym_info.kind or None,
                    lang,
                    sym_info.signature_documentation.text if sym_info.HasField("signature_documentation") else None,
                    "\n".join(sym_info.documentation) if sym_info.documentation else None,
                    repository_id,
                    snapshot_id,
                ))

        # Collect external symbols
        for sym_info in index.external_symbols:
            rows.append((
                sym_info.symbol,
                sym_info.display_name or sym_info.symbol.split(".")[-1],
                sym_info.kind or None,
                None,  # no language on external symbols
                sym_info.signature_documentation.text if sym_info.HasField("signature_documentation") else None,
                "\n".join(sym_info.documentation) if sym_info.documentation else None,
                repository_id,
                snapshot_id,
            ))

        conn.executemany(
            """
            INSERT INTO symbols
                (scip_symbol, symbol_name, kind, language, signature, documentation, repository_id, snapshot_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (scip_symbol, snapshot_id) DO UPDATE SET
                symbol_name   = excluded.symbol_name,
                kind          = excluded.kind,
                language      = COALESCE(excluded.language, symbols.language),
                signature     = COALESCE(excluded.signature, symbols.signature),
                documentation = COALESCE(excluded.documentation, symbols.documentation)
            """,
            rows,
        )

        # Fetch all inserted/updated IDs in one query
        scip_symbols = list({r[0] for r in rows})
        placeholders = ",".join("?" * len(scip_symbols))
        cursor = conn.execute(
            f"""
            SELECT scip_symbol, id FROM symbols
            WHERE scip_symbol IN ({placeholders}) AND snapshot_id = ?
            """,
            (*scip_symbols, snapshot_id),
        )
        for scip_symbol, sym_id in cursor.fetchall():
            scip_symbol_to_id[scip_symbol] = sym_id

        return scip_symbol_to_id
    
    def ingest_relationships(
        self,
        conn: sqlite3.Connection,
        index: Index,
        snapshot_id: int,
        scip_symbol_to_id: dict[str, int],
        ) -> None:
        rows: list[tuple] = []
        errors: list[tuple] = []

        all_sym_infos: list[tuple[str, any]] = [
            (sym_info.symbol, sym_info)
            for doc in index.documents
            for sym_info in doc.symbols
        ]
        for sym_info in index.external_symbols:
            all_sym_infos.append((sym_info.symbol, sym_info))

        for scip_symbol, sym_info in all_sym_infos:
            source_id = scip_symbol_to_id.get(scip_symbol)
            if source_id is None:
                errors.append((
                    snapshot_id,
                    None,  # no document path here
                    scip_symbol,
                    f"ingest_relationships: source symbol not found in cache",
                ))
                continue

            for rel in sym_info.relationships:
                target_id = scip_symbol_to_id.get(rel.symbol)
                if target_id is None:
                    errors.append((
                        snapshot_id,
                        None,
                        rel.symbol,
                        f"ingest_relationships: target symbol '{rel.symbol}' not found in cache (referenced by '{scip_symbol}')",
                    ))
                    continue

                rows.append((
                    source_id,
                    target_id,
                    rel.is_reference,
                    rel.is_implementation,
                    rel.is_type_definition,
                    rel.is_definition,
                    snapshot_id,
                ))

        if rows:
            conn.executemany(
                """
                INSERT INTO relationships
                    (source_symbol_id, target_symbol_id, is_reference, is_implementation,
                    is_type_definition, is_definition, snapshot_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (source_symbol_id, target_symbol_id, snapshot_id) DO UPDATE SET
                    is_reference      = excluded.is_reference,
                    is_implementation = excluded.is_implementation,
                    is_type_definition = excluded.is_type_definition,
                    is_definition     = excluded.is_definition
                """,
                rows,
            )

        if errors:
            conn.executemany(
                """
                INSERT INTO indexing_errors (snapshot_id, document_path, scip_symbol, error_message)
                VALUES (?, ?, ?, ?)
                """,
                errors,
            )