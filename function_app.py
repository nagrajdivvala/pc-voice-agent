import logging
import json
import os
import requests
import asyncio
import azure.functions as func
from azure.communication.callautomation import (
    CallAutomationClient,
    CallConnectionClient,
    MediaStreamingOptions,
    MediaStreamingTransportType,
    MediaStreamingAudioChannelType,
    MediaStreamingContentType,
    AudioFormat
)
from websockets import connect

app = func.FunctionApp()

# Load environment variables
acs_connection_string = os.getenv("ACS_CONNECTION_STRING")
callback_url = os.getenv("CALLBACK_URL")  # Callback URL for call status updates
pipecat_start_call_url = os.getenv("PIPECAT_START_CALL_URL")  # PipeCat start call webhook URL
# Temporary in-memory store for WebSocket URLs
websocket_url_store = {}
# Initialize Call Automation Client
call_automation_client = CallAutomationClient.from_connection_string(acs_connection_string)

@app.function_name(name="EventGridTrigger1")
@app.event_grid_trigger(arg_name="event")
async def eventGridTrigger1(event: func.EventGridEvent):
    """
    Event Grid Trigger for ACS Incoming Call Events.
    """
    try:
        # Log basic event information
        event_data = event.get_json()
        logging.info(f"EventGrid trigger processed event: {json.dumps(event_data)}")

        incoming_call_context = event_data.get("incomingCallContext")
        if not incoming_call_context:
            logging.error("incomingCallContext is missing in the Event Grid data.")
            return

        # Step 1: Call PipeCat start call webhook to get WebSocket URL
        logging.info("Calling PipeCat start call webhook to retrieve WebSocket URL...")
        response = requests.post(pipecat_start_call_url, json={"callId": event.id})
        if response.status_code != 200:
            logging.error(f"PipeCat webhook returned non-200 status: {response.status_code}")
            return

        response_data = response.json()
        websocket_url = response_data.get("websocketUrl")
        if not websocket_url:
            logging.error("WebSocket URL is missing in the PipeCat webhook response.")
            return
        logging.info(f"Retrieved WebSocket URL: {websocket_url}")

        # Step 2: Configure media streaming options to start immediately
        media_streaming_options = MediaStreamingOptions(
            transport_url=websocket_url,
            content_type=MediaStreamingContentType.AUDIO,
            transport_type=MediaStreamingTransportType.WEBSOCKET,
            audio_channel_type=MediaStreamingAudioChannelType.MIXED,
            start_media_streaming=True,  # Start streaming immediately
            enable_bidirectional=True,
            audio_format=AudioFormat.PCM24_K_MONO,
        )

        # Answer the call and start media streaming immediately
        answer_result = call_automation_client.answer_call(
            incoming_call_context=incoming_call_context,
            callback_url=callback_url,
            media_streaming=media_streaming_options
        )
        call_connection_id = answer_result.call_connection_id
        logging.info(f"Call answered successfully. Call Connection ID: {call_connection_id}")

        # Step 3: Establish WebSocket connection to PipeCat (Initial Setup)
       # await initialize_websocket(websocket_url, call_connection_id)
        # Log the Subscription ID for tracking
        subscription_id = answer_result.media_streaming_subscription.id
        logging.info(f"Media streaming started with Subscription ID: {subscription_id}")


    except Exception as e:
        logging.error(f"Error handling Event Grid trigger: {e}")



@app.function_name(name="CallbackHandler")
@app.route(route="callback", methods=["POST"])
async def callback_handler(req: func.HttpRequest) -> func.HttpResponse:
    """
    HTTP Trigger to handle call state updates from ACS.
    """
    try:
        raw_data = req.get_body()
        data = json.loads(raw_data)
        events = data if isinstance(data, list) else [data]

        for event in events:
            event_type = event.get("type")
            call_connection_id = event.get("data", {}).get("callConnectionId")

            if not event_type or not call_connection_id:
                logging.error("Invalid callback data. Missing callConnectionId or eventType.")
                continue

            if event_type == "Microsoft.Communication.CallConnected":
                logging.info(f"Call connected. Call Connection ID: {call_connection_id}")

                # Start media streaming
                call_connection_client = call_automation_client.get_call_connection(call_connection_id)
                call_connection_client.start_media_streaming()
                logging.info(f"Media streaming started for Call Connection ID: {call_connection_id}")

        return func.HttpResponse("Callback processed successfully.", status_code=200)

    except Exception as e:
        logging.error(f"Error processing callback: {e}")
        return func.HttpResponse(f"Error: {e}", status_code=500)





