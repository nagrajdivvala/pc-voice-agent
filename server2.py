import json
import os
import uvicorn
import logging
import asyncio
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from bot5 import run_bot  # Assuming `run_bot` processes audio data and provides responses
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
    WebSocket handler for real-time bi-directional audio streaming.
    """
    await websocket.accept()
    logger.info("WebSocket connection accepted")

    try:
        # Step 1: Wait for the initial connection and incoming audio stream from ACS (ACS sends audio packets with callConnectionId embedded)
        async for message in websocket.iter_text():
            try:
                packet = json.loads(message)
                kind = packet.get("kind")

                if kind == "AudioData":
                    # Audio data is sent directly in the media stream
                    audio_data = packet.get("audioData")
                    if audio_data:
                        logger.info(f"AudioData: {packet}")
                        logger.info(f"Received AudioData for Call Connection ID: {packet.get('callConnectionId')}")  # The callConnectionId will be part of the stream

                        # Process audio with `run_bot`
                        await run_bot(websocket, packet.get('callConnectionId'))  # Ensure run_bot uses the callConnectionId

                elif kind == "AudioMetadata":
                    # Handle Audio Metadata (this might include information about the call, participant, etc.)
                    metadata = packet.get("audioMetadata")
                    logger.info(f"Received Audio Metadata: {metadata}")

            except Exception as e:
                logger.error(f"Error processing WebSocket message: {e}")
                break

    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        logger.info("WebSocket connection closed")




if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8765)
