import subprocess
import os
from pathlib import Path


class SCIPIndexer:
    """
    Generates a SCIP index for a given project.
    Add a new _index_* method per language and dispatch via index().
    """
    SUPPORTED_LANGUAGES = {"dotnet"}

    def index(self, language: str, working_dir: str = None) -> Path:
        """
        Generate a SCIP index for the given language.
        Returns the path to the generated index.scip file.
        """
        language = language.lower().strip()

        if language not in self.SUPPORTED_LANGUAGES:
            raise ValueError(
                f"Unsupported language '{language}'. "
                f"Supported: {', '.join(sorted(self.SUPPORTED_LANGUAGES))}"
            )

        if working_dir is None:
            working_dir = os.getcwd()

        working_dir = Path(working_dir)

        dispatch = {
            "dotnet": self._index_dotnet,
        }

        return dispatch[language](working_dir)

    def _index_dotnet(self, working_dir: Path) -> Path:
        result = subprocess.run(
            ["scip-dotnet", "index", "--working-directory", str(working_dir)],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"scip-dotnet failed:\n"
                f"STDOUT: {result.stdout}\n"
                f"STDERR: {result.stderr}\n"
                f"Return code: {result.returncode}"
            )

        index_path = working_dir / "index.scip"

        if not index_path.exists():
            raise FileNotFoundError(f"index.scip not generated at {index_path}")

        print(f"Index generated: {index_path}")
        print(result.stdout)

        return index_path