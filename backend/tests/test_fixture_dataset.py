import json
from collections import Counter
from pathlib import Path

DATASET = Path(__file__).parents[2] / "fixtures" / "classroom_questions.jsonl"


def test_fixture_has_enough_labeled_examples() -> None:
    records = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines()]
    questions = [record for record in records if record["is_question"]]
    cluster_sizes = Counter(record["expected_cluster"] for record in questions)

    assert len(records) >= 60
    assert len(cluster_sizes) >= 8
    assert all(size >= 4 for size in cluster_sizes.values())
    assert {record["split"] for record in questions} == {"train", "eval"}
    assert len({record["id"] for record in records}) == len(records)
