
**Stage 4: WebRTC ICE Candidate Exchange and Data Channel Setup**

*   **Goal:** Implement the exchange of ICE candidates via the signaling server. Establish the actual peer-to-peer connection (`RTCPeerConnection` state reaches "connected") and set up the basic data channel, verifying its "open" event fires.
*   **Essential Functionality:**
    *   Server relays ICE candidates between peers.
    *   Clients generate and send ICE candidates.
    *   Clients receive and process peer ICE candidates.
    *   The initiating client creates a data channel.
    *   The receiving client accepts the data channel.
    *   Both clients register basic event handlers (`open`, `close`, `message`) on the data channel.
    *   Verify connection state reaches "connected".
    *   Verify data channel state reaches "open".

*   **Server Implementation (`server.py`):**
    1.  **Update `relay_message`:** Modify the `relay_message` function to include `"candidate"` in the list of message types it forwards to the peer. No other server changes are essential for this stage.
        ```python
        # Example snippet within connection_handler or a message router
        if msg_type in ["offer", "answer", "candidate"]: # Add "candidate" here
            await relay_message(client_id, message_data)
        # ... other message types
        ```

*   **Client Implementation (`client.py`):**
    1.  **Initialize Global:** Add `data_channel = None` to the global variables section.
    2.  **Implement ICE Candidate Sending (`@pc.on("icecandidate")`):**
        *   Define an asynchronous function decorated with `@pc.on("icecandidate")`.
        *   Inside the handler, check `if event.candidate:`.
        *   If a candidate exists, construct the message payload. Ensure essential parts are included for the peer to reconstruct the `RTCIceCandidate`.
            ```python
            # Inside the @pc.on("icecandidate") handler:
            if event.candidate:
                logger.info(f"Local ICE candidate generated: {event.candidate.sdp[:30]}...") # Log abbreviated candidate
                payload = {
                    "type": "candidate",
                    "candidate": {
                        "candidate": event.candidate.sdp,
                        "sdpMid": event.candidate.sdpMid,
                        "sdpMLineIndex": event.candidate.sdpMLineIndex,
                    },
                }
                await send_ws_message(payload)
            ```
    3.  **Implement Data Channel Reception (`@pc.on("datachannel")`):**
        *   Define an asynchronous function decorated with `@pc.on("datachannel")`.
        *   Inside the handler, assign `event.channel` to the global `data_channel`.
        *   Log that the data channel was received.
        *   Call `setup_datachannel_handlers(data_channel)`.
            ```python
            @pc.on("datachannel")
            def on_datachannel(channel):
                global data_channel
                logger.info(f"Data channel '{channel.label}' received.")
                data_channel = channel
                setup_datachannel_handlers(data_channel)
            ```
    4.  **Implement `setup_datachannel_handlers` Function:**
        *   Define a synchronous function `setup_datachannel_handlers(channel)`. This function will register handlers on the provided channel object.
        *   Inside, define basic handlers using the `@channel.on(...)` decorator syntax for `"open"`, `"close"`, and `"message"`. These handlers should just log the event.
            ```python
            def setup_datachannel_handlers(channel):
                @channel.on("open")
                def on_open():
                    logger.info("*** Data channel opened! Ready for messages. ***")
                    # In Stage 5, we might trigger sending queued messages or enable input

                @channel.on("close")
                def on_close():
                    logger.info("*** Data channel closed. ***")
                    # In Stage 5, we might trigger cleanup or state reset

                @channel.on("message")
                def on_message(message):
                    # For Stage 4, just log receipt. Stage 5 will display it.
                    logger.info(f"Data channel message received (length: {len(message)}).")
                    # Example: logger.info(f"< Peer: {message}") # If expecting text
            ```
    5.  **Update `start_webrtc` (Initiator Creates Data Channel):**
        *   Modify the `start_webrtc` function.
        *   Inside the `if is_initiator:` block, *before* calling `pc.createOffer()`, create the data channel.
        *   Assign the created channel to the global `data_channel`.
        *   Call `setup_datachannel_handlers(data_channel)`.
            ```python
            # Inside start_webrtc function:
            async def start_webrtc(is_initiator):
                global pc, data_channel
                # ... (pc initialization if needed, though likely done globally)

                if is_initiator:
                    logger.info("Creating data channel...")
                    data_channel = pc.createDataChannel("chat") # Use a consistent label
                    logger.info(f"Data channel '{data_channel.label}' created.")
                    setup_datachannel_handlers(data_channel) # Setup handlers immediately

                    logger.info("Creating SDP offer...")
                    offer = await pc.createOffer()
                    await pc.setLocalDescription(offer)
                    logger.info("SDP offer created and set as local description.")
                    payload = {"type": "offer", "sdp": pc.localDescription.sdp}
                    await send_ws_message(payload)
                    logger.info("Sent offer to peer via signaling server.")
                else:
                    logger.info("Waiting for SDP offer from peer...")
            ```
    6.  **Update `handle_server_message` (Receive Candidates):**
        *   Add an `elif` block for `message_data["type"] == "candidate"` and `message_data.get("from_peer")`.
        *   Extract the candidate details (`candidate`, `sdpMid`, `sdpMLineIndex`) from `message_data["candidate"]`.
        *   Check that necessary fields exist.
        *   Create an `aiortc.RTCIceCandidate` object.
        *   Use `await pc.addIceCandidate(candidate_obj)`. Wrap this call in a `try...except` block to catch potential errors during candidate addition and log them.
            ```python
            # Inside handle_server_message function:
            elif msg_type == "candidate" and message_data.get("from_peer"):
                logger.info("Received ICE candidate from peer.")
                candidate_data = message_data.get("candidate")
                if candidate_data and "candidate" in candidate_data:
                    try:
                        # Reconstruct RTCIceCandidate (ensure aiortc is imported)
                        candidate = RTCIceCandidate(
                            sdp=candidate_data["candidate"],
                            sdpMid=candidate_data.get("sdpMid"),
                            sdpMLineIndex=candidate_data.get("sdpMLineIndex"),
                        )
                        logger.info(f"Adding received ICE candidate: {candidate.sdp[:30]}...")
                        await pc.addIceCandidate(candidate)
                        logger.info("Successfully added ICE candidate.")
                    except Exception as e:
                        logger.error(f"Error adding received ICE candidate: {e}", exc_info=True)
                        logger.error(f"Problematic candidate data: {candidate_data}")
                else:
                    logger.warning("Received malformed candidate message.")
            ```
    7.  **Update `@pc.on("connectionstatechange")` Logging:**
        *   Ensure the existing handler clearly logs when the state becomes `connected`.
            ```python
            @pc.on("connectionstatechange")
            async def on_connectionstatechange():
                logger.info(f"Peer connection state is {pc.connectionState}")
                if pc.connectionState == "connected":
                    logger.info("!!! PEER CONNECTION ESTABLISHED !!!")
                # Add logging for "failed", "disconnected", "closed" if desired for debug
                elif pc.connectionState in ["failed", "disconnected", "closed"]:
                     logger.warning(f"Peer connection entered state: {pc.connectionState}")
            ```

