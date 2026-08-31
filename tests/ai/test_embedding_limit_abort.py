"""Quota / rate-limit errors must abort embedding generation immediately."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from ai.embeddings.generator import _index_helper_batch, generate_embeddings
from ai.errors import AI_CREDITS_EMPTY_MESSAGE
from common.exceptions import AIServiceError


class EmbeddingLimitAbortTests(SimpleTestCase):
    @patch("ai.embeddings.generator.get_client")
    def test_generate_embeddings_maps_quota_error(self, mock_get_client):
        client = MagicMock()
        mock_get_client.return_value = client
        client.embeddings.create.side_effect = Exception(
            "Error code: 429 - {'error': {'message': 'You have no credits remaining. "
            "Add credits to continue using the API.', 'type': 'insufficient_quota', "
            "'code': 'credit_balance_exhausted'}}"
        )

        with self.assertRaises(AIServiceError) as ctx:
            generate_embeddings(["pipe"])

        self.assertEqual(str(ctx.exception), AI_CREDITS_EMPTY_MESSAGE)
        self.assertEqual(client.embeddings.create.call_count, 1)

    @patch("ai.embeddings.generator.generate_embeddings")
    def test_quota_error_does_not_retry_row_by_row(self, mock_embed):
        mock_embed.side_effect = AIServiceError(AI_CREDITS_EMPTY_MESSAGE)
        helpers = [MagicMock(pk=index) for index in range(5)]
        texts = [f"row {index}" for index in range(5)]
        store = MagicMock()

        with self.assertRaises(AIServiceError) as ctx:
            _index_helper_batch(store, helpers, texts)

        self.assertEqual(str(ctx.exception), AI_CREDITS_EMPTY_MESSAGE)
        self.assertEqual(mock_embed.call_count, 1)
        store.upsert_helpers.assert_not_called()
        store.upsert_helper.assert_not_called()

    @patch("ai.embeddings.generator.generate_embedding")
    @patch("ai.embeddings.generator.generate_embeddings")
    def test_non_limit_batch_error_still_retries_rows(
        self, mock_embed, mock_one
    ):
        mock_embed.side_effect = AIServiceError("timeout talking to OpenAI")
        mock_one.return_value = [0.1, 0.2]
        helpers = [MagicMock(pk=1), MagicMock(pk=2)]
        store = MagicMock()

        generated, errors = _index_helper_batch(
            store, helpers, ["one", "two"]
        )

        self.assertEqual(generated, 2)
        self.assertEqual(errors, 0)
        self.assertEqual(mock_embed.call_count, 1)
        self.assertEqual(mock_one.call_count, 2)
        self.assertEqual(store.upsert_helper.call_count, 2)
