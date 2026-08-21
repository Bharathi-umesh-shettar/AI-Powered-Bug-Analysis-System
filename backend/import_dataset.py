"""Import the historical bug CSV into the knowledge_base table."""
import os
import pandas as pd
from database import init_db, insert_knowledge_bulk

CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "datasets", "bug_dataset.csv")


def import_csv(path=CSV_PATH):
    init_db()
    df = pd.read_csv(path).fillna("")
    required = ["bug_id", "title", "description", "category", "severity", "root_cause", "suggested_fix", "created_at"]
    for col in required:
        if col not in df.columns:
            df[col] = ""
    records = [
        (
            int(row["bug_id"]) if str(row["bug_id"]).strip().isdigit() else i + 1,
            str(row["title"]),
            str(row["description"]),
            str(row["category"]),
            str(row["severity"]),
            str(row["root_cause"]),
            str(row["suggested_fix"]),
            str(row["created_at"]) or "",
        )
        for i, row in df.iterrows()
    ]
    insert_knowledge_bulk(records)
    print(f"Imported {len(records)} bug records into knowledge_base.")


if __name__ == "__main__":
    import_csv()