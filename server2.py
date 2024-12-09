import json
import os
import uvicorn
import logging
import asyncio
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from bot6 import run_bot  # Assuming `run_bot` processes audio data and provides responses
from typing import Dict

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# State to store active WebSocket connections by CallConnectionId
connection_state: Dict[str, WebSocket] = {}

# Environment variables for configuration
ws_url = os.getenv("WS_URL", "wss://a715-24-228-1-63.ngrok-free.app/ws")  # WebSocket URL for the PipeCat bot

# CORS settings for development and testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/start_call")
async def start_call():
    """
    Endpoint for ACS to retrieve the WebSocket URL for audio streaming.
    """
    return {"websocketUrl": ws_url}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket handler for real-time bidirectional audio streaming with ACS.
    """
    await websocket.accept()
    logging.info("WebSocket connection accepted.")

    subscription_id = None  # Initialize subscription ID

    try:
        async for message in websocket.iter_text():
            packet = json.loads(message)
            kind = packet.get("kind")

            if kind == "AudioMetadata":
                # Extract and store subscription ID from AudioMetadata
                metadata = packet.get("audioMetadata", {})
                subscription_id = metadata.get("subscriptionId")
                logging.info(f"Received AudioMetadata with subscriptionId: {subscription_id}")

            elif kind == "AudioData" and subscription_id:
                # Process AudioData if subscription ID is known
                audio_data = packet.get("audioData", {})
                raw_audio = audio_data.get("data")
                if audio_data.get("silent"):
                    logging.info(f"Silent audio packet for subscriptionId: {subscription_id}")
                    continue

                logging.info(f"Processing AudioData for subscriptionId: {subscription_id}")

                # Pass the raw audio to the bot for processing
                await run_bot(websocket, subscription_id)

                # # Send the processed audio back to ACS
                # response_packet = {
                #     "kind": "AudioData",
                #     "audioData": {
                #         "subscriptionId": subscription_id,
                #         "data": processed_audio,
                #         "timestamp": audio_data.get("timestamp"),
                #         "participantRawID": audio_data.get("participantRawID"),
                #         "silent": False,
                #     },
                # }
                # await websocket.send_json(response_packet)
                logging.info(f"Sent processed audio back for subscriptionId: {subscription_id}")

            else:
                logging.warning("AudioData received before AudioMetadata or missing subscriptionId.")

    except Exception as e:
        logging.error(f"WebSocket error: {e}")
    finally:
        logging.info("WebSocket connection closed.")




if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8765)
