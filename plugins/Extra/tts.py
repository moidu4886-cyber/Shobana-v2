import traceback
from asyncio import get_running_loop
from io import BytesIO
from googletrans import Translator, LANGUAGES
from gtts import gTTS
from pyrogram import Client, filters
from pyrogram.types import Message


async def convert(text):
    try:
        # Detect language using Google Translate API
        translator = Translator()
        detected_lang = translator.detect(text).lang
        lang_name = LANGUAGES.get(detected_lang, "Unknown")
        
        # Generate the TTS (Text-to-Speech) audio
        tts = gTTS(text, lang=detected_lang)
        
        # Use BytesIO to store the audio in memory
        audio = BytesIO()
        tts.write_to_fp(audio)
        audio.seek(0)  # Rewind the BytesIO object to the start
        
        audio.name = f"{lang_name}.mp3"
        return audio, lang_name
    except Exception as e:
        print(f"Error during TTS conversion: {e}")
        return None, str(e)


@Client.on_message(filters.command("tts"))
async def text_to_speech(_, message: Message):
    if not message.reply_to_message:
        return await message.reply_text("Please reply to a message containing text.")
    
    if not message.reply_to_message.text:
        return await message.reply_text("The replied message does not contain any text.")
    
    text = message.reply_to_message.text
    m = await message.reply_text("Processing...")

    try:
        # Asynchronously handle the TTS conversion
        loop = get_running_loop()
        audio, lang_name = await loop.run_in_executor(None, convert, text)

        if audio:
            await message.reply_audio(audio, caption=f"Audio in {lang_name} language.")
            await m.delete()
            audio.close()  # Ensure resource cleanup
        else:
            await m.edit(f"Error: {lang_name}")  # lang_name contains the error message
    except Exception as e:
        await m.edit("An error occurred.")
        print(f"Error: {e}")
        e_traceback = traceback.format_exc()
        print(e_traceback)
