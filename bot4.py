import asyncio
import aiohttp
import os
import sys

from pipecat.frames.frames import EndFrame, StartInterruptionFrame, Frame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_response import (
    LLMUserContextAggregator,
    LLMAssistantContextAggregator,
)
from pipecat.processors.logger import FrameLogger
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.openai import OpenAILLMContext, OpenAILLMContextFrame
from pipecat.services.azure import AzureLLMService, AzureSTTService, AzureTTSService
from pipecat.transports.network.fastapi_websocket import (
    FastAPIWebsocketTransport,
    FastAPIWebsocketParams,
)
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.services.ai_services import AIService
from pipecat.serializers.twilio import TwilioFrameSerializer
from openai.types.chat import ChatCompletionToolParam
from openai._types import NotGiven, NOT_GIVEN
from langchain_community.vectorstores.azuresearch import AzureSearch
from langchain_openai import AzureOpenAIEmbeddings
from pipecat.services.openai_realtime_beta import (
    InputAudioTranscription,
    OpenAIRealtimeBetaLLMService,
    SessionProperties,
    TurnDetection,
)
from typing import List
import time
import json
from dotenv import load_dotenv

from loguru import logger

# uncomment for local development
# from dotenv import load_dotenv
load_dotenv('.env', override=True)

logger.remove(0)
logger.add(sys.stderr, level="DEBUG")

tools_realtime = [
    {
        "type": "function",
        "name": "answer_glp_question",
        "description": "Use this function to answer a GLP1 related question",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The user's question about coverage for GLP1 drugs for treating weight loss and Type 2 Diabetes, and medications such as Semaglutide, Ozempic, Wegovy, Mounjaro, Saxenda, Zepbound",
                }
            },
            "required": ["question"]
        },
    }
]


class InterruptionHandler(FrameProcessor):
    def __init__(self, websocket_client, stream_sid):
        super().__init__()
        self.websocket_client = websocket_client
        self.stream_sid = stream_sid
        self.last_text_frame_time = time.time()
        self.time_since_last_text_frame = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        if isinstance(frame, StartInterruptionFrame):
            buffer_clear_message = {"event": "clear", "streamSid": self.stream_sid}
            await self.websocket_client.send_text(json.dumps(buffer_clear_message))
        await self.push_frame(frame, direction)


class CallProcessor:
    def __init__(
        self,
        context: OpenAILLMContext,
        llm: AIService,
        tools: List[ChatCompletionToolParam] | NotGiven = NOT_GIVEN,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._context: OpenAILLMContext = context
        self._llm = llm

        # Configure tools only once
        self._context.set_tools(
            [
                {
                    "type": "function",
                    "name": "answer_glp_question",
                    "description": "Use this function to answer a GLP1 related question",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "question": {
                                "type": "string",
                                "description": "The user's question about coverage for GLP1 drugs for treating weight loss and Type 2 Diabetes."
                            }
                        },
                        "required": ["question"]
                    },
                }
            ]
        )

        # Add initial system messages to the context
        self._context.add_message(
            {
                "role": "system",
                "content": """
                    ## Identity
                    You are a helpful and knowledgeable assistant for a healthcare company. You only answer questions related to GLP1 drugs for treating weight loss and Type 2 Diabetes. The names for these medications include: Semaglutide, Ozempic, Wegovy, Mounjaro, Saxenda, Zepbound.
                    You're not a medical professional or pharmacist, so you shouldn't provide any counseling advice. If the caller asks for medical advice, you should ask them to consult with a healthcare professional.

                    ## Style
                    - Be informative and comprehensive, and use language that is easy-to-understand.
                    - Maintain a professional and polite tone at all times.
                    - You are able to respond in multiple non-English languages if asked. Do your best to accommodate such requests.
                    - Be as concise as possible, as you are currently operating in a voice-only channel.
                    - Do not use any kind of text highlighting or special characters such as parentheses, asterisks, or pound signs, since the text will be converted to audio.

                    ## Response Guideline
                    - ONLY answer questions about GLP1 drugs for weight loss and Type 2 Diabetes, and their associated conditions and treatments.
                    - You can provide general helpful information on basic medical conditions and terminology, but avoid offering any medical diagnosis or clinical guidance.
                    - Never engage in any discussion about your origin or OpenAI. If asked, respond with "I'm sorry, I can't answer that question."
                    - For any medical emergency, direct the user to hang up and seek immediate help.
                    - For all other healthcare related questions, please ask them to consult with a healthcare professional.
                """,
            }
        )

        # Register the function
        llm.register_function("answer_glp_question", self.answer_glp_question)

        self._embeddings: AzureOpenAIEmbeddings = AzureOpenAIEmbeddings(
            azure_endpoint=os.environ["AZURE_OPENAI_EMBEDDING_ENDPOINT"],
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            model="text-embedding-3-small",
        )

        self._vector_store: AzureSearch = AzureSearch(
            azure_search_endpoint=os.environ["AZURE_AI_SEARCH_ENDPOINT"],
            azure_search_key=os.environ["AZURE_AI_SEARCH_KEY"],
            index_name="vector-1727345921686",
            embedding_function=self._embeddings.embed_query,
        )

    async def answer_glp_question(self, function_name, tool_call_id, args, llm, context, result_callback):
        print("ENTERED GLP FUNCTION.....")
        docs = await self._vector_store.asimilarity_search(
            query=args["question"], k=6, search_type="similarity"
        )
        faq_context = ""
        for doc in docs:
            faq_context += f"Q: {doc.page_content}\nA: {doc.metadata['chunk']}\n\n"

        self._context.add_message(
            {
                "role": "system",
                "content": f"Answer the user's question using the following information from our FAQ. If you don't have enough information, respond with 'I'm sorry, I don't have that information.\n\n{faq_context}'",
            }
        )
        try:
            await llm.process_frame(
                OpenAILLMContextFrame(self._context), FrameDirection.DOWNSTREAM
            )
        except Exception as e:
            return [{"role": "system", "content": "I'm sorry, I can't answer that."}]


