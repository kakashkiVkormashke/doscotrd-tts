import asyncio
import logging
import os
import shutil
import tempfile
import uuid
from pathlib import Path

import discord
from dotenv import load_dotenv
from gtts import gTTS

load_dotenv()

TOKEN = os.getenv('DISCORD_TOKEN', '').strip()
TTS_CHANNEL_ID = int(os.getenv('TTS_CHANNEL_ID', '1428896474611187734'))
MAX_TEXT_LENGTH = int(os.getenv('MAX_TEXT_LENGTH', '450'))
DEFAULT_VOICE_MODE = os.getenv('VOICE_MODE', 'normal').strip().lower()

VOICE_FILTERS = {
    'normal': '-vn',
    'thin': '-vn -af "asetrate=44100*0.82,aresample=44100,atempo=1.08,afftfilt=real=re*0.75:imag=im*1.8,aecho=0.8:0.9:35:0.25,aecho=0.6:0.6:80:0.18"',
    'decepticon': '-vn -af "asetrate=44100*1.28,aresample=44100,atempo=0.75,afftfilt=real=re*1.35:imag=im*0.55,aecho=0.9:0.9:95:0.35,aecho=0.7:0.6:170:0.22"',
}

VOICE_LABELS = {
    'normal': 'обычный',
    'thin': 'тонкий',
    'decepticon': 'десептикон',
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
log = logging.getLogger('tts')


class TTSBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.voice_states = True
        intents.message_content = True
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.queue = asyncio.Queue(maxsize=50)
        self.worker = None
        self.voice_mode = DEFAULT_VOICE_MODE if DEFAULT_VOICE_MODE in VOICE_FILTERS else 'normal'

    async def setup_hook(self):
        self.worker = asyncio.create_task(self.player())

    async def on_ready(self):
        log.info('Connected as %s; TTS channel=%s; voice_mode=%s', self.user, TTS_CHANNEL_ID, self.voice_mode)

    async def safe_delete(self, message):
        try:
            await message.delete()
        except discord.Forbidden:
            log.warning('Missing Manage Messages permission in channel %s', message.channel.id)
        except discord.HTTPException:
            log.warning('Could not delete message %s', message.id)

    async def say(self, channel, text):
        try:
            await channel.send(text[:1900])
        except discord.HTTPException:
            log.warning('Could not send status message')

    def parse_control(self, text):
        normalized = ' '.join(text.lower().replace('ё', 'е').split()).rstrip('!.?')
        if normalized in {'десептикон', 'голос десептикона', 'режим десептикон', 'робот', 'робо голос'}:
            return 'decepticon'
        if normalized in {'тонкий голос', 'тонкий', 'высокий голос', 'режим тонкий'}:
            return 'thin'
        if normalized in {'обычный голос', 'нормальный голос', 'обычный', 'режим обычный'}:
            return 'normal'
        if normalized in {'голос', 'какой голос', 'режим голоса'}:
            return 'status'
        return None

    async def on_message(self, message):
        if message.author.bot or not message.guild or message.channel.id != TTS_CHANNEL_ID:
            return

        text = ' '.join(message.content.split())
        await self.safe_delete(message)

        if not text:
            return

        control = self.parse_control(text)
        if control in {'decepticon', 'thin', 'normal'}:
            self.voice_mode = control
            await self.say(message.channel, f'Голос включён: {VOICE_LABELS[control]}.')
            return
        if control == 'status':
            await self.say(message.channel, f'Сейчас голос: {VOICE_LABELS[self.voice_mode]}.')
            return

        if not getattr(message.author, 'voice', None) or not message.author.voice.channel:
            await self.say(message.channel, 'Зайди в голосовой канал, потом напиши текст для озвучки.')
            return
        if len(text) > MAX_TEXT_LENGTH:
            await self.say(message.channel, f'Слишком длинный текст. Лимит: {MAX_TEXT_LENGTH} символов.')
            return
        if self.queue.full():
            await self.say(message.channel, 'Очередь озвучки заполнена, попробуй чуть позже.')
            return

        self.queue.put_nowait((message.channel, message.author.voice.channel, text, self.voice_mode))

    async def make_tts_file(self, text):
        path = Path(tempfile.gettempdir()) / f'discord_tts_{uuid.uuid4().hex}.mp3'

        def save():
            gTTS(text=text, lang='ru', slow=False).save(str(path))

        await asyncio.to_thread(save)
        return path

    async def get_voice_client(self, text_channel, voice_channel):
        voice_client = text_channel.guild.voice_client
        if voice_client is None or not voice_client.is_connected():
            return await voice_channel.connect(timeout=30, self_deaf=True)
        if voice_client.channel != voice_channel:
            await voice_client.move_to(voice_channel)
        return voice_client

    async def play_file(self, voice_client, path, voice_mode):
        loop = asyncio.get_running_loop()
        done = loop.create_future()

        def finish(error):
            loop.call_soon_threadsafe(done.set_result, error)

        source = discord.FFmpegPCMAudio(str(path), options=VOICE_FILTERS.get(voice_mode, VOICE_FILTERS['normal']))
        voice_client.play(source, after=finish)
        error = await done
        source.cleanup()
        if error:
            raise error

    async def player(self):
        while True:
            text_channel, voice_channel, text, voice_mode = await self.queue.get()
            path = None
            try:
                path = await self.make_tts_file(text)
                voice_client = await self.get_voice_client(text_channel, voice_channel)
                await self.play_file(voice_client, path, voice_mode)
                log.info('Spoken text from #%s with %s voice: %s', text_channel.id, voice_mode, text)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                log.warning('TTS failed: %s', error)
                await self.say(text_channel, 'Не получилось озвучить сообщение. Проверь логи, FFmpeg и доступ к gTTS.')
            finally:
                if path and path.exists():
                    try:
                        path.unlink()
                    except OSError:
                        log.warning('Could not remove temp file %s', path)
                self.queue.task_done()

    async def close(self):
        if self.worker:
            self.worker.cancel()
        for voice_client in self.voice_clients:
            await voice_client.disconnect(force=True)
        if self.worker:
            await asyncio.gather(self.worker, return_exceptions=True)
        await super().close()


if __name__ == '__main__':
    if not TOKEN:
        raise SystemExit('Set DISCORD_TOKEN in environment or .env')
    if not shutil.which('ffmpeg'):
        raise SystemExit('Install ffmpeg and add it to PATH')
    TTSBot().run(TOKEN)
