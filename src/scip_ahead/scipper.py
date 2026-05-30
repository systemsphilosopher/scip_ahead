import subprocess
import os
import sqlite3
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
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
                with open(schema_path, "r", encoding="utf-8") as f:
                    conn.executescript(f.read())
                print(f"Initialized database schema at {self.DB_PATH}")
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
        repo_root = Path(str(path).strip().strip('"').strip("'"))
        indexer = SCIPIndexer()

        print("Discovering project files...")
        projects = indexer.discover_projects(language, str(repo_root))
        if not projects:
            return f"No {language} project files found under {repo_root}"

        errors: list[str] = []
        index_paths: list[str] = []

        work_dir = Path(tempfile.mkdtemp(prefix="scip_ahead_"))
        try:
            for i, project in enumerate(projects):
                output_path = work_dir / f"{i}_{project.stem}.scip"
                print(f"Indexing {project} ...")
                try:
                    indexer.index_project(language, project, output_path)
                    index_paths.append(str(output_path))
                except Exception as e:
                    errors.append(f"[index] {project}: {e}")

            print("Ingesting...")
            repo_name = repo_root.name or str(repo_root)
            commit_sha = self._resolve_commit_sha(repo_root)
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
            return summary + "\n\nErrors:\n" + "\n".join(f"- {e}" for e in errors)
        return summary + " No errors."

    def _resolve_commit_sha(self, repo_root: Path) -> str:
        """Use the repo's current git commit as the snapshot key when available;
        otherwise fall back to a timestamp so each run gets a fresh snapshot."""
        try:
            result = subprocess.run(
                ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass
        return "snapshot-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def get_schema_context(self) -> str:
        """Opens schema.md from the project root and returns its content as a string."""        
        root_dir = os.path.dirname(os.path.abspath(__file__))
        schema_path = os.path.join(root_dir, "schema.md")
        
        with open(schema_path, "r", encoding="utf-8") as f:
            return f.read()

    def search(self, query : str):
        searcher = SCIPSearcher();
        return searcher.query(query)
