

*   **Terminology Clarification:**
    *   **Extremely Out-of-Scope:** ICE Candidate Exchange (sending/receiving `candidate` messages), Data Channel setup (`createDataChannel`, `@pc.on("datachannel")`, sending data P2P), actual P2P connection reaching "connected" state, robust error handling for SDP/aiortc operations, TURN server usage, multi-track/channel support, renegotiation, server ping/pong keepalives, WebRTC-specific peer disconnection handling (beyond base WebSocket disconnect).
    *   **Out-of-Scope (Not essential for Stage 3):** Implementing `@pc.on("icecandidate")` even without sending, implementing data channel event handlers (`@data_channel.on(...)`), adding detailed logging beyond state changes/basic info, handling signaling race conditions, configuration files for STUN/TURN, timeouts for offer/answer waits, graceful cleanup of `pc` during mid-exchange WebSocket drops.

---

**Stage 3 Implementation Plan:**

**1. Server Implementation (`server.py`)**

*   **1.1. Implement `relay_message` Function:**
    *   Create a new asynchronous function: `async def relay_message(sender_id: str, message: dict):`
    *   **Lookup Peer:** Inside the function, use `sender_id` to find the corresponding `peer_id` from the global `pairings` dictionary.
        *   If `sender_id` is not in `pairings` or `pairings[sender_id]` is `None`, log a warning (e.g., `f"Client {sender_id} attempted to relay message but has no peer."`) and return.
        *   Store the found `peer_id`.
    *   **Lookup Peer Websocket:** Use the `peer_id` to find the peer's information and websocket object in the global `clients` dictionary (e.g., `peer_info = clients.get(peer_id)`).
        *   If `peer_info` is `None` or the websocket is invalid/closed, log a warning (e.g., `f"Cannot relay message to peer {peer_id}: Client not found or disconnected."`) and return.
        *   Get the `peer_websocket = peer_info["websocket"]`.
    *   **Add Relay Marker:** Modify the `message` dictionary by adding a key to indicate it's being relayed: `message["from_peer"] = True`. This allows the receiving client to distinguish server messages from relayed peer messages.
    *   **Send to Peer:** Use the existing `send_json(peer_websocket, message)` function to forward the modified message to the peer.
    *   **Logging:** Add logging to indicate the relay action (e.g., `logging.info(f"Relaying '{message.get('type')}' message from {sender_id} to {peer_id}")`).
    *   **Error Handling:** Wrap the `send_json` call in a `try...except websockets.exceptions.ConnectionClosed:` block to handle cases where the peer disconnects just before sending; log a warning if this occurs.
*   **1.2. Update `connection_handler`:**
    *   Locate the message processing loop (`async for raw_message in websocket:`).
    *   After parsing the JSON into `message`, add conditions to check the message `type`.
    *   Add `elif message.get("type") == "offer": await relay_message(client_id, message)`
    *   Add `elif message.get("type") == "answer": await relay_message(client_id, message)`
    *   Ensure these checks occur *before* any default handling for unknown message types.

**2. Client Implementation (`client.py`)**

*   **2.1. Add Dependencies and Imports:**
    *   Add `aiortc` to your project requirements (e.g., `requirements.txt`) and install it (`pip install aiortc`).
    *   Import necessary components at the top of `client.py`:
        ```python
        from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
        # Keep existing imports (asyncio, json, logging, websockets)
        ```
*   **2.2. Configure `RTCPeerConnection`:**
    *   Define a constant for a public STUN server URL: `STUN_SERVER = "stun:stun.l.google.com:19302"`
    *   Define the `RTCConfiguration` using the STUN server:
        ```python
        RTC_CONFIG = RTCConfiguration(
            iceServers=[RTCIceServer(urls=[STUN_SERVER])]
        )
        ```
    *   Initialize a global variable to hold the peer connection instance: `pc: RTCPeerConnection | None = None`.
*   **2.3. Implement `create_peer_connection` Function:**
    *   Define a synchronous or asynchronous function (async preferred if using async handlers): `def create_peer_connection():` (or `async def`).
    *   Use the `global pc` keyword.
    *   If `pc` is not `None`, close the existing one first: `await pc.close()` (make the function async if using await). Reset `pc = None`.
    *   Log: `logging.info("Creating new RTCPeerConnection")`
    *   Instantiate the connection: `pc = RTCPeerConnection(config=RTC_CONFIG)`
    *   **Attach Basic Log Handlers:** Define and attach handlers *immediately* after creating `pc` to observe state changes during the handshake:
        ```python
        @pc.on("iceconnectionstatechange")
        async def on_iceconnectionstatechange():
            if pc: # Check pc hasn't been closed concurrently
                logging.info(f"ICE Connection State: {pc.iceConnectionState}")

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            if pc: # Check pc hasn't been closed concurrently
                logging.info(f"Connection State: {pc.connectionState}")

        # DO NOT add @pc.on("icecandidate") or @pc.on("datachannel") yet.
        ```
