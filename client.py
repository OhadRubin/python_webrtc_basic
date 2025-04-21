import asyncio
import json
import logging
import websockets
import sys # Add sys import
import argparse # Add argparse import
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer

# --- Configuration ---
SERVER_URL = f"ws://localhost:8765" # Use the server host/port defined there
STUN_SERVER = "stun:stun.l.google.com:19302"
RTC_CONFIG = RTCConfiguration(
    iceServers=[RTCIceServer(urls=[STUN_SERVER])]
)

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: [Client] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    stream=sys.stdout # Explicitly log to stdout for pexpect
)
logger = logging.getLogger(__name__)

# --- Client State ---
websocket: websockets.WebSocketClientProtocol | None = None
my_id: str | None = None
peer_id: str | None = None
is_initiator: bool = False
listen_mode: bool = False
pc: RTCPeerConnection | None = None
# data_channel will be added in Stage 4

# --- Argument Parsing ---
def parse_arguments():
    parser = argparse.ArgumentParser(description="WebSocket client with peer-to-peer functionality")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--listen", action="store_true", help="Listen mode: print UUID and wait for connection")
    group.add_argument("--connect-to", type=str, help="Peer's UUID to connect to")
    return parser.parse_args()

# --- WebRTC Functions ---
def create_peer_connection():
    """Creates or resets the RTCPeerConnection object."""
    global pc
    if pc and pc.connectionState != "closed":
        logger.warning("Closing existing PeerConnection before creating a new one.")
        # Closing might need to be async if done elsewhere, but here it's prep
        # If this causes issues, we might need to manage closure more carefully async
        asyncio.create_task(pc.close()) # Fire and forget close, handle errors if needed

    logger.info("Creating new RTCPeerConnection")

    pc = RTCPeerConnection(configuration=RTC_CONFIG)

    @pc.on("iceconnectionstatechange")
    async def on_iceconnectionstatechange():
        if pc: logger.info(f"ICE Connection State: {pc.iceConnectionState}")

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        if pc: logger.info(f"Peer Connection State: {pc.connectionState}")

    # @pc.on("icecandidate") will be added in Stage 4
    # @pc.on("datachannel") will be added in Stage 4

async def start_webrtc(initiator_flag: bool):
    """Starts the WebRTC handshake process."""
    global pc
    if not pc:
        logger.error("RTCPeerConnection not initialized. Cannot start WebRTC.")
        return

    if initiator_flag:
        logger.info("Starting WebRTC as initiator.")
        # --- Data Channel Creation (Required for Offer) ---
        # We create it here to make createOffer work, full handling in Stage 4
        if not pc: # Add extra safety check
             logger.error("PeerConnection not available for data channel creation.")
             return
        logger.info("Creating data channel 'chat' (needed for offer generation)...")
        # Assign to a local var for now, global assignment/handlers in Stage 4
        _channel = pc.createDataChannel("chat")
        logger.info(f"Data channel '{_channel.label}' created locally.")
        # setup_datachannel_handlers will be called in Stage 4
        # ---------------------------------------------------

        logger.info("Creating offer...")
        try:
            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)
            logger.info("Offer created and set as local description.")
            await send_ws_message({
                "type": "offer",
                "sdp": pc.localDescription.sdp
            })
            logger.info("Sent offer to signaling server.")
        except Exception as e:
            logger.error(f"Error creating/sending offer: {e}", exc_info=True)
    else:
        logger.info("Starting WebRTC as receiver. Waiting for offer...")

