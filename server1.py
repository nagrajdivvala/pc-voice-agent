import os
import logging
import asyncio
import uuid
from fastapi import FastAPI
from azure.messaging.webpubsubservice import WebPubSubServiceClient
from azure.core.credentials import AzureKeyCredential
from websockets import connect
from bot4 import run_bot  # Assuming run_bot can handle WebSocket and stream_id

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI()

# Environment variables for Web PubSub
web_pubsub_endpoint = os.getenv("WEB_PUBSUB_ENDPOINT")  # e.g., "https://<your-webpubsub-name>.webpubsub.azure.com"
web_pubsub_key = os.getenv("WEB_PUBSUB_KEY")            # Web PubSub access key
hub_name = "Hub"  # Name of your hub

# Initialize Web PubSub Service Client with AzureKeyCredential
web_pubsub_client = WebPubSubServiceClient(
    endpoint=web_pubsub_endpoint,
    hub=hub_name,
    credential=AzureKeyCredential(web_pubsub_key)
)

# Generate WebSocket URL with an access token
def get_websocket_url():
    client_token_info = web_pubsub_client.get_client_access_token()
    client_access_url = client_token_info["url"]
    return client_access_url

# Background task to automatically listen to Web PubSub
async def listen_to_webpubsub():
    # Generate a unique stream ID for this session
    stream_id = str(uuid.uuid4())
    logger.info(f"Assigned stream ID: {stream_id}")

    client_url = get_websocket_url()
    logger.info(f"Connecting to Web PubSub with URL: {client_url}")

    # Connect to Web PubSub as a client
    async with connect(client_url) as websocket:
        logger.info("Connected to Azure Web PubSub")

        # Listen for binary audio data from Web PubSub
        async for message in websocket:
            if isinstance(message, bytes):  # Expecting binary audio data
                logger.info(f"Received audio chunk of size {len(message)} bytes for stream ID {stream_id}")
                await run_bot(websocket, stream_id)
            else:
                logger.warning(f"Received non-binary message of type {type(message)}, skipping.")

# Start the background task when FastAPI starts
@app.on_event("startup")
async def startup_event():
    # Start the WebSocket listener in the background when FastAPI starts
    asyncio.create_task(listen_to_webpubsub())

# Main endpoint for health check or additional APIs
@app.get("/")
async def root():
    return {"message": "FastAPI WebSocket client connected to Azure Web PubSub"}

# Run FastAPI app
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8765)
