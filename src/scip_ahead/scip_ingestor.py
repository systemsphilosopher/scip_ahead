import sqlite3
from scip_ahead.scip_pb2 import Index
from scip_ahead.scip_ahead_logger import logger


class SCIPIngestor:

    def ingest_scip(
        self,
        db_path: str,
        scip_paths: list[str],
        repo_name: str,
        commit_sha: str,
    ) -> list[str]:
        """
        Ingest one or more SCIP index files into a single repository + snapshot.

        Each index file is ingested in its own transaction so that a failure in
        one project does not abort the others. Returns a list of human-readable
        error messages (empty if everything succeeded). Cross-project references
        resolve automatically because symbols are merged by their global SCIP
        symbol string within the shared snapshot (UNIQUE(scip_symbol, snapshot_id)).
        """
        errors: list[str] = []
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            repository_id = self.get_or_create_repo(conn, repo_name)
            logger.info("ingest_scip: repo=%r id=%d, %d index file(s)",
                        repo_name, repository_id, len(scip_paths))

            snapshot_id = self.check_or_create_snapshot(conn, repository_id, commit_sha)
            if snapshot_id is None:
                logger.warning("ingest_scip: snapshot %r already exists — skipping", commit_sha)
                return [
                    f"Snapshot for {repo_name!r} @ {commit_sha!r} already exists — "
                    f"nothing ingested. Delete the database or index a new commit to re-ingest."
                ]
            logger.info("ingest_scip: using snapshot id=%d", snapshot_id)

            for scip_path in scip_paths:
                try:
                    index = Index()
                    with open(scip_path, "rb") as f:
                        index.ParseFromString(f.read())
                    logger.info("ingesting %s: %d document(s)", scip_path, len(index.documents))

                    conn.execute("BEGIN")
                    doc_ids = self.ingest_docs(conn, index, repository_id, snapshot_id)
                    scip_symbol_to_id = self.ingest_symbols(
                        conn, index, repository_id, snapshot_id
                    )
                    self.ingest_occurrences(
                        conn, index, repository_id, snapshot_id, doc_ids, scip_symbol_to_id
                    )
                    self.ingest_relationships(
                        conn, index, snapshot_id, scip_symbol_to_id
                    )
                    conn.commit()
                    logger.info("ingested %s: %d doc(s), %d symbol(s)",
                                scip_path, len(doc_ids), len(scip_symbol_to_id))
                except Exception as e:
                    conn.rollback()
                    logger.exception("ingest failed for %s", scip_path)
                    errors.append(f"[ingest] {scip_path}: {e}")
        finally:
            conn.close()

        logger.info("ingest_scip complete: %d error(s)", len(errors))
        return errors

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

    def get_or_create_repo(self, conn: sqlite3.Connection, repo_name: str) -> int:
        """Resolve the repository row for the whole repo root, creating it if needed.

        The repository represents the indexed root directory (which may contain
        many projects), so identity is the caller-supplied repo name rather than
        any single index's project_root.
        """
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
            return None

        cursor = conn.execute(
            "INSERT INTO index_snapshots (repository_id, commit_sha) VALUES (?, ?)",
            (repository_id, commit_sha),
        )
        conn.commit()
        return cursor.lastrowid

    @staticmethod
    def _symbol_name_fallback(scip_symbol: str) -> str:
        """
        Extract a readable short name from a SCIP symbol string when display_name
        is absent. SCIP symbols look like:
            scip-dotnet nuget . . ClassLibrary1/Class1Child#class1_child_function1().
        The descriptor after the last '#' or '.' run is the meaningful part.
        Strips trailing punctuation characters that SCIP uses as descriptor suffixes
        (parens, dots, slashes, hashes) so we get 'class1_child_function1' not ''.
        """
        name = scip_symbol.rstrip("()./#").split("/")[-1].split("#")[-1]
        return name or scip_symbol

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
                    sym_info.display_name or self._symbol_name_fallback(sym_info.symbol),
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
                sym_info.display_name or self._symbol_name_fallback(sym_info.symbol),
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

    @staticmethod
    def _decode_range(values) -> tuple[int, int, int, int] | None:
        """
        Decode a SCIP range into (start_line, end_line, start_character, end_character).

        SCIP ranges are variable length (see scip.proto, Range encoding):
          - 4 elements: [start_line, start_char, end_line, end_char]  (spans lines)
          - 3 elements: [start_line, start_char, end_char]            (single line;
                          end_line is implicitly equal to start_line)
        Returns None for an empty/unrecognized range (e.g. an absent enclosing_range).
        """
        vals = list(values)
        if len(vals) == 4:
            return vals[0], vals[2], vals[1], vals[3]
        if len(vals) == 3:
            return vals[0], vals[0], vals[1], vals[2]
        return None

    def ingest_occurrences(
        self,
        conn: sqlite3.Connection,
        index: Index,
        repository_id: int,
        snapshot_id: int,
        doc_ids: dict[str, int],
        scip_symbol_to_id: dict[str, int],
    ) -> None:
        from scip_ahead.scip_pb2 import SyntaxKind

        DEFINITION_ROLE = 0x1  # SymbolRole.Definition (scip.proto)

        # An occurrence's symbol often has no SymbolInformation entry — most
        # references point at namespaces or external/framework symbols
        # (e.g. System/Console#WriteLine). Synthesize minimal symbol rows for
        # those so every occurrence can satisfy the NOT NULL symbol_id FK.
        missing: set[str] = set()
        for doc in index.documents:
            for occ in doc.occurrences:
                if occ.symbol and occ.symbol not in scip_symbol_to_id:
                    missing.add(occ.symbol)

        if missing:
            conn.executemany(
                """
                INSERT INTO symbols (scip_symbol, symbol_name, repository_id, snapshot_id)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (scip_symbol, snapshot_id) DO NOTHING
                """,
                [(s, s, repository_id, snapshot_id) for s in missing],
            )
            placeholders = ",".join("?" * len(missing))
            cursor = conn.execute(
                f"""
                SELECT scip_symbol, id FROM symbols
                WHERE scip_symbol IN ({placeholders}) AND snapshot_id = ?
                """,
                (*missing, snapshot_id),
            )
            for scip_symbol, sym_id in cursor.fetchall():
                scip_symbol_to_id[scip_symbol] = sym_id

        rows: list[tuple] = []
        for doc in index.documents:
            document_id = doc_ids.get(doc.relative_path)
            if document_id is None:
                continue

            for occ in doc.occurrences:
                symbol_id = scip_symbol_to_id.get(occ.symbol)
                if symbol_id is None:
                    continue

                rng = self._decode_range(occ.range)
                if rng is None:
                    continue
                start_line, end_line, start_char, end_char = rng

                enc = self._decode_range(occ.enclosing_range)
                enc_start_line, enc_end_line, enc_start_char, enc_end_char = (
                    enc if enc is not None else (None, None, None, None)
                )

                syntax_kind = (
                    SyntaxKind.Name(occ.syntax_kind)
                    if occ.syntax_kind != SyntaxKind.UnspecifiedSyntaxKind
                    else None
                )
                is_definition = 1 if (occ.symbol_roles & DEFINITION_ROLE) else 0

                rows.append((
                    symbol_id,
                    document_id,
                    start_line,
                    end_line,
                    start_char,
                    end_char,
                    enc_start_line,
                    enc_end_line,
                    enc_start_char,
                    enc_end_char,
                    syntax_kind,
                    is_definition,
                ))

        if rows:
            conn.executemany(
                """
                INSERT INTO occurrences
                    (symbol_id, document_id, start_line, end_line,
                     start_character, end_character,
                     enclosing_start_line, enclosing_end_line,
                     enclosing_start_character, enclosing_end_character,
                     syntax_kind, is_definition)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

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