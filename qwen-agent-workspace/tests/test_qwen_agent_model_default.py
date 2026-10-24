"""bin/qwen-agent tests for the --model default: DEFAULT_MODEL when served, else the
server's one loaded model (story-server mlx-vision serves it by path).

Run from the workspace root: python3 -m pytest tests/test_qwen_agent_model_default.py -v
Loads bin/qwen-agent with importlib.machinery.SourceFileLoader. No model server: GET
/models is a fake urlopen and the tool probe is skipped.
"""

import importlib.machinery
import importlib.util
import io
import json
import os

import pytest

WS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
QA_PATH = os.path.join(WS, "bin", "qwen-agent")
VLM = "/Users/ailab1/mlx_models/qwen3-vl"


def _load(path=QA_PATH, name="qwen_agent_model_default_under_test"):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def qa(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return _load()


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _serve(qa, monkeypatch, models):
    body = json.dumps({"object": "list", "data": models}).encode("utf-8")
    monkeypatch.setattr(qa.urllib.request, "urlopen", lambda req, timeout=None: _Resp(body))


def test_parse_args_records_whether_model_was_given(qa):
    ns = qa.parse_args([])
    assert (ns.model, ns.model_explicit) == (qa.DEFAULT_MODEL, False)
    ns = qa.parse_args(["--model=other"])
    assert (ns.model, ns.model_explicit) == ("other", True)


def test_default_served_model(qa):
    d = qa.DEFAULT_MODEL
    assert qa.default_served_model([d, VLM], [VLM]) == d
    assert qa.default_served_model([VLM, "cached-a", "cached-b"], [VLM]) == VLM
    assert qa.default_served_model([VLM], []) == VLM
    assert qa.default_served_model(["a", "b"], []) == d
    assert qa.default_served_model(["a", "b"], ["a", "b"]) == d
    assert qa.default_served_model([], []) == d


def test_preflight_unset_model_uses_the_loaded_model(qa, monkeypatch):
    _serve(qa, monkeypatch, [{"id": VLM, "loaded": True}, {"id": "cached", "loaded": False}])
    assert qa.preflight("http://127.0.0.1:8177/v1", None, None, skip_tool_probe=True) == VLM


def test_preflight_explicit_model_stays_strict(qa, monkeypatch, capsys):
    _serve(qa, monkeypatch, [{"id": VLM, "loaded": True}])
    with pytest.raises(SystemExit) as e:
        qa.preflight("http://127.0.0.1:8177/v1", qa.DEFAULT_MODEL, None, skip_tool_probe=True)
    assert e.value.code == 2
    assert "model '%s' not served. Available: %s." % (qa.DEFAULT_MODEL, VLM) in capsys.readouterr().err


def test_setup_passes_the_resolved_model_on(qa, monkeypatch, tmp_path):
    seen = []

    def fake_preflight(base_url, model, api_key, skip_tool_probe=False):
        seen.append(model)
        return VLM

    monkeypatch.setattr(qa, "preflight", fake_preflight)
    monkeypatch.setattr(qa, "searxng_probe", lambda: None)
    monkeypatch.setattr(qa, "discover_context_window", lambda *a: 8192)
    ns = qa.parse_args(["--workspace=%s" % tmp_path, "--user-prompt=x"])
    qa.setup(ns)
    assert seen == [None] and ns.model == VLM
