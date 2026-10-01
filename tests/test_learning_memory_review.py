"""Real-source regressions for the student reflection path."""

import pytest

from models import AssignmentKnowledgePoint, StudentLearningVector, Submission, User, db
from services import student_vector_store as store
from services.learning_graph import build_student_learning_graph
from tests.test_student_vector_store import vector_context, seeded_student_vector_context


def _login(app, student_id):
    client = app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = student_id
        session['_fresh'] = True
    return client


def test_changed_feedback_is_not_recalled_before_rebuild(seeded_student_vector_context):
    app, ids = seeded_student_vector_context
    with app.app_context():
        store.rebuild_student_vector_index(ids['student_one'])
        submission = db.session.get(Submission, ids['submission_one'])
        submission.feedback = '现在请检查数组下标。'
        submission.ai_feedback = ''
        db.session.commit()
        result = store.search_student_learning_vectors(ids['student_one'], '递归边界和终止条件')
        assert not any(item['source_type'] == 'submission_feedback' for item in result['evidence'])
        assert result['metrics']['outdated_source_count'] == 1
        store.rebuild_student_vector_index(ids['student_one'])
        fresh = store.search_student_learning_vectors(ids['student_one'], '数组下标')
        assert any('数组下标' in item['content'] for item in fresh['evidence'])


@pytest.mark.parametrize('change', ['deleted', 'pending', 'owner'])
def test_ineligible_submission_is_not_recalled(seeded_student_vector_context, change):
    app, ids = seeded_student_vector_context
    with app.app_context():
        store.rebuild_student_vector_index(ids['student_one'])
        submission = db.session.get(Submission, ids['submission_one'])
        if change == 'deleted':
            db.session.delete(submission)
        elif change == 'pending':
            submission.status = 'pending'
        else:
            submission.student_id = ids['student_two']
        db.session.commit()
        result = store.search_student_learning_vectors(ids['student_one'], '递归边界和终止条件')
        assert not any(item['source_type'] == 'submission_feedback' for item in result['evidence'])


@pytest.mark.parametrize('payload', ['broken', '[]', '{"递归": "bad"}', '{"递归": NaN}'])
def test_corrupt_embedding_does_not_break_other_memory(seeded_student_vector_context, payload):
    app, ids = seeded_student_vector_context
    with app.app_context():
        store.rebuild_student_vector_index(ids['student_one'])
        row = StudentLearningVector.query.filter_by(source_type='submission_feedback').one()
        row.embedding = payload
        db.session.commit()
        result = store.search_student_learning_vectors(ids['student_one'], '递归')
        assert result['status'] == 'grounded'
        assert all(item['source_type'] != 'submission_feedback' for item in result['evidence'])
        assert result['metrics']['invalid_source_count'] == 1
        store.rebuild_student_vector_index(ids['student_one'])
        repaired = store.search_student_learning_vectors(ids['student_one'], '递归边界和终止条件')
        assert any(item['source_type'] == 'submission_feedback' for item in repaired['evidence'])


def test_review_page_search_return_and_withdrawal(seeded_student_vector_context):
    app, ids = seeded_student_vector_context
    with app.app_context():
        store.rebuild_student_vector_index(ids['student_one'])
    client = _login(app, ids['student_one'])
    response = client.get('/student/learning-memory?q=递归边界')
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert '递归边界和终止条件' in page
    assert f'/view_submission/{ids["submission_one"]}' in page
    withdrawn = client.post('/student/learning-memory/revoke', data={
        'source_type': 'submission_feedback', 'source_id': f'submission:{ids["submission_one"]}',
        'return_to': 'learning_memory', 'q': '递归边界',
    }, follow_redirects=True)
    assert withdrawn.status_code == 200
    assert '递归边界和终止条件' not in withdrawn.get_data(as_text=True)
    assert 'value="递归边界"' in withdrawn.get_data(as_text=True)


def test_review_scope_and_nonstudent_access(seeded_student_vector_context):
    app, ids = seeded_student_vector_context
    client = _login(app, ids['student_two'])
    response = client.get(f'/student/learning-memory?assignment_id={ids["assignment_one"]}&q=递归')
    assert response.status_code == 403
    assert _login(app, ids['student_one']).get('/student/learning-memory?assignment_id=nope').status_code == 400


