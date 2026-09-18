"""学生学习向量检索的可复现离线评测。"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from services.knowledge_vector_store import NgramCountEmbedder


DEFAULT_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "student_vector_eval.json"
)


def load_fixture(path: str | Path = DEFAULT_FIXTURE):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return tuple(payload["sources"]), tuple(payload["queries"])


def _cosine_similarity(left, right) -> float:
    if not left or not right:
        return 0.0
    dot = sum(value * right.get(key, 0.0) for key, value in left.items())
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def evaluate_student_vector_fixture(
    path: str | Path = DEFAULT_FIXTURE,
    *,
    embedder=None,
) -> dict[str, Any]:
    """检查作用域过滤、撤回来源过滤和有限检索召回率。"""

    sources, queries = load_fixture(path)
    embedder = embedder or NgramCountEmbedder()
    active_sources = [source for source in sources if source.get("status") == "active"]
    revoked_sources = [source for source in sources if source.get("status") == "revoked"]
    recall_at_1 = []
    recall_at_k = []
    cross_scope_hit_count = 0
    revoked_hit_count = 0
    case_results = []

    for case in queries:
        student_id = str(case["student_id"])
        assignment_id = case.get("assignment_id")
        scoped_sources = [
            source
            for source in active_sources
            if str(source.get("student_id")) == student_id
            and (
                assignment_id is None
                or source.get("assignment_id") == assignment_id
            )
        ]
        query_vector = embedder.embed(case["query"])
        scored = []
        for source in scoped_sources:
            score = _cosine_similarity(query_vector, embedder.embed(source["content"]))
            if score <= 0.0:
                continue
            scored.append((score, str(source["source_id"]), source))
        scored.sort(key=lambda item: (-item[0], item[1]))
        top_k = max(1, int(case.get("top_k", 5)))
        selected = scored[:top_k]
        actual_ids = [item[1] for item in selected]
        expected_ids = set(case.get("relevant_source_ids", []))
        expected_status = case.get("expected_status")
        actual_status = "grounded" if actual_ids else "no_result"

        if any(str(item[2].get("student_id")) != student_id for item in selected):
            cross_scope_hit_count += 1
        if any(
            any(
                revoked.get("source_id") == item[1]
                and str(revoked.get("student_id")) == student_id
                for revoked in revoked_sources
            )
            for item in selected
        ):
            revoked_hit_count += 1

        case_result = {
            "query": case["query"],
            "student_id": student_id,
            "assignment_id": assignment_id,
            "expected_status": expected_status,
            "actual_status": actual_status,
            "retrieved_source_ids": actual_ids,
            "status_match": expected_status in {None, actual_status},
        }
        if expected_ids:
            recall_1 = len(set(actual_ids[:1]) & expected_ids) / len(expected_ids)
            recall_k = len(set(actual_ids[:top_k]) & expected_ids) / len(expected_ids)
            recall_at_1.append(recall_1)
            recall_at_k.append(recall_k)
            case_result["recall_at_1"] = round(recall_1, 3)
            case_result["recall_at_k"] = round(recall_k, 3)
        else:
            case_result["recall_at_1"] = None
            case_result["recall_at_k"] = None
        case_results.append(case_result)

    return {
        "source_count": len(sources),
        "active_source_count": len(active_sources),
        "revoked_source_count": len(revoked_sources),
        "query_count": len(queries),
        "recall_at_1": round(sum(recall_at_1) / len(recall_at_1), 3)
        if recall_at_1
        else 0.0,
        "recall_at_k": round(sum(recall_at_k) / len(recall_at_k), 3)
        if recall_at_k
        else 0.0,
        "cross_scope_hit_count": cross_scope_hit_count,
        "revoked_hit_count": revoked_hit_count,
        "status_mismatch_count": sum(
            1 for result in case_results if not result["status_match"]
        ),
        "case_results": case_results,
    }


def main() -> None:
    print(json.dumps(evaluate_student_vector_fixture(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
