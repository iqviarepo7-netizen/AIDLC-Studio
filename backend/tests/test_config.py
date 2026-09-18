from app.config_loader import load_app_config


def test_policy_loads_model_routes() -> None:
    config = load_app_config()
    assert config.policy.model_routing
    assert config.policy.automation.mode == "full"


def test_public_ui_config_has_theme_and_stages() -> None:
    config = load_app_config()
    public = config.public_ui_config()
    assert public["app"]["name"] == "AIDLC Studio"
    assert public["stages"]
