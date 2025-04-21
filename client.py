import asyncio
import json
import logging
import websockets
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

# --- Configuration ---
SERVER_URL = f"ws://localhost:8765" # Use the server host/port defined there

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: [Client] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# --- Client State ---
websocket = None
my_id = None

# --- Core Logic ---
async def handle_server_message(message):
    """Handles messages received from the signaling server."""
    global my_id
    try:
        data = json.loads(message)
        msg_type = data.get("type")
        logger.debug(f"Received message: {data}")

        if msg_type == "your_id":
            my_id = data.get("id")
            if my_id:
                logger.info(f"*** Your Client ID: {my_id} ***")
            else:
                logger.error("Received 'your_id' message but ID was missing.")
        # In Stage 1, we only expect 'your_id'
        else:
            logger.warning(f"Received unhandled message type: {msg_type} | Data: {data}")

    except json.JSONDecodeError:
        logger.error(f"Failed to decode JSON message from server: {message[:200]}")
    except Exception as e:
        logger.error(f"Error handling server message: {e}", exc_info=True)

# --- Main Execution ---
async def main():
    """Connects to the server and listens for messages."""
    global websocket
    logger.info(f"Attempting to connect to server at {SERVER_URL}...")
    try:
        # The 'async with' ensures the connection is closed automatically on exit
        async with websockets.connect(SERVER_URL) as ws:
            websocket = ws
            logger.info("Connected to server.")

            # Listener loop
            async for message in websocket:
                await handle_server_message(message)

    except ConnectionClosedOK:
        logger.info("Server closed the connection cleanly.")
    except ConnectionClosedError as e:
        logger.warning(f"Connection closed unexpectedly: {e.code} {e.reason}")
    except ConnectionRefusedError:
        logger.error(f"Connection refused. Is the server running at {SERVER_URL}?")
    except Exception as e:
        logger.error(f"Failed to connect or error during communication: {e}", exc_info=True)
    finally:
        logger.info("Disconnecting...")
        # websocket is automatically closed by 'async with', setting to None is good practice
        websocket = None
        logger.info("Client shut down.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # This allows graceful shutdown on Ctrl+C, triggering the finally block in main()
        logger.info("Client shutdown requested.")
