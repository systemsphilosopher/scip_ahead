from fastmcp import FastMCP
from scip_ahead.scip_ahead_logger import logger
from scip_ahead.scipper import SCIPper

mcp = FastMCP("SCIPAhead")
scipper = SCIPper()


@mcp.tool()
def index(language: str, path: str) -> str:
    """Index a codebase and ingest the SCIP data into the database.

    Args:
        language: The programming language of the codebase (e.g. 'dotnet', 'python')
        path: The absolute path to the root of the codebase to index
    """
    logger.info("tool index(language=%r, path=%r)", language, path)
    return scipper.index(language, path)


@mcp.tool()
def get_schema_context() -> str:
    """Returns the database schema context from schema.md to help construct valid queries."""
    logger.info("tool get_schema_context()")
    return scipper.get_schema_context()


@mcp.tool()
def search(query: str) -> str:
    """Execute a SQL query against the SCIP symbol database.

    Args:
        query: A SQL query string (e.g. 'SELECT * FROM symbols WHERE name LIKE \\'%Foo%\\'')
    """
    logger.info("tool search(query=%r)", query)
    return scipper.search(query)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()