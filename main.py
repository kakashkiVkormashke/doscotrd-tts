import discord
import os
import asyncio
from gtts import gTTS
import uuid

TOKEN = os.environ.get('DISCORD_TOKEN')
TTS_CHANNEL_ID = int(os.environ.get('TTS_CHANNEL_ID', 1428896474611187734))

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = discord.Client(intents=intents)

@bot.event
async def on_ready():
    print(f'✅ Бот {bot.user} запущен!')

@bot.event
async def on_message(message):
    if message.author.bot or message.channel.id != TTS_CHANNEL_ID:
        return
    
    if message.author.voice is None:
        await message.delete()
        return

    text = message.content.strip()
    await message.delete()
    
    if not text:
        return

    try:
        filename = f'tts_{uuid.uuid4()}.mp3'
        tts = gTTS(text=text, lang='ru', slow=False)
        tts.save(filename)
        
        voice_channel = message.author.voice.channel
        voice_client = message.guild.voice_client
        
        if voice_client is None:
            voice_client = await voice_channel.connect()
        elif voice_client.channel != voice_channel:
            await voice_client.move_to(voice_channel)
        
        audio_source = discord.FFmpegPCMAudio(filename)
        
        def cleanup(error):
            if os.path.exists(filename):
                os.remove(filename)
            if voice_client.is_connected():
                asyncio.create_task(voice_client.disconnect())
        
        voice_client.play(audio_source, after=cleanup)
        print(f"🔊 Озвучено: {text}")
        
    except Exception as e:
        print(f'❌ Ошибка: {e}')
        if 'filename' in locals() and os.path.exists(filename):
            os.remove(filename)

if __name__ == "__main__":
    bot.run(TOKEN)