"""Unit tests for VidaaClient reconnection, rate limiting, and rejection handling."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.vidaa.client import VidaaClient


@pytest.mark.anyio
async def test_ensure_connected_rate_limiting_and_cleanup():
    """Test async_ensure_connected rate limits reconnection attempts."""
    client = VidaaClient(ip="192.168.1.100", client_id="test_client", username="u", access_token="t")
    client.connected = False

    with (
        patch.object(client, "async_connect_and_run") as mock_connect,
        patch.object(client, "async_check_and_refresh_token"),
    ):
        res1 = await client.async_ensure_connected(min_interval=5.0)
        assert res1 is True
        mock_connect.assert_awaited_once()

        # Immediate second call is rate-limited
        res2 = await client.async_ensure_connected(min_interval=5.0)
        assert res2 is False
        assert mock_connect.await_count == 1


def test_on_connect_rc5_no_refresh_token():
    """Test rc=5 connection rejection without refresh token stops loop and dispatches auth_failed without spawning thread."""
    client = VidaaClient(ip="192.168.1.100")
    mock_mqtt = MagicMock()
    mock_auth_failed = MagicMock()
    client.register_auth_failed_callback(mock_auth_failed)

    with patch.object(client._token_manager, "async_refresh_token_and_update_creds") as mock_refresh:
        client._on_connect(mock_mqtt, None, None, rc=5)
        mock_mqtt.loop_stop.assert_called_once()
        mock_refresh.assert_not_called()
        mock_auth_failed.assert_called_once()


def test_on_connect_rc5_pairing_future():
    """Test rc=5 connection rejection during active pairing sets exception on auth_future and stops loop."""
    client = VidaaClient(ip="192.168.1.100")
    mock_mqtt = MagicMock()

    loop = asyncio.new_event_loop()
    client._loop = loop
    client._auth_future = loop.create_future()

    client._on_connect(mock_mqtt, None, None, rc=5)
    mock_mqtt.loop_stop.assert_called_once()
    assert client._auth_future.done()
    assert "rejected with code 5" in str(client._auth_future.exception())
    loop.close()


@pytest.mark.anyio
async def test_rejected_connection_schedules_delayed_reconnect():
    """On rc 5 inside the backoff window a reconnect is scheduled instead of stranding the client."""
    client = VidaaClient(
        ip="192.168.1.100",
        client_id="cid",
        username="his$1",
        access_token="expired",
        refresh_token="valid_refresh",
        refresh_token_time=int(time.time()),
        refresh_token_duration=30,
    )
    client._last_refresh_attempt = time.time()  # a refresh was attempted seconds ago
    client._rejected_refresh_failures = 1

    with patch.object(client, "_schedule_rejected_retry") as mock_schedule, patch.object(client, "async_sync_clock"):
        await client._token_manager.async_handle_auth_rejection(5)
        mock_schedule.assert_called_once()
        assert mock_schedule.call_args[0][0] >= 5.0

    # After the backoff has passed a refresh task is started instead
    client._last_refresh_attempt = time.time() - 10_000
    with (
        patch.object(client._token_manager, "async_refresh_token_and_update_creds") as mock_refresh_task,
        patch.object(client, "_schedule_rejected_retry") as mock_schedule,
        patch.object(client, "async_sync_clock"),
    ):
        await client._token_manager.async_handle_auth_rejection(5)
        mock_refresh_task.assert_called_once()
        mock_schedule.assert_not_called()
    client._refreshing_token = False
    await client.async_disconnect()


def test_broker_rejection_threshold_triggers_auth_failed():
    """Consecutive broker rejections (rc: 4/5) beyond threshold trigger auth_failed callback."""
    now = int(time.time())
    client = VidaaClient(
        ip="192.168.1.100",
        refresh_token="valid_refresh",
        refresh_token_time=now - 3600,
        refresh_token_duration=30,
    )
    client._last_refresh_connect_rc = 4
    mock_auth_failed = MagicMock()
    client.register_auth_failed_callback(mock_auth_failed)

    for _ in range(client.MAX_BROKER_REJECTION_ATTEMPTS - 1):
        client._refreshing_token = False
        with patch.object(client, "check_and_refresh_token", return_value=False):
            client._refresh_token_and_update_creds()
        mock_auth_failed.assert_not_called()

    # The next rejection hits the limit and must fire auth_failed
    client._refreshing_token = False
    with patch.object(client, "check_and_refresh_token", return_value=False):
        client._refresh_token_and_update_creds()
    mock_auth_failed.assert_called_once()


def test_broker_rejection_mqtt5_reason_code_134_triggers_auth_failed():
    """MQTT v5 reason code 134 (Bad authentication data) is treated identically to rc: 4."""
    now = int(time.time())
    client = VidaaClient(
        ip="192.168.1.100",
        refresh_token="valid_refresh",
        refresh_token_time=now - 3600,
        refresh_token_duration=30,
    )
    client._last_refresh_connect_rc = 134
    mock_auth_failed = MagicMock()
    client.register_auth_failed_callback(mock_auth_failed)

    for _ in range(client.MAX_BROKER_REJECTION_ATTEMPTS):
        client._refreshing_token = False
        with patch.object(client, "check_and_refresh_token", return_value=False):
            client._refresh_token_and_update_creds()

    mock_auth_failed.assert_called_once()


def test_broker_rejection_threshold_not_reached_suppresses_auth_failed():
    """Transient rejections below the threshold do not fire auth_failed."""
    now = int(time.time())
    client = VidaaClient(
        ip="192.168.1.100",
        refresh_token="valid_refresh",
        refresh_token_time=now - 3600,
        refresh_token_duration=30,
    )
    client._last_refresh_connect_rc = 4
    mock_auth_failed = MagicMock()
    client.register_auth_failed_callback(mock_auth_failed)

    for _ in range(client.MAX_BROKER_REJECTION_ATTEMPTS - 1):
        client._refreshing_token = False
        with patch.object(client, "check_and_refresh_token", return_value=False):
            client._refresh_token_and_update_creds()

    mock_auth_failed.assert_not_called()


def test_standby_refresh_timeout_preserves_backoff_without_auth_failed():
    """Standby gettoken timeout (connect rc: 0) must NOT increment broker rejection count."""
    now = int(time.time())
    client = VidaaClient(
        ip="192.168.1.100",
        refresh_token="valid_refresh",
        refresh_token_time=now - 3600,
        refresh_token_duration=30,
    )
    client._last_refresh_connect_rc = 0
    mock_auth_failed = MagicMock()
    client.register_auth_failed_callback(mock_auth_failed)

    for _ in range(5):
        client._refreshing_token = False
        with patch.object(client, "check_and_refresh_token", return_value=False):
            client._refresh_token_and_update_creds()
        mock_auth_failed.assert_not_called()
        assert client._broker_rejection_failures == 0
        assert client._rejected_refresh_failures > 0


def test_broker_rejection_counter_resets_on_successful_refresh():
    """A successful token refresh must reset _rejected_refresh_failures back to 0."""
    now = int(time.time())
    client = VidaaClient(
        ip="192.168.1.100",
        refresh_token="valid_refresh",
        refresh_token_time=now - 3600,
        refresh_token_duration=30,
    )
    client._rejected_refresh_failures = client.MAX_BROKER_REJECTION_ATTEMPTS - 1
    client._broker_rejection_failures = client.MAX_BROKER_REJECTION_ATTEMPTS - 1

    with patch.object(client, "check_and_refresh_token", return_value=True):
        client._refresh_token_and_update_creds()

    assert client._rejected_refresh_failures == 0
    assert client._broker_rejection_failures == 0


@pytest.mark.anyio
async def test_token_watch_restarts_after_stop():
    """stop_token_watch's one-way latch must be cleared on restart."""
    client = VidaaClient(ip="192.168.1.100", client_id="cid", username="his$1", access_token="tok")
    client._start_token_watch()
    assert client._token_watch is not None
    try:
        client._stop_token_watch()
        assert client._token_watch is None
        assert client._token_watch_closed is True

        client._start_token_watch()
        assert client._token_watch is not None
        assert client._token_watch_closed is False
    finally:
        client._stop_token_watch()


