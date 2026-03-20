import subprocess
import os
from pathlib import Path
from Classes.scip_ingestor import SCIPIngestor
import struct
from Classes.scip_indexer import SCIPIndexer
from Classes.scip_searcher import SCIPSearcher

class SCIPper:

    def index(self, language : str, path : str):
        print("Indexing...")    
        indexer = SCIPIndexer();
        index_result = indexer.index(language, path)

        print("Ingesting...")
        ingestor = SCIPIngestor();
        ingestor.ingest_scip('scip_ahead.db', path + r"\index.scip", str(index_result))    

    def get_schema_context(self) -> str:
        """Opens schema.md from the project root and returns its content as a string."""        
        root_dir = os.path.dirname(os.path.abspath(__file__))
        schema_path = os.path.join(root_dir, "schema.md")
        
        with open(schema_path, "r", encoding="utf-8") as f:
            return f.read()

    def search(self, query : str):
        searcher = SCIPSearcher();
        return searcher.query(query)
