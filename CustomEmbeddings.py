from __future__ import annotations
import os
import requests
from typing import Any, List, Dict
from pydantic import BaseModel, Field, SecretStr
from langchain_openai.embeddings import OpenAIEmbeddings  # Inherit tokenization/batching if needed

class CustomGatewayClient:
    """
    Client for calling your custom gateway.
    
    This client sends a payload of the form {"input": "text"} and uses an OAuth2 token
    (fetched via Okta) for authentication.
    """
    def __init__(self, endpoint: str, token: str):
        self.endpoint = endpoint
        self.token = token

    def create(self, input: str) -> Dict:
        headers = {"Authorization": f"Bearer {self.token}"}
        # The payload is exactly as required by your service:
        payload = {"input": input}
        response = requests.post(self.endpoint, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()


class CustomAzureOpenAIOAuthEmbeddings(OpenAIEmbeddings):
    """
    Custom embeddings class that mimics AzureOpenAIEmbeddings
    but authenticates using OAuth2 via Okta.
    
    The underlying custom gateway expects a payload like:
        {"input": "text"}
    and returns a response in the same format as Azure OpenAI.
    """
    # Configuration parameters (can be set via environment variables)
    custom_endpoint: str = Field(..., env="CUSTOM_GATEWAY_ENDPOINT")
    client_id: SecretStr = Field(..., env="CUSTOM_GATEWAY_CLIENT_ID")
    client_secret: SecretStr = Field(..., env="CUSTOM_GATEWAY_CLIENT_SECRET")
    okta_token_url: str = Field(..., env="OKTA_TOKEN_URL")
    model: str = "text-embedding-3-small"  # or your chosen model
    chunk_size: int = 2048  # can be adjusted as needed

    def _fetch_oauth_token(self) -> str:
        """
        Fetch an OAuth2 token from Okta using client credentials.
        Adjust the payload (e.g. 'scope') as required by your setup.
        """
        token_data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id.get_secret_value(),
            "client_secret": self.client_secret.get_secret_value(),
            "scope": "your_scope_here"  # adjust the scope as needed
        }
        response = requests.post(self.okta_token_url, data=token_data)
        response.raise_for_status()
        token_response = response.json()
        return token_response["access_token"]

    def __init__(self, **data: Any):
        super().__init__(**data)
        # Use the OAuth2 token from Okta instead of an API key or AAD token.
        token = self._fetch_oauth_token()
        # Create our custom client that sends the simple payload.
        self.client = CustomGatewayClient(self.custom_endpoint, token)

    def embed_query(self, text: str) -> List[float]:
        """
        Embed a single query text by calling the custom gateway.
        The payload sent is simply {"input": text}.
        """
        response = self.client.create(input=text)
        # Expected response format: {"data": [{"embedding": [ ... ]}]}
        return response["data"][0]["embedding"]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        Embed multiple texts by calling embed_query for each.
        """
        return [self.embed_query(text) for text in texts]

    # Optionally, you can implement asynchronous versions (aembed_query/aembed_documents)
    # if required by your use case.
    
# === Usage Example ===
if __name__ == "__main__":
    # Make sure the following environment variables are set:
    #   CUSTOM_GATEWAY_ENDPOINT, CUSTOM_GATEWAY_CLIENT_ID,
    #   CUSTOM_GATEWAY_CLIENT_SECRET, OKTA_TOKEN_URL
    embeddings = CustomAzureOpenAIOAuthEmbeddings()
    
    # This call uses the inherited embed_query method,
    # which now sends a payload {"input": "text"} to your custom gateway.
    query = "What is the meaning of life?"
    embedding_vector = embeddings.embed_query(query)
    print("First three dimensions of embedding:", embedding_vector[:3])
    
    # You can also use embed_documents to embed multiple texts.
    docs = ["Document one text", "Document two text"]
    docs_embeddings = embeddings.embed_documents(docs)
    print("Embedding for first document:", docs_embeddings[0][:3])
