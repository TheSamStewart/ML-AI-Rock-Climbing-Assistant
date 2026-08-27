import importlib

import redis_client as redis_client_module


def _reload_with_env(monkeypatch, env_value):
    # redis_client.py reads REDIS_URL and builds the client at import time,
    # so exercising both branches means reloading the module under a
    # controlled environment. Redis.from_url() doesn't connect eagerly, so
    # this never touches the network.
    if env_value is None:
        monkeypatch.delenv("REDIS_URL", raising=False)
    else:
        monkeypatch.setenv("REDIS_URL", env_value)

    return importlib.reload(redis_client_module)


def test_default_redis_url_when_env_unset(monkeypatch):
    module = _reload_with_env(monkeypatch, None)

    assert module.redis_url == "redis://localhost:6379/0"


def test_redis_url_read_from_env(monkeypatch):
    module = _reload_with_env(monkeypatch, "redis://some-host:6380/2")

    assert module.redis_url == "redis://some-host:6380/2"


def test_client_decode_responses_enabled(monkeypatch):
    # decode_responses=True is what makes the "processing" sentinel string
    # comparisons in main.py work at all - without it GET/SET return bytes.
    module = _reload_with_env(monkeypatch, None)

    kwargs = module.redis_client.connection_pool.connection_kwargs
    assert kwargs.get("decode_responses") is True


def test_client_connects_to_configured_host_and_port(monkeypatch):
    module = _reload_with_env(monkeypatch, "redis://some-host:6380/2")

    kwargs = module.redis_client.connection_pool.connection_kwargs
    assert kwargs.get("host") == "some-host"
    assert kwargs.get("port") == 6380
    assert kwargs.get("db") == 2


def teardown_module(module):
    # Leave the module in its normal (env-unset) state for any test that
    # imports it after this file runs.
    importlib.reload(redis_client_module)
