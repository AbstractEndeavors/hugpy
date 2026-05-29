"""Unit test for the VL branch in chat/streaming.py.

Monkeypatches the abstract_hugpy imports inside stream_events so the test
can run without abstract_hugpy / huggingface_hub / abstract_flask installed.
Covers:
  - text-only path still falls through to runner.stream / runner.run
  - images present + runner is VisionRunner -> emits a one-shot token + done
  - images present + runner is NOT VisionRunner -> emits an error event
"""
from __future__ import annotations

import asyncio
import json
import sys
import types
import unittest
from pathlib import Path


# Make the api package importable
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "api"))


def _install_stubs():
    """Stub the abstract_hugpy modules referenced inside stream_events."""

    class VisionRunner:
        pass

    class _DummyResult:
        def __init__(self, text):
            self.text = text

    class FakeVRunner(VisionRunner):
        last_req = None

        def run(self, *, req):
            FakeVRunner.last_req = req
            return _DummyResult("the image shows a frog")

    class FakeTextRunner:
        async def stream(self, req):
            yield types.SimpleNamespace(type="token", text="hi")
            yield types.SimpleNamespace(type="done", finish_reason="stop")

        async def run(self, req):
            return _DummyResult("hi")

    class ChatRequest:
        def __init__(self, **kw):
            self.kw = kw

    class VisionRequest:
        def __init__(self, *, prompt, image_b64=None, image_path=None):
            if not (bool(image_b64) ^ bool(image_path)):
                raise ValueError("need exactly one image source")
            self.prompt = prompt
            self.image_b64 = image_b64
            self.image_path = image_path

    # Build the stub package tree
    hugpy = types.ModuleType("abstract_hugpy")
    managers = types.ModuleType("abstract_hugpy.managers")
    dispatch = types.ModuleType("abstract_hugpy.managers.dispatch")
    vision = types.ModuleType("abstract_hugpy.managers.vision")
    vision_schemas = types.ModuleType("abstract_hugpy.managers.vision.schemas")
    imports_pkg = types.ModuleType("abstract_hugpy.imports")
    imports_src = types.ModuleType("abstract_hugpy.imports.src")
    schemas_pkg = types.ModuleType("abstract_hugpy.imports.src.schemas")
    chat_schemas = types.ModuleType("abstract_hugpy.imports.src.schemas.chat_schemas")

    state = {"runner": FakeVRunner()}

    def runner_for(model_key=None, **kw):
        return state["runner"]

    dispatch.runner_for = runner_for
    vision.VisionRunner = VisionRunner
    vision_schemas.VisionRequest = VisionRequest
    chat_schemas.ChatRequest = ChatRequest

    sys.modules.update(
        {
            "abstract_hugpy": hugpy,
            "abstract_hugpy.managers": managers,
            "abstract_hugpy.managers.dispatch": dispatch,
            "abstract_hugpy.managers.vision": vision,
            "abstract_hugpy.managers.vision.schemas": vision_schemas,
            "abstract_hugpy.imports": imports_pkg,
            "abstract_hugpy.imports.src": imports_src,
            "abstract_hugpy.imports.src.schemas": schemas_pkg,
            "abstract_hugpy.imports.src.schemas.chat_schemas": chat_schemas,
        }
    )

    return state, FakeVRunner, FakeTextRunner


def _collect(agen):
    out = []

    async def drain():
        async for ev in agen:
            out.append(ev)

    asyncio.run(drain())
    return out


def _parse_sse(lines):
    payloads = []
    for line in lines:
        for sub in line.split("\n\n"):
            sub = sub.strip()
            if sub.startswith("data: "):
                payloads.append(json.loads(sub[len("data: "):]))
    return payloads


class _Msg:
    def __init__(self, role, content, images=None):
        self.role = role
        self.content = content
        self.images = images

    def model_dump(self, exclude_none=False):
        d = {"role": self.role, "content": self.content}
        if self.images is not None or not exclude_none:
            d["images"] = self.images
        return d


