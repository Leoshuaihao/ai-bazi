"""流年分析 API 测试"""
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

SAMPLE_BIRTH = {
    "year": 1990, "month": 6, "day": 15,
    "hour": 12, "minute": 20,
    "gender": "male", "calendar_type": "solar",
}


@pytest.fixture(scope="module")
def auth_token():
    """模块级 fixture：登录一次，复用 token"""
    phone = "13800138000"
    resp = client.post("/api/auth/send-code", json={"phone": phone})
    import sqlite3, time
    if not resp.json().get("ok"):
        time.sleep(1)
        resp = client.post("/api/auth/send-code", json={"phone": phone})
    conn = sqlite3.connect("data/bazi.db")
    row = conn.execute(
        "SELECT code FROM verification_codes WHERE phone=? AND used=0 ORDER BY id DESC LIMIT 1",
        (phone,)
    ).fetchone()
    conn.close()
    assert row, "no verification code"
    resp = client.post("/api/auth/login", json={"phone": phone, "code": row[0]})
    assert resp.status_code == 200, f"login failed: {resp.text}"
    return resp.json()["token"]


@pytest.fixture(scope="module")
def sample_chart():
    """获取排盘数据"""
    resp = client.post("/api/chart", json=SAMPLE_BIRTH)
    assert resp.status_code == 200, f"排盘失败: {resp.text}"
    return resp.json()


def test_liunian_requires_auth():
    """未登录返回 401"""
    resp = client.post("/api/liunian", json={"chart_data": {}, "year": 2026})
    assert resp.status_code == 401


def test_liunian_returns_year_gz(auth_token, sample_chart):
    """流年接口返回正确的年份干支"""
    resp = client.post(
        "/api/liunian",
        json={"chart_data": sample_chart, "year": 2026},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["year"] == 2026
    assert data["year_gz"] == "丙午", f"2026年干支应为丙午，实际为{data.get('year_gz')}"


def test_liunian_has_five_dims(auth_token, sample_chart):
    """流年分析包含五维度"""
    resp = client.post(
        "/api/liunian",
        json={"chart_data": sample_chart, "year": 2026},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    dims = data.get("analysis", {})
    for key in ["career", "wealth", "marriage", "relationship", "health"]:
        assert key in dims, f"缺少维度: {key}"
        assert "summary" in dims[key], f"{key} 缺少 summary"


def test_liunian_has_deterministic_fields(auth_token, sample_chart):
    """流年确定性项：干支、十神、喜忌"""
    resp = client.post(
        "/api/liunian",
        json={"chart_data": sample_chart, "year": 2026},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["year_gz"]) == 2
    assert data["ten_god"] != ""
    assert data["xi_ji"] in ("喜", "忌", "平")


def test_liunian_1995(auth_token, sample_chart):
    """1995年出生，测试2025年流年"""
    birth_1995 = {**SAMPLE_BIRTH, "year": 1995}
    chart_resp = client.post("/api/chart", json=birth_1995)
    assert chart_resp.status_code == 200, chart_resp.text
    chart = chart_resp.json()

    resp = client.post(
        "/api/liunian",
        json={"chart_data": chart, "year": 2025},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["year"] == 2025
    assert data["year_gz"] == "乙巳", f"2025年干支应为乙巳，实际为{data.get('year_gz')}"
