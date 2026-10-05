import unittest
import json
from unittest.mock import patch

import httpx

from drishti.assistant import answer_question


class DrishtiAssistantTests(unittest.IsolatedAsyncioTestCase):
    async def test_responses_api_request_returns_answer_and_clickable_sources(self):
        def respond(request):
            self.assertEqual(str(request.url), "https://api.openai.com/v1/responses")
            self.assertEqual(request.headers["Authorization"], "Bearer private-test-key")
            payload = json.loads(request.content)
            self.assertEqual(payload["tools"], [{"type": "web_search"}])
            self.assertFalse(payload["store"])
            self.assertEqual(payload["input"], [{"role": "user", "content": "What changed today?"}])
            return httpx.Response(200, json={"output": [{
                "type": "message",
                "content": [{
                    "type": "output_text",
                    "text": "Here is the answer. [Source]",
                    "annotations": [{"type": "url_citation", "url": "https://example.com/story", "title": "Source"}],
                }],
            }]})

        client_factory = httpx.AsyncClient
        with patch(
            "drishti.assistant.httpx.AsyncClient",
            side_effect=lambda timeout: client_factory(transport=httpx.MockTransport(respond), timeout=timeout),
        ):
            result = await answer_question(
                [{"role": "user", "content": "What changed today?"}],
                api_key="private-test-key",
            )
        self.assertEqual(result, {
            "answer": "Here is the answer. [Source]",
            "sources": [{"title": "Source", "url": "https://example.com/story"}],
        })


if __name__ == "__main__":
    unittest.main()
