# test_strict_e2e_stage2.py
import pexpect
import unittest
import sys
import time
import re
import logging
import os
import signal

# --- Configuration ---
SERVER_CMD = f"{sys.executable} server.py"
CLIENT_CMD = f"{sys.executable} client.py"
SERVER_READY_PATTERN = r"Server listening on ws://.*:8765"  # Regex pattern
CLIENT_ID_PATTERN = r"\*\*\* Your Client ID: ([0-9a-f-]+) \*\*\*"  # Pattern to extract client ID from output
CLIENT_CONNECTED_PATTERN = r"Connected to server\."  # Add pattern for successful connection
CLIENT_PROMPT_PATTERN = r">"  # Add pattern for the prompt
CLIENT_PAIRED_INITIATOR_PATTERN = r"\*\*\* Paired with ([0-9a-f-]+)! You are the initiator\. \*\*\*"
CLIENT_PAIRED_RECEIVER_PATTERN = r"\*\*\* Paired with ([0-9a-f-]+)! You are the receiver\. \*\*\*"
CLIENT_ERROR_PATTERN = r"\*\*\* Server Error: (.*) \*\*\*"
CLIENT_PROMPT = "> "  # Expected prompt after connection/pairing (adjust if client.py changes)
CLIENT_EXCEPTION_PATTERN = r"Traceback \(most recent call last\)"  # Generic traceback indicator

# Shorter timeout for expected immediate responses, longer for potential waits
EXPECT_TIMEOUT_SHORT = 3
EXPECT_TIMEOUT_LONG = 5  # Increasing timeout for client operations
SETUP_TIMEOUT = 5  # Increase timeout for server/client startup

# --- Logging ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s: [TestStrict] %(message)s"
)
test_logger = logging.getLogger(__name__)


class TestStrictE2EStage2(unittest.TestCase):

    server_process = None
    client_processes = {}  # Dictionary to store name: {proc: process, id: client_id}

    @classmethod
    def setUpClass(cls):
        """Starts the server once before all tests in the class."""
        test_logger.info(f"Starting server process... {SERVER_CMD=}")
        # Log server output directly to test output for debugging

        cls.server_process = pexpect.spawn(
            SERVER_CMD, encoding="utf-8", timeout=SETUP_TIMEOUT
        )  # codec_errors='replace'
        cls.server_process.logfile_read = sys.stdout  # Show server logs during test run

        try:
            cls.server_process.expect(SERVER_READY_PATTERN, timeout=SETUP_TIMEOUT)
            test_logger.info("Server process reported ready.")
            # Give it more time to fully bind
            time.sleep(3)
        except (pexpect.TIMEOUT, pexpect.EOF) as e:
            test_logger.error(f"Server failed to start within timeout: {e}")
            cls.server_process.terminate(force=True)
            raise AssertionError(f"Server failed to start: {e}") from e

    @classmethod
    def tearDownClass(cls):
        """Stops the server once after all tests."""
        if cls.server_process and cls.server_process.isalive():
            test_logger.info("Stopping server process...")
            # Send SIGTERM first for potentially cleaner shutdown
            try:
                os.kill(cls.server_process.pid, signal.SIGTERM)
                cls.server_process.wait()  # Wait for graceful exit
                test_logger.info("Server process terminated gracefully.")
            except ProcessLookupError:
                test_logger.warning("Server process already exited.")
            except Exception:  # Fallback if wait fails or other error
                if cls.server_process.isalive():
                    cls.server_process.terminate(force=True)
                    test_logger.warning("Server process terminated forcefully.")
        else:
            test_logger.info("Server process was not running or already stopped.")

    def tearDown(self):
        """Stops all client processes after each test."""
        test_logger.info("--- Tearing down test ---")
        for name, client_info in self.client_processes.items():
            proc = client_info.get("proc")
            if proc and proc.isalive():
                test_logger.info(f"Stopping client process: {name}")
                proc.terminate(
                    force=True
                )  # Clients often don't have graceful shutdown signal handling
        self.client_processes.clear()
        time.sleep(0.2)  # Allow OS to release resources
    def _start_client(self, name):
        """Helper to start a client process and extract its ID."""
        test_logger.info(f"Starting client process: {name} with command: {CLIENT_CMD}")
        proc = pexpect.spawn(CLIENT_CMD, encoding="utf-8", timeout=EXPECT_TIMEOUT_LONG)
        proc.logfile_read = sys.stdout  # Show client logs
        self.client_processes[name] = {
            "proc": proc,
            "id": None,
        }  # Store proc immediately
        test_logger.info(f"Waiting for {name} to connect to server and receive ID...")

        proc.expect("Attempting to connect to server")
        proc.expect("Connected to server")
        client_id_pattern = r"\*\*\* Your Client ID: ([0-9a-f-]+) \*\*\*"
        proc.expect(client_id_pattern)
        match = re.search(client_id_pattern, proc.after)

        if match:
            client_id = match.group(1)
        else:
            raise AssertionError(f"Client {name} did not receive ID")

        self.client_processes[name]["id"] = client_id

    def _send_command(self, proc, name, command):
        """Sends a command (like a peer ID) to a client process."""
        test_logger.info(f"Sending command '{command}' to {name}")
        # Make sure we have a prompt
        


    # --- Test Cases ---

    def test_successful_pairing(self):
        """Tests two clients connecting and successfully pairing via user simulation."""
        proc_a, id_a = self._start_client("Client A")
        proc_b, id_b = self._start_client("Client B")

        # Client A enters Client B's ID
        self._send_command(proc_a, "Client A", id_b)

        # Verify confirmations
        self._expect_paired(proc_a, "Client A", id_b, is_initiator=True)
        self._expect_paired(proc_b, "Client B", id_a, is_initiator=False)


if __name__ == "__main__":
    unittest.main()
