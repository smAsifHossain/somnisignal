import gzip
import os
import time

from fastapi.testclient import TestClient

TOKEN = "local-development-token-change-me-123456"
os.environ.setdefault("ML_API_TOKEN", TOKEN)
os.environ.setdefault("LOCAL_UI_ENABLED", "true")
os.environ.setdefault("RESEARCH_DEMO_UPLOADS_ENABLED", "true")

from app.main import app


HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def test_authentication_and_demo_job() -> None:
    with TestClient(app) as client:
        assert client.post("/v1/demo-predictions", json={}).status_code == 401
        accepted = client.post(
            "/v1/demo-predictions",
            headers=HEADERS,
            json={
                "record_id": "c01",
                "adult_confirmed": True,
                "research_consent": True,
            },
        )
        assert accepted.status_code == 202
        job_id = accepted.json()["job_id"]
        for _ in range(50):
            response = client.get(f"/v1/predictions/{job_id}", headers=HEADERS)
            if response.json()["status"] == "completed":
                break
            time.sleep(0.02)
        payload = response.json()
        assert payload["status"] == "completed"
        assert payload["result"]["outcome"] == "inconclusive"
        assert any(
            "release gate" in reason for reason in payload["result"]["reasons"]
        )
        assert "minute" not in payload["result"]
        assert "diagnosis" in payload["result"]["disclaimer"]


def test_consent_and_public_upload_gate() -> None:
    with TestClient(app) as client:
        missing_consent = client.post(
            "/v1/demo-predictions",
            headers=HEADERS,
            json={
                "record_id": "a01",
                "adult_confirmed": False,
                "research_consent": True,
            },
        )
        assert missing_consent.status_code == 422

        gated = client.post(
            "/v1/predictions",
            headers=HEADERS,
            data={
                "sampling_rate_hz": "100",
                "adult_confirmed": "true",
                "research_consent": "true",
            },
            files={"ecg_file": ("record.csv.gz", b"data", "application/gzip")},
        )
        assert gated.status_code == 403


def test_authenticated_research_upload_requires_non_patient_confirmation() -> None:
    compressed = gzip.compress(b"ecg_mv\n0.1\n0.2\n")
    fields = {
        "sampling_rate_hz": "100",
        "adult_confirmed": "true",
        "research_consent": "true",
        "non_patient_test_data_confirmed": "true",
    }
    with TestClient(app) as client:
        assert client.post(
            "/v1/research-predictions",
            data=fields,
            files={"ecg_file": ("research.csv.gz", compressed, "application/gzip")},
        ).status_code == 401

        rejected = client.post(
            "/v1/research-predictions",
            headers=HEADERS,
            data={**fields, "non_patient_test_data_confirmed": "false"},
            files={"ecg_file": ("research.csv.gz", compressed, "application/gzip")},
        )
        assert rejected.status_code == 422

        accepted = client.post(
            "/v1/research-predictions",
            headers=HEADERS,
            data=fields,
            files={"ecg_file": ("research.csv.gz", compressed, "application/gzip")},
        )
        assert accepted.status_code == 202
        job_id = accepted.json()["job_id"]
        for _ in range(50):
            response = client.get(f"/v1/predictions/{job_id}", headers=HEADERS)
            if response.json()["status"] in {"completed", "failed"}:
                break
            time.sleep(0.02)
        payload = response.json()
        assert payload["status"] == "completed"
        assert payload["result"]["outcome"] == "inconclusive"
        assert not any(
            "release gate" in reason for reason in payload["result"]["reasons"]
        )


def test_health_distinguishes_research_demo_and_patient_uploads() -> None:
    with TestClient(app) as client:
        payload = client.get("/health").json()
        assert payload["model_ready"] is True
        assert payload["research_demo_uploads_enabled"] is True
        assert payload["public_uploads_enabled"] is False


def test_delete_job_and_unknown_ids() -> None:
    with TestClient(app) as client:
        assert client.get("/v1/predictions/not-an-id", headers=HEADERS).status_code == 404
        accepted = client.post(
            "/v1/demo-predictions",
            headers=HEADERS,
            json={
                "record_id": "b01",
                "adult_confirmed": True,
                "research_consent": True,
            },
        )
        job_id = accepted.json()["job_id"]
        assert client.delete(f"/v1/predictions/{job_id}", headers=HEADERS).status_code == 204
        assert client.get(f"/v1/predictions/{job_id}", headers=HEADERS).status_code == 404


