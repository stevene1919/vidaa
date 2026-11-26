"""Coverage tests for protocol/connection.py, mqtt_session.py, auth_lifecycle.py, and dispatcher.py."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiomqtt.exceptions import MqttConnectError, MqttError

from custom_components.vidaa.client import VidaaClient
from custom_components.vidaa.protocol.dispatcher import (
    dispatch_incoming_mqtt_message,
    mask_sensitive_payload,
)
from custom_components.vidaa.protocol.mqtt_session import (
    MqttSessionAdapter,
    decode_mqtt_payload,
)


def _make_client(auth_profile: str = "modern") -> VidaaClient:
    return VidaaClient(
        ip="192.168.1.100",
        mac="e8:51:77:aa:bb:cc",
        client_id="e8:51:77:aa:bb:cc$his$abc123_vidaacommon_001",
        username="his$12345",
        access_token="acc_tok",
        refresh_token="ref_tok",
        auth_profile=auth_profile,
        use_ssl=True,
    )


@pytest.mark.anyio
async def test_connection_ssl_connect_disconnect_and_queries(tmp_path) -> None:
    """Cover _async_build_ssl_context, _handle_connected/disconnected/message, and async_query."""
    client = _make_client("modern")
    p12_file = tmp_path / "client.p12"
    p12_file.write_bytes(b"dummy")
    cert_file = tmp_path / "hisense.crt"
    key_file = tmp_path / "hisense.key"
    cert_file.write_text("CERT")
    key_file.write_text("KEY")
    client.certfile = str(p12_file)
    client.keyfile = str(p12_file)

    with (
        patch("custom_components.vidaa.protocol.resolve_certificates", return_value=(str(cert_file), str(key_file))),
        patch("custom_components.vidaa.protocol.resolve_ca_certificate", return_value=None),
        patch("custom_components.vidaa.protocol.connection.build_mqtt_ssl_context", return_value="SSL_CTX") as mock_ssl,
    ):
        ctx = await client._async_build_ssl_context()
    assert ctx == "SSL_CTX"
    mock_ssl.assert_called_once()

    # _handle_connected with refresh_token schedules proactive refresh
    client.async_sync_clock = AsyncMock()
    client.async_query_initial_state = AsyncMock()
    client._token_manager.async_proactive_token_refresh = AsyncMock()
    adapter = MagicMock()
    client._handle_connected(adapter, standard=True)
    await asyncio.sleep(0)
    assert client.connected is True
    adapter.subscribe.assert_called_once()
    await client._async_stop_session()

    # _async_delayed_initial_query breaks early when disconnected
    client.connected = False
    with patch("custom_components.vidaa.protocol.connection.asyncio.sleep", AsyncMock()):
        await client._async_delayed_initial_query()
    client.async_query_initial_state.assert_awaited()

    # _handle_disconnected cancels existing debounce handle and fires call_later callback
    client.connected = True
    old_handle = MagicMock()
    client._disconnect_debounce_handle = old_handle
    fut = asyncio.get_running_loop().create_future()
    client._pending_queries["t/1"] = [fut]

    scheduled_cbs = []
    fake_loop = MagicMock()
    fake_loop.is_running.return_value = True
    fake_loop.call_later.side_effect = lambda _delay, cb: scheduled_cbs.append(cb) or MagicMock()
    client._loop = fake_loop

    client._handle_disconnected(debounce=True)
    old_handle.cancel.assert_called_once()
    assert fut.done() and isinstance(fut.exception(), ConnectionError)
    assert len(scheduled_cbs) == 1
    scheduled_cbs[0]()  # fires _fire_disconnect -> _logged_unavailable = True

    # Second disconnect uses debug log branch
    client.connected = True
    client._handle_disconnected(debounce=False)

    # _handle_message resolves pending query futures
    q_fut = asyncio.get_running_loop().create_future()
    client._pending_queries["topic/resp"] = [q_fut]
    client._handle_message("topic/resp", '{"ok": 1}')
    assert q_fut.result() == '{"ok": 1}'

    # async_query disconnected -> raises
    client.mqtt_client = None
    with pytest.raises(Exception, match="MQTT client not initialized"):
        await client.async_query("pub/t", "sub/t")

    # async_query happy path & error cleanup
    live_adapter = MagicMock(closed=False)
    live_adapter.async_subscribe = AsyncMock()

    def _pub_resp(_topic, _payload):
        for w in list(client._pending_queries.get("sub/ok", [])):
            w.set_result('{"val": 42}')

    live_adapter.async_publish = AsyncMock(side_effect=_pub_resp)
    client.mqtt_client = live_adapter
    res = await client.async_query("pub/ok", "sub/ok", "{}")
    assert res == {"val": 42}

    live_adapter.async_publish = AsyncMock(side_effect=RuntimeError("boom"))
    with pytest.raises(TimeoutError):
        await client.async_query("pub/fail", "sub/fail", "{}", timeout=0.01)
    assert "sub/fail" not in client._pending_queries


@pytest.mark.anyio
async def test_connection_supervisor_loop_pairing_and_ensure_connected() -> None:
    """Cover _mqtt_session_loop, async_open_pairing_session timeout, nudge_reconnect, and async_ensure_connected."""
    client = _make_client("modern")
    client.async_sync_clock = AsyncMock()
    client.async_query_initial_state = AsyncMock()

    async def _empty_messages():
        yield SimpleNamespace(topic="t/1", payload=b'{"statetype":"fake_sleep_1"}')

    class _FakeSession:
        def __init__(self, mode: str) -> None:
            self.mode = mode
            self.messages = _empty_messages()

        async def __aenter__(self):
            if self.mode == "conn_err":
                raise MqttConnectError(5)
            if self.mode == "os_err_then_cancel":
                raise OSError("net down")
            return self

        async def __aexit__(self, *args):
            return False

        async def publish(self, *_args):
            return None

        async def subscribe(self, *_args):
            return None

    # 1. Normal session (reconnect=False) resolves ready future and exits cleanly
    ready = asyncio.get_running_loop().create_future()
    with patch("custom_components.vidaa.protocol.connection.Client", return_value=_FakeSession("ok")):
        await client._mqtt_session_loop("cid", "u", "p", None, reconnect=False, standard=False, ready=ready)
    assert ready.result() is True
    assert client.mqtt_client is None

    # 2. MqttConnectError with active _auth_future fails future and returns
    auth_fut = asyncio.get_running_loop().create_future()
    client._auth_future = auth_fut
    ready2 = asyncio.get_running_loop().create_future()
    with patch("custom_components.vidaa.protocol.connection.Client", return_value=_FakeSession("conn_err")):
        await client._mqtt_session_loop("cid", "u", "p", None, reconnect=False, standard=False, ready=ready2)
    assert ready2.done() and ready2.exception() is not None
    assert auth_fut.done() and auth_fut.exception() is not None
    client._auth_future = None

    # 3. MqttConnectError with AUTH_REJECTION_CODES on standard=True spawns token rejection handler
    client._token_manager.async_handle_auth_rejection = AsyncMock()
    with patch("custom_components.vidaa.protocol.connection.Client", return_value=_FakeSession("conn_err")):
        await client._mqtt_session_loop("cid", "u", "p", None, reconnect=True, standard=True)
    await asyncio.sleep(0)

    # 4. OSError with reconnect=True hits timeout backoff, then event wakeup, then CancelledError
    attempts = 0

    def _client_factory(**_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts >= 3:
            raise asyncio.CancelledError()
        return _FakeSession("os_err_then_cancel")

    wait_calls = 0

    async def _fake_wait_for(coro, timeout=None):
        nonlocal wait_calls
        wait_calls += 1
        coro.close()
        if wait_calls == 1:
            raise TimeoutError()
        return True

    with (
        patch("custom_components.vidaa.protocol.connection.Client", side_effect=_client_factory),
        patch("custom_components.vidaa.protocol.connection.asyncio.wait_for", side_effect=_fake_wait_for),
        pytest.raises(asyncio.CancelledError),
    ):
        await client._mqtt_session_loop("cid", "u", "p", None, reconnect=True, standard=False)

    # async_open_pairing_session TimeoutError stops session and raises
    pending_ready = asyncio.get_running_loop().create_future()
    with (
        patch.object(client, "_async_build_ssl_context", AsyncMock(return_value=None)),
        patch.object(client, "_async_stop_session", AsyncMock()) as mock_stop,
        patch.object(client, "_mqtt_session_loop", AsyncMock()),
        patch("custom_components.vidaa.protocol.connection.asyncio.wait_for", AsyncMock(side_effect=TimeoutError())),
        pytest.raises(Exception, match="connection timeout"),
    ):
        await client.async_open_pairing_session("cid", "u", "p", timeout=0.01)
    assert mock_stop.await_count >= 2
    pending_ready.cancel()

    # async_connect_and_run sync/async shim
    called = []
    client.connect_and_run = lambda: called.append("sync")
    await client.async_connect_and_run()

    async def _async_shim():
        called.append("async")

    client.connect_and_run = _async_shim
    await client.async_connect_and_run()
    assert called == ["sync", "async"]
    del client.__dict__["connect_and_run"]

    # nudge_reconnect across same-loop, different-loop, and no-loop branches
    ev = asyncio.Event()
    client._reconnect_event = ev
    client._loop = asyncio.get_running_loop()
    client.nudge_reconnect()
    assert ev.is_set()

    ev.clear()
    other_loop = MagicMock()
    other_loop.is_running.return_value = True
    client._loop = other_loop
    with patch("custom_components.vidaa.protocol.connection.asyncio.get_running_loop", side_effect=RuntimeError):
        client.nudge_reconnect()
    other_loop.call_soon_threadsafe.assert_called_once()

    with patch("custom_components.vidaa.protocol.connection.asyncio.get_running_loop", side_effect=RuntimeError):
        other_loop.is_running.return_value = False
        client.nudge_reconnect()

    # async_ensure_connected branches
    client.ensure_connected = lambda min_interval=5.0: True
    assert await client.async_ensure_connected() is True

    async def _async_ec(min_interval=5.0):
        return False

    client.ensure_connected = _async_ec
    assert await client.async_ensure_connected() is False
    del client.__dict__["ensure_connected"]

    client.connected = True
    client.mqtt_client = MagicMock()
    assert await client.async_ensure_connected() is True

    client.connected = False
    client._mqtt_task = MagicMock(done=MagicMock(return_value=False))
    assert await client.async_ensure_connected() is True

    client._mqtt_task = None
    client._last_reconnect_time = 0.0
    with patch.object(client, "async_check_and_refresh_token", AsyncMock(side_effect=RuntimeError("err"))):
        assert await client.async_ensure_connected(min_interval=0.0) is False


def test_connection_sync_wrappers() -> None:
    """Cover synchronous CLI wrappers ensure_connected, connect_and_run, and disconnect."""
    client = _make_client("legacy")

    # ensure_connected: in-loop RuntimeError
    fake_loop = MagicMock()
    fake_loop.is_running.return_value = True
    client._loop = fake_loop
    with (
        patch("custom_components.vidaa.protocol.connection.asyncio.get_running_loop", return_value=fake_loop),
        pytest.raises(RuntimeError, match="event loop"),
    ):
        client.ensure_connected()

    # ensure_connected: cross-thread
    with (
        patch("custom_components.vidaa.protocol.connection.asyncio.get_running_loop", side_effect=RuntimeError),
        patch(
            "custom_components.vidaa.protocol.connection.asyncio.run_coroutine_threadsafe",
            return_value=MagicMock(result=MagicMock(return_value=True)),
        ) as mock_rcts,
    ):
        assert client.ensure_connected() is True
    mock_rcts.assert_called_once()

    # ensure_connected: no loop -> asyncio.run
    client._loop = None
    with patch(
        "custom_components.vidaa.protocol.connection.asyncio.run",
        side_effect=lambda coro: coro.close() or False,
    ) as mock_run:
        assert client.ensure_connected() is False
    mock_run.assert_called_once()

    # connect_and_run: creates mocked loop/thread when none exists
    created_loop = MagicMock()
    created_loop.is_running.return_value = False
    created_loop.is_closed.return_value = False
    with (
        patch("custom_components.vidaa.protocol.connection.asyncio.get_running_loop", side_effect=RuntimeError),
        patch("custom_components.vidaa.protocol.connection.asyncio.new_event_loop", return_value=created_loop),
        patch("threading.Thread") as mock_thread,
        patch.object(client, "async_connect_and_run", MagicMock(return_value="CORO")),
    ):
        client.connect_and_run()
    mock_thread.return_value.start.assert_called_once()
    created_loop.run_until_complete.assert_called_once_with("CORO")

    # disconnect: no loop
    client._loop = None
    client.disconnect()
    assert client.connected is False

    # disconnect: same running loop
    same_loop = MagicMock()
    same_loop.is_closed.return_value = False
    same_loop.is_running.return_value = True
    client._loop = same_loop
    with (
        patch("custom_components.vidaa.protocol.connection.asyncio.get_running_loop", return_value=same_loop),
        patch.object(client, "async_disconnect", MagicMock(return_value="D_CORO")),
    ):
        client.disconnect()
    same_loop.create_task.assert_called_once_with("D_CORO")

    # disconnect: different running loop and non-running loop
    with (
        patch("custom_components.vidaa.protocol.connection.asyncio.get_running_loop", side_effect=RuntimeError),
        patch(
            "custom_components.vidaa.protocol.connection.asyncio.run_coroutine_threadsafe",
            return_value=MagicMock(result=MagicMock(return_value=None)),
        ) as mock_disc_rcts,
        patch.object(client, "async_disconnect", MagicMock(return_value="D_CORO")),
    ):
        client.disconnect()
    mock_disc_rcts.assert_called_once()

    same_loop.is_running.return_value = False
    with patch.object(client, "async_disconnect", MagicMock(return_value="D_CORO")):
        client.disconnect()
    same_loop.run_until_complete.assert_called_once_with("D_CORO")


@pytest.mark.anyio
async def test_mqtt_session_adapter_and_decode_branches() -> None:
    """Cover MqttSessionAdapter error paths, sync publish/subscribe, cross-thread enqueue, and decode."""
    assert decode_mqtt_payload(b"hello") == "hello"
    assert decode_mqtt_payload(None) == ""
    assert decode_mqtt_payload(123) == "123"

    session = MagicMock()
    session.publish = AsyncMock(side_effect=MqttError("pub fail"))
    session.subscribe = AsyncMock(return_value=None)
    loop = asyncio.get_running_loop()
    adapter = MqttSessionAdapter(session, loop)

    adapter.publish("t/p", "1")
    adapter.subscribe("t/s")
    await asyncio.sleep(0)

    with pytest.raises(MqttError, match="pub fail"):
        await adapter.async_publish("t/p", "2")

    # Cross-thread enqueue path and RuntimeError path
    with (
        patch("custom_components.vidaa.protocol.mqtt_session.asyncio.get_running_loop", side_effect=RuntimeError),
        patch.object(loop, "call_soon_threadsafe", side_effect=RuntimeError("loop closed")),
    ):
        fut = loop.create_future()
        adapter._enqueue(("pub", "t/x", "p", fut))
        assert isinstance(fut.exception(), RuntimeError)

    # _drain_queue when QueueEmpty occurs mid-drain
    adapter._queue.put_nowait(("pub", "t/q", "1", None))
    adapter.close()


@pytest.mark.anyio
async def test_auth_lifecycle_and_dispatcher_branches() -> None:
    """Cover TokenLifecycleManager and dispatcher edge branches."""
    client = _make_client("modern")
    mgr = client._token_manager

    # _spawn_task fallback without client._spawn
    bare_client = SimpleNamespace(ip="192.168.1.100")
    bare_mgr = type(mgr)(bare_client)  # type: ignore[arg-type]

    async def _noop():
        return None

    t = bare_mgr._spawn_task(_noop())
    assert t is not None
    await t

    with patch("custom_components.vidaa.protocol.auth_lifecycle.asyncio.get_running_loop", side_effect=RuntimeError):
        c = _noop()
        assert bare_mgr._spawn_task(c) is None

    # start_token_watch early return when already active
    mgr.token_watch_task = asyncio.create_task(_noop())
    mgr.start_token_watch()
    await mgr.token_watch_task

    # _token_watch_loop logs and continues on exception
    mgr.token_watch_closed = False
    calls = 0

    async def _raise_then_stop():
        nonlocal calls
        calls += 1
        mgr.token_watch_closed = True
        raise RuntimeError("watch fail")

    with (
        patch("custom_components.vidaa.protocol.auth_lifecycle.asyncio.sleep", AsyncMock()),
        patch.object(mgr, "async_maybe_refresh_while_awake", side_effect=_raise_then_stop),
    ):
        await mgr._token_watch_loop()
    assert calls == 1

    # Sync wrappers inside running loop
    with (
        patch.object(mgr, "async_maybe_refresh_while_awake", AsyncMock()),
        patch.object(mgr, "async_proactive_token_refresh", AsyncMock()),
        patch.object(mgr, "async_handle_auth_rejection", AsyncMock()),
        patch.object(mgr, "async_refresh_token_and_update_creds", AsyncMock()),
    ):
        mgr._token_watch_tick()
        mgr.maybe_refresh_while_awake()
        mgr.proactive_token_refresh()
        mgr.handle_auth_rejection(5)
        mgr.refresh_token_and_update_creds()
        mgr._rejected_retry_fire()
        await asyncio.sleep(0)

    # Sync wrappers outside running loop
    with (
        patch("custom_components.vidaa.protocol.auth_lifecycle.asyncio.get_running_loop", side_effect=RuntimeError),
        patch("custom_components.vidaa.protocol.auth_lifecycle.asyncio.run") as mock_run,
        patch.object(mgr, "async_maybe_refresh_while_awake", MagicMock(return_value="C1")),
        patch.object(mgr, "async_proactive_token_refresh", MagicMock(return_value="C2")),
        patch.object(mgr, "async_handle_auth_rejection", MagicMock(return_value="C3")),
        patch.object(client, "async_connect_and_run", MagicMock(return_value="C4")),
    ):
        mgr._token_watch_tick()
        client.refresh_token = None
        mgr._rejected_retry_fire()
    assert mock_run.call_count == 2

    # async_maybe_refresh_while_awake branches
    client.connected = False
    await mgr.async_maybe_refresh_while_awake()

    client.connected = True
    client.is_on = True
    client.refresh_token = "ref_tok"
    client.access_token_time = 100
    client.access_token_duration = 1
    with patch("custom_components.vidaa.protocol.auth_lifecycle.is_token_expired", return_value=False):
        await mgr.async_maybe_refresh_while_awake()

    mgr.awake_refresh_failures = 0
    mgr.last_awake_refresh_attempt = 9e9
    with patch("custom_components.vidaa.protocol.auth_lifecycle.is_token_expired", return_value=True):
        await mgr.async_maybe_refresh_while_awake()

    mgr.last_awake_refresh_attempt = 0.0
    mgr.last_refresh_attempt = 0.0
    with (
        patch("custom_components.vidaa.protocol.auth_lifecycle.is_token_expired", return_value=True),
        patch.object(client, "async_refresh_tokens", AsyncMock(side_effect=RuntimeError("boom"))),
    ):
        await mgr.async_maybe_refresh_while_awake()
    assert mgr.awake_refresh_failures == 1

    # async_proactive_token_refresh exception branch
    with (
        patch("custom_components.vidaa.protocol.auth_lifecycle.is_token_expired", return_value=True),
        patch("custom_components.vidaa.protocol.auth_lifecycle.asyncio.sleep", AsyncMock(side_effect=RuntimeError)),
    ):
        await mgr.async_proactive_token_refresh()

    # async_handle_auth_rejection with broker_rejection_failures > 0
    client.async_sync_clock = AsyncMock()
    client.refresh_token = "ref_tok"
    mgr.broker_rejection_failures = 1
    mgr.last_refresh_attempt = 9e9
    client._schedule_rejected_retry = MagicMock()
    with patch("custom_components.vidaa.protocol.auth_lifecycle.is_token_expired", return_value=False):
        await mgr.async_handle_auth_rejection(5)
    client._schedule_rejected_retry.assert_called_once()

    # _rejected_retry_runner branches
    with (
        patch("custom_components.vidaa.protocol.auth_lifecycle.asyncio.sleep", AsyncMock()),
        patch("custom_components.vidaa.protocol.auth_lifecycle.is_token_expired", return_value=False),
        patch.object(mgr, "async_handle_auth_rejection", AsyncMock()) as mock_rej,
    ):
        await mgr._rejected_retry_runner(0.1)
    mock_rej.assert_awaited_once()

    with (
        patch("custom_components.vidaa.protocol.auth_lifecycle.asyncio.sleep", AsyncMock()),
        patch("custom_components.vidaa.protocol.auth_lifecycle.is_token_expired", return_value=True),
        patch.object(client, "async_connect_and_run", AsyncMock(side_effect=RuntimeError("fail"))),
    ):
        await mgr._rejected_retry_runner(0.1)

    # async_refresh_token_and_update_creds fallback to schedule_rejected_retry & exception + expired token
    delattr(client, "_schedule_rejected_retry") if "_schedule_rejected_retry" in client.__dict__ else None
    with (
        patch.object(client, "async_check_and_refresh_token", AsyncMock(return_value=False)),
        patch("custom_components.vidaa.protocol.auth_lifecycle.is_token_expired", return_value=False),
        patch.object(mgr, "schedule_rejected_retry") as mock_sched,
    ):
        mgr.last_refresh_connect_rc = None
        mgr.broker_rejection_failures = 0
        await mgr.async_refresh_token_and_update_creds()
    if not hasattr(client, "_schedule_rejected_retry"):
        mock_sched.assert_called_once()

    client._dispatch_auth_failed = MagicMock()
    with (
        patch.object(client, "async_check_and_refresh_token", AsyncMock(side_effect=RuntimeError("crash"))),
        patch("custom_components.vidaa.protocol.auth_lifecycle.is_token_expired", return_value=True),
    ):
        await mgr.async_refresh_token_and_update_creds()
    client._dispatch_auth_failed.assert_called_once()

    # Dispatcher coverage
    assert mask_sensitive_payload("not-json", "/gettoken") == "[payload masked]"
    client._auth_code_future = asyncio.get_running_loop().create_future()
    dispatch_incoming_mqtt_message(client, f"{client.topics.mobile}ui_service/data/authenticationcode", "1234")
    assert client._auth_code_future.result() == "1234"
    client._auth_code_future = None

    client._token_future = asyncio.get_running_loop().create_future()
    dispatch_incoming_mqtt_message(
        client, f"{client.topics.mobile}platform_service/data/tokenissuance", json.dumps({"accesstoken": "x"})
    )
    assert "accesstoken" in client._token_future.result()
    client._token_future = None

    client.state = "off"
    client.current_source = "HDMI 1"
    client._dispatch_state_update = MagicMock()
    client._dispatch_volume_update = MagicMock()
    client._dispatch_hotel_mode_update = MagicMock()
    client._dispatch_picture_update = MagicMock()
    client._dispatch_sound_update = MagicMock()
    dispatch_incoming_mqtt_message(
        client, f"{client.topics.broadcast}platform_service/actions/volumechange", '{"volume_value": 10}'
    )
    dispatch_incoming_mqtt_message(client, f"{client.topics.broadcast}platform_service/actions/tvwake", "")
    dispatch_incoming_mqtt_message(client, f"{client.topics.broadcast}ui_service/data/hotelmodechange", "true")
    dispatch_incoming_mqtt_message(client, f"{client.topics.mobile}platform_service/data/picturesetting", "[]")
    dispatch_incoming_mqtt_message(client, f"{client.topics.mobile}platform_service/data/soundsetting", "[]")
    client._dispatch_hotel_mode_update.assert_called_with(True)
    client._dispatch_picture_update.assert_called_with([])
    client._dispatch_sound_update.assert_called_with([])

    # Invalid JSON paths on all topic handlers
    for suffix in (
        f"{client.topics.broadcast}ui_service/state",
        f"{client.topics.broadcast}ui_service/volume",
        f"{client.topics.broadcast}ui_service/data/hotelmodechange",
        f"{client.topics.mobile}ui_service/data/sourcelist",
        f"{client.topics.mobile}ui_service/data/applist",
        f"{client.topics.mobile}platform_service/data/picturesetting",
        f"{client.topics.mobile}platform_service/data/soundsetting",
        f"{client.topics.mobile}platform_service/data/getdeviceinfo",
    ):
        dispatch_incoming_mqtt_message(client, suffix, "{bad-json")
