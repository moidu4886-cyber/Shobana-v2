import logging
import asyncio
import re
from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery

# Ensure this import path is correct for your bot's setup
from database.ia_filterdb import Media

# You MUST define ADMINS in your bot's config (e.g., info.py)
from info import ADMINS

logger = logging.getLogger(__name__)

# Constants for Batch Deletion
BATCH_SIZE = 20  # Number of files to delete in each batch
SLEEP_TIME = 2    # Seconds to wait between batches to avoid overloading the DB/bot


@Client.on_message(filters.command("deletefiles") & filters.user(ADMINS))
async def deletemultiplefiles(bot: Client, message: Message):
    """
    Handles the /deletefiles command to prompt for confirmation before deleting
    files from the database based on a keyword in their filenames.
    This command is restricted to private chat with the bot for safety.
    """
    if message.chat.type != enums.ChatType.PRIVATE:
        return await message.reply_text(
            f"<b>Hey {message.from_user.mention}, this command won't work in groups. It only works in my PM!</b>",
            parse_mode=enums.ParseMode.HTML
        )
    
    try:
        # Extract the keyword from the command (e.g., '/deletefiles keyword')
        keyword = message.text.split(" ", 1)[1].strip()
        if not keyword:
            return await message.reply_text(
                f"<b>Hey {message.from_user.mention}, give me a keyword along with the command to delete files.</b>\n"
                "Usage: `/deletefiles <keyword>`\nExample: `/deletefiles unwanted_movie`",
                parse_mode=enums.ParseMode.HTML
            )
    except IndexError: # Catches cases where no keyword is provided after /deletefiles
        return await message.reply_text(
            f"<b>Hey {message.from_user.mention}, give me a keyword along with the command to delete files.</b>\n"
            "Usage: `/deletefiles <keyword>`\nExample: `/deletefiles unwanted_movie`",
            parse_mode=enums.ParseMode.HTML
        )
    
    # Create inline keyboard for confirmation
    confirm_button = InlineKeyboardButton("Yes, Continue !", callback_data=f"confirm_delete_files#{keyword}")
    abort_button = InlineKeyboardButton("No, Abort operation !", callback_data="close_message")
    
    markup = InlineKeyboardMarkup([[confirm_button], [abort_button]])
    
    await message.reply_text(
        text=f"<b>Are you sure? Do you want to continue deleting files with the keyword: '{keyword}'?\n\n"
             "Note: This is a destructive action and cannot be undone!</b>",
        reply_markup=markup,
        parse_mode=enums.ParseMode.HTML,
        quote=True
    )

@Client.on_callback_query(filters.regex(r'^confirm_delete_files#'))
async def confirm_and_delete_files_by_keyword(bot: Client, query: CallbackQuery):
    """
    Handles the callback query from the /deletefiles confirmation message.
    Performs batch deletion of files from the Media collection.
    """
    await query.answer() # Acknowledge the callback query

    # Extract the keyword from the callback_data
    command_prefix, keyword = query.data.split("#", 1)
    
    # Build regex to match filenames containing the keyword.
    raw_pattern = r'(\b|[\.\+\-_])' + re.escape(keyword) + r'(\b|[\.\+\-_])'
    regex = re.compile(raw_pattern, flags=re.IGNORECASE)

    # Filter query targets the 'file_name' field
    filter_query = {'file_name': regex}

    await query.message.edit_text(f"🔍 Searching for files containing **'{keyword}'** in their filenames...", parse_mode=enums.ParseMode.HTML)

    # Get the initial count of matching documents
    initial_count = await Media.count_documents(filter_query)
    if initial_count == 0:
        return await query.message.edit_text(
            f"❌ No files found with **'{keyword}'** in their filenames. Deletion aborted.",
            parse_mode=enums.ParseMode.HTML
        )

    await query.message.edit_text(
        f"Found `{initial_count}` files containing **'{keyword}'** in their filenames. Starting batch deletion...",
        parse_mode=enums.ParseMode.HTML
    )

    deleted_count = 0
    # Loop to delete in batches
    while True:
        # Fetch IDs of documents to delete in the current batch.
        documents_to_delete = await Media.collection.find(filter_query, {"_id": 1}).limit(BATCH_SIZE).to_list(length=BATCH_SIZE)
        
        if not documents_to_delete:
            break # No more documents left to delete

        # Create a list of '_id' values for the current batch
        ids_to_delete = [doc["_id"] for doc in documents_to_delete]

        # Perform the batch deletion using the collected IDs
        batch_result = await Media.collection.delete_many({"_id": {"$in": ids_to_delete}})
        
        deleted_in_batch = batch_result.deleted_count
        deleted_count += deleted_in_batch
        
        await query.message.edit_text(
            f"🗑️ Deleted `{deleted_in_batch}` files in current batch. Total deleted: `{deleted_count}` / `{initial_count}`",
            parse_mode=enums.ParseMode.HTML
        )

        if deleted_count >= initial_count or deleted_in_batch == 0:
            break # Exit loop if all found files are deleted or no more were deleted in the last batch

        await asyncio.sleep(SLEEP_TIME) # Wait before the next batch

    await query.message.edit_text(
        f"✅ Finished deletion process for keyword: **'{keyword}'**. Total files deleted: `{deleted_count}` from database.",
        parse_mode=enums.ParseMode.HTML
    )

@Client.on_callback_query(filters.regex(r'^close_message$'))
async def close_message(bot: Client, query: CallbackQuery):
    """
    Handles the 'close_message' callback to simply delete the message.
    """
    await query.answer()
    await query.message.delete()
