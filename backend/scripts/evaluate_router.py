"""Reproducible Level 3 intent-router evaluation."""
from __future__ import annotations
import json
from pathlib import Path
from app.review.workflow import classify_query

def main() -> int:
    path=Path(__file__).parents[2]/"data/router_queries.json"
    rows=json.loads(path.read_text())
    predictions=[{**row,"predicted":classify_query(row["question"])} for row in rows]
    correct=sum(row["route"]==row["predicted"] for row in predictions)
    print(json.dumps({"total":len(rows),"correct":correct,"accuracy":correct/len(rows),"rows":predictions},indent=2))
    return 0 if correct==len(rows) else 1
if __name__=="__main__": raise SystemExit(main())
