"""Tests for auth blueprint."""


class TestLogin:
    def test_login_page_renders(self, client):
        resp = client.get("/admin/login")
        assert resp.status_code == 200

    def test_login_success(self, client):
        resp = client.post(
            "/admin/login",
            data={
                "email": "admin@test.com",
                "password": "testpass",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200

    def test_login_failure(self, client):
        resp = client.post(
            "/admin/login",
            data={
                "email": "admin@test.com",
                "password": "wrong",
            },
            follow_redirects=True,
        )
        assert b"incorrects" in resp.data.lower() or b"Identifiants" in resp.data