class _Body:
    def __init__(self, messages):
        self.model_key = "test-model"
        self.messages = messages
        self.max_new_tokens = 16
        self.temperature = 0.1
        self.do_sample = False


class VLBranchTests(unittest.TestCase):
    def setUp(self):
        # Reload the module under test against fresh stubs.
        for name in list(sys.modules):
            if name.startswith("api.app.functions.chat.streaming"):
                del sys.modules[name]
            if name.startswith("abstract_hugpy"):
                del sys.modules[name]
        self.state, self.FakeVRunner, self.FakeTextRunner = _install_stubs()

    def _load_stream_events(self):
        # Import the streaming module by file path so we don't need the full
        # abstract_flask-based app package to be importable.
        import importlib.util

        path = (
            HERE.parent
            / "api"
            / "app"
            / "functions"
            / "chat"
            / "streaming.py"
        )
        # The module does `from .imports import *`; satisfy that by stubbing
        # what it needs from the imports surface.
        stub_imports = types.ModuleType("_chat_streaming_imports_stub")
        stub_imports.json = json
        import inspect as _inspect

        stub_imports.inspect = _inspect

        class _ChatBody:
            pass

        stub_imports.ChatBody = _ChatBody

        # Inject as the relative `.imports` parent
        pkg = types.ModuleType("_vl_test_pkg")
        pkg.__path__ = []
        sys.modules["_vl_test_pkg"] = pkg
        sys.modules["_vl_test_pkg.imports"] = stub_imports

        src = path.read_text()
        src = src.replace("from .imports import *", "from _vl_test_pkg.imports import *")
        mod = types.ModuleType("_vl_streaming_under_test")
        exec(compile(src, str(path), "exec"), mod.__dict__)
        return mod.stream_events

    def test_vl_branch_with_image(self):
        self.state["runner"] = self.FakeVRunner()
        stream_events = self._load_stream_events()
        body = _Body([_Msg("user", "what is this?", images=["AAAA"])])
        events = _parse_sse(_collect(stream_events(body)))

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["type"], "token")
        self.assertEqual(events[0]["text"], "the image shows a frog")
        self.assertEqual(events[1]["type"], "done")
        self.assertEqual(self.FakeVRunner.last_req.prompt, "what is this?")
        self.assertEqual(self.FakeVRunner.last_req.image_b64, "AAAA")

    def test_images_with_non_vl_runner_emits_error(self):
        self.state["runner"] = self.FakeTextRunner()
        stream_events = self._load_stream_events()
        body = _Body([_Msg("user", "hi", images=["AAAA"])])
        events = _parse_sse(_collect(stream_events(body)))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "error")
        self.assertIn("does not accept images", events[0]["message"])

    def test_text_only_path_uses_stream(self):
        self.state["runner"] = self.FakeTextRunner()
        stream_events = self._load_stream_events()
        body = _Body([_Msg("user", "hello")])
        events = _parse_sse(_collect(stream_events(body)))

        self.assertGreaterEqual(len(events), 2)
        self.assertEqual(events[0]["type"], "token")
        self.assertEqual(events[0]["text"], "hi")
        self.assertEqual(events[-1]["type"], "done")

    def test_text_fallback_handles_sync_run(self):
        # Runner with no .stream and a SYNC .run — regression for the bug
        # where the non-streaming fallback did `await runner.run(req)`.
        class SyncOnlyRunner:
            def stream(self, req):
                raise NotImplementedError

            def run(self, req):
                class R:
                    text = "sync result"
                return R()

        self.state["runner"] = SyncOnlyRunner()
        stream_events = self._load_stream_events()
        body = _Body([_Msg("user", "hello")])
        events = _parse_sse(_collect(stream_events(body)))

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["type"], "token")
        self.assertEqual(events[0]["text"], "sync result")
        self.assertEqual(events[1]["type"], "done")


if __name__ == "__main__":
    unittest.main()