def test_proactive_refresh_noop_does_not_clear_inflight_flag():
    """A no-op proactive refresh must not clobber another task's refreshing_token."""
    now = int(time.time())
    client = VidaaClient(
        ip="192.168.1.100",
        client_id="cid",
        username="his$1",
        access_token="fresh_token",
        access_token_time=now,
        access_token_duration=2,
    )
    client.PROACTIVE_REFRESH_SETTLE_SECONDS = 0
    client.state = "on"
    client._refreshing_token = True
    client._proactive_token_refresh()
    assert client._refreshing_token is True


@pytest.mark.anyio
async def test_on_connect_tracks_query_timer_and_disconnect_cancels_it():
    """The query_initial_state task must be stored and cancelled by async_disconnect()."""
    client = VidaaClient(ip="192.168.1.100", client_id="cid", username="his$1", access_token="tok")
    client.mqtt_client = MagicMock()
    with patch.object(client, "async_query_initial_state"):
        client._on_connect(client.mqtt_client, None, None, 0)

    task = client._query_timer
    assert task is not None

    with patch.object(task, "cancel", wraps=task.cancel) as mock_cancel:
        await client.async_disconnect()
        assert mock_cancel.called
    assert client._query_timer is None


@pytest.mark.anyio
async def test_connect_and_run_is_serialized_by_reconnect_lock():
    """async_connect_and_run must hold _reconnect_lock so concurrent callers cannot race."""
    client = VidaaClient(ip="192.168.1.100", client_id="cid", username="his$1", access_token="tok")
    done = asyncio.Event()

    with (
        patch.object(client, "_async_build_ssl_context", return_value=None),
        patch.object(client, "_mqtt_session_loop", return_value=None),
    ):
        await client._reconnect_lock.acquire()
        try:

            async def worker():
                await client.async_connect_and_run()
                done.set()

            task = asyncio.create_task(worker())
            await asyncio.sleep(0.05)
            assert not done.is_set()
        finally:
            client._reconnect_lock.release()

        await asyncio.wait_for(done.wait(), timeout=1.0)
        await task
    await client.async_disconnect()


