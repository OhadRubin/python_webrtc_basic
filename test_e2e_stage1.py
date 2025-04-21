# test_e2e_stage1.py
import asyncio
import json
import logging
import unittest
import websockets
from io import StringIO

# Import server elements - adjust path if server.py is in a different directory
import server as server_module

# --- Test Configuration ---
SERVER_HOST = server_module.SERVER_HOST
SERVER_PORT = server_module.SERVER_PORT
SERVER_URL = f"ws://{SERVER_HOST}:{SERVER_PORT}"
TEST_TIMEOUT = 5 # Seconds

class TestE2EStage1(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        """Starts the server in a background task for each test."""
        self.log_stream = StringIO()
        self.log_handler = logging.StreamHandler(self.log_stream)
        self.log_handler.setFormatter(logging.Formatter('%(levelname)s: [Server] %(message)s'))

        # Get the server's logger and add our handler
        self.server_logger = server_module.logger
        self.original_level = self.server_logger.level
        self.server_logger.setLevel(logging.INFO) # Ensure INFO messages are captured
        self.server_logger.addHandler(self.log_handler)

        self.server_ready_queue = asyncio.Queue()
        self.server_stop_event = asyncio.Event()
        self.server_task = asyncio.create_task(
            server_module.main(ready_queue=self.server_ready_queue, stop_event=self.server_stop_event)
        )

        # Wait for the server to be ready
        try:
            await asyncio.wait_for(self.server_ready_queue.get(), timeout=TEST_TIMEOUT)
            logging.info("Test Setup: Server reported ready.")
        except asyncio.TimeoutError:
            self.fail("Server did not start within timeout")
        # Add a tiny delay to ensure the port is fully bound before clients try connecting
        await asyncio.sleep(0.1)


    async def asyncTearDown(self):
        """Stops the server task and cleans up resources."""
        logging.info("Test Teardown: Stopping server...")
        self.server_stop_event.set() # Signal server main loop to exit
        try:
            # Wait for the server task to finish
            await asyncio.wait_for(self.server_task, timeout=TEST_TIMEOUT)
            logging.info("Test Teardown: Server task finished.")
        except asyncio.TimeoutError:
            logging.warning("Test Teardown: Server task did not finish within timeout. Cancelling.")
            self.server_task.cancel()
            try:
                await self.server_task # Allow cancellation to propagate
            except asyncio.CancelledError:
                pass # Expected
        except Exception as e:
            logging.error(f"Test Teardown: Error waiting for server task: {e}")

        # Remove the log handler and restore original level
        self.server_logger.removeHandler(self.log_handler)
        self.server_logger.setLevel(self.original_level)
        self.log_handler.close()
        logging.info("Test Teardown: Complete.")
        # Short sleep to allow port release if running tests rapidly
        await asyncio.sleep(0.1)

    async def _connect_client_and_get_id(self, client_name="Client"):
        """Helper coroutine to connect a client and validate the 'your_id' message."""
        try:
            ws = await asyncio.wait_for(
                websockets.connect(SERVER_URL),
                timeout=TEST_TIMEOUT
            )
            self.assertIsNotNone(ws, f"{client_name} failed to connect")

            message_raw = await asyncio.wait_for(ws.recv(), timeout=TEST_TIMEOUT)
            self.assertIsInstance(message_raw, str, f"{client_name} did not receive string message")

            message_data = json.loads(message_raw)
            self.assertEqual(message_data.get("type"), "your_id", f"{client_name} did not receive 'your_id' message type")
            client_id = message_data.get("id")
            self.assertIsInstance(client_id, str, f"{client_name} 'your_id' message missing 'id' string")
            self.assertTrue(len(client_id) > 10, f"{client_name} ID seems too short: {client_id}") # Basic UUID check

            logging.info(f"Test: {client_name} connected with ID: {client_id}")
            return ws, client_id

        except asyncio.TimeoutError:
            self.fail(f"{client_name} connection or receive timed out")
        except Exception as e:
            self.fail(f"{client_name} connection/receive failed: {e}")


    async def test_client_connection_id_and_disconnect(self):
        """Tests client connection, unique ID assignment, and disconnect logging."""
        # Connect Client 1
        ws1, client1_id = await self._connect_client_and_get_id("Client 1")

        # Connect Client 2
        ws2, client2_id = await self._connect_client_and_get_id("Client 2")

        # Assert IDs are unique
        self.assertNotEqual(client1_id, client2_id, "Client IDs are not unique")

        # Allow logs to propagate
        await asyncio.sleep(0.1)

        # Check server logs for connections
        log_content = self.log_stream.getvalue()
        self.assertIn(f"INFO: [Server] Client {client1_id} connected", log_content)
        self.assertIn(f"INFO: [Server] Client {client2_id} connected", log_content)
        logging.info("Test: Verified connection logs.")

        # Disconnect Client 1
        logging.info("Test: Disconnecting Client 1...")
        await ws1.close()
        await asyncio.sleep(0.1) # Allow server to process disconnect

        # Check server logs for disconnect 1
        log_content = self.log_stream.getvalue() # Get updated logs
        self.assertIn(f"INFO: [Server] Client {client1_id} disconnected", log_content)
        self.assertIn("Remaining clients: 1", log_content)
        logging.info("Test: Verified Client 1 disconnect log.")

        # Disconnect Client 2
        logging.info("Test: Disconnecting Client 2...")
        await ws2.close()
        await asyncio.sleep(0.1) # Allow server to process disconnect

        # Check server logs for disconnect 2
        log_content = self.log_stream.getvalue() # Get updated logs
        self.assertIn(f"INFO: [Server] Client {client2_id} disconnected", log_content)
        self.assertIn("Remaining clients: 0", log_content)
        logging.info("Test: Verified Client 2 disconnect log.")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
    unittest.main()