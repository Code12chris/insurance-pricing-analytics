"""Cross-check: does the SQL cleaning (policies_analysis.sql, chapter 2) give
exactly the same data as the Python cleaning (data_prep.clean)?

Run after:  python main.py   and   python run_sql.py
Two independent implementations of the same rules that agree are a strong
check that neither contains a mistake.
"""
import sqlite3

import numpy as np
import pandas as pd

from data_prep import load_raw, clean

con = sqlite3.connect("insurance.db")
sql_pol = pd.read_sql_query("SELECT * FROM policies_clean ORDER BY IDpol", con)
sql_cl = pd.read_sql_query("SELECT IDpol, ClaimAmount FROM claims_clean", con)
con.close()

py_pol, py_cl = clean(*load_raw(), verbose=False)
py_pol = py_pol.sort_values("IDpol").reset_index(drop=True)

checks = {
    "same number of policies": len(sql_pol) == len(py_pol),
    "same policy IDs": np.array_equal(sql_pol["IDpol"].to_numpy(), py_pol["IDpol"].astype(int).to_numpy()),
    "same exposure per policy": np.allclose(sql_pol["Exposure"], py_pol["Exposure"]),
    "same ClaimNb per policy": np.array_equal(sql_pol["ClaimNb"], py_pol["ClaimNb"]),
    "same number of claims": len(sql_cl) == len(py_cl),
    "same total claim amount": np.isclose(sql_cl["ClaimAmount"].sum(), py_cl["ClaimAmount"].sum()),
    "same claim amounts per policy": sql_cl.groupby("IDpol")["ClaimAmount"].sum().sort_index()
        .round(2).equals(py_cl.groupby(py_cl["IDpol"].astype(int))["ClaimAmount"].sum().sort_index().round(2)),
}
for name, ok in checks.items():
    print(f"{'OK  ' if ok else 'FAIL'}  {name}")
print(f"\nSQL: {len(sql_pol):,} policies, {len(sql_cl):,} claims | "
      f"Python: {len(py_pol):,} policies, {len(py_cl):,} claims")
if not all(checks.values()):
    raise SystemExit("SQL and Python cleaning differ")
