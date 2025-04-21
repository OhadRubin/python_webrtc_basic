# test_e2e_stage2.py
import asyncio
import json
import logging
import unittest
import websockets
from websockets.exceptions import ConnectionClosedOK
from io import StringIO

# Import server elements - adjust path if server.py is in a different directory
import server as server_module

# --- Test Configuration ---
SERVER_HOST = server_module.SERVER_HOST
SERVER_PORT = server_module.SERVER_PORT
SERVER_URL = f"ws://{SERVER_HOST}:{SERVER_PORT}"
TEST_TIMEOUT = 5 # Seconds for async operations
RECEIVE_TIMEOUT = 2 # Shorter timeout for expected receives

# --- Logging Setup ---
# Configure root logger for test output
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: [Test] %(message)s')
test_logger = logging.getLogger(__name__)

class TestE2EStage2(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        """Starts the server in a background task for each test."""
        self.log_stream = StringIO()
        # Configure a specific handler for the server's logger
        self.server_log_handler = logging.StreamHandler(self.log_stream)
        self.server_log_handler.setFormatter(logging.Formatter('%(levelname)s: [Server] %(message)s'))

        self.server_logger = server_module.logger
        self.original_level = self.server_logger.level
        self.server_logger.setLevel(logging.DEBUG) # Capture more detail from server
        self.server_logger.addHandler(self.server_log_handler)

        self.server_ready_queue = asyncio.Queue()
        self.server_stop_event = asyncio.Event()
        self.server_task = asyncio.create_task(
            server_module.main(ready_queue=self.server_ready_queue, stop_event=self.server_stop_event)
        )

        try:
            await asyncio.wait_for(self.server_ready_queue.get(), timeout=TEST_TIMEOUT)
            test_logger.info("Test Setup: Server reported ready.")
        except asyncio.TimeoutError:
            # If server fails to start, stop the task if possible and fail hard
            self.server_stop_event.set()
            try:
                await asyncio.wait_for(self.server_task, timeout=1)
            except asyncio.TimeoutError:
                 self.server_task.cancel()
            except Exception:
                pass # Ignore other errors during cleanup on failure
            self.fail("Server did not start within timeout")

        await asyncio.sleep(0.1) # Ensure port is fully bound
        self.clients = {} # Store connected test clients {name: (ws, id)}

    async def asyncTearDown(self):
        """Stops the server task and cleans up resources."""
        test_logger.info("Test Teardown: Closing client connections...")
        for name, (ws, _) in self.clients.items():
            if ws:
                try:
                    await ws.close()
                    test_logger.info(f"Test Teardown: Closed connection for {name}")
                except ConnectionClosedOK:
                     test_logger.info(f"Test Teardown: Connection already closed for {name}")
                except Exception as e:
                    test_logger.warning(f"Test Teardown: Error closing connection for {name}: {e}")
        self.clients.clear()

        test_logger.info("Test Teardown: Stopping server...")
        self.server_stop_event.set()
        try:
            await asyncio.wait_for(self.server_task, timeout=TEST_TIMEOUT)
            test_logger.info("Test Teardown: Server task finished.")
        except asyncio.TimeoutError:
            test_logger.warning("Test Teardown: Server task did not finish within timeout. Cancelling.")
            self.server_task.cancel()
            try:
                await self.server_task
            except asyncio.CancelledError:
                pass # Expected
            except Exception as e:
                test_logger.error(f"Test Teardown: Error awaiting cancelled server task: {e}")
        except Exception as e:
            test_logger.error(f"Test Teardown: Error waiting for server task: {e}")

        self.server_logger.removeHandler(self.server_log_handler)
        self.server_logger.setLevel(self.original_level)
        self.server_log_handler.close()
        test_logger.info("Test Teardown: Complete.")
        await asyncio.sleep(0.1) # Allow port release


    async def _connect_client(self, name="Client"):
        """Helper coroutine to connect a client and validate the 'your_id' message."""
        try:
            ws = await asyncio.wait_for(
                websockets.connect(SERVER_URL, ping_interval=None),
                timeout=TEST_TIMEOUT
            )
            self.assertIsNotNone(ws, f"{name} failed to connect")

            message_raw = await asyncio.wait_for(ws.recv(), timeout=RECEIVE_TIMEOUT)
            message_data = json.loads(message_raw)

            self.assertEqual(message_data.get("type"), "your_id", f"{name} did not receive 'your_id' message")
            client_id = message_data.get("id")
            self.assertIsInstance(client_id, str, f"{name} 'your_id' message missing 'id' string")
            self.assertTrue(len(client_id) > 10, f"{name} ID seems too short: {client_id}")

            test_logger.info(f"Test Helper: {name} connected with ID: {client_id}")
            self.clients[name] = (ws, client_id) # Store client info
            return ws, client_id

        except asyncio.TimeoutError:
            self.fail(f"{name} connection or initial receive timed out")
        except json.JSONDecodeError:
             self.fail(f"{name} received non-JSON initial message: {message_raw}")
        except Exception as e:
            self.fail(f"{name} connection/receive failed: {e}")


    async def _receive_and_parse(self, ws, client_name):
        """Helper to receive a message, parse JSON, and handle timeouts."""
        try:
            message_raw = await asyncio.wait_for(ws.recv(), timeout=RECEIVE_TIMEOUT)
            return json.loads(message_raw)
        except asyncio.TimeoutError:
            self.fail(f"{client_name} did not receive expected message within {RECEIVE_TIMEOUT}s")
        except json.JSONDecodeError:
            self.fail(f"{client_name} received non-JSON message: {message_raw}")
        except ConnectionClosedOK:
            self.fail(f"{client_name} connection closed unexpectedly while waiting for message.")
        except Exception as e:
             self.fail(f"{client_name} error receiving message: {e}")


    async def _send_message(self, ws, payload, client_name):
        """Helper to send a JSON message."""
        try:
            await ws.send(json.dumps(payload))
            test_logger.debug(f"Test Helper: Sent from {client_name}: {payload}")
        except Exception as e:
            self.fail(f"Failed to send message from {client_name}: {e}")


    async def _expect_no_message(self, ws, client_name, duration=0.5):
        """Helper to assert that no message is received for a short duration."""
        try:
            message_raw = await asyncio.wait_for(ws.recv(), timeout=duration)
            self.fail(f"{client_name} received unexpected message: {message_raw}")
        except asyncio.TimeoutError:
            pass # Expected behavior - no message received
        except Exception as e:
             self.fail(f"{client_name} error checking for no message: {e}")


    # --- Test Cases ---

    async def test_successful_pairing(self):
        """Tests two clients connecting and successfully pairing."""
        ws_a, id_a = await self._connect_client("Client A")
        ws_b, id_b = await self._connect_client("Client B")

        # Client A requests pairing with Client B
        test_logger.info(f"Test: Client A ({id_a}) requesting pair with Client B ({id_b})")
        await self._send_message(ws_a, {"type": "pair_request", "target_id": id_b}, "Client A")

        # Verify Client A receives 'paired' confirmation as initiator
        msg_a = await self._receive_and_parse(ws_a, "Client A")
        self.assertEqual(msg_a.get("type"), "paired")
        self.assertEqual(msg_a.get("peer_id"), id_b)
        self.assertTrue(msg_a.get("initiator"))
        test_logger.info(f"Test: Client A received paired confirmation (initiator)")

        # Verify Client B receives 'paired' confirmation as receiver
        msg_b = await self._receive_and_parse(ws_b, "Client B")
        self.assertEqual(msg_b.get("type"), "paired")
        self.assertEqual(msg_b.get("peer_id"), id_a)
        self.assertFalse(msg_b.get("initiator"))
        test_logger.info(f"Test: Client B received paired confirmation (receiver)")

        # Check server logs for successful pairing
        await asyncio.sleep(0.1) # Allow logs to flush
        log_content = self.log_stream.getvalue() # Get fresh logs
        self.assertIn(f"Pairing successful: {id_a} <-> {id_b}", log_content)
        test_logger.info("Test: Verified server log for successful pairing.")


    async def test_pairing_errors(self):
        """Tests various pairing failure scenarios."""
        ws_a, id_a = await self._connect_client("Client A")
        ws_b, id_b = await self._connect_client("Client B")
        ws_c, id_c = await self._connect_client("Client C")

        # 1. Target Not Found
        test_logger.info(f"Test: Client A ({id_a}) requesting pair with non-existent ID")
        fake_id = "non-existent-client-id"
        await self._send_message(ws_a, {"type": "pair_request", "target_id": fake_id}, "Client A")
        msg_a_err1 = await self._receive_and_parse(ws_a, "Client A")
        self.assertEqual(msg_a_err1.get("type"), "error")
        self.assertIn("Target client not found", msg_a_err1.get("message", ""))
        test_logger.info("Test: Verified 'Target not found' error.")
        # Ensure others didn't get messages
        await self._expect_no_message(ws_b, "Client B")
        await self._expect_no_message(ws_c, "Client C")


        # 2. Setup for Already Paired errors: Pair A and B successfully
        test_logger.info(f"Test: Setting up - Pairing Client A ({id_a}) with Client B ({id_b})")
        await self._send_message(ws_a, {"type": "pair_request", "target_id": id_b}, "Client A")
        await self._receive_and_parse(ws_a, "Client A") # Receive A's 'paired' msg
        await self._receive_and_parse(ws_b, "Client B") # Receive B's 'paired' msg
        test_logger.info("Test: Setup complete for already-paired tests.")


        # 3. Requester Already Paired
        test_logger.info(f"Test: Client A ({id_a}) requesting pair with Client C ({id_c}) while already paired")
        await self._send_message(ws_a, {"type": "pair_request", "target_id": id_c}, "Client A")
        msg_a_err2 = await self._receive_and_parse(ws_a, "Client A")
        self.assertEqual(msg_a_err2.get("type"), "error")
        self.assertIn("You are already paired", msg_a_err2.get("message", ""))
        test_logger.info("Test: Verified 'You are already paired' error.")
        # Ensure others didn't get messages
        await self._expect_no_message(ws_b, "Client B")
        await self._expect_no_message(ws_c, "Client C")


        # 4. Target Already Paired
        test_logger.info(f"Test: Client C ({id_c}) requesting pair with Client B ({id_b}) while B is paired")
        await self._send_message(ws_c, {"type": "pair_request", "target_id": id_b}, "Client C")
        msg_c_err1 = await self._receive_and_parse(ws_c, "Client C")
        self.assertEqual(msg_c_err1.get("type"), "error")
        self.assertIn("Target client is already paired", msg_c_err1.get("message", ""))
        test_logger.info("Test: Verified 'Target client is already paired' error.")
        # Ensure others didn't get messages
        await self._expect_no_message(ws_a, "Client A")
        await self._expect_no_message(ws_b, "Client B")


    async def test_paired_client_disconnect_cleanup(self):
        """Tests server cleanup when a paired client disconnects (Stage 2 logic)."""
        ws_a, id_a = await self._connect_client("Client A")
        ws_b, id_b = await self._connect_client("Client B")

        # Pair A and B successfully first
        test_logger.info(f"Test: Setting up - Pairing Client A ({id_a}) with Client B ({id_b})")
        await self._send_message(ws_a, {"type": "pair_request", "target_id": id_b}, "Client A")
        await self._receive_and_parse(ws_a, "Client A") # Consume A's 'paired' msg
        await self._receive_and_parse(ws_b, "Client B") # Consume B's 'paired' msg
        test_logger.info("Test: Setup complete - A and B are paired.")

        # Disconnect Client A
        test_logger.info(f"Test: Disconnecting Client A ({id_a})...")
        await ws_a.close()
        await asyncio.sleep(0.2) # Allow server time to process disconnect and run unregister

        # Verify Server Logs for Disconnect and Pairing Cleanup (Server-Side only)
        log_content = self.log_stream.getvalue()
        self.assertIn(f"Client {id_a} disconnected", log_content)
        # Crucially, check the log message confirming server-side pairing removal for Stage 2
        self.assertIn(f"removing server-side pairing with {id_b}", log_content)
        test_logger.info("Test: Verified server logs for disconnect and server-side pairing cleanup.")

        # Verify Client B (the peer) did NOT receive any notification
        test_logger.info("Test: Verifying Client B received no peer disconnect notification...")
        await self._expect_no_message(ws_b, "Client B", duration=1.0) # Check for a longer duration
        test_logger.info("Test: Confirmed Client B received no message.")

        # Verify Server *still considers B paired* (Stage 2 behavior)
        # Attempt to pair B with a new client C - it should fail as B's peer_id wasn't cleared server-side
        ws_c, id_c = await self._connect_client("Client C")
        test_logger.info(f"Test: Attempting to pair Client B ({id_b}) with Client C ({id_c}) - should fail.")
        await self._send_message(ws_b, {"type": "pair_request", "target_id": id_c}, "Client B")
        msg_b_err = await self._receive_and_parse(ws_b, "Client B")
        self.assertEqual(msg_b_err.get("type"), "error")
        self.assertIn("You are already paired", msg_b_err.get("message", ""))
        test_logger.info("Test: Verified Client B still considered paired by the server.")
        await self._expect_no_message(ws_c, "Client C") # Ensure C didn't get anything


if __name__ == '__main__':
    unittest.main()