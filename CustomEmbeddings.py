from __future__ import annotations
import os
import requests
from typing import Any, List, Dict
from langchain_openai.embeddings import OpenAIEmbeddings

class CustomGatewayClient:
    """
    A simple client for calling your custom gateway.
    This client sends a payload of the form {"input": "text"}
    with an OAuth2 Bearer token (fetched via Okta) for authentication.
    """
    def __init__(self, endpoint: str, token: str):
        self.endpoint = endpoint
        self.token = token

    def create(self, input: str) -> Dict:
        headers = {"Authorization": f"Bearer {self.token}"}
        payload = {"input": input}
        response = requests.post(self.endpoint, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()


class CustomAzureOpenAIOAuthEmbeddings(OpenAIEmbeddings):
    """
    Custom embeddings class that mimics AzureOpenAIEmbeddings but uses OAuth2 via Okta.
    
    The custom gateway expects a payload like:
        {"input": "text"}
    and returns a response in the format:
        {"data": [{"embedding": [ ... ]}]}
    """
    model: str = "text-embedding-3-small"  # or your chosen model
    chunk_size: int = 2048  # adjust as needed

    def __init__(self, **data: Any):
        # Initialize any OpenAIEmbeddings fields.
        super().__init__(**data)

        # Load environment variables using os.getenv
        custom_endpoint = os.getenv("CUSTOM_GATEWAY_ENDPOINT")
        client_id = os.getenv("CUSTOM_GATEWAY_CLIENT_ID")
        client_secret = os.getenv("CUSTOM_GATEWAY_CLIENT_SECRET")
        okta_token_url = os.getenv("OKTA_TOKEN_URL")

        # Validate that required environment variables are present.
        if not custom_endpoint:
            raise ValueError("CUSTOM_GATEWAY_ENDPOINT environment variable is not set.")
        if not client_id:
            raise ValueError("CUSTOM_GATEWAY_CLIENT_ID environment variable is not set.")
        if not client_secret:
            raise ValueError("CUSTOM_GATEWAY_CLIENT_SECRET environment variable is not set.")
        if not okta_token_url:
            raise ValueError("OKTA_TOKEN_URL environment variable is not set.")

        self.custom_endpoint = custom_endpoint
        self.client_id = client_id
        self.client_secret = client_secret
        self.okta_token_url = okta_token_url

        # Fetch the OAuth2 token from Okta using the client credentials.
        token = self._fetch_oauth_token()

        # Initialize the custom client with the endpoint and token.
        self.client = CustomGatewayClient(self.custom_endpoint, token)

    def _fetch_oauth_token(self) -> str:
        """
        Fetches an OAuth2 token from Okta using client credentials.
        Adjust the payload (e.g. scope) as needed for your configuration.
        """
        token_data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "your_scope_here"  # Adjust the scope as needed.
        }
        response = requests.post(self.okta_token_url, data=token_data)
        response.raise_for_status()
        token_response = response.json()
        token = token_response.get("access_token")
        if not token:
            raise ValueError("No access_token found in the token response.")
        return token

    def embed_query(self, text: str) -> List[float]:
        """
        Embeds a single query text by sending {"input": text} to the custom gateway.
        Expects the response to contain an embedding at response["data"][0]["embedding"].
        """
        response = self.client.create(input=text)
        return response["data"][0]["embedding"]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        Embeds multiple documents by calling embed_query on each text.
        """
        return [self.embed_query(text) for text in texts]


# === Example Usage ===
if __name__ == "__main__":
    # Make sure your .env file is loaded (if using one):
    # from dotenv import load_dotenv
    # load_dotenv()

    # Instantiate the embeddings class.
    embeddings = CustomAzureOpenAIOAuthEmbeddings()

    # Test embedding a query.
    query = "What is the meaning of life?"
    vector = embeddings.embed_query(query)
    print("Query embedding (first three dimensions):", vector[:3])

    # Test embedding multiple documents.
    docs = ["Document one text", "Document two text"]
    docs_vectors = embeddings.embed_documents(docs)
    print("First document embedding (first three dimensions):", docs_vectors[0][:3])
