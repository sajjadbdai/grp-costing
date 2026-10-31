"""Muse client checks: payloads, parsing and key safety (no network)."""

import io
import os
import urllib.error
from unittest import mock

import unittest

from app import muse_client


class PayloadTests(unittest.TestCase):
    def test_responses_payload(self):
        payload = muse_client.build_responses_payload(
            "muse-wonder-1.0", "sys", "hi", image="data:image/png;base64,AA",
            schema=muse_client.EXTRACTION_SCHEMA)
        self.assertEqual(payload["model"], "muse-wonder-1.0")
        content = payload["input"][0]["content"]
        self.assertEqual(content[0]["type"], "input_text")
        self.assertEqual(content[1]["type"], "input_image")
        self.assertEqual(payload["text"]["format"]["type"], "json_schema")

    def test_chat_payload(self):
        payload = muse_client.build_chat_payload("m", "sys", "hi", image="data:x",
                                                 schema={"type": "object"})
        messages = payload["messages"]
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["content"][1]["type"], "image_url")
        self.assertEqual(payload["response_format"]["type"], "json_schema")

    def test_payload_without_image(self):
        payload = muse_client.build_responses_payload("m", "sys", "hi")
        self.assertEqual(len(payload["input"][0]["content"]), 1)


class ParseTests(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(muse_client.extract_json('{"a": 1}'), {"a": 1})

    def test_fenced_json(self):
        self.assertEqual(muse_client.extract_json('```json\n{"a": 1}\n```'), {"a": 1})

    def test_prose_wrapped_json(self):
        self.assertEqual(muse_client.extract_json('Here it is: {"a": 1} done'), {"a": 1})

    def test_empty_reply(self):
        with self.assertRaises(muse_client.MuseError):
            muse_client.extract_json("   ")

    def test_responses_text_shape(self):
        data = {"output": [{"content": [{"type": "output_text", "text": "hello"}]}]}
        self.assertEqual(muse_client.extract_output_text(data), "hello")

    def test_chat_text_shape(self):
        data = {"choices": [{"message": {"content": "hi there"}}]}
        self.assertEqual(muse_client.extract_output_text(data), "hi there")


class NormalizeTests(unittest.TestCase):
    def test_valid_extraction(self):
        raw = {"shape": "panel", "dims": [
            {"field": "length", "value": 675, "unit": "mm",
             "source": "drawing", "quote": "675"},
            {"field": "thickness", "value": None, "unit": None,
             "source": "description", "quote": ""}],
            "missing": ["Laminate thickness"], "ambiguities": [],
            "questions": ["What is the thickness?"], "quantity": 4}
        review = muse_client.normalize_extraction(raw)
        self.assertEqual(review["shape"], "panel")
        self.assertEqual(review["quantity"], 4)
        self.assertEqual(review["dims"][0]["value"], 675.0)
        self.assertEqual(len(review["questions"]), 1)

    def test_unknown_shape_falls_back_to_hint(self):
        review = muse_client.normalize_extraction({"shape": "vault", "dims": []}, "cylinder")
        self.assertEqual(review["shape"], "cylinder")
        self.assertTrue(review["notes"])

    def test_garbage_never_raises(self):
        review = muse_client.normalize_extraction(
            {"shape": "panel", "dims": [{"field": "nope", "value": -3, "unit": "furlong"},
                                        "junk",
                                        {"field": "length", "value": "wide"}]})
        self.assertEqual(review["shape"], "panel")
        self.assertTrue(review["notes"])

    def test_option_coercion(self):
        review = muse_client.normalize_extraction(
            {"shape": "cylinder", "dims": [],
             "options": {"closed_bottom": "yes", "closed_top": "open"}})
        self.assertEqual(review["options"], {"closed_bottom": True, "closed_top": False})


class ConfigTests(unittest.TestCase):
    def test_unconfigured_without_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            config = muse_client.MuseConfig()
            self.assertFalse(config.configured)
            self.assertEqual(config.model, "muse-wonder-1.0")
            self.assertNotIn("MODEL_API_KEY", repr(config.summary()))

    def test_configured_with_key(self):
        env = {"MODEL_API_KEY": "secret-key", "MODEL_ID": "custom-1",
               "MODEL_API_FORMAT": "chat"}
        with mock.patch.dict(os.environ, env, clear=True):
            config = muse_client.MuseConfig()
            self.assertTrue(config.configured)
            self.assertEqual(config.model, "custom-1")
            summary = repr(config.summary())
            self.assertNotIn("secret-key", summary)

    def test_extract_requires_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(muse_client.MuseError) as raised:
                muse_client.extract_inputs("panel please")
            self.assertIn("MODEL_API_KEY", str(raised.exception))

    def test_error_never_leaks_key(self):
        failure = urllib.error.HTTPError(
            "https://api.meta.ai/v1/responses", 401, "Unauthorized", {}, io.BytesIO(b"bad"))
        with mock.patch("urllib.request.urlopen", side_effect=failure):
            with self.assertRaises(muse_client.MuseError) as raised:
                muse_client._post("https://x", {}, "super-secret-key", 5)
        self.assertIn("401", str(raised.exception))
        self.assertNotIn("super-secret-key", str(raised.exception))


if __name__ == "__main__":
    unittest.main()

class RobustnessTests(unittest.TestCase):
    def test_incomplete_status_raises(self):
        data = {"status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"}, "output": []}
        with mock.patch("app.muse_client._post_with_retry", return_value=data):
            with mock.patch.dict(os.environ, {"MODEL_API_KEY": "k"}, clear=True):
                with self.assertRaises(muse_client.MuseError) as raised:
                    muse_client._call(muse_client.MuseConfig(), "sys", "hi")
                self.assertIn("max_output_tokens", str(raised.exception))

    def test_partial_text_survives_incomplete(self):
        data = {"status": "incomplete",
                "output": [{"content": [{"type": "output_text", "text": "x"}]}]}
        with mock.patch("app.muse_client._post_with_retry", return_value=data):
            with mock.patch.dict(os.environ, {"MODEL_API_KEY": "k"}, clear=True):
                out = muse_client._call(muse_client.MuseConfig(), "sys", "hi")
                self.assertEqual(out, data)

    def test_extraction_payload_tuning(self):
        payload = muse_client.build_responses_payload("m", "s", "u", temperature=0.0,
                                                      reasoning_effort="low")
        self.assertEqual(payload["temperature"], 0.0)
        self.assertEqual(payload["reasoning"], {"effort": "low"})
        self.assertEqual(payload["max_output_tokens"], 16000)