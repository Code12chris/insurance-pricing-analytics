"""Run an SQL file statement by statement against insurance.db and print the results.

Usage:
    python run_sql.py                         # runs policies_analysis.sql
    python run_sql.py policies_analysis.sql 3 # only statements from chapter 3 on

The database is created by main.py (tables policies and claims from the CSV files).
Each result is printed together with the comment line directly above the query,
and the run time per statement is shown (useful for the index comparison).
"""
import sqlite3
import sys
import time

import pandas as pd

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 20)
pd.set_option("display.max_rows", 40)


def split_statements(sql_text):
    """Split into complete statements.

    Returns (title, code) pairs: title is the last '--' comment line directly
    above the statement, code is the statement without leading comments.
    """
    statements, buffer = [], ""
    for line in sql_text.splitlines():
        buffer += line + "\n"
        if sqlite3.complete_statement(buffer):
            statements.append(strip_leading_comments(buffer))
            buffer = ""
    return [s for s in statements if s[1] and s[1] != ";"]


def strip_leading_comments(chunk):
    """Remove /* ... */ blocks and -- lines before the code, remember the title."""
    group, code = [], chunk.strip()
    while True:
        if code.startswith("/*"):
            code = code[code.find("*/") + 2:].strip()
            group = []
        elif code.startswith("--"):
            line, _, code = code.partition("\n")
            text = line.lstrip("-").strip()
            # a separator line (only dashes) starts a new comment group
            group = group + [text] if text else []
            code = code.strip()
        else:
            return " ".join(group), code


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "policies_analysis.sql"
    start_chapter = sys.argv[2] if len(sys.argv) > 2 else None
    sql_text = open(path, encoding="utf-8").read()
    if start_chapter:
        marker = f"-- CHAPTER {start_chapter}"
        if marker not in sql_text:
            sys.exit(f"'{marker}' not found in {path}")
        sql_text = sql_text[sql_text.index(marker):]

    # isolation_level=None: Python does not open or commit transactions itself,
    # BEGIN / COMMIT in the SQL file are executed exactly as written
    con = sqlite3.connect("insurance.db", isolation_level=None)
    for i, (title, code) in enumerate(split_statements(sql_text), start=1):
        t0 = time.perf_counter()
        cur = con.execute(code)
        rows = cur.fetchall()
        elapsed = time.perf_counter() - t0
        first_line = code.splitlines()[0]
        print(f"\n[{i}] {title}\n    {first_line} ...  ({elapsed * 1000:.0f} ms)")
        if cur.description:
            cols = [d[0] for d in cur.description]
            print(pd.DataFrame(rows, columns=cols).to_string(index=False))
    con.close()


if __name__ == "__main__":
    main()
