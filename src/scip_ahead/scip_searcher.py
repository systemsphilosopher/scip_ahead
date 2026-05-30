import json
import sqlite3
import sqlparse
from sqlparse.tokens import DML

from scip_ahead.scip_ahead_logger import logger


class SCIPSearcher:

    DB_PATH = "scip_ahead.db"

    FORBIDDEN_KEYWORDS = {
        "INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER",
        "TRUNCATE", "REPLACE", "UPSERT", "ATTACH", "DETACH", "PRAGMA"
    }

    def __is_readonly_query(self, sql: str) -> None:
        """
        Validates that the SQL is a safe, read-only SELECT statement.
        Raises ValueError if the query is rejected for any reason.
        """
        parsed = sqlparse.parse(sql.strip())

        if not parsed or not sql.strip():
            raise ValueError("Empty query")

        if len(parsed) > 1:
            raise ValueError("Multiple statements are not allowed")

        statement = parsed[0]

        first_token = statement.token_first(skip_cm=True)
        if (
            not first_token
            or first_token.ttype not in (DML,)
            or first_token.normalized.upper() != "SELECT"
        ):
            raise ValueError("Only SELECT statements are allowed")

        for token in statement.flatten():
            if token.normalized.upper() in self.FORBIDDEN_KEYWORDS:
                raise ValueError(f"Forbidden keyword detected: {token.normalized}")

    def query(self, sql: str) -> str:
        """
        Executes a read-only SQL query and returns results as a list of dicts.
        Raises ValueError if the query is not a safe SELECT statement.
        Raises sqlite3.OperationalError if the query fails at the database level.
        """
        if not sql or not sql.strip():
            raise ValueError("No SQL provided")

        self.__is_readonly_query(sql)
        logger.info("query validated, executing against %s", self.DB_PATH)

        conn = sqlite3.connect(f"file:{self.DB_PATH}?mode=ro", uri=True)
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(sql)
            rows = [dict(row) for row in cur.fetchall()]
            logger.info("query returned %d row(s)", len(rows))
            return json.dumps(rows, indent=2)
        finally:
            conn.close()