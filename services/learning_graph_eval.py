def _edge_key(edge):
    return (
        str(edge.get("source") or ""),
        str(edge.get("target") or ""),
        str(edge.get("relation_type") or ""),
        str(edge.get("scope") or ""),
    )


def _edge_sample(key):
    return {
        "source": key[0],
        "target": key[1],
        "relation_type": key[2],
        "scope": key[3],
    }


def evaluate_student_learning_graph(graph, *, assignment_id, expected):
    """按固定样例衡量学生图谱的关系召回、来源和权限范围。"""

    assignment_node = f"assignment:{assignment_id}"
    knowledge_nodes = {
        f"knowledge:{code}"
        for code in expected.get("knowledge_points", [])
    }
    expected_nodes = {assignment_node, *knowledge_nodes}
    expected_edges = set()

    for resource in expected.get("learning_resources", []):
        resource_node = f"resource:{resource['resource_id']}"
        expected_nodes.add(resource_node)
        expected_edges.add((
            assignment_node, resource_node, "provides", "student_assignments",
        ))
        expected_edges.add((
            resource_node,
            f"knowledge:{resource['knowledge_point']}",
            "explains", "student_assignments",
        ))

    for code in expected.get("knowledge_points", []):
        expected_edges.add(
            (
                assignment_node,
                f"knowledge:{code}",
                "covers",
                "student_assignments",
            )
        )
    for code in expected.get("mastery_points", []):
        expected_edges.add(
            (
                "student:mastery",
                f"knowledge:{code}",
                "mastery",
                "student_private",
            )
        )
    for pair in expected.get("co_occurrence_pairs", []):
        left, right = sorted(pair)
        expected_edges.add(
            (
                f"knowledge:{left}",
                f"knowledge:{right}",
                "co_occurs",
                "student_assignments",
            )
        )

    nodes = list(graph.get("nodes") or [])
    edges = list(graph.get("edges") or [])
    actual_node_ids = {
        str(node.get("id"))
        for node in nodes
        if node.get("id")
    }
    actual_edges = {_edge_key(edge) for edge in edges}
    missing_nodes = sorted(expected_nodes - actual_node_ids)
    unexpected_nodes = sorted(actual_node_ids - expected_nodes)
    missing_edges = sorted(expected_edges - actual_edges)
    unexpected_edges = sorted(actual_edges - expected_edges)
    edges_missing_provenance = [
        {
            "source": str(edge.get("source") or ""),
            "target": str(edge.get("target") or ""),
            "relation_type": str(edge.get("relation_type") or ""),
        }
        for edge in edges
        if not edge.get("source_refs") or not edge.get("source_version")
    ]
    allowed_scopes = set(expected.get("allowed_edge_scopes", []))
    scope_leak_count = int(
        (graph.get("meta") or {}).get("scope") != "student"
    ) + sum(edge.get("scope") not in allowed_scopes for edge in edges)
    forbidden_points = set(expected.get("forbidden_knowledge_points", []))
    forbidden_hits = sorted(
        str(node.get("code"))
        for node in nodes
        if node.get("type") == "knowledge_point"
        and node.get("code") in forbidden_points
    )
    matched_node_count = len(expected_nodes & actual_node_ids)
    matched_edge_count = len(expected_edges & actual_edges)

    return {
        "expected_node_count": len(expected_nodes),
        "actual_node_count": len(actual_node_ids),
        "node_precision": round(
            matched_node_count / len(actual_node_ids),
            3,
        ) if actual_node_ids else 1.0,
        "node_recall": round(
            matched_node_count / len(expected_nodes),
            3,
        ) if expected_nodes else 1.0,
        "expected_edge_count": len(expected_edges),
        "actual_edge_count": len(actual_edges),
        "edge_precision": round(
            matched_edge_count / len(actual_edges),
            3,
        ) if actual_edges else 1.0,
        "edge_recall": round(
            matched_edge_count / len(expected_edges),
            3,
        ) if expected_edges else 1.0,
        "source_completeness": round(
            (len(edges) - len(edges_missing_provenance)) / len(edges),
            3,
        ) if edges else 1.0,
        "scope_leak_count": scope_leak_count,
        "forbidden_knowledge_point_count": len(forbidden_hits),
        "failure_samples": {
            "missing_node_ids": missing_nodes,
            "unexpected_node_ids": unexpected_nodes,
            "missing_edges": [_edge_sample(edge) for edge in missing_edges],
            "unexpected_edges": [_edge_sample(edge) for edge in unexpected_edges],
            "edges_missing_provenance": edges_missing_provenance,
            "forbidden_knowledge_points": forbidden_hits,
        },
    }
