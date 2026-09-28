import importlib
import importlib.util
import json
from pathlib import Path

from models import AssignmentKnowledgePoint, db
from services.learning_graph import build_student_learning_graph
from tests.test_learning_graph import learning_graph_context


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "knowledge_graph_eval.json"


def _evaluate(graph, assignment_id, case):
    specification = importlib.util.find_spec("services.learning_graph_eval")
    assert specification is not None, "图谱离线评测器尚未提供"
    evaluator = importlib.import_module("services.learning_graph_eval")
    return evaluator.evaluate_student_learning_graph(
        graph,
        assignment_id=assignment_id,
        expected=case,
    )


def test_graph_fixture_measures_sources_scope_and_expected_relations(
    learning_graph_context,
):
    app, ids = learning_graph_context
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    with app.app_context():
        graph = build_student_learning_graph(
            student_id=ids["student_one"],
            assignment_id=ids["assignment_one"],
        )
        metrics = _evaluate(graph, ids["assignment_one"], fixture["initial"])

    assert metrics["node_precision"] == 1.0
    assert metrics["node_recall"] == 1.0
    assert metrics["edge_precision"] == 1.0
    assert metrics["edge_recall"] == 1.0
    assert metrics["source_completeness"] == 1.0
    assert metrics["scope_leak_count"] == 0
    assert metrics["forbidden_knowledge_point_count"] == 0
    assert metrics["failure_samples"] == {
        "missing_node_ids": [],
        "unexpected_node_ids": [],
        "missing_edges": [],
        "unexpected_edges": [],
        "edges_missing_provenance": [],
        "forbidden_knowledge_points": [],
    }


def test_graph_fixture_confirms_removed_assignment_source_is_absent(
    learning_graph_context,
):
    app, ids = learning_graph_context
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    with app.app_context():
        removed_source = AssignmentKnowledgePoint.query.filter_by(
            assignment_id=ids["assignment_one"],
            knowledge_point="array",
        ).one()
        db.session.delete(removed_source)
        db.session.add(
            AssignmentKnowledgePoint(
                assignment_id=ids["assignment_one"],
                knowledge_point="linked_list",
                auto_detected=False,
            )
        )
        db.session.commit()
        graph = build_student_learning_graph(
            student_id=ids["student_one"],
            assignment_id=ids["assignment_one"],
        )
        metrics = _evaluate(graph, ids["assignment_one"], fixture["after_retag"])

    assert metrics["node_precision"] == 1.0
    assert metrics["node_recall"] == 1.0
    assert metrics["edge_precision"] == 1.0
    assert metrics["edge_recall"] == 1.0
    assert metrics["source_completeness"] == 1.0
    assert metrics["scope_leak_count"] == 0
    assert metrics["forbidden_knowledge_point_count"] == 0