*   **Deliverable:**
    *   Server successfully relays `"candidate"` messages.
    *   Clients exchange ICE candidates and add them to their `RTCPeerConnection`.
    *   The `pc.connectionState` on both clients reaches `"connected"` and is logged.
    *   The data channel's `"open"` event fires on both clients and is logged.

*   **Test Plan:**
    1.  Run `server.py`.
    2.  Run Client A and Client B. Note their IDs.
    3.  Pair Client A with Client B.
    4.  Verify the SDP Offer/Answer exchange occurs as logged in Stage 3 tests.
    5.  **Verify Candidate Exchange:**
        *   Observe Client A logging "Local ICE candidate generated..." and sending payloads with `"type": "candidate"`.
        *   Observe Server logging relaying candidate messages between A and B.
        *   Observe Client B logging "Received ICE candidate from peer." and "Adding received ICE candidate...".
        *   Repeat observation for candidates generated by Client B and received/added by Client A.
    6.  **Verify Connection State:** Observe both clients logging `Peer connection state is connected` and `!!! PEER CONNECTION ESTABLISHED !!!`.
    7.  **Verify Data Channel Opens:** Observe both clients logging "*** Data channel opened! Ready for messages. ***" (or similar message from the `@data_channel.on("open")` handler).

*   **Out-of-Scope for Stage 4 (Not Essential):**
    *   Implementing detailed logging for `iceconnectionstatechange` or `icegatheringstatechange`.
    *   Adding specific error handling logic beyond logging for `addIceCandidate` failures.
    *   Implementing visual indicators for connection status beyond log messages.
    *   Measuring connection time.
    *   Handling data channel `"close"` or `"message"` events beyond basic logging (e.g., no actual message display or state cleanup based on close).

*   **Extremely Out-of-Scope for Stage 4:**
    *   Sending/receiving actual user data over the data channel.
    *   Handling signaled peer disconnection (`"peer_disconnected"` message).
    *   Server keepalives (ping/pong).
    *   Media streams (audio/video).
    *   TURN server implementation or complex NAT traversal logic.
    *   Renegotiation, multiple data channels.
    *   UI elements.