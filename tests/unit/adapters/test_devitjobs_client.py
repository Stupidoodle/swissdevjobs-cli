"""The devitjobs board client, driven through a hand-written HTTP fake."""

from __future__ import annotations

import json

from conftest import job
from swissdevjobs_cli.adapters.boards.registry import BOARDS
from swissdevjobs_cli.adapters.boards.worldwide.devitjobs.client import DevITJobsClient
from swissdevjobs_cli.domain.model.application import Applicant


class FakeHttp:
    """Records requests, serves canned payloads."""

    def __init__(self, payloads):
        self.payloads = payloads
        self.gets = []
        self.posts = []

    def get(self, path, **kwargs):
        self.gets.append(path)
        key = path.split("?")[0]
        return json.dumps(self.payloads[key]).encode()

    def post_multipart(self, path, fields, files, *, referer, timeout=30):
        self.posts.append(
            {"path": path, "fields": fields, "files": files, "referer": referer}
        )
        return {"status": 200, "response": "ok"}


def applicant(**overrides):
    base = {
        "name": "Ada",
        "email": "ada@example.com",
        "cv_path": "",
        "is_from_europe": True,
        "lang_skills": "native",
    }
    base.update(overrides)
    return Applicant(**base)


def test_fetch_jobs_normalizes_through_the_acl():
    http = FakeHttp({"/api/jobsLight": [job()]})
    client = DevITJobsClient(BOARDS["germantechjobs"], http)
    jobs = client.fetch_jobs()
    assert jobs[0].board is BOARDS["germantechjobs"]
    assert jobs[0].salary.currency == "EUR"


def test_a_forced_refresh_busts_the_edge_cache():
    http = FakeHttp({"/api/jobsLight": []})
    DevITJobsClient(BOARDS["swissdevjobs"], http).fetch_jobs(force=True)
    assert "?_cb=" in http.gets[0]


def test_fetch_detail_hits_the_job_endpoint():
    http = FakeHttp({"/api/job/abc123": job(description="<p>x</p>")})
    detail = DevITJobsClient(BOARDS["swissdevjobs"], http).fetch_detail("abc123")
    assert detail.raw["description"] == "<p>x</p>"


def test_submit_builds_the_native_form(tmp_path):
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4")
    http = FakeHttp({})
    client = DevITJobsClient(BOARDS["swissdevjobs"], http)
    detail = client_detail(job(hasLangCheck=True))
    result = client.submit_application(detail, applicant(cv_path=str(cv)), "Dear team")
    assert result["status"] == 200
    sent = http.posts[0]
    assert sent["path"] == "/api/jobApply"
    fields = sent["fields"]
    assert fields["name"] == "Ada"
    assert fields["motivationLetter"] == "Dear team"
    assert fields["langSkills"] == "native"
    assert fields["companyEmail"] == "jobs@acme.example"
    # honeypots stay absent
    for honeypot in ("yearsOfExperience", "personal_website_url", "address"):
        assert honeypot not in fields
    assert sent["files"]["cvFile"][0] == "cv.pdf"
    assert sent["referer"].endswith("/jobs/acme-senior-python-engineer")


def client_detail(wire):
    from swissdevjobs_cli.adapters.boards.worldwide.devitjobs import acl

    return acl.detail_from_wire(wire, BOARDS["swissdevjobs"])
