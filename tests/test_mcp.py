from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ag.mcp import PROTOCOL, _write_message, serve


class McpFramingTests(unittest.TestCase):
    def test_write_message_is_ndjson_not_content_length(self) -> None:
        buf = io.StringIO()
        _write_message(buf, {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": PROTOCOL}})
        text = buf.getvalue()
        self.assertFalse(text.startswith("Content-Length"))
        self.assertNotIn("Content-Length", text)
        payload = json.loads(text.splitlines()[0])
        self.assertEqual(payload["result"]["protocolVersion"], PROTOCOL)

    def test_initialize_stdout_is_json_line(self) -> None:
        request = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            ensure_ascii=False,
        )
        writer = io.StringIO()
        serve(stdin=io.StringIO(request + "\n"), stdout=writer)
        text = writer.getvalue()
        self.assertTrue(text)
        first = text.splitlines()[0]
        self.assertFalse(first.startswith("Content-Length"))
        payload = json.loads(first)
        self.assertEqual(payload["jsonrpc"], "2.0")
        self.assertEqual(payload["id"], 1)
        self.assertEqual(payload["result"]["protocolVersion"], PROTOCOL)

    def test_empty_stdin_writes_nothing(self) -> None:
        writer = io.StringIO()
        serve(stdin=io.StringIO(""), stdout=writer)
        self.assertEqual(writer.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
