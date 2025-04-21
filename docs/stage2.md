
**Part 1: Essential Functionality for Stage 2**

*   **Server:**
    *   Maintain state for which clients are paired (`pairings` dictionary, potentially augmenting the `clients` dictionary).
    *   Receive a `"pair_request"` message from a client containing a `target_id`.
    *   Validate the request:
        *   Does the requesting client exist?
        *   Does the target client exist?
        *   Is the requesting client already paired?
        *   Is the target client already paired?
    *   If validation passes:
        *   Update the server state to reflect the pairing (e.g., store `peer_id` for both clients in the `clients` dictionary, add entries to `pairings`).
        *   Send a `"paired"` message to the *initiating* client, including the peer's ID and an `initiator: True` flag.
        *   Send a `"paired"` message to the *target* client, including the initiator's ID and an `initiator: False` flag.
    *   If validation fails:
        *   Send an `"error"` message back to the *requesting* client with a reason (e.g., "Target not found", "Already paired", "Target already paired").
    *   Update the `unregister` function: When a client disconnects, if it was paired, clean up its pairing information *on the server side* (remove from `pairings`, clear its `peer_id` in the `clients` dictionary). **Crucially, do not notify the remaining peer in this stage.**
    *   Update the main connection handler to parse incoming JSON and route `"pair_request"` messages appropriately. Handle basic JSON parsing errors and unknown message types gracefully (e.g., log a warning).
*   **Client:**
    *   Maintain state for whether it's paired and who the peer is (`peer_id` variable).
    *   Implement a non-blocking way to read user input from the terminal.
    *   If the client is *not* paired (`peer_id` is `None`), interpret user input as the ID of the client they wish to pair with.
    *   Send a `{"type": "pair_request", "target_id": <entered_id>}` message to the server via the WebSocket.
    *   Handle incoming server messages:
        *   `"paired"`: Store the provided `peer_id`, potentially store the `initiator` status (e.g., log it or store in a variable), and print a confirmation message to the user (e.g., "*** Paired with <peer_id>! You are the [initiator/receiver]. ***").
        *   `"error"`: Print the error message received from the server (e.g., "*** Server Error: <error_message> ***").
    *   Run the WebSocket message listener and the user input handler concurrently.

**Part 2: Out-of-Scope (Going Above and Beyond) for Stage 2**

*   Any `aiortc` / WebRTC specific code (`RTCPeerConnection`, SDP offers/answers, ICE candidates).
*   Establishing the actual P2P data channel.
*   Sending messages *between* clients (either via server relay *after* pairing, or via the data channel). User input should *only* trigger pairing requests at this stage.
*   Server notifying the *remaining* client when its peer disconnects.
*   Server-side ping/pong keepalive mechanism.
*   Client handling of `"ping"` or `"peer_disconnected"` messages from the server.
*   Client-side logic to explicitly *unpair*. Unpairing only happens implicitly when a client disconnects.
*   Robust input validation beyond basic existence (e.g., checking if input looks like a UUID).
*   Reconnection logic for dropped WebSocket connections.
*   Generating or using API keys for connection (sticking to server-assigned UUIDs for now).
*   Any UI beyond basic terminal input/output.

**Part 3: Extremely Out-of-Scope for Stage 2**

*   Implementing the actual application that *uses* the P2P connection (e.g., file sharing, video/audio streaming, game state sync).
*   Authentication, authorization, user accounts beyond the transient client IDs.
*   Database persistence.
*   Load balancing, scalability considerations.
*   Implementing STUN/TURN servers.
*   Deployment considerations (Docker, cloud hosting, etc.).
*   Advanced error handling (e.g., rate limiting).

---

**Part 4: Detailed Plan for Stage 2 (Essential Functionality Only)**

**Phase 2.1: Server-Side State and Pairing Logic**

