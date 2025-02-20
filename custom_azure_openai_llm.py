import json
import logging
from typing import Any, Dict, List

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Assuming the following types are imported from your framework:
#   - OpenAILLMContext, ChatCompletionMessageParam, ChatCompletionChunk, LLMService, AsyncStream, AsyncOpenAI, NOT_GIVEN

class CustomAzureOpenAIAsyncLLMService(BaseOpenAILLMService):
    def __init__(
        self,
        *,
        token_url: str,
        gateway_endpoint: str,
        client_id: str,
        client_secret: str,
        # Additional parameters (e.g., model, api_key, base_url, params) are passed via kwargs.
        **kwargs,
    ):
        """
        Initializes the custom async service.

        :param token_url: URL to fetch the Okta token.
        :param gateway_endpoint: Custom gateway endpoint wrapping the Azure OpenAI service.
        :param client_id: Okta client ID.
        :param client_secret: Okta client secret.
        Additional parameters are passed via kwargs.
        """
        super().__init__(**kwargs)
        self.token_url = token_url
        self.gateway_endpoint = gateway_endpoint
        self.client_id = client_id
        self.client_secret = client_secret

    async def _get_okta_token(self) -> str:
        """
        Asynchronously fetches an Okta access token.

        :return: Access token as a string.
        :raises Exception: If the token cannot be obtained.
        """
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(self.token_url, data=payload)
            response.raise_for_status()
            data = response.json()
            token = data.get("access_token")
            if not token:
                raise Exception("Failed to obtain Okta token.")
            return token

    async def get_chat_completions(
        self,
        context: "OpenAILLMContext",
        messages: List["ChatCompletionMessageParam"],
    ) -> AsyncStream["ChatCompletionChunk"]:
        """
        Asynchronously calls the custom gateway to perform a chat completion and returns
        an AsyncStream of ChatCompletionChunk objects. This closely mirrors the behavior of
        the base class, which returns the output of self._client.chat.completions.create(**params).

        :param context: The OpenAILLMContext containing tools and tool_choice.
        :param messages: List of chat messages.
        :return: An AsyncStream yielding chat completion chunks.
        """
        token = await self._get_okta_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": self.model_name,
            "stream": True,
            "messages": messages,
            "tools": context.tools,
            "tool_choice": context.tool_choice,
            "stream_options": {"include_usage": True},
            "frequency_penalty": self._settings["frequency_penalty"],
            "presence_penalty": self._settings["presence_penalty"],
            "seed": self._settings["seed"],
            "temperature": self._settings["temperature"],
            "top_p": self._settings["top_p"],
            "max_tokens": self._settings["max_tokens"],
            "max_completion_tokens": self._settings["max_completion_tokens"],
        }
        payload.update(self._settings["extra"])

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.gateway_endpoint,
                headers=headers,
                json=payload,
                stream=True
            )
            response.raise_for_status()
            # Wrap the httpx.Response in an AsyncStream using self._client.
            # This returns the same type as self._client.chat.completions.create(**params)
            return AsyncStream(
                cast_to=ChatCompletionChunk,
                response=response,
                client=self._client,
            )

    async def _stream_chat_completions(
        self, context: "OpenAILLMContext"
    ) -> AsyncStream["ChatCompletionChunk"]:
        """
        Calls the custom gateway for streaming chat completions without additional processing.
        This method simply retrieves messages from the context and delegates to get_chat_completions,
        ensuring the returned type is an AsyncStream, just like in the base class.

        :param context: The OpenAILLMContext containing messages and additional data.
        :return: An AsyncStream yielding chat completion chunks.
        """
        messages = context.get_messages()
        return await self.get_chat_completions(context, messages)