# --- Core Logic ---
async def handle_server_message(message):
    """Handles messages received from the signaling server."""
    global my_id, peer_id, is_initiator, pc
    try:
        data = json.loads(message)
        msg_type = data.get("type")
        from_peer = data.get("from_peer", False) # Check if relayed by server

        # Log differently based on origin
        log_prefix = "[From Peer] " if from_peer else "[From Server] "
        logger.debug(f"{log_prefix} Received message: {data}")

        if msg_type == "your_id":
            my_id = data.get("id")
            if my_id:
                logger.info(f"*** Your Client ID: {my_id} ***")
                if listen_mode:
                    logger.info("*** Waiting for connection... ***")
                sys.stdout.flush()  # Explicitly flush stdout
            else:
                logger.error("Received 'your_id' message but ID was missing.")
        elif msg_type == "paired":
            p_id = data.get("peer_id")
            initiator = data.get("initiator", False)
            if p_id:
                peer_id = p_id
                is_initiator = initiator
                role = "initiator" if is_initiator else "receiver"
                logger.info(f"*** Paired with {peer_id}! You are the {role}. ***")
                sys.stdout.flush()  # Explicitly flush stdout
                # --- Start WebRTC ---
                create_peer_connection()
                await start_webrtc(is_initiator)
            else:
                logger.error("Received 'paired' message but peer_id was missing.")
        elif msg_type == "message":
            # Handle message from peer
            sender_id = data.get("from")
            content = data.get("content")
            if sender_id and content:
                logger.info(f"*** Message from {sender_id}: {content} ***")
                sys.stdout.flush()  # Explicitly flush stdout
            else:
                logger.error("Received 'message' with missing fields.")
        elif msg_type == "peer_disconnected":
            disconnected_peer = data.get("peer_id")
            if disconnected_peer and disconnected_peer == peer_id:
                logger.info(f"*** Peer {peer_id} has disconnected. ***")
                # Reset pairing state
                peer_id = None
                is_initiator = False
                sys.stdout.flush()  # Explicitly flush stdout
            else:
                logger.warning(f"Received peer_disconnected for unknown peer: {disconnected_peer}")
        elif msg_type == "error":
            error_msg = data.get("message", "Unknown error")
            logger.error(f"*** Server Error: {error_msg} ***")
            sys.stdout.flush()  # Explicitly flush stdout
        # --- WebRTC Signaling Handlers ---
        elif msg_type == "offer" and from_peer:
            if not pc:
                logger.error("Received offer but PeerConnection is not ready.")
                return
            if is_initiator:
                 logger.warning("Received offer but I am the initiator. Ignoring.")
                 return # Initiator should not receive offers in this basic setup

            offer_sdp = data.get("sdp")
            if not offer_sdp:
                logger.error("Received offer message missing 'sdp'.")
                return

            logger.info("Received offer from peer. Processing...")
            offer_desc = RTCSessionDescription(sdp=offer_sdp, type="offer")
            try:
                await pc.setRemoteDescription(offer_desc)
                logger.info("Set remote description (offer). Creating answer...")
                answer = await pc.createAnswer()
                await pc.setLocalDescription(answer)
                logger.info("Answer created and set as local description.")
                await send_ws_message({
                    "type": "answer",
                    "sdp": pc.localDescription.sdp
                })
                logger.info("Sent answer to signaling server.")
            except Exception as e:
                logger.error(f"Error processing offer/creating answer: {e}", exc_info=True)

        elif msg_type == "answer" and from_peer:
            if not pc:
                logger.error("Received answer but PeerConnection is not ready.")
                return
            if not is_initiator:
                logger.warning("Received answer but I am not the initiator. Ignoring.")
                return # Receiver should not receive answers

            answer_sdp = data.get("sdp")
            if not answer_sdp:
                logger.error("Received answer message missing 'sdp'.")
                return

            logger.info("Received answer from peer. Setting remote description...")
            answer_desc = RTCSessionDescription(sdp=answer_sdp, type="answer")
            try:
                await pc.setRemoteDescription(answer_desc)
                logger.info("Set remote description (answer). SDP exchange complete.")
                # ICE candidate exchange will start automatically via @pc.on('icecandidate') in Stage 4
            except Exception as e:
                logger.error(f"Error setting remote description (answer): {e}", exc_info=True)

        elif msg_type == "candidate" and from_peer:
            # Handle candidates in Stage 4
            logger.debug("Received ICE candidate (handling deferred to Stage 4).")
            pass

        else:
            # Check if it's a known type but not from peer when expected
            if msg_type in ["offer", "answer", "candidate"] and not from_peer:
                logger.warning(f"Received signaling message '{msg_type}' directly from server? Discarding.")
            else:
                logger.warning(f"Received unhandled message type: {msg_type} | Data: {data}")

    except json.JSONDecodeError:
        logger.error(f"Failed to decode JSON message from server: {message[:200]}")
    except Exception as e:
        logger.error(f"Error handling server message: {e}", exc_info=True)