1.  **Update Server State (`server.py`):**
    *   Initialize `pairings: Dict[str, str] = {}` globally to store `client_id -> peer_id` mappings.
    *   Modify the `clients` dictionary structure within `register` to include a `peer_id` field, initialized to `None`:
        ```python
        clients[client_id] = {
            "ws": websocket,
            "peer_id": None,
            # "last_pong": time.time() # Add this now or in Stage 5, doesn't hurt now
        }
        ```
2.  **Implement `handle_pair_request(client_id, target_id)` (`server.py`):**
    *   Get the websocket object for `client_id`: `ws_requester = clients[client_id]["ws"]`.
    *   **Validation:**
        *   Check if `target_id` exists in `clients`: If not, `await send_json(ws_requester, {"type": "error", "message": "Target client not found"})` and return.
        *   Check if `clients[client_id]["peer_id"]` is not `None`: If so, `await send_json(ws_requester, {"type": "error", "message": "You are already paired"})` and return.
        *   Check if `clients[target_id]["peer_id"]` is not `None`: If so, `await send_json(ws_requester, {"type": "error", "message": "Target client is already paired"})` and return.
    *   **Update State:**
        *   `clients[client_id]["peer_id"] = target_id`
        *   `clients[target_id]["peer_id"] = client_id`
        *   `pairings[client_id] = target_id`
        *   `pairings[target_id] = client_id`
        *   Log the successful pairing: `logging.info(f"Pairing successful: {client_id} <-> {target_id}")`
    *   **Send Confirmation:**
        *   Get target websocket: `ws_target = clients[target_id]["ws"]`
        *   Send to requester: `await send_json(ws_requester, {"type": "paired", "peer_id": target_id, "initiator": True})`
        *   Send to target: `await send_json(ws_target, {"type": "paired", "peer_id": client_id, "initiator": False})`
3.  **Update `connection_handler` (`server.py`):**
    *   Inside the `async for message in websocket:` loop:
        *   Add a `try...except json.JSONDecodeError:` block around `message_data = json.loads(message)`. Log error and `continue` if parsing fails.
        *   Get message type: `msg_type = message_data.get("type")`.
        *   If `msg_type == "pair_request"`:
            *   Extract `target_id = message_data.get("target_id")`.
            *   Check if `target_id` exists. If not, log error, maybe send error back, and `continue`.
            *   Call `await handle_pair_request(client_id, target_id)`.
        *   Else (unknown type):
            *   Log a warning: `logging.warning(f"Received unknown message type from {client_id}: {msg_type}")`
            *   *(Optional: Send an error back to the client)*
4.  **Update `unregister(client_id)` (`server.py`):**
    *   Inside the `finally` block of `connection_handler`, *before* `del clients[client_id]`:
    *   Check if `client_id` is still in `clients` (it should be unless registration failed).
    *   Get the potential peer: `peer_id = clients[client_id].get("peer_id")`.
    *   If `peer_id` is not `None`:
        *   Log the unpairing due to disconnect: `logging.info(f"Client {client_id} disconnected, removing pairing with {peer_id}")`
        *   Remove entries from `pairings`:
            *   `pairings.pop(client_id, None)`
            *   `pairings.pop(peer_id, None)`
        *   **(Crucial based on prompt): Only modify the state of the disconnecting client.** The prompt says "clear the `peer_id` in the `clients` dictionary for the disconnecting client *only*". This state is implicitly removed when we `del clients[client_id]`. We *do not* modify `clients[peer_id]` at this stage.
    *   Proceed with `del clients[client_id]` as before.

**Phase 2.2: Client-Side Pairing Request and Handling**

1.  **Update Client State (`client.py`):**
    *   Add global variable `peer_id: Optional[str] = None`.
    *   Add global variable `is_initiator: bool = False` (optional, but useful for clarity).
2.  **Implement `send_ws_message(payload)` (`client.py`):**
    *   Check if `websocket` and `websocket.open` are true.
    *   If yes: `await websocket.send(json.dumps(payload))`
    *   If no: `logging.warning("WebSocket not connected, cannot send message.")`
    *   Add basic error handling (e.g., `try...except websockets.exceptions.ConnectionClosed`).
