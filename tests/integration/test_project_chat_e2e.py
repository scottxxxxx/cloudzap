"""Integration tests for the Project Chat policy endpoint and /v1/chat path."""

import sqlite3

import pytest

from tests.conftest import _insert_user, _jwt_token, chat_request


PREFLIGHT_PATH = "/v1/features/project-chat/check"


@pytest.fixture
def gate_enabled(client):
    """Bump min_client_version on the runtime tiers config so the gate fires.

    The chat router resolves project_chat config from remote_configs first
    (tiers.json under the current locale), falling back to features.yml
    only if the tiers entry is missing. We mutate the live remote_configs
    dict so the gate actually applies for the test request.
    """
    configs = client.app.state.remote_configs
    pc = configs["tiers"]["feature_definitions"]["project_chat"]
    original = pc.get("min_client_version", 0)
    pc["min_client_version"] = 18
    yield 18
    pc["min_client_version"] = original


class TestProjectChatPreflight:
    def test_unauthenticated_returns_login_required(self, client):
        """No JWT → verdict=login_required, regardless of selected_model."""
        resp = client.post(
            PREFLIGHT_PATH,
            json={"selected_model": "external"},
        )
        assert resp.status_code == 200
        body = resp.json()
        # Default flag is "plus" — non-logged-in always gets login_required
        assert body["verdict"] == "login_required"
        assert body["cta"]["kind"] == "login_required"

    def test_plus_user_external_model_routes_to_user_model(self, client, tmp_db_path):
        """Plus user with external model selected → send_to_user_model under default 'plus' policy."""
        _insert_user(tmp_db_path, user_id="plus-pc", tier="plus", monthly_limit=-1)
        headers = {"Authorization": f"Bearer {_jwt_token('plus-pc')}"}
        resp = client.post(
            PREFLIGHT_PATH,
            json={"selected_model": "external"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["verdict"] == "send_to_user_model"

    def test_plus_user_ssai_model_routes_to_gp(self, client, tmp_db_path):
        """Plus user with SS AI selected → send_to_gp."""
        _insert_user(tmp_db_path, user_id="plus-ssai", tier="plus", monthly_limit=-1)
        headers = {"Authorization": f"Bearer {_jwt_token('plus-ssai')}"}
        resp = client.post(
            PREFLIGHT_PATH,
            json={"selected_model": "ssai"},
            headers=headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["verdict"] == "send_to_gp"
        # No CTA for paid users
        assert "cta" not in body

    def test_free_user_with_quota_returns_send_to_gp_with_cta(self, client, tmp_db_path):
        """Free user, quota=1, no use yet → send_to_gp_with_cta + quota_remaining CTA."""
        _insert_user(tmp_db_path, user_id="free-pc", tier="free", monthly_limit=0.35)
        headers = {"Authorization": f"Bearer {_jwt_token('free-pc')}"}
        resp = client.post(
            PREFLIGHT_PATH,
            json={"selected_model": "external"},
            headers=headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["verdict"] == "send_to_gp_with_cta"
        assert body["cta"]["kind"] == "quota_remaining"
        assert body["quota_remaining"] == 1
        assert body["quota_total"] == 1

    def test_preflight_does_not_decrement_quota(self, client, tmp_db_path):
        """Calling preflight repeatedly does not change the counter."""
        _insert_user(tmp_db_path, user_id="free-no-decrement", tier="free", monthly_limit=0.35)
        headers = {"Authorization": f"Bearer {_jwt_token('free-no-decrement')}"}
        for _ in range(3):
            resp = client.post(
                PREFLIGHT_PATH,
                json={"selected_model": "ssai"},
                headers=headers,
            )
            assert resp.status_code == 200

        conn = sqlite3.connect(tmp_db_path)
        used = conn.execute(
            "SELECT project_chat_used_this_period FROM users WHERE id = ?",
            ("free-no-decrement",),
        ).fetchone()[0]
        conn.close()
        assert used == 0


class TestProjectChatMinClientVersionGate:
    """When min_client_version > 0 and X-Client-Version is missing or below
    threshold, /v1/chat ProjectChat falls through to PR #80 legacy behavior:
    Free users get the canned-bypass response; paid users process normally
    with no feature_state.
    """

    def test_old_client_free_user_gets_canned_bypass(
        self, client, tmp_db_path, gate_enabled, mock_provider
    ):
        """Free user, no X-Client-Version header, gate enabled → canned response, no LLM call."""
        _insert_user(tmp_db_path, user_id="old-free", tier="free", monthly_limit=0.35)
        headers = {"Authorization": f"Bearer {_jwt_token('old-free')}"}
        resp = client.post(
            "/v1/chat",
            json=chat_request(prompt_mode="ProjectChat"),
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        # Canned shape from PR #80
        assert data["model"] == "ghostpour-canned"
        assert data["ai_tier"] == "free"
        assert "Project Chat" in data["text"]
        assert "Plus" in data["text"]
        # No feature_state — old contract
        assert "feature_state" not in data
        # No LLM call
        mock_provider.assert_not_called()

    def test_old_client_paid_user_processes_normally_no_feature_state(
        self, client, tmp_db_path, gate_enabled, mock_provider
    ):
        """Paid user, no X-Client-Version, gate enabled → normal LLM call, no feature_state."""
        _insert_user(tmp_db_path, user_id="old-paid", tier="pro", monthly_limit=-1)
        headers = {"Authorization": f"Bearer {_jwt_token('old-paid')}"}
        resp = client.post(
            "/v1/chat",
            json=chat_request(prompt_mode="ProjectChat"),
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        # Real LLM response
        assert data["model"] != "ghostpour-canned"
        mock_provider.assert_called_once()
        # No feature_state for old clients
        assert "feature_state" not in data

    def test_new_client_free_user_gets_new_policy_with_feature_state(
        self, client, tmp_db_path, gate_enabled, mock_provider
    ):
        """Free user with X-Client-Version >= threshold → new policy applies."""
        _insert_user(tmp_db_path, user_id="new-free", tier="free", monthly_limit=0.35)
        headers = {
            "Authorization": f"Bearer {_jwt_token('new-free')}",
            "X-Client-Version": "18",
        }
        resp = client.post(
            "/v1/chat",
            json=chat_request(prompt_mode="ProjectChat"),
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        # New contract — real LLM + feature_state
        assert data["model"] != "ghostpour-canned"
        mock_provider.assert_called_once()
        assert "feature_state" in data
        assert data["feature_state"]["feature"] == "project_chat"

    def test_client_version_below_threshold_treated_as_old(
        self, client, tmp_db_path, gate_enabled, mock_provider
    ):
        """X-Client-Version: 17 with min_client_version: 18 → old client."""
        _insert_user(tmp_db_path, user_id="below-thresh", tier="free", monthly_limit=0.35)
        headers = {
            "Authorization": f"Bearer {_jwt_token('below-thresh')}",
            "X-Client-Version": "17",
        }
        resp = client.post(
            "/v1/chat",
            json=chat_request(prompt_mode="ProjectChat"),
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["model"] == "ghostpour-canned"
        mock_provider.assert_not_called()

    def test_malformed_client_version_header_treated_as_old(
        self, client, tmp_db_path, gate_enabled, mock_provider
    ):
        """Non-integer X-Client-Version → defaults to 0 → old client."""
        _insert_user(tmp_db_path, user_id="malformed", tier="free", monthly_limit=0.35)
        headers = {
            "Authorization": f"Bearer {_jwt_token('malformed')}",
            "X-Client-Version": "v1.2.3-beta",
        }
        resp = client.post(
            "/v1/chat",
            json=chat_request(prompt_mode="ProjectChat"),
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["model"] == "ghostpour-canned"
        mock_provider.assert_not_called()


class TestProjectChatTierUpgradeZerosCounter:
    def test_free_to_plus_upgrade_zeros_counter(self, client, tmp_db_path):
        """Verify-receipt Free→Plus zeros project_chat_used_this_period."""
        from app.models.tier import load_tier_config

        _insert_user(tmp_db_path, user_id="upgrader", tier="free", monthly_limit=0.35)
        # Burn some quota first to confirm zeroing actually happens
        conn = sqlite3.connect(tmp_db_path)
        conn.execute(
            "UPDATE users SET project_chat_used_this_period = 1, project_chat_period = '2026-04' WHERE id = ?",
            ("upgrader",),
        )
        conn.commit()
        conn.close()

        plus_product = (
            load_tier_config("config/tiers.yml")
            .tiers["plus"]
            .storekit_product_id
        )
        headers = {"Authorization": f"Bearer {_jwt_token('upgrader')}"}
        resp = client.post(
            "/v1/verify-receipt",
            json={
                "product_id": plus_product,
                "transaction_id": "txn_upgrade",
                "is_trial": False,
            },
            headers=headers,
        )
        assert resp.status_code == 200

        conn = sqlite3.connect(tmp_db_path)
        used = conn.execute(
            "SELECT project_chat_used_this_period FROM users WHERE id = ?",
            ("upgrader",),
        ).fetchone()[0]
        conn.close()
        assert used == 0
