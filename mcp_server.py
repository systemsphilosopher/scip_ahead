from fastmcp import FastMCP
from Classes.scipper import SCIPper

mcp = FastMCP("SCIPAhead")
scipper = SCIPper()


@mcp.tool()
def index(language: str, path: str) -> str:
    """Index a codebase and ingest the SCIP data into the database.
    
    Args:
        language: The programming language of the codebase (e.g. 'dotnet', 'python')
        path: The absolute path to the root of the codebase to index
    """
    scipper.index(language, path)
    return f"Successfully indexed and ingested {path}"


@mcp.tool()
def get_schema_context() -> str:
    """Returns the database schema context from schema.md to help construct valid queries."""
    return scipper.get_schema_context()


@mcp.tool()
def search(query: str) -> str:
    """Execute a SQL query against the SCIP symbol database.
    
    Args:
        query: A SQL query string (e.g. 'SELECT * FROM symbols WHERE name LIKE \\'%Foo%\\'')
    """
    return scipper.search(query)


if __name__ == "__main__":
    mcp.run()