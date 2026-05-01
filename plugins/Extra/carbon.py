import aiohttp
import logging
from io import BytesIO
from pyrogram import Client, filters

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def make_carbon(code):
    """Generate a carbon image from code using Carbonara API."""
    url = "https://carbonara.solopov.dev/api/cook"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json={"code": code}) as resp:
                if resp.status != 200:
                    logger.error(f"Failed to fetch carbon image. Status code: {resp.status}")
                    return None
                image = BytesIO(await resp.read())
                image.name = "carbon.png"
                return image
    except Exception as e:
        logger.error(f"Error while making carbon: {e}")
        return None

@Client.on_message(filters.command("carbon"))
async def _carbon(client, message):
    """Handler for the /carbon command to generate a carbon image from replied text."""
    replied = message.reply_to_message
    if not replied or not (replied.text or replied.caption):
        await message.reply_text("**Please reply to a text message to generate a carbon.**")
        return

    text_content = replied.text or replied.caption
    text = await message.reply("**Processing your request...**")

    carbon_image = await make_carbon(text_content)
    if carbon_image is None:
        await text.edit("**Failed to generate carbon. Please try again later.**")
        return

    try:
        await text.edit("**Uploading carbon image...**")
        await message.reply_photo(carbon_image, caption="Here is your carbon image!")
    except Exception as e:
        logger.error(f"Error while uploading carbon image: {e}")
        await text.edit("**Failed to upload carbon image.**")
    finally:
        carbon_image.close()
        await text.delete()

# Add additional error handling or functionality if needed
