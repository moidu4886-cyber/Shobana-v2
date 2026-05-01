from googletrans import Translator, LANGUAGES
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import re

@Client.on_message(filters.command(["tr"]))
async def translate(client, message):
    if message.reply_to_message:
        try:
            # Extract language code from the command, default to auto-detection if not specified
            text = message.text.strip()
            command_parts = text.split("/tr")
            
            if len(command_parts) > 1:
                lang_code = command_parts[1].strip().lower()
                if lang_code not in LANGUAGES:
                    raise ValueError(f"Invalid language code: {lang_code}")
            else:
                lang_code = 'auto'  # Use 'auto' for language detection

            tr_text = message.reply_to_message.text
            translator = Translator()

            # If language is 'auto', detect the source language
            if lang_code == 'auto':
                detected = translator.detect(tr_text)
                from_lang = detected.lang
                to_lang = 'auto'
                translated_text = translator.translate(tr_text, src=from_lang, dest=lang_code).text
            else:
                from_lang = 'auto'  # Set to auto for now since user is specifying the destination
                to_lang = lang_code
                translated_text = translator.translate(tr_text, dest=to_lang).text

            # Construct response
            from_lang_name = LANGUAGES.get(from_lang, "Unknown")
            to_lang_name = LANGUAGES.get(to_lang, "Unknown")
            reply_text = f"Translated from {from_lang_name} to {to_lang_name}:\n\n{translated_text}"

            # Print to console for logging
            print(f"Translated from {from_lang_name} to {to_lang_name}: {translated_text}")

            # Reply with the translated text
            await message.reply_text(reply_text)

        except Exception as e:
            print(f"Error: {e}")
            await message.reply_text(f"An error occurred during translation: {e}")

    else:
        await message.reply_text("You can use this command by replying to a message.")