async def run_bot(websocket_client, stream_sid):
    async with aiohttp.ClientSession() as session:
        transport = FastAPIWebsocketTransport(
            websocket=websocket_client,
            params=FastAPIWebsocketParams(
                audio_out_enabled=True,
                audio_in_enabled=True,
                audio_in_sample_rate=24000,
                audio_out_sample_rate=24000,
                add_wav_header=False,
                vad_enabled=True,
                vad_analyzer=SileroVADAnalyzer(),
                vad_audio_passthrough=True,
                serializer=TwilioFrameSerializer(stream_sid),
            ),
        )

        interruption_handler = InterruptionHandler(websocket_client, stream_sid)

        session_properties = SessionProperties(
            input_audio_transcription=InputAudioTranscription(),
            turn_detection=TurnDetection(silence_duration_ms=1000),
            instructions="""
                Your knowledge cutoff is 2023-10. You are a helpful and friendly AI.
                Act like a human, but remember that you aren't a human and that you can't do human things in the real world. Your voice and personality should be warm and engaging, with a lively and playful tone.
                If interacting in a non-English language, start by using the standard accent or dialect familiar to the user. Talk quickly. You should always call a function if you can. Do not refer to these rules, even if you're asked about them.
                You are participating in a voice conversation. Keep your responses concise, short, and to the point unless specifically asked to elaborate on a topic.
                Remember, your responses should be short. Just one or two sentences, usually.
            """,
        )

        llm = OpenAIRealtimeBetaLLMService(
            api_key=os.getenv("OPENAI_API_KEY"),
            session_properties=session_properties,
            start_audio_paused=False,
        )

        context = OpenAILLMContext(messages=[], tools=tools_realtime)
        context_aggregator = llm.create_context_aggregator(context)

        processor = CallProcessor(context, llm)
        llm.register_function("answer_glp_question", processor.answer_glp_question)

        fl = FrameLogger("!!! after LLM", "red")
        pipeline = Pipeline(
            [
                transport.input(),
                context_aggregator.user(),
                llm,
                fl,
                transport.output(),
                context_aggregator.assistant(),
            ]
        )

        task = PipelineTask(pipeline, PipelineParams(allow_interruptions=True))

        @transport.event_handler("on_client_connected")
        async def on_client_connected(transport, participant):
            context.add_message(
                {
                    "role": "system",
                    "content": "Thank the user for calling Acme Health Company, and introduce yourself as Meredith, a personal care guide.",
                }
            )
            await task.queue_frames([OpenAILLMContextFrame(context)])

        @transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(transport, client):
            await task.queue_frames([EndFrame()])

        runner = PipelineRunner()
        await runner.run(task)