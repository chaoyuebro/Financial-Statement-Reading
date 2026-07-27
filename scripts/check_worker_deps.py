import sys
mods = ["psycopg2", "redis", "fitz", "pgvector", "dotenv", "pymupdf"]
missing = []
for m in mods:
    try:
        __import__(m)
    except ImportError:
        missing.append(m)
print("deps OK" if not missing else f"missing: {missing}")
sys.exit(0 if not missing else 1)