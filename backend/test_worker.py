import importlib

import worker as worker_module
from worker import analysis


def test_analysis_concatenates_filename_and_content_type():
    result = analysis("photo.jpg", "image/jpeg")

    assert result == "photo.jpgimage/jpeg"


def test_analysis_default_taps_is_none_and_unused():
    # taps isn't used by the current stub implementation, but the signature
    # accepts it (and defaults it) since main.py always passes it - this
    # locks in that calling without taps doesn't error.
    result = analysis("photo.png", "image/png")

    assert result == "photo.pngimage/png"


def test_analysis_accepts_taps_without_using_them():
    taps = [{"x": 0.1, "y": 0.2}]

    result = analysis("photo.png", "image/png", taps)

    assert result == "photo.pngimage/png"


def test_analysis_handles_empty_strings():
    result = analysis("", "")

    assert result == ""


def test_analysis_handles_unicode_filename():
    result = analysis("crux-étape.jpg", "image/jpeg")

    assert result == "crux-étape.jpgimage/jpeg"


def test_analysis_is_registered_as_a_celery_task():
    assert "worker.analysis" in worker_module.app.tasks


def test_analysis_task_name_matches_module_path():
    assert analysis.name == "worker.analysis"


def _reload_with_env(monkeypatch, env_value):
    if env_value is None:
        monkeypatch.delenv("REDIS_URL", raising=False)
    else:
        monkeypatch.setenv("REDIS_URL", env_value)

    return importlib.reload(worker_module)


def test_default_broker_and_backend_when_env_unset(monkeypatch):
    module = _reload_with_env(monkeypatch, None)

    assert module.app.conf.broker_url == "redis://localhost:6379/0"
    assert module.app.conf.result_backend == "redis://localhost:6379/0"


def test_broker_and_backend_read_from_env(monkeypatch):
    module = _reload_with_env(monkeypatch, "redis://some-host:6380/3")

    assert module.app.conf.broker_url == "redis://some-host:6380/3"
    assert module.app.conf.result_backend == "redis://some-host:6380/3"


def teardown_module(module):
    importlib.reload(worker_module)
