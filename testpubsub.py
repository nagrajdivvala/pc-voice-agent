from azure.messaging.webpubsubservice import WebPubSubServiceClient
from azure.core.credentials import AzureKeyCredential
import os

# Set environment variables or replace with actual values
web_pubsub_endpoint = os.getenv("WEB_PUBSUB_ENDPOINT")
web_pubsub_key = os.getenv("WEB_PUBSUB_KEY")
hub_name = "Hub"  # Replace with your hub name

# Initialize Web PubSub client
web_pubsub_client = WebPubSubServiceClient(
    endpoint=web_pubsub_endpoint,
    hub=hub_name,
    credential=AzureKeyCredential(web_pubsub_key)
)

# Send a test message to all clients connected to the hub
def send_test_message():
    message = "Test message from Web PubSub client"
    web_pubsub_client.send_to_all(message)

send_test_message()
