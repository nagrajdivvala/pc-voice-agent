import json
import base64
from pydantic import BaseModel
from pipecat.frames.frames import Frame, AudioRawFrame, StartInterruptionFrame
from pipecat.serializers.base_serializer import FrameSerializer
from pipecat.audio.utils import ulaw_to_pcm, pcm_to_ulaw # Replace with your utility functions


class ACSFrameSerializer(FrameSerializer):
    """
    Serializer for handling ACS-specific audio streaming frames.
    """
    class InputParams(BaseModel):
        acs_sample_rate: int = 24000
        sample_rate: int = 24000

    def __init__(self, stream_sid: str, params: InputParams = InputParams()):
        self._stream_sid = stream_sid  # Unique session identifier for the audio stream
        self._params = params

    def serialize(self, frame: Frame) -> str | bytes | None:
        """
        Serialize an AudioRawFrame or StartInterruptionFrame into an ACS-compatible WebSocket message.
        """
        if isinstance(frame, AudioRawFrame):
            data = frame.audio

            # Convert PCM to uLaw and encode to base64 for ACS compatibility
            serialized_data = pcm_to_ulaw(data, frame.sample_rate, self._params.acs_sample_rate)
            payload = base64.b64encode(data).decode("utf-8")
            answer = {
                "kind": "AudioData",
                "audioData": {
                    "data": payload,
                    "encoding": "base64",
                    "sampleRate": self._params.acs_sample_rate,
                },
                "streamSid": self._stream_sid,
            }
            return json.dumps(answer)

        if isinstance(frame, StartInterruptionFrame):
            # Serialize interruption frames as metadata
            answer = {
                "kind": "AudioMetadata",
                "event": "clear",
                "streamSid": self._stream_sid,
            }
            return json.dumps(answer)

        return None

    def deserialize(self, data: str | bytes) -> Frame | None:
        """
        Deserialize ACS WebSocket messages into Frame objects.
        """
        try:
            message = json.loads(data)
            kind = message.get("kind")

            if kind == "AudioData":
                payload_base64 = message["audioData"]["data"]
                payload = base64.b64decode(payload_base64)

                # Convert uLaw to PCM
                deserialized_data = ulaw_to_pcm(
                    payload, self._params.acs_sample_rate, self._params.sample_rate
                )
                audio_frame = AudioRawFrame(
                    audio=payload, num_channels=1, sample_rate=self._params.sample_rate
                )
                return audio_frame

            if kind == "AudioMetadata" and message.get("event") == "clear":
                # Deserialize interruption metadata
                return StartInterruptionFrame()

        except Exception as e:
            print(f"Error deserializing ACS message: {e}")

        return None
