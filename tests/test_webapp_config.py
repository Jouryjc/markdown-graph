"""后端系统配置路由 + 覆盖层 store 测试。

约定（避免污染真实环境）：
- 用 ``monkeypatch.setattr(config_store, "OVERLAY_PATH", tmp_path/...)`` 把覆盖层
  指向临时文件，绝不写真实 .mdgraph/config.json。
- 用 ``monkeypatch.setenv/delenv`` 改环境（测试结束自动还原）。
- 每个测试前清空 ``config_store._applied_keys``（模块级可变状态），避免跨用例泄漏。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from webapp.backend import config_store
from webapp.backend.app import create_app
from webapp.backend.config_schema import (
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_EMBED_BASE_URL,
    DEFAULT_EMBED_MODEL,
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    FIELD_SPECS,
    GROUPS,
)
from webapp.backend.config_store import SECRET_MASK


@pytest.fixture(autouse=True)
def isolate_overlay(monkeypatch, tmp_path):
    """每个测试用独立的临时覆盖层文件，并清空模块级 _applied_keys。"""
    overlay = tmp_path / ".mdgraph" / "config.json"
    monkeypatch.setattr(config_store, "OVERLAY_PATH", overlay)
    config_store._applied_keys.clear()
    yield
    config_store._applied_keys.clear()


@pytest.fixture
def client():
    return TestClient(create_app())


def _all_fields(config_groups) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for group in config_groups:
        for field in group["fields"]:
            out[field["key"]] = field
    return out


# ---------------------------------------------------------------------------
# schema 一致性
# ---------------------------------------------------------------------------
def test_schema_has_17_fields_and_provider_defaults_match():
    assert len(FIELD_SPECS) == 17
    by_key = {f.key: f for f in FIELD_SPECS}
    # provider 默认串与 schema 常量一致（断言不漂移）。
    assert by_key["MDGRAPH_EMBED_BASE_URL"].default == DEFAULT_EMBED_BASE_URL
    assert by_key["MDGRAPH_EMBED_MODEL"].default == DEFAULT_EMBED_MODEL
    assert by_key["MDGRAPH_LLM_BASE_URL"].default == DEFAULT_LLM_BASE_URL
    assert by_key["MDGRAPH_LLM_MODEL"].default == DEFAULT_LLM_MODEL
    assert by_key["ANTHROPIC_MODEL"].default == DEFAULT_ANTHROPIC_MODEL
    # high_risk 仅 STORE / EMBEDDER。
    high_risk = {f.key for f in FIELD_SPECS if f.high_risk}
    assert high_risk == {"MDGRAPH_STORE", "MDGRAPH_EMBEDDER"}
    # secret 为 4 个凭证。
    secrets = {f.key for f in FIELD_SPECS if f.secret}
    assert secrets == {
        "MDGRAPH_EMBED_API_KEY",
        "MDGRAPH_LLM_API_KEY",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
    }


# ---------------------------------------------------------------------------
# GET /api/config
# ---------------------------------------------------------------------------
def test_get_config_structure_and_default_source(client, monkeypatch):
    # 确保相关 env 未设，落到 default。
    monkeypatch.delenv("MDGRAPH_EMBED_MODEL", raising=False)
    resp = client.get("/api/config")
    assert resp.status_code == 200
    body = resp.json()
    # 分组顺序与 GROUPS 一致。
    assert [g["key"] for g in body["groups"]] == [k for k, _ in GROUPS]
    fields = _all_fields(body["groups"])
    embed_model = fields["MDGRAPH_EMBED_MODEL"]
    assert embed_model["value"] == DEFAULT_EMBED_MODEL
    assert embed_model["source"] == "default"
    assert embed_model["type"] == "string"
    assert embed_model["applies"] == "rebuild"
    assert embed_model["secret"] is False
    # 每个字段都带契约里的键。
    for f in fields.values():
        assert set(f) >= {
            "key",
            "label",
            "type",
            "value",
            "default",
            "source",
            "secret",
            "high_risk",
            "applies",
            "description",
            "is_set",
        }


def test_get_config_env_source(client, monkeypatch):
    monkeypatch.setenv("MDGRAPH_EMBED_MODEL", "bge-m3")
    fields = _all_fields(client.get("/api/config").json()["groups"])
    assert fields["MDGRAPH_EMBED_MODEL"]["value"] == "bge-m3"
    assert fields["MDGRAPH_EMBED_MODEL"]["source"] == "env"


# ---------------------------------------------------------------------------
# PUT /api/config — 写覆盖层 + env + reset_engine
# ---------------------------------------------------------------------------
def test_put_writes_overlay_env_and_calls_reset_engine(
    client, monkeypatch
):
    monkeypatch.delenv("MDGRAPH_LLM_MODEL", raising=False)
    spy = {"count": 0}
    # router 模块持有自己的 reset_engine 引用，需 patch 那里。
    import webapp.backend.routers.config as config_router

    monkeypatch.setattr(
        config_router, "reset_engine", lambda: spy.__setitem__("count", spy["count"] + 1)
    )

    resp = client.put(
        "/api/config", json={"values": {"MDGRAPH_LLM_MODEL": "qwen2.5:7b"}}
    )
    assert resp.status_code == 200
    body = resp.json()
    # 落盘。
    assert config_store.OVERLAY_PATH.exists()
    saved = json.loads(config_store.OVERLAY_PATH.read_text(encoding="utf-8"))
    assert saved == {"MDGRAPH_LLM_MODEL": "qwen2.5:7b"}
    # 写 os.environ。
    import os

    assert os.environ["MDGRAPH_LLM_MODEL"] == "qwen2.5:7b"
    # reset_engine 被调用。
    assert spy["count"] == 1
    # 返回新配置：来源 overlay。config 镜像 GET 的 {groups: [...]} 形状。
    fields = _all_fields(body["config"]["groups"])
    assert fields["MDGRAPH_LLM_MODEL"]["value"] == "qwen2.5:7b"
    assert fields["MDGRAPH_LLM_MODEL"]["source"] == "overlay"


def test_put_secret_mask_not_overwritten(client, monkeypatch):
    # 预置一个真实密钥到覆盖层。
    config_store.save_overlay({"ANTHROPIC_API_KEY": "sk-real-secret"})
    config_store._applied_keys.add("ANTHROPIC_API_KEY")

    # 提交掩码占位串 → 应被忽略，不覆盖真实值。
    resp = client.put(
        "/api/config", json={"values": {"ANTHROPIC_API_KEY": SECRET_MASK}}
    )
    assert resp.status_code == 200
    saved = json.loads(config_store.OVERLAY_PATH.read_text(encoding="utf-8"))
    assert saved["ANTHROPIC_API_KEY"] == "sk-real-secret"
    fields = _all_fields(resp.json()["config"]["groups"])
    # secret 字段返回真实值 + is_set。
    assert fields["ANTHROPIC_API_KEY"]["value"] == "sk-real-secret"
    assert fields["ANTHROPIC_API_KEY"]["is_set"] is True


def test_put_int_validation_422(client):
    resp = client.put(
        "/api/config", json={"values": {"MDGRAPH_MAX_ENTRIES": "-3"}}
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert any(d["key"] == "MDGRAPH_MAX_ENTRIES" for d in detail)

    resp2 = client.put(
        "/api/config", json={"values": {"MDGRAPH_MAX_ENTRIES": "abc"}}
    )
    assert resp2.status_code == 422


def test_put_url_validation_422(client):
    resp = client.put(
        "/api/config", json={"values": {"MDGRAPH_EMBED_BASE_URL": "ftp://nope"}}
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert any(d["key"] == "MDGRAPH_EMBED_BASE_URL" for d in detail)


def test_put_unknown_key_422(client):
    resp = client.put("/api/config", json={"values": {"NOPE": "x"}})
    assert resp.status_code == 422


def test_put_rebuild_field_returns_warnings(client, monkeypatch):
    import webapp.backend.routers.config as config_router

    monkeypatch.setattr(config_router, "reset_engine", lambda: None)
    resp = client.put(
        "/api/config", json={"values": {"MDGRAPH_EMBED_MODEL": "bge-m3"}}
    )
    assert resp.status_code == 200
    warnings = resp.json()["warnings"]
    assert warnings
    assert "MDGRAPH_EMBED_MODEL" in warnings[0]


def test_put_live_field_no_warnings(client, monkeypatch):
    import webapp.backend.routers.config as config_router

    monkeypatch.setattr(config_router, "reset_engine", lambda: None)
    resp = client.put(
        "/api/config", json={"values": {"MDGRAPH_MAX_ARCHIVE_BYTES": "1048576"}}
    )
    assert resp.status_code == 200
    assert resp.json()["warnings"] == []


# ---------------------------------------------------------------------------
# 上传限制热生效：get_settings() 现读为新值
# ---------------------------------------------------------------------------
def test_put_max_archive_bytes_visible_to_get_settings(client, monkeypatch):
    import webapp.backend.routers.config as config_router

    monkeypatch.setattr(config_router, "reset_engine", lambda: None)
    monkeypatch.delenv("MDGRAPH_MAX_ARCHIVE_BYTES", raising=False)

    from webapp.backend.settings import get_settings

    resp = client.put(
        "/api/config", json={"values": {"MDGRAPH_MAX_ARCHIVE_BYTES": "1234567"}}
    )
    assert resp.status_code == 200
    assert get_settings().max_archive_bytes == 1234567


# ---------------------------------------------------------------------------
# POST /api/config/reset
# ---------------------------------------------------------------------------
def test_reset_clears_overlay_and_falls_back(client, monkeypatch):
    import os

    import webapp.backend.routers.config as config_router

    monkeypatch.setattr(config_router, "reset_engine", lambda: None)
    monkeypatch.delenv("MDGRAPH_LLM_MODEL", raising=False)

    # 先写一项。
    client.put("/api/config", json={"values": {"MDGRAPH_LLM_MODEL": "custom"}})
    assert os.environ.get("MDGRAPH_LLM_MODEL") == "custom"

    resp = client.post("/api/config/reset")
    assert resp.status_code == 200
    saved = json.loads(config_store.OVERLAY_PATH.read_text(encoding="utf-8"))
    assert saved == {}
    # 我们写过的键被 pop，回落 default。
    assert "MDGRAPH_LLM_MODEL" not in os.environ
    fields = _all_fields(resp.json()["config"]["groups"])
    assert fields["MDGRAPH_LLM_MODEL"]["value"] == DEFAULT_LLM_MODEL
    assert fields["MDGRAPH_LLM_MODEL"]["source"] == "default"


# ---------------------------------------------------------------------------
# 删除单键（None）回落
# ---------------------------------------------------------------------------
def test_put_none_removes_key(client, monkeypatch):
    import os

    import webapp.backend.routers.config as config_router

    monkeypatch.setattr(config_router, "reset_engine", lambda: None)
    monkeypatch.delenv("MDGRAPH_LLM_MODEL", raising=False)

    client.put("/api/config", json={"values": {"MDGRAPH_LLM_MODEL": "custom"}})
    assert os.environ.get("MDGRAPH_LLM_MODEL") == "custom"

    resp = client.put("/api/config", json={"values": {"MDGRAPH_LLM_MODEL": None}})
    assert resp.status_code == 200
    saved = json.loads(config_store.OVERLAY_PATH.read_text(encoding="utf-8"))
    assert "MDGRAPH_LLM_MODEL" not in saved
    assert "MDGRAPH_LLM_MODEL" not in os.environ


# ---------------------------------------------------------------------------
# 启动钩子：apply_overlay_to_env 命中 os.environ
# ---------------------------------------------------------------------------
def test_startup_hook_applies_overlay(monkeypatch):
    import os

    monkeypatch.delenv("MDGRAPH_EMBED_MODEL", raising=False)
    # 预置覆盖层文件。
    config_store.save_overlay({"MDGRAPH_EMBED_MODEL": "preset-model"})
    config_store.apply_overlay_to_env(config_store.load_overlay())
    assert os.environ["MDGRAPH_EMBED_MODEL"] == "preset-model"
    # 清理（apply 写了真实 os.environ，monkeypatch 不还原它）。
    os.environ.pop("MDGRAPH_EMBED_MODEL", None)
