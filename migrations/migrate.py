"""Database migration runner — applies 001_schema.sql and 002_seed.sql."""
import sys
from pathlib import Path
import mysql.connector

# Ensure backend root is in sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.config import Config


def run_sql_file(conn, file_path: Path):
    print(f"Executing {file_path.name}...")
    with open(file_path, "r", encoding="utf-8") as f:
        sql_content = f.read()

    cursor = conn.cursor()
    statement_count = 0
    for result in cursor.execute(sql_content, multi=True):
        statement_count += 1
        if result.with_rows:
            result.fetchall()
    conn.commit()
    cursor.close()
    print(f"Successfully applied {file_path.name} ({statement_count} statements).")


def main():
    print(f"Connecting to MySQL at {Config.MYSQL_HOST}:{Config.MYSQL_PORT} (DB: {Config.MYSQL_DATABASE}, User: {Config.MYSQL_USER})...")
    conn = mysql.connector.connect(
        host=Config.MYSQL_HOST,
        port=Config.MYSQL_PORT,
        user=Config.MYSQL_USER,
        password=Config.MYSQL_PASSWORD,
        database=Config.MYSQL_DATABASE,
        autocommit=False,
    )

    migrations_dir = Path(__file__).resolve().parent
    schema_file = migrations_dir / "001_schema.sql"
    seed_file = migrations_dir / "002_seed.sql"

    run_sql_file(conn, schema_file)
    run_sql_file(conn, seed_file)

    conn.close()
    print("Database schema and seed data loaded successfully!")


if __name__ == "__main__":
    main()
