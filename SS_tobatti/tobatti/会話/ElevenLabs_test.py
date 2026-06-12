# pip install elevenlabs
from elevenlabs.client import ElevenLabs

def _speak_with_elevenlabs(text):
    client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
    audio = client.generate(
        text=text,
        voice="grace",  # 柔らかい女性音声
        model="eleven_monolingual_v1"
    )
    # 再生処理