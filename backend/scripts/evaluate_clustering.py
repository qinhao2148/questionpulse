from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import adjusted_rand_score


@dataclass(frozen=True)
class Record:
    id: str
    text: str
    participant_id: str
    expected_cluster: str
    split: str
    is_question: bool


def load_records(path: Path) -> list[Record]:
    records: list[Record] = []
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                records.append(Record(**json.loads(line)))
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError(f"Invalid JSONL record at line {line_number}") from exc
    return records


def normalize(text: str) -> str:
    return "".join(text.lower().strip().split())


def pairwise_counts(expected: list[str], predicted: list[int]) -> tuple[int, int, int]:
    true_positive = false_positive = false_negative = 0
    for left in range(len(expected)):
        for right in range(left + 1, len(expected)):
            same_expected = expected[left] == expected[right]
            same_predicted = predicted[left] == predicted[right]
            if same_expected and same_predicted:
                true_positive += 1
            elif not same_expected and same_predicted:
                false_positive += 1
            elif same_expected and not same_predicted:
                false_negative += 1
    return true_positive, false_positive, false_negative


def metrics(expected: list[str], predicted: list[int]) -> dict[str, float]:
    true_positive, false_positive, false_negative = pairwise_counts(expected, predicted)
    precision = (
        true_positive / (true_positive + false_positive)
        if true_positive + false_positive
        else 0
    )
    recall = (
        true_positive / (true_positive + false_negative)
        if true_positive + false_negative
        else 0
    )
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "ari": adjusted_rand_score(expected, predicted),
    }


def online_cluster(similarity: np.ndarray, threshold: float) -> list[int]:
    assignments: list[int] = []
    members: dict[int, list[int]] = defaultdict(list)

    for item_index in range(similarity.shape[0]):
        if not members:
            cluster_id = 0
        else:
            scores = {
                cluster_id: max(similarity[item_index, member] for member in cluster_members)
                for cluster_id, cluster_members in members.items()
            }
            best_cluster, best_score = max(scores.items(), key=lambda item: item[1])
            cluster_id = best_cluster if best_score >= threshold else max(members) + 1
        assignments.append(cluster_id)
        members[cluster_id].append(item_index)
    return assignments


def find_errors(
    records: list[Record], similarity: np.ndarray, threshold: float, limit: int = 8
) -> list[dict[str, object]]:
    errors: list[dict[str, object]] = []
    for left in range(len(records)):
        for right in range(left + 1, len(records)):
            same_expected = records[left].expected_cluster == records[right].expected_cluster
            predicted_same = float(similarity[left, right]) >= threshold
            if same_expected == predicted_same:
                continue
            errors.append(
                {
                    "kind": "false_merge" if predicted_same else "false_split",
                    "score": round(float(similarity[left, right]), 4),
                    "left": records[left].text,
                    "right": records[right].text,
                    "left_cluster": records[left].expected_cluster,
                    "right_cluster": records[right].expected_cluster,
                }
            )
    return sorted(
        errors,
        key=lambda item: (-float(item["score"]))
        if item["kind"] == "false_merge"
        else float(item["score"]),
    )[:limit]


def evaluate(dataset_path: Path) -> dict[str, object]:
    all_records = load_records(dataset_path)
    records = [record for record in all_records if record.is_question]
    texts = [normalize(record.text) for record in records]
    expected = [record.expected_cluster for record in records]

    vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 4), min_df=1, sublinear_tf=True)
    matrix = vectorizer.fit_transform(texts)
    similarity = (matrix @ matrix.T).toarray()

    train_indices = [index for index, record in enumerate(records) if record.split == "train"]
    eval_indices = [index for index, record in enumerate(records) if record.split == "eval"]
    train_similarity = similarity[np.ix_(train_indices, train_indices)]
    eval_similarity = similarity[np.ix_(eval_indices, eval_indices)]
    train_expected = [expected[index] for index in train_indices]
    eval_expected = [expected[index] for index in eval_indices]
    eval_records = [records[index] for index in eval_indices]

    candidates: list[dict[str, float]] = []
    best: tuple[float, dict[str, float]] | None = None
    for threshold in np.arange(0.15, 0.61, 0.01):
        predicted = online_cluster(train_similarity, float(threshold))
        result = metrics(train_expected, predicted)
        candidates.append({"threshold": round(float(threshold), 2), **result})
        if best is None or result["f1"] > best[1]["f1"]:
            best = (float(threshold), result)

    assert best is not None
    threshold, train_result = best
    eval_predicted = online_cluster(eval_similarity, threshold)
    eval_result = metrics(eval_expected, eval_predicted)
    train_count = sum(record.split == "train" for record in records)
    eval_count = sum(record.split == "eval" for record in records)
    cluster_count = len(set(eval_predicted))

    return {
        "dataset": str(dataset_path),
        "records_total": len(all_records),
        "question_records": len(records),
        "non_question_records": len(all_records) - len(records),
        "train_records": train_count,
        "eval_records": eval_count,
        "expected_clusters": len(set(expected)),
        "predicted_clusters": cluster_count,
        "method": "character n-gram TF-IDF (2-4) + online nearest-cluster threshold",
        "best_threshold": round(threshold, 2),
        "selection": "threshold selected on train split; metrics reported on held-out eval split",
        "train_metrics": {key: round(value, 4) for key, value in train_result.items()},
        "metrics": {key: round(value, 4) for key, value in eval_result.items()},
        "errors": find_errors(eval_records, eval_similarity, threshold),
        "threshold_search": [
            {key: round(value, 4) for key, value in candidate.items()}
            for candidate in candidates
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the offline QuestionPulse baseline.")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = evaluate(args.dataset)
    content = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content + "\n", encoding="utf-8")
    print(content)


if __name__ == "__main__":
    main()

