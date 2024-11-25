from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from pipecat.services.ai_services import AIService

class AzureSearchService(AIService):
    def __init__(self, endpoint, index_name, api_key):
        self.search_client = SearchClient(
            endpoint=endpoint,
            index_name=index_name,
            credential=AzureKeyCredential(api_key)
        )

    def retrieve_documents(self, query):
        results = self.search_client.search(query)
        return [doc for doc in results]