3.  **Implement `user_input_handler()` (`client.py`):**
    *   Import `sys`.
    *   Get the current event loop: `loop = asyncio.get_event_loop()`.
    *   Start an infinite loop: `while True:`.
    *   Inside the loop, check `if peer_id is None:`:
        *   Print a prompt: `print("> Enter target client ID to pair with: ", end='', flush=True)`
        *   Read input non-blockingly: `cmd = await loop.run_in_executor(None, sys.stdin.readline)`
        *   Clean input: `target_id = cmd.strip()`.
        *   If `target_id`:
            *   `await send_ws_message({"type": "pair_request", "target_id": target_id})`
        *   *(Optional: Add a small `await asyncio.sleep(0.1)` to prevent potential tight loop issues)*
    *   Else (`peer_id` is not `None`):
        *   Print a placeholder prompt: `print(f"> Paired with {peer_id}. Waiting for data channel (Stage 4)...")`
        *   **(Important): Prevent sending messages for now.** Just wait or sleep. We could read input but discard it, or simply block here for now. A simple `await asyncio.sleep(1)` inside the `else` block would suffice for Stage 2 to prevent this part from busy-looping.
4.  **Update `handle_server_message(message)` (`client.py`):**
    *   Keep the existing `"your_id"` handler.
    *   Add `elif msg_type == "paired":`
        *   Get data: `p_id = message_data.get("peer_id")`, `initiator = message_data.get("initiator", False)`.
        *   Check if `p_id` exists.
        *   Set globals: `peer_id = p_id`, `is_initiator = initiator`.
        *   Print confirmation: `role = "initiator" if is_initiator else "receiver"`
        *   `logging.info(f"*** Paired with {peer_id}! You are the {role}. ***")`
        *   *(Clear the input prompt line if necessary using terminal control characters or just print the confirmation on a new line)*
    *   Add `elif msg_type == "error":`
        *   Get error message: `error_msg = message_data.get("message", "Unknown error")`.
        *   Log the error: `logging.error(f"*** Server Error: {error_msg} ***")`
5.  **Update `main()` (`client.py`):**
    *   After successfully connecting and assigning `websocket`:
    *   Create the listener task: `listener_task = asyncio.create_task(listener_loop())` (wrap the `async for message...` part in its own async function `listener_loop`).
    *   Create the input handler task: `input_task = asyncio.create_task(user_input_handler())`.
    *   Use `await asyncio.wait([listener_task, input_task], return_when=asyncio.FIRST_COMPLETED)` or `asyncio.gather` (gather might be simpler if you handle cancellation correctly). Ensure both tasks are cancelled properly in the `finally` block when one exits or an error occurs.

**Phase 2.3: Testing**

1.  Run `server.py`.
2.  Run `client.py` (Client A). Note its ID (e.g., `ID_A`).
3.  Run a second `client.py` (Client B). Note its ID (e.g., `ID_B`).
4.  In Client A's terminal, type `ID_B` and press Enter.
5.  **Verify:** Client A logs `*** Paired with ID_B! You are the initiator. ***`.
6.  **Verify:** Client B logs `*** Paired with ID_A! You are the receiver. ***`.
7.  **Verify:** Server logs show the `pair_request` received from A and the successful pairing event.
8.  In Client A's terminal, try entering `ID_B` again.
9.  **Verify:** Client A logs `*** Server Error: You are already paired ***`.
10. Run a third `client.py` (Client C). Note its ID (`ID_C`).
11. In Client C's terminal, try entering `ID_B`.
12. **Verify:** Client C logs `*** Server Error: Target client is already paired ***`.
13. In Client C's terminal, enter a fake ID (e.g., `nonexistent-id`).
14. **Verify:** Client C logs `*** Server Error: Target client not found ***`.
15. Stop Client B (Ctrl+C).
16. **Verify:** Server logs Client B disconnecting and removing the pairing state associated with B. **Crucially, Client A should *not* receive any notification about B disconnecting in this stage.** Client A's `peer_id` variable remains `ID_B`. (This asymmetry is per the stage requirements).
