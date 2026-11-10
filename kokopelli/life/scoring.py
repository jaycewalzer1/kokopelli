"""The only code allowed to read a life's hidden target. Nothing in the engine imports this."""


def load_target(store, run_id):
    row = store.conn.execute("SELECT target FROM hidden_targets WHERE run_id = ?", (run_id,)).fetchone()
    return row["target"] if row else None
