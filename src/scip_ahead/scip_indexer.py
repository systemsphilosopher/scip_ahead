import os
import subprocess
from pathlib import Path

from scip_ahead.scip_ahead_logger import logger


class SCIPIndexer:
    """
    Discovers and indexes project files within a repository.
    Add a new language by extending SUPPORTED_LANGUAGES, PROJECT_SUFFIXES, and the
    dispatch in index_project().
    """
    SUPPORTED_LANGUAGES = {"dotnet"}

    # File suffixes that identify an indexable project per language.
    PROJECT_SUFFIXES = {
        "dotnet": (".csproj", ".vbproj"),
    }

    # Directories never worth descending into: build output, VCS, editor, and
    # dependency caches. Skipping them keeps discovery fast and avoids indexing
    # generated or vendored projects.
    EXCLUDED_DIRS = {
        "bin", "obj", ".git", ".vs", ".idea", ".vscode",
        "node_modules", "packages", ".venv", "venv",
    }

    # Hard ceiling on a single project's indexing run so a hung `dotnet restore`
    # cannot freeze the whole repository index. Slightly above scip-dotnet's own
    # 300s restore default.
    INDEX_TIMEOUT_SECONDS = 360

    def discover_projects(self, language: str, repo_root: str) -> list[Path]:
        """
        Recursively find every project file for the given language under repo_root,
        skipping build/VCS/dependency directories. Returns a sorted, de-duplicated
        list of absolute project file paths.
        """
        language = self._validate_language(language)

        root = Path(str(repo_root).strip().strip('"').strip("'"))
        if not root.is_dir():
            raise NotADirectoryError(f"Repo root is not a directory: {root}")

        suffixes = self.PROJECT_SUFFIXES[language]
        logger.info("discovering %s projects (suffixes=%s) under %s", language, suffixes, root)
        projects: set[Path] = set()
        for dirpath, dirnames, filenames in os.walk(root):
            # Prune excluded directories in place so os.walk does not descend them.
            dirnames[:] = [d for d in dirnames if d not in self.EXCLUDED_DIRS]
            for filename in filenames:
                if filename.endswith(suffixes):
                    projects.add(Path(dirpath) / filename)

        result = sorted(projects)
        logger.info("discovery found %d project file(s)", len(result))
        return result

    def index_project(self, language: str, project_file: Path, output_path: Path) -> Path:
        """
        Generate a SCIP index for a single project file, written to output_path.
        Returns output_path. Raises on failure so the caller can record the error
        and continue with the remaining projects.
        """
        language = self._validate_language(language)

        dispatch = {
            "dotnet": self._index_dotnet_project,
        }
        return dispatch[language](Path(project_file), Path(output_path))

    def _validate_language(self, language: str) -> str:
        language = language.lower().strip()
        if language not in self.SUPPORTED_LANGUAGES:
            raise ValueError(
                f"Unsupported language '{language}'. "
                f"Supported: {', '.join(sorted(self.SUPPORTED_LANGUAGES))}"
            )
        return language

    def _index_dotnet_project(self, project_file: Path, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info("running scip-dotnet for %s -> %s", project_file, output_path)
        try:
            result = subprocess.run(
                [
                    "scip-dotnet", "index",
                    # restore runs in the project's own directory
                    "--working-directory", str(project_file.parent),
                    # write each project's index to its own file (avoids overwrites)
                    "--output", str(output_path),
                    # absolute project path: scip-dotnet resolves positional paths
                    # against the process CWD, not --working-directory
                    str(project_file),
                ],
                capture_output=True,
                text=True,
                timeout=self.INDEX_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"scip-dotnet timed out after {self.INDEX_TIMEOUT_SECONDS}s for {project_file}"
            )

        if result.returncode != 0:
            raise RuntimeError(
                f"scip-dotnet failed for {project_file}:\n"
                f"STDOUT: {result.stdout}\n"
                f"STDERR: {result.stderr}\n"
                f"Return code: {result.returncode}"
            )

        if not output_path.exists():
            raise FileNotFoundError(f"index.scip not generated at {output_path}")

        logger.info("scip-dotnet succeeded for %s", project_file)
        return output_path
