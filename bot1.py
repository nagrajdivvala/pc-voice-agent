import os
import sys
import aiohttp
import asyncio
import ssl

from pipecat.frames.frames import EndFrame, LLMMessagesFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_response import (
    LLMAssistantResponseAggregator,
    LLMUserResponseAggregator,
)
from pipecat.services.cartesia import CartesiaTTSService
from pipecat.services.openai import OpenAILLMService
from pipecat.services.azure import AzureLLMService
from azuresearch import AzureSearchService
from pipecat.services.deepgram import DeepgramSTTService,DeepgramTTSService
from pipecat.transports.network.fastapi_websocket import (
    FastAPIWebsocketTransport,
    FastAPIWebsocketParams,
)
from pipecat.vad.silero import SileroVADAnalyzer
from pipecat.serializers.twilio import TwilioFrameSerializer

from loguru import logger

from dotenv import load_dotenv

import certifi
print(certifi.where())
print(ssl.get_default_verify_paths())

load_dotenv(override=True)

logger.remove(0)
logger.add(sys.stderr, level="DEBUG")


ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

async def run_bot(websocket_client, stream_sid):
        
    transport = FastAPIWebsocketTransport(
        websocket=websocket_client,
        params=FastAPIWebsocketParams(
            audio_out_enabled=True,
            add_wav_header=False,
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(),
            vad_audio_passthrough=True,
            serializer=TwilioFrameSerializer(stream_sid),
        ),
    )

    llm = OpenAILLMService(api_key=os.getenv("OPENAI_API_KEY"), model="gpt-4o")
    stt = DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY"))
    tts = DeepgramTTSService(api_key=os.getenv("DEEPGRAM_API_KEY"))
     # Initialize Azure Cognitive Search service for RAG
    search_service = AzureSearchService(
        endpoint=os.getenv("AZURE_SEARCH_ENDPOINT"),
        index_name=os.getenv("AZURE_SEARCH_INDEX"),
        api_key=os.getenv("AZURE_SEARCH_KEY"),
    )

    # Define a custom processing step to integrate Azure RAG
    class AzureRAGStep:
        async def __call__(self, frame):
            user_query = frame.content

            # Retrieve relevant documents from Azure Cognitive Search
            retrieved_docs = search_service.retrieve_documents(user_query)

            # Prepare the prompt with retrieved documents as context
            context = "\n\n".join([doc["content"] for doc in retrieved_docs])
            prompt = f"Context:\n{context}\n\nQuestion:\n{user_query}\n\nAnswer:"

            # Call Azure OpenAI to generate the response
            response = await llm.generate_response(prompt)

            # Update the messages for the conversation history
            messages.append({"role": "user", "content": user_query})
            messages.append({"role": "assistant", "content": response})

            # Return the response as a new frame
            return LLMMessagesFrame(messages)

    azure_rag_step = AzureRAGStep()

    messages = [
        {
            "role": "system",
            "content": "You are a helpful LLM in an audio call. Your goal is to demonstrate your capabilities in a succinct way. Your output will be converted to audio so don't include special characters in your answers. Respond to what the user said in a creative and helpful way.",
        },
    ]

    tma_in = LLMUserResponseAggregator(messages)
    tma_out = LLMAssistantResponseAggregator(messages)

    pipeline = Pipeline(
        [
            transport.input(),  # Websocket input from client
            stt,  # Speech-To-Text
            tma_in,  # User responses
            azure_rag_step,  # Azure RAG processing step
            tts,  # Text-To-Speech
            transport.output(),  # Websocket output to client
            tma_out,  # LLM responses
        ]
    )

    task = PipelineTask(pipeline, params=PipelineParams(allow_interruptions=True))

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        # Kick off the conversation.
        messages.append({"role": "system", "content": "Please introduce yourself to the user."})
        await task.queue_frames([LLMMessagesFrame(messages)])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        await task.queue_frames([EndFrame()])

    runner = PipelineRunner(handle_sigint=False)

    await runner.run(task)