*   **2.4. Implement `start_webrtc` Function:**
    *   Define `async def start_webrtc(is_initiator: bool):`.
    *   Access the global `pc`. Check if `pc` is `None`, log an error if it is, and return.
    *   **If Initiator:**
        *   Check `if is_initiator:`.
        *   Log: `logging.info("I am the initiator. Creating SDP offer...")`
        *   Create offer: `offer = await pc.createOffer()`
        *   Set local description: `await pc.setLocalDescription(offer)`
        *   Log: `logging.info("Offer created and set as local description.")`
        *   Send offer via WebSocket:
            ```python
            await send_ws_message({
                "type": "offer",
                "sdp": pc.localDescription.sdp,
                # type is implicitly 'offer' from pc.localDescription, but explicit is fine
            })
            logging.info("Sent offer to signaling server.")
            ```
    *   **If Receiver:**
        *   Check `else: # is_initiator is False`.
        *   Log: `logging.info("I am the receiver. Waiting for SDP offer...")`
        *   (No further action needed here; the offer will trigger steps in `handle_server_message`).
*   **2.5. Update `handle_server_message`:**
    *   **Modify `"paired"` Handler:**
        *   Retrieve `peer_id` and `is_initiator` from the `message`.
        *   Store `is_initiator` locally or globally if needed elsewhere (maybe just pass to `start_webrtc`).
        *   Update the confirmation print statement to indicate initiator status.
        *   Call `create_peer_connection()` (or `await create_peer_connection()` if async) to set up the `pc` instance.
        *   Call `await start_webrtc(is_initiator)`.
    *   **Add Handler for `"offer"`:**
        *   Add `elif message_type == "offer" and message.get("from_peer"):`.
        *   Check if `pc` exists; if not, log an error ("Received offer but PeerConnection not ready") and return.
        *   Log: `logging.info("Received offer from peer via signaling server.")`
        *   Extract SDP: `offer_sdp = message["sdp"]`
        *   Create `RTCSessionDescription`: `offer_desc = RTCSessionDescription(sdp=offer_sdp, type="offer")`
        *   Set remote description: `await pc.setRemoteDescription(offer_desc)`
        *   Log: `logging.info("Set remote description (offer). Creating answer...")`
        *   Create answer: `answer = await pc.createAnswer()`
        *   Set local description: `await pc.setLocalDescription(answer)`
        *   Log: `logging.info("Answer created and set as local description.")`
        *   Send answer via WebSocket:
            ```python
            await send_ws_message({
                "type": "answer",
                "sdp": pc.localDescription.sdp,
                # type is implicitly 'answer'
            })
            logging.info("Sent answer to signaling server.")
            ```
    *   **Add Handler for `"answer"`:**
        *   Add `elif message_type == "answer" and message.get("from_peer"):`.
        *   Check if `pc` exists; if not, log an error ("Received answer but PeerConnection not ready") and return.
        *   Log: `logging.info("Received answer from peer via signaling server.")`
        *   Extract SDP: `answer_sdp = message["sdp"]`
        *   Create `RTCSessionDescription`: `answer_desc = RTCSessionDescription(sdp=answer_sdp, type="answer")`
        *   Set remote description: `await pc.setRemoteDescription(answer_desc)`
        *   Log: `logging.info("Set remote description (answer). SDP Offer/Answer exchange complete.")`
*   **2.6. Client Cleanup (Minor Enhancement):**
    *   In the `finally` block of the client's `main` function, ensure potential cleanup of the peer connection happens *before* closing the WebSocket:
        ```python
        finally:
            global pc
            if pc and pc.connectionState != "closed":
                logging.info("Closing RTCPeerConnection...")
                await pc.close()
                pc = None
            # ... existing websocket closing logic ...
        ```

**3. Testing Strategy for Stage 3**

*   **Setup:** Run `server.py`. Run two instances of `client.py` (Client A and Client B). Note their IDs.
*   **Action:** In Client A's terminal, enter the ID of Client B to initiate pairing.
*   **Verification:** Observe the console logs of the server and both clients.
    *   **Server Logs:** Verify messages confirming pairing, followed by logs indicating the relay of an `"offer"` message from A to B, and then the relay of an `"answer"` message from B to A.
    *   **Client A (Initiator) Logs:**
        *   Pairing confirmation (`"...You are the initiator..."`).
        *   `Creating new RTCPeerConnection`.
        *   `Starting WebRTC as initiator...`.
        *   `Offer created...`, `Sent offer...`.
        *   State change logs (e.g., `ICE Connection State: checking`, `Connection State: connecting`).
        *   `Received answer from peer...`.
        *   `Set remote description (answer). SDP Offer/Answer exchange complete.`.
    *   **Client B (Receiver) Logs:**
        *   Pairing confirmation (`"...You are the receiver..."`).
        *   `Creating new RTCPeerConnection`.
        *   `Starting WebRTC as receiver...`.
        *   `Received offer from peer...`.
        *   `Set remote description (offer)...`, `Creating answer...`.
        *   `Answer created...`, `Sent answer...`.
        *   State change logs (e.g., `ICE Connection State: checking`, `Connection State: connecting`).
*   **Expected Outcome:** The logs should clearly show the sequence: Pair -> A Creates Offer -> A Sends Offer -> Server Relays Offer -> B Receives Offer -> B Creates Answer -> B Sends Answer -> Server Relays Answer -> A Receives Answer. Both clients should log connection state changes, but the connection will likely *not* reach `connected` in this stage (it usually stalls at `checking` or `connecting` without ICE candidates). The primary goal is verifying the SDP exchange happened successfully via the signaling channel.