@pytest.mark.anyio
async def test_refresh_tokens_unbinds_callbacks_before_teardown():
    """async_refresh_tokens must tear down previous session before refreshing."""
    now = int(time.time())
    client = VidaaClient(
        ip="192.168.1.100",
        client_id="cid",
        username="his$1",
        access_token="at",
        access_token_time=now,
        access_token_duration=2,
        refresh_token="rt",
        refresh_token_time=now,
        refresh_token_duration=30,
    )
    old_session = MagicMock()
    client.mqtt_client = old_session
    client.connected = True

    with (
        patch(
            "custom_components.vidaa.client.async_perform_token_refresh",
            return_value={
                "accesstoken": "new_at",
                "accesstoken_time": now,
                "accesstoken_duration_day": 2,
            },
        ),
        patch.object(client, "async_sync_clock"),
        patch.object(client, "async_connect_and_run"),
    ):
        await client.async_refresh_tokens()

    old_session.close.assert_called_once()
    await client.async_disconnect()


@pytest.mark.anyio
async def test_disconnect_debounce_cancels_on_quick_reconnect():
    """Verify disconnect debounce delays dispatch and cancels if reconnected within window."""
    client = VidaaClient(ip="192.168.1.100", client_id="cid", username="u", access_token="at")
    client.connected = True
    loop = asyncio.get_running_loop()
    client._loop = loop

    disconnected_events = []
    client.register_disconnected_callback(lambda: disconnected_events.append(True))

    # Trigger disconnect with debounce
    client._handle_disconnected(debounce=True)
    assert client.connected is False
    assert client._disconnect_debounce_handle is not None
    # Callback has NOT fired yet
    assert len(disconnected_events) == 0

    # Quick reconnect before timer fires
    mock_adapter = MagicMock()
    client._handle_connected(mock_adapter, standard=False)
    assert client.connected is True
    assert client._disconnect_debounce_handle is None

    # Wait a bit past what would have been debounce
    await asyncio.sleep(0.05)
    # Callback was cancelled, so never fired
    assert len(disconnected_events) == 0

    await client.async_disconnect()


@pytest.mark.anyio
async def test_mqtt_session_adapter_publish_and_subscribe_success():
    """Verify MqttSessionAdapter publishes and subscribes through underlying aiomqtt session."""
    from custom_components.vidaa.protocol.mqtt_session import MqttSessionAdapter

    mock_session = AsyncMock()
    loop = asyncio.get_running_loop()
    adapter = MqttSessionAdapter(mock_session, loop)

    await adapter.async_publish("test/topic", "payload")
    mock_session.publish.assert_awaited_once_with("test/topic", "payload")

    await adapter.async_subscribe("test/topic")
    mock_session.subscribe.assert_awaited_once_with("test/topic")

    adapter.close()


@pytest.mark.anyio
async def test_mqtt_session_adapter_closed_rejects_immediately():
    """Verify calling async_publish or async_subscribe on closed adapter raises ConnectionError without hanging."""
    from custom_components.vidaa.protocol.mqtt_session import MqttSessionAdapter

    mock_session = AsyncMock()
    loop = asyncio.get_running_loop()
    adapter = MqttSessionAdapter(mock_session, loop)
    adapter.close()
    assert adapter.closed is True

    with pytest.raises(ConnectionError, match="MQTT session is closed"):
        await adapter.async_publish("test/topic", "payload")

    with pytest.raises(ConnectionError, match="MQTT session is closed"):
        await adapter.async_subscribe("test/topic")


@pytest.mark.anyio
async def test_mqtt_session_adapter_close_drains_queued_futures():
    """Verify closing an adapter drains all pending queued futures and raises ConnectionError."""
    from custom_components.vidaa.protocol.mqtt_session import MqttSessionAdapter

    hang_event = asyncio.Event()

    async def slow_publish(topic, payload):
        await hang_event.wait()

    mock_session = MagicMock()
    mock_session.publish = AsyncMock(side_effect=slow_publish)

    loop = asyncio.get_running_loop()
    adapter = MqttSessionAdapter(mock_session, loop)

    task1 = asyncio.create_task(adapter.async_publish("topic1", "1"))
    await asyncio.sleep(0.01)

    task2 = asyncio.create_task(adapter.async_publish("topic2", "2"))
    await asyncio.sleep(0.01)

    adapter.close()

    with pytest.raises(ConnectionError):
        await task1

    with pytest.raises(ConnectionError):
        await task2


@pytest.mark.anyio
async def test_async_publish_and_subscribe_resilience_on_disconnect():
    """Verify ConnectionManagerMixin.async_publish and async_subscribe return False on closed or timed-out session."""
    client = VidaaClient(ip="192.168.1.100", client_id="cid", username="u", access_token="at")
    client.connected = True
    loop = asyncio.get_running_loop()
    client._loop = loop

    # 1. No adapter
    client.mqtt_client = None
    assert await client.async_publish("topic", "p") is False
    assert await client.async_subscribe("topic") is False

    # 2. Closed adapter
    mock_adapter = MagicMock()
    mock_adapter.closed = True
    client.mqtt_client = mock_adapter
    assert await client.async_publish("topic", "p") is False
    assert await client.async_subscribe("topic") is False

    # 3. Adapter that raises ConnectionError or times out
    mock_adapter.closed = False
    mock_adapter.async_publish = AsyncMock(side_effect=ConnectionError("MQTT session is closed"))
    mock_adapter.async_subscribe = AsyncMock(side_effect=TimeoutError())
    assert await client.async_publish("topic", "p") is False
    assert await client.async_subscribe("topic", timeout=0.05) is False

    await client.async_disconnect()


@pytest.mark.anyio
async def test_handle_disconnected_fails_pending_queries():
    """Verify _handle_disconnected immediately fails any pending async_query futures with ConnectionError."""
    client = VidaaClient(ip="192.168.1.100", client_id="cid", username="u", access_token="at")
    client.connected = True
    loop = asyncio.get_running_loop()
    client._loop = loop

    fut = loop.create_future()
    client._pending_queries["test/resp"] = [fut]

    client._handle_disconnected(debounce=False)
    assert fut.done()
    with pytest.raises(ConnectionError, match="Disconnected from TV MQTT broker"):
        fut.result()
    assert "test/resp" not in client._pending_queries

    await client.async_disconnect()


@pytest.mark.anyio
async def test_auth_rejection_clears_mqtt_task_and_prevents_stale_reconnect():
    """Verify auth rejection clears _mqtt_task and failed refresh does not attempt stale reconnect."""
    now = int(time.time())
    client = VidaaClient(
        ip="192.168.1.100",
        client_id="cid",
        username="u",
        access_token="expired_tok",
        refresh_token="valid_ref",
        refresh_token_time=now,
        refresh_token_duration=30,
    )
    loop = asyncio.get_running_loop()
    client._loop = loop

    from aiomqtt.exceptions import MqttConnectError

    mock_connect_err = MqttConnectError(5)

    with (
        patch("custom_components.vidaa.protocol.connection.Client") as mock_client_cls,
        patch.object(client, "async_sync_clock"),
    ):
        mock_client_cls.side_effect = mock_connect_err

        ready = loop.create_future()
        client._mqtt_task = loop.create_task(
            client._mqtt_session_loop(
                client.client_id,
                client.username,
                client.access_token,
                None,
                reconnect=True,
                standard=True,
                ready=ready,
            )
        )
        await client._mqtt_task

        assert client._mqtt_task is None
        assert client.mqtt_client is None
        assert client.connected is False

    with (
        patch(
            "custom_components.vidaa.client.async_perform_token_refresh",
            return_value=None,
        ),
        patch.object(client, "async_sync_clock"),
        patch.object(client, "async_connect_and_run") as mock_connect,
    ):
        refreshed = await client.async_refresh_tokens()
        assert refreshed is False
        mock_connect.assert_not_called()

    await client.async_disconnect()


@pytest.mark.anyio
async def test_auth_rejection_recovery_triggers_connect_on_success():
    """Verify that when token refresh succeeds following auth rejection, connection is established with new credentials."""
    now = int(time.time())
    client = VidaaClient(
        ip="192.168.1.100",
        client_id="cid",
        username="u",
        access_token="old_tok",
        refresh_token="valid_ref",
        refresh_token_time=now,
        refresh_token_duration=30,
    )
    client.connected = False
    loop = asyncio.get_running_loop()
    client._loop = loop

    with (
        patch(
            "custom_components.vidaa.client.async_perform_token_refresh",
            return_value={
                "accesstoken": "new_shiny_token",
                "accesstoken_time": now,
                "accesstoken_duration_day": 2,
                "refreshtoken": "new_refresh_token",
            },
        ),
        patch.object(client, "async_sync_clock"),
        patch.object(client, "async_connect_and_run") as mock_connect,
    ):
        await client._token_manager.async_refresh_token_and_update_creds()

        assert client.access_token == "new_shiny_token"
        assert client.refresh_token == "new_refresh_token"
        assert client._token_manager.rejected_refresh_failures == 0
        assert client._token_manager.broker_rejection_failures == 0
        mock_connect.assert_awaited_once()

    await client.async_disconnect()


@pytest.mark.anyio
async def test_auth_rejection_max_attempts_cancels_retry_and_dispatches_auth_failed():
    """Verify repeated broker rejections cancel any scheduled retry tasks and fire auth_failed callback."""
    now = int(time.time())
    client = VidaaClient(
        ip="192.168.1.100",
        client_id="cid",
        username="u",
        access_token="old_tok",
        refresh_token="valid_ref",
        refresh_token_time=now,
        refresh_token_duration=30,
    )
    mock_auth_failed = MagicMock()
    client.register_auth_failed_callback(mock_auth_failed)
    client._token_manager.broker_rejection_failures = client.MAX_BROKER_REJECTION_ATTEMPTS - 1
    client._token_manager.last_refresh_connect_rc = 5

    loop = asyncio.get_running_loop()
    dummy_task = loop.create_task(asyncio.sleep(100))
    client._token_manager.rejected_retry_task = dummy_task

    with patch.object(client, "async_check_and_refresh_token", return_value=False):
        await client._token_manager.async_refresh_token_and_update_creds()

    mock_auth_failed.assert_called_once()
    await asyncio.sleep(0)
    assert dummy_task.cancelled()
    assert client._token_manager.rejected_retry_task is None

    await client.async_disconnect()
