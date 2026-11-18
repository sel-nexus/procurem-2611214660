"""Validate list pagination and audit ordering against file-backed SQLite."""
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.core.database import connect
from app.main import create_app


@pytest.fixture
def workspace():
    """Start a seeded isolated workspace."""
    with TemporaryDirectory(dir=Path.home()) as folder:
        path = str(Path(folder) / 'bounds.db')
        with TestClient(create_app(Settings(database_path=path))) as client:
            assert client.post('/api/v1/auth/login', json={'email': 'admin@procurem.demo', 'password': 'Admin@5678'}).status_code == 200
            yield client, path


@pytest.mark.parametrize('route', ['/api/v1/audit', '/api/v1/approvals', '/api/v1/users', '/api/v1/roles', '/api/v1/notifications'])
def test_page_and_page_size_bounds(workspace, route):
    client, _ = workspace
    for params in ({'page': 0}, {'page': -1}, {'page': 2147483648}, {'page': '999999999999999999999999999999999999'}, {'page_size': 0}, {'page_size': 101}):
        assert client.get(route, params=params).status_code == 422
    response = client.get(route, params={'page': 2147483647, 'page_size': 100})
    assert response.status_code == 200
    assert response.json()['items'] == []
    assert response.json()['page'] == 2147483647
    assert client.get(route, params={'page': 1, 'page_size': 1}).status_code == 200


def test_audit_sorting_and_invalid_inputs(workspace):
    client, path = workspace
    with connect(path) as db:
        for action, record in [('z_bound', 'z'), ('a_bound', 'a'), ('m_bound', 'm')]:
            db.execute("INSERT INTO audit_log(user_id,role,action,record_type,record_id,detail,created_at) VALUES (1,'analyst',?,'bounds',?,'test','2026-01-01T00:00:00+00:00')", (action, record))
    for order, expected in [('asc', ['a_bound', 'm_bound', 'z_bound']), ('desc', ['z_bound', 'm_bound', 'a_bound'])]:
        response = client.get('/api/v1/audit', params={'sort': 'action', 'order': order, 'page_size': 100})
        assert response.status_code == 200
        assert [row['action'] for row in response.json()['items'] if row['record_type'] == 'bounds'] == expected
    for route in ['/api/v1/audit', '/api/v1/audit/csv']:
        for params in ({'sort': 'id; DROP TABLE users'}, {'order': 'bad'}, {'from_date': '2026-02-01', 'to_date': '2026-01-01'}, {'user_id': 0}):
            assert client.get(route, params=params).status_code == 422
