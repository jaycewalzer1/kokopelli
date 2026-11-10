"""A tiny pretend OpenAI chat server, for testing the guardrail wrapper against the real lm-eval without a real model.

Run:  python experiments/benchmarks/tests/fake_openai_server.py <port>
It always answers the same thing. Scores from it mean nothing. It only proves the harness and our parser fit together.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

ANSWER = "Answer: (A)"


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        messages = body if isinstance(body, list) else [body]
        reply = lambda request: {
            "id": "evals_fake", "object": "chat.completion", "model": request.get("model", "fake"),
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": ANSWER}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        data = json.dumps([reply(m) for m in messages] if isinstance(body, list) else reply(body)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
