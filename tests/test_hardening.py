"""Tests B015 — Hardening & Production (security headers, health check)."""


class TestHealthCheck:
    def test_health_check_ok(self, client):
        """GET /health répond 200 sans auth quand DB et disque sont OK."""
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_check_returns_json(self, client):
        """GET /health retourne un JSON avec status, db, disk."""
        resp = client.get("/health")
        assert resp.content_type == "application/json"
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["db"] is True
        assert data["disk"] is True
        assert isinstance(data["uptime_s"], int)


class TestSecurityHeaders:
    def test_security_headers_present(self, client):
        """Les 5 headers de sécurité sont présents sur une réponse normale."""
        resp = client.get("/health")
        for header in (
            "Strict-Transport-Security",
            "X-Content-Type-Options",
            "X-Frame-Options",
            "Referrer-Policy",
            "Content-Security-Policy",
        ):
            assert header in resp.headers, f"header manquant : {header}"

    def test_security_headers_on_error_response(self, client):
        """Les headers sont aussi présents sur une réponse d'erreur (404)."""
        resp = client.get("/route-inexistante")
        assert resp.status_code == 404
        for header in (
            "Strict-Transport-Security",
            "X-Content-Type-Options",
            "X-Frame-Options",
            "Referrer-Policy",
            "Content-Security-Policy",
        ):
            assert header in resp.headers

    def test_csp_header(self, client):
        """La CSP restreint les sources à 'self' (+ inline pour Alpine.js)."""
        resp = client.get("/health")
        csp = resp.headers["Content-Security-Policy"]
        assert "default-src 'self'" in csp
        assert "script-src 'self' 'unsafe-inline'" in csp
        assert "connect-src 'self'" in csp

    def test_hsts_header(self, client):
        """HSTS est actif 1 an avec les sous-domaines."""
        resp = client.get("/health")
        assert (
            resp.headers["Strict-Transport-Security"]
            == "max-age=31536000; includeSubDomains"
        )

    def test_x_frame_options(self, client):
        """X-Frame-Options est DENY (pas d'intégration en iframe)."""
        resp = client.get("/health")
        assert resp.headers["X-Frame-Options"] == "DENY"

    def test_referrer_policy(self, client):
        """Referrer-Policy est strict-origin-when-cross-origin."""
        resp = client.get("/health")
        assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
