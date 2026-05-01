import os
import io
import asyncio
from pyrogram import Client, filters
from info import ADMINS
from subprocess import getoutput as run, TimeoutExpired


@Client.on_message(filters.command(["sh", "shell"]) & filters.user(ADMINS))
async def shell(client, message):
    # Ensure the message contains a command
    if len(message.command) < 2:
        await message.reply("Please provide a shell command to execute.")
        return
    
    # Extract the code to be run
    code = message.text.split(None, 1)[1]
    message_text = await message.reply_text("`Running...`")

    try:
        # Run the shell command with a timeout (e.g., 60 seconds)
        output = await asyncio.to_thread(run, code)

        if len(output) > 4096:
            # If the output is too large, send it as a document
            with io.BytesIO(str.encode(output)) as out_file:
                out_file.name = "shell_output.txt"
                await message.reply_document(document=out_file, disable_notification=True)
                await message_text.delete()
        else:
            # Send the output as a regular message
            await message_text.edit(f"Output:\n{output}")
    except TimeoutExpired:
        # Handle command timeouts
        await message_text.edit("The command timed out. Please try again with a shorter command.")
    except Exception as e:
        # Catch any other errors (e.g., invalid command)
        await message_text.edit(f"An error occurred while running the command: {e}")
        print(f"Error executing shell command: {e}")
