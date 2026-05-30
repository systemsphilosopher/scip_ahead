import os
import sqlite3
import shutil
import tempfile
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from scip_ahead.scip_ahead_logger import logger
from scip_ahead.scip_ingestor import SCIPIngestor
from scip_ahead.scip_indexer import SCIPIndexer
from scip_ahead.scip_searcher import SCIPSearcher


class SCIPper:

    DB_PATH = "scip_ahead.db"

    def __init__(self):
        self._ensure_database()

    def _ensure_database(self) -> None:
        """Create the database file (if missing) and apply schema.sql when the
        database is empty. Runs at startup so a fresh checkout works out of the box."""
        schema_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "schema.sql"
        )
        # connect() creates the file if it does not exist
        conn = sqlite3.connect(self.DB_PATH)
        try:
            already_initialized = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='repositories'"
            ).fetchone()
            if already_initialized is None:
                logger.info("database empty — applying schema from %s to %s",
                            schema_path, os.path.abspath(self.DB_PATH))
                with open(schema_path, "r", encoding="utf-8") as f:
                    conn.executescript(f.read())
            else:
                logger.debug("database already initialized at %s",
                             os.path.abspath(self.DB_PATH))
        finally:
            conn.close()

    def index(self, language: str, path: str) -> str:
        """
        Treat `path` as the root of a repository that may contain many project
        files. Discover every project, index each one, and ingest all of the
        resulting SCIP files into a single snapshot. Indexing/ingestion errors for
        individual projects are collected and reported at the end rather than
        aborting the whole run.
        """
        t0 = time.monotonic()
        logger.info(
            "index() called: language=%r path=%r cwd=%r db=%r",
            language, path, os.getcwd(), os.path.abspath(self.DB_PATH),
        )
        try:
            repo_root = Path(str(path).strip().strip('"').strip("'"))
            indexer = SCIPIndexer()

            projects = indexer.discover_projects(language, str(repo_root))
            logger.info("discovered %d project(s): %s", len(projects), [str(p) for p in projects])
            if not projects:
                return f"No {language} project files found under {repo_root}"

            errors: list[str] = []
            index_paths: list[str] = []

            work_dir = Path(tempfile.mkdtemp(prefix="scip_ahead_"))
            try:
                for i, project in enumerate(projects):
                    output_path = work_dir / f"{i}_{project.stem}.scip"
                    p0 = time.monotonic()
                    logger.info("indexing [%d/%d] %s", i + 1, len(projects), project)
                    try:
                        indexer.index_project(language, project, output_path)
                        index_paths.append(str(output_path))
                        logger.info("  done in %.1fs", time.monotonic() - p0)
                    except Exception as e:
                        logger.exception("  failed after %.1fs", time.monotonic() - p0)
                        errors.append(f"[index] {project}: {e}")

                repo_name = repo_root.name or str(repo_root)
                commit_sha = self._resolve_commit_sha(repo_root)
                logger.info("ingesting %d index file(s) as repo=%r commit=%r",
                            len(index_paths), repo_name, commit_sha)
                errors.extend(
                    SCIPIngestor().ingest_scip(
                        self.DB_PATH, index_paths, repo_name, commit_sha
                    )
                )
            finally:
                shutil.rmtree(work_dir, ignore_errors=True)

            summary = (
                f"Indexed {len(index_paths)}/{len(projects)} project(s) under {repo_root}."
            )
            if errors:
                summary += "\n\nErrors:\n" + "\n".join(f"- {e}" for e in errors)
            else:
                summary += " No errors."
            logger.info("index() returning after %.1fs: %s", time.monotonic() - t0, summary)
            return summary
        except Exception:
            logger.error("index() raised after %.1fs:\n%s",
                         time.monotonic() - t0, traceback.format_exc())
            raise

    def _resolve_commit_sha(self, repo_root: Path) -> str:
        """Snapshot key for this indexing run. A timestamp gives each run its own
        snapshot."""
        return "snapshot-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def get_schema_context(self) -> str:
        """Opens schema.md from the project root and returns its content as a string."""
        root_dir = os.path.dirname(os.path.abspath(__file__))
        schema_path = os.path.join(root_dir, "schema.md")

        logger.info("get_schema_context() reading %s", schema_path)
        with open(schema_path, "r", encoding="utf-8") as f:
            return f.read()

    def search(self, query: str):
        logger.info("search() called")
        searcher = SCIPSearcher()
        return searcher.query(query)