def test_local_ui_and_demo_adapter_are_loopback_only() -> None:
    origin = {"Origin": "http://localhost:8000"}
    with TestClient(app, base_url="http://localhost:8000", headers=origin) as client:
        page = client.get("/", follow_redirects=True)
        assert page.status_code == 200
        assert "somnisignal" in page.text.lower()

        accepted = client.post(
            "/local/v1/demo-predictions",
            json={
                "record_id": "c01",
                "adult_confirmed": True,
                "research_consent": True,
            },
        )
        assert accepted.status_code == 202
        job_id = accepted.json()["job_id"]
        for _ in range(50):
            response = client.get(f"/local/v1/predictions/{job_id}")
            if response.json()["status"] == "completed":
                break
            time.sleep(0.02)
        assert response.json()["status"] == "completed"
        assert response.headers["cache-control"] == "no-store"
        assert client.delete(f"/local/v1/predictions/{job_id}").status_code == 204
        assert client.get(f"/local/v1/predictions/{job_id}").status_code == 404

    with TestClient(app, base_url="http://public.example") as client:
        assert client.post(
            "/local/v1/demo-predictions",
            headers={"Origin": "http://public.example"},
            json={
                "record_id": "c01",
                "adult_confirmed": True,
                "research_consent": True,
            },
        ).status_code == 404


def test_local_upload_sandbox_accepts_only_confirmed_test_data() -> None:
    origin = {"Origin": "http://localhost:8000"}
    compressed = gzip.compress(b"ecg_mv\n0.1\n0.2\n")
    fields = {
        "sampling_rate_hz": "100",
        "adult_confirmed": "true",
        "research_consent": "true",
        "non_patient_test_data_confirmed": "true",
    }
    with TestClient(app, base_url="http://localhost:8000", headers=origin) as client:
        rejected = client.post(
            "/local/v1/test-predictions",
            data={**fields, "non_patient_test_data_confirmed": "false"},
            files={"ecg_file": ("synthetic.csv.gz", compressed, "application/gzip")},
        )
        assert rejected.status_code == 422

        accepted = client.post(
            "/local/v1/test-predictions",
            data=fields,
            files={"ecg_file": ("synthetic.csv.gz", compressed, "application/gzip")},
        )
        assert accepted.status_code == 202
        job_id = accepted.json()["job_id"]
        for _ in range(50):
            response = client.get(f"/local/v1/predictions/{job_id}")
            if response.json()["status"] in {"completed", "failed"}:
                break
            time.sleep(0.02)
        payload = response.json()
        assert payload["status"] == "completed"
        assert payload["result"]["outcome"] == "inconclusive"
        assert payload["result"]["signal_quality"] == "fail"


def test_local_polling_allows_same_origin_get_without_origin_header() -> None:
    with TestClient(app, base_url="http://localhost:8000") as client:
        accepted = client.post(
            "/local/v1/demo-predictions",
            headers={"Origin": "http://localhost:8000"},
            json={
                "record_id": "c01",
                "adult_confirmed": True,
                "research_consent": True,
            },
        )
        assert accepted.status_code == 202
        job_id = accepted.json()["job_id"]
        same_origin = client.get(
            f"/local/v1/predictions/{job_id}",
            headers={
                "Referer": "http://localhost:8000/ui/",
                "Sec-Fetch-Site": "same-origin",
            },
        )
        assert same_origin.status_code == 200

        cross_site = client.get(
            f"/local/v1/predictions/{job_id}",
            headers={
                "Referer": "https://attacker.example/",
                "Sec-Fetch-Site": "cross-site",
            },
        )
        assert cross_site.status_code == 404


def test_local_demo_reports_raw_research_outcome_without_release_override() -> None:
    with TestClient(
        app,
        base_url="http://localhost:8000",
        headers={"Origin": "http://localhost:8000"},
    ) as client:
        accepted = client.post(
            "/local/v1/demo-predictions",
            json={
                "record_id": "c01",
                "adult_confirmed": True,
                "research_consent": True,
            },
        )
        assert accepted.status_code == 202
        job_id = accepted.json()["job_id"]
        for _ in range(50):
            response = client.get(f"/local/v1/predictions/{job_id}")
            if response.json()["status"] == "completed":
                break
            time.sleep(0.02)
        payload = response.json()
        assert payload["result"]["outcome"] in {
            "low_risk",
            "inconclusive",
            "elevated_risk",
        }
        assert payload["result"]["model_version"] == "somnisignal-rr-cnn-1.0.0"
        assert payload["result"]["risk_score"] is not None
        assert not any(
            "release gate" in reason for reason in payload["result"]["reasons"]
        )