async def send_ws_message(payload):
    """Sends a JSON message to the WebSocket server."""
    global websocket
    if websocket:
        try:
            await websocket.send(json.dumps(payload))
            logger.debug(f"Sent message: {payload}")
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket closed, cannot send message.")
        except Exception as e:
            logger.error(f"Error sending message: {e}", exc_info=True)
    else:
        logger.warning("WebSocket not connected, cannot send message.")

async def connect_to_peer(target_id):
    """Send pair request to connect to the specified peer ID."""
    logger.info(f"Connecting to peer: {target_id}")
    await send_ws_message({"type": "pair_request", "target_id": target_id})

async def user_input_handler():
    """Handles user input for pairing or sending messages (currently server-relayed)."""
    global peer_id, listen_mode
    loop = asyncio.get_running_loop()
    
    # In listen mode, we just wait for incoming connections
    if listen_mode:
        while peer_id is None:
            await asyncio.sleep(1)
    
    while True:
        if peer_id is None:
            # Unpaired state - prompt for target ID
            print("> ", end="", flush=True)
            cmd = await loop.run_in_executor(None, sys.stdin.readline)
            target_id = cmd.strip()
            
            if target_id:
                logger.debug(f"Sending pair request to: {target_id}")
                await send_ws_message({"type": "pair_request", "target_id": target_id})
        else:
            # Paired. Check if WebRTC data channel is ready (Stage 4/5)
            # For now, continue sending via server relay if paired.
            # In Stage 5, this logic changes to use data_channel.send()
            print("[server relay msg]> ", end="", flush=True)
            cmd = await loop.run_in_executor(None, sys.stdin.readline)
            message = cmd.strip()
            
            if message:
                logger.info(f"Sending message via server relay: {message}")
                # Send message with proper message type instead of pair_request
                await send_ws_message({
                    "type": "message", 
                    "to": peer_id, 
                    "content": message
                })
            
            # Sleep to prevent CPU spinning - longer sleep since we're just waiting
            await asyncio.sleep(0.5)

async def listener_loop():
    """Listens for messages from the server."""
    global websocket
    try:
        async for message in websocket:
            await handle_server_message(message)
    except Exception as e:
        logger.error(f"Error in listener loop: {e}", exc_info=True)

# --- Main Execution ---
async def main():
    """Connects to the server and listens for messages."""
    global websocket, listen_mode, pc
    args = parse_arguments()
    
    # Set listen mode based on arguments
    listen_mode = args.listen
    connect_target = args.connect_to
    
    logger.info(f"Attempting to connect to server at {SERVER_URL}...")
    try:
        # The 'async with' ensures the connection is closed automatically on exit
        # Increase timeout values to prevent premature disconnections
        async with websockets.connect(
            SERVER_URL,
            close_timeout=10,
            max_size=None,
            max_queue=None,
            open_timeout=30  # Increase open timeout
        ) as ws:
            websocket = ws
            logger.info("Connected to server.")
            
            # Create task for listening to server messages
            listener_task = asyncio.create_task(listener_loop())
            
            # Automatically connect if --connect-to was specified
            if connect_target:
                # Wait a moment for the your_id message to be processed
                await asyncio.sleep(0.5)
                connect_task = asyncio.create_task(connect_to_peer(connect_target))
                input_task = asyncio.create_task(user_input_handler())
                await asyncio.gather(listener_task, connect_task, input_task)
            else:
                # Just start the regular input handler
                input_task = asyncio.create_task(user_input_handler())
                await asyncio.gather(listener_task, input_task)
            
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
        global pc
        if pc and pc.connectionState != "closed":
            logger.info("Closing RTCPeerConnection...")
            await pc.close()
            pc = None
        websocket = None
        logger.info("Client shut down.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # This allows graceful shutdown on Ctrl+C, triggering the finally block in main()
        logger.info("Client shutdown requested.")
