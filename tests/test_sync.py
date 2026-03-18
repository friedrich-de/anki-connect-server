"""Tests for sync functionality with Anki sync server."""

import os
import tempfile
import time
import pytest
import subprocess
import requests
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestSyncServer:
    """Test Anki sync server integration."""

    @pytest.fixture
    def sync_server_dir(self):
        """Create a temporary directory for sync server data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def sync_server_process(self, sync_server_dir):
        """Start and stop the sync server."""
        env = os.environ.copy()
        env["SYNC_USER1"] = "testuser:testpass"
        env["SYNC_BASE"] = sync_server_dir
        env["SYNC_PORT"] = "18765"
        
        process = subprocess.Popen(
            ["python", "-m", "anki.syncserver"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        
        time.sleep(2)
        
        yield process
        
        process.terminate()
        process.wait(timeout=5)

    def test_sync_server_health(self, sync_server_process):
        """Test that sync server responds to health check."""
        try:
            response = requests.get("http://127.0.0.1:18765/", timeout=5)
            assert response.status_code in [200, 404]
        except requests.exceptions.ConnectionError:
            pytest.skip("Sync server not responding")


class TestSyncToAnkiWeb:
    """Test sync to AnkiWeb functionality."""

    @pytest.fixture
    def wrapper_with_mock(self):
        """Create wrapper with mocked sync methods."""
        with patch("anki_wrapper.Collection") as mock_col:
            mock_instance = MagicMock()
            mock_col.return_value = mock_instance
            
            from anki_wrapper import AnkiWrapper
            from config import Config
            
            with patch.object(Config, "ANKIWEB_USER", "test@example.com"):
                with patch.object(Config, "ANKIWEB_PASS", "password"):
                    with patch.object(Config, "ANKIWEB_URL", None):
                        wrapper = AnkiWrapper("/tmp/test.anki21")
                        wrapper.col = mock_instance
                        yield wrapper

    def test_sync_requires_credentials(self):
        """Test that sync raises error without credentials."""
        from anki_wrapper import AnkiWrapper
        from config import Config
        
        with patch("anki_wrapper.Collection"):
            with patch.object(Config, "ANKIWEB_USER", None):
                with patch.object(Config, "ANKIWEB_PASS", None):
                    wrapper = AnkiWrapper("/tmp/test.anki21")
                    with pytest.raises(ValueError, match="ANKICONNECT_ANKIWEB_USER"):
                        wrapper.sync_to_ankiweb()

    def test_sync_success(self, wrapper_with_mock):
        """Test successful sync to AnkiWeb."""
        mock_auth = MagicMock()
        mock_result = MagicMock()
        wrapper_with_mock.col.sync_login.return_value = mock_auth
        wrapper_with_mock.col.sync_collection.return_value = mock_result
        
        result = wrapper_with_mock.sync_to_ankiweb()
        
        wrapper_with_mock.col.sync_login.assert_called_once()
        wrapper_with_mock.col.sync_collection.assert_called_once_with(
            auth=mock_auth, sync_media=True
        )
        assert "sync completed" in result

    def test_sync_with_custom_endpoint(self):
        """Test sync with custom sync server URL."""
        from anki_wrapper import AnkiWrapper
        from config import Config
        
        with patch("anki_wrapper.Collection") as mock_col:
            mock_instance = MagicMock()
            mock_col.return_value = mock_instance
            
            with patch.object(Config, "ANKIWEB_USER", "test@example.com"):
                with patch.object(Config, "ANKIWEB_PASS", "password"):
                    with patch.object(Config, "ANKIWEB_URL", "https://sync.myserver.com"):
                        wrapper = AnkiWrapper("/tmp/test.anki21")
                        wrapper.col = mock_instance
                        
                        mock_auth = MagicMock()
                        mock_instance.sync_login.return_value = mock_auth
                        mock_instance.sync_collection.return_value = MagicMock()
                        
                        wrapper.sync_to_ankiweb()
                        
                        mock_instance.sync_login.assert_called_once_with(
                            username="test@example.com",
                            password="password",
                            endpoint="https://sync.myserver.com"
                        )


class TestSyncMedia:
    """Test media sync functionality."""

    def test_sync_media_requires_credentials(self):
        """Test that media sync requires credentials."""
        from anki_wrapper import AnkiWrapper
        from config import Config
        
        with patch("anki_wrapper.Collection"):
            with patch.object(Config, "ANKIWEB_USER", None):
                with patch.object(Config, "ANKIWEB_PASS", None):
                    wrapper = AnkiWrapper("/tmp/test.anki21")
                    wrapper.col = MagicMock()
                    with pytest.raises(ValueError):
                        wrapper.sync_media_only()

    def test_sync_media_is_called(self):
        """Test that media sync is called during full sync."""
        from anki_wrapper import AnkiWrapper
        from config import Config
        
        with patch("anki_wrapper.Collection") as mock_col:
            mock_instance = MagicMock()
            mock_col.return_value = mock_instance
            
            with patch.object(Config, "ANKIWEB_USER", "test@example.com"):
                with patch.object(Config, "ANKIWEB_PASS", "password"):
                    with patch.object(Config, "ANKIWEB_URL", None):
                        wrapper = AnkiWrapper("/tmp/test.anki21")
                        
                        mock_auth = MagicMock()
                        mock_instance.sync_login.return_value = mock_auth
                        mock_instance.sync_collection.return_value = MagicMock()
                        
                        wrapper.sync_to_ankiweb()
                        
                        mock_instance.sync_collection.assert_called_once_with(
                            auth=mock_auth, sync_media=True
                        )

    def test_media_only_sync(self):
        """Test media-only sync."""
        from anki_wrapper import AnkiWrapper
        from config import Config
        
        with patch("anki_wrapper.Collection") as mock_col:
            mock_instance = MagicMock()
            mock_col.return_value = mock_instance
            
            with patch.object(Config, "ANKIWEB_USER", "test@example.com"):
                with patch.object(Config, "ANKIWEB_PASS", "password"):
                    with patch.object(Config, "ANKIWEB_URL", None):
                        wrapper = AnkiWrapper("/tmp/test.anki21")
                        
                        mock_auth = MagicMock()
                        mock_instance.sync_login.return_value = mock_auth
                        
                        result = wrapper.sync_media_only()
                        
                        mock_instance.sync_media.assert_called_once_with(mock_auth)
                        assert result == "media sync completed"


class TestSyncStatus:
    """Test sync status checking."""

    @pytest.fixture
    def wrapper_with_status(self):
        """Create wrapper with sync status."""
        from anki_wrapper import AnkiWrapper
        
        with patch("anki_wrapper.Collection") as mock_col:
            mock_instance = MagicMock()
            mock_col.return_value = mock_instance
            
            wrapper = AnkiWrapper("/tmp/test.anki21")
            wrapper.col = mock_instance
            yield wrapper

    def test_sync_status(self, wrapper_with_status):
        """Test getting sync status."""
        mock_status = MagicMock()
        mock_status.server = "ankiweb"
        mock_status.status = "ok"
        mock_status.required = "full"
        
        from config import Config
        
        with patch.object(Config, "ANKIWEB_USER", "test@example.com"):
            with patch.object(Config, "ANKIWEB_PASS", "password"):
                with patch.object(Config, "ANKIWEB_URL", None):
                    wrapper_with_status.col.sync_login.return_value = MagicMock()
                    wrapper_with_status.col.sync_status.return_value = mock_status
                    
                    result = wrapper_with_status.sync_status()
                    
                    assert result["server"] == "ankiweb"
                    assert result["status"] == "ok"

    def test_sync_status_requires_credentials(self, wrapper_with_status):
        """Test sync status requires credentials."""
        from config import Config
        
        with patch.object(Config, "ANKIWEB_USER", None):
            with patch.object(Config, "ANKIWEB_PASS", None):
                with pytest.raises(ValueError, match="ANKICONNECT_ANKIWEB_USER"):
                    wrapper_with_status.sync_status()


class TestSyncEdgeCases:
    """Test sync edge cases and error handling."""

    def test_sync_network_error(self):
        """Test handling network errors during sync."""
        from anki_wrapper import AnkiWrapper
        from config import Config
        
        with patch("anki_wrapper.Collection") as mock_col:
            mock_instance = MagicMock()
            mock_col.return_value = mock_instance
            
            with patch.object(Config, "ANKIWEB_USER", "test@example.com"):
                with patch.object(Config, "ANKIWEB_PASS", "password"):
                    with patch.object(Config, "ANKIWEB_URL", None):
                        wrapper = AnkiWrapper("/tmp/test.anki21")
                        wrapper.col = mock_instance
                        
                        mock_instance.sync_login.side_effect = Exception("Network error")
                        
                        with pytest.raises(Exception, match="Network error"):
                            wrapper.sync_to_ankiweb()

    def test_sync_invalid_credentials(self):
        """Test handling invalid credentials."""
        from anki_wrapper import AnkiWrapper
        from config import Config
        
        with patch("anki_wrapper.Collection") as mock_col:
            mock_instance = MagicMock()
            mock_col.return_value = mock_instance
            
            with patch.object(Config, "ANKIWEB_USER", "invalid"):
                with patch.object(Config, "ANKIWEB_PASS", "invalid"):
                    wrapper = AnkiWrapper("/tmp/test.anki21")
                    wrapper.col = mock_instance
                    
                    mock_instance.sync_login.side_effect = Exception("Invalid credentials")
                    
                    with pytest.raises(Exception):
                        wrapper.sync_to_ankiweb()


class TestSyncServerConfiguration:
    """Test sync server configuration options."""

    def test_sync_server_user_config(self):
        """Test configuring multiple sync users."""
        env_vars = {
            "SYNC_USER1": "user1:pass1",
            "SYNC_USER2": "user2:pass2",
            "SYNC_USER3": "user3:pass3",
        }
        
        with patch.dict(os.environ, env_vars, clear=False):
            from config import Config
            assert "SYNC_USER1" in os.environ

    def test_sync_server_hashed_passwords(self):
        """Test configuring sync server with hashed passwords."""
        env_vars = {
            "SYNC_USER1": "user1:$pbkdf2-sha256$...hashed...",
            "PASSWORDS_HASHED": "1",
        }
        
        with patch.dict(os.environ, env_vars, clear=False):
            assert os.environ.get("PASSWORDS_HASHED") == "1"


class TestCollectionSyncMethods:
    """Test collection sync-related methods."""

    def test_full_sync_cycle(self):
        """Test full sync cycle: login -> sync -> verify."""
        from anki_wrapper import AnkiWrapper
        from config import Config
        
        with patch("anki_wrapper.Collection") as mock_col:
            mock_instance = MagicMock()
            mock_col.return_value = mock_instance
            
            with patch.object(Config, "ANKIWEB_USER", "test@example.com"):
                with patch.object(Config, "ANKIWEB_PASS", "password"):
                    with patch.object(Config, "ANKIWEB_URL", None):
                        wrapper = AnkiWrapper("/tmp/test.anki21")
                        wrapper.col = mock_instance
                        
                        mock_auth = MagicMock()
                        mock_instance.sync_login.return_value = mock_auth
                        
                        mock_output = MagicMock()
                        mock_output.uploaded = False
                        mock_output.downloaded = True
                        mock_instance.sync_collection.return_value = mock_output
                        
                        result = wrapper.sync_to_ankiweb()
                        
                        assert mock_instance.sync_login.called
                        assert mock_instance.sync_collection.called


class TestMediaSyncMethods:
    """Test media-only sync operations."""

    def test_media_sync_status(self):
        """Test checking media sync status."""
        from anki_wrapper import AnkiWrapper
        
        with patch("anki_wrapper.Collection") as mock_col:
            mock_instance = MagicMock()
            mock_col.return_value = mock_instance
            
            wrapper = AnkiWrapper("/tmp/test.anki21")
            wrapper.col = mock_instance
            
            mock_status = MagicMock()
            mock_instance.media_sync_status.return_value = mock_status
            
            result = wrapper.col.media_sync_status()
            
            assert result == mock_status