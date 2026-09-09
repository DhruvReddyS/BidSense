import json
from pathlib import Path
from app.review.workflow import classify_query
def test_labeled_router_set_is_perfect():
    rows=json.loads((Path(__file__).parents[2]/"data/router_queries.json").read_text())
    assert len(rows)>=12
    assert all(classify_query(row["question"])==row["route"] for row in rows)
