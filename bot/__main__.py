from loguru import logger
import uvicorn
from dotenv import load_dotenv
load_dotenv()

try:
    uvicorn.run("bot.dashboard.dashboard:app", host="0.0.0.0", port=5000, log_level="info")
except KeyboardInterrupt as e:
    logger.info(f"Exiting app...")
    exit(0)

except BaseException as e:
    logger.critical(f"Error {e} happened when stating the bot ")
    raise