def test_memory_citations_resolve_to_owned_submission(seeded_student_vector_context):
    app, ids = seeded_student_vector_context
    with app.app_context():
        store.rebuild_student_vector_index(ids['student_one'])
        result = store.search_student_learning_vectors(ids['student_one'], '递归边界和终止条件')
        receipt = store.render_student_learning_receipt(result)
        assert f'/view_submission/{ids["submission_one"]}' in receipt
        evidence = store.project_student_learning_evidence(result)['evidence']
        assert any(item.get('submission_id') == ids['submission_one'] for item in evidence)


def test_graph_and_assignment_lead_to_scoped_reflection(seeded_student_vector_context):
    app, ids = seeded_student_vector_context
    with app.app_context():
        db.session.add(AssignmentKnowledgePoint(assignment_id=ids['assignment_one'], knowledge_point='recursion'))
        db.session.commit()
    client = _login(app, ids['student_one'])
    home = client.get('/home').get_data(as_text=True)
    assert '回顾相关学习记录' in home
    detail = client.get(f'/view_assignment/{ids["assignment_one"]}').get_data(as_text=True)
    assert '回顾本题学习记录' in detail


def test_graph_memory_edges_follow_live_source_and_withdrawal(seeded_student_vector_context):
    app, ids = seeded_student_vector_context
    with app.app_context():
        store.rebuild_student_vector_index(ids['student_one'])
        graph = build_student_learning_graph(student_id=ids['student_one'])
        edges = [edge for edge in graph['edges'] if edge['relation_type'] == 'reflects_on']
        assert len(edges) == 1
        assert edges[0]['scope'] == 'student_private'
        assert edges[0]['source_refs'] == [f'submission:{ids["submission_one"]}']
        assert len(edges[0]['source_version']) == 64
        store.revoke_student_vector_source(ids['student_one'], 'submission_feedback', f'submission:{ids["submission_one"]}')
        withdrawn = build_student_learning_graph(student_id=ids['student_one'])
        assert not any(edge['relation_type'] == 'reflects_on' for edge in withdrawn['edges'])


def test_rebuild_recovery_retains_query_and_never_restores_revoked_source(seeded_student_vector_context, monkeypatch):
    app, ids = seeded_student_vector_context
    client = _login(app, ids['student_one'])
    first = client.get('/student/learning-memory?q=递归边界')
    assert '索引还没有准备好' in first.get_data(as_text=True)
    values = {'return_to': 'learning_memory', 'q': '递归边界', 'assignment_id': ids['assignment_one']}
    updated = client.post('/student/rebuild-learning-memory', data=values, follow_redirects=True)
    assert '递归边界和终止条件' in updated.get_data(as_text=True)
    assert 'value="递归边界"' in updated.get_data(as_text=True)
    client.post('/student/learning-memory/revoke', data=dict(values, source_type='submission_feedback', source_id=f'submission:{ids["submission_one"]}'))
    rebuilt = client.post('/student/rebuild-learning-memory', data=values, follow_redirects=True)
    assert '递归边界和终止条件' not in rebuilt.get_data(as_text=True)
    from routes import main as main_routes
    def fail(*args, **kwargs):
        raise store.StudentVectorRebuildError('simulated')
    monkeypatch.setattr(main_routes, 'rebuild_student_vector_index_with_retry', fail)
    failed = client.post('/student/rebuild-learning-memory', data=values, follow_redirects=True)
    assert '学习记忆更新失败' in failed.get_data(as_text=True)
    assert 'value="递归边界"' in failed.get_data(as_text=True)


@pytest.mark.parametrize('role', ['教师', '管理员'])
def test_staff_cannot_browse_student_private_memory(seeded_student_vector_context, role):
    app, ids = seeded_student_vector_context
    with app.app_context():
        db.session.get(User, ids['student_two']).usertype = role
        db.session.commit()
    assert _login(app, ids['student_two']).get('/student/learning-memory?q=递归').status_code == 403


def test_review_read_failure_is_recoverable_and_not_cached(seeded_student_vector_context, monkeypatch):
    app, ids = seeded_student_vector_context
    from routes import main as main_routes
    def fail(*args, **kwargs):
        raise TimeoutError('private database details')
    monkeypatch.setattr(main_routes, 'search_student_learning_vectors', fail)
    response = _login(app, ids['student_one']).get('/student/learning-memory?q=递归')
    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert '暂时无法读取' in page
    assert 'private database details' not in page
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert response.headers['Referrer-Policy'] == 'same-origin'
