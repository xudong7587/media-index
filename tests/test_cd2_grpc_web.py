import struct
from unittest.mock import Mock, patch

import grpc
import httpx
import pytest
from google.protobuf.empty_pb2 import Empty

from app.clients import cd2_grpc_web, cd2_pb2 as wire
from app.clients.cd2 import Cd2Client, Cd2Error


def frame(payload, flag=0):
    return struct.pack(">BI", flag, len(payload)) + payload


def response(messages=(), status="0"):
    return b"".join(frame(item.SerializeToString()) for item in messages) + frame(
        f"grpc-status: {status}\r\n".encode(), 128)


def invoke(body, *, headers=None, status_code=200, stream=True):
    def handler(request):
        assert request.url.path == "/clouddrive.CloudDriveFileSrv/GetSubFiles"
        assert request.headers["authorization"] == "Bearer fixture-token"
        assert request.headers["content-type"] == "application/grpc-web+proto"
        assert wire.ListSubFileRequest.FromString(request.content[5:]).path == "/test"
        return httpx.Response(status_code, headers={"content-type": "application/grpc-web+proto", **(headers or {})}, content=body)

    real_client = httpx.Client
    def factory(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return real_client(transport=httpx.MockTransport(handler), **kwargs)
    with patch.object(cd2_grpc_web.httpx, "Client", side_effect=factory):
        return cd2_grpc_web.call("https://cd2.example", "fixture-token", "GetSubFiles",
                                 wire.ListSubFileRequest(path="/test"), wire.SubFilesReply, stream=stream)


def test_stream_requires_success_trailer_and_preserves_all_messages():
    messages = [wire.SubFilesReply(subFiles=[wire.CloudDriveFile(name=name)]) for name in ["电影", "剧集"]]
    assert [item.subFiles[0].name for item in invoke(response(messages))] == ["电影", "剧集"]
    assert invoke(response()) == []


@pytest.mark.parametrize("body", [
    b"", b"\0", frame(b"", 1), struct.pack(">BI", 0, 100) + b"a",
    frame(b""), response() + frame(b""), frame(b"grpc-status: 0\r\ngrpc-status: 0", 128),
    frame(b"\xff", 128), frame(b"\xff"),
])
def test_malformed_or_incomplete_stream_never_looks_like_success(body):
    with pytest.raises(cd2_grpc_web.GrpcWebError):
        invoke(body)


def test_trailers_only_auth_failure_is_safe_and_readable():
    with pytest.raises(cd2_grpc_web.GrpcWebError, match="授权失败") as caught:
        invoke(b"", headers={"grpc-status": "16", "grpc-message": "fixture-token sensitive server detail"})
    assert "fixture-token" not in str(caught.value)
    assert "sensitive" not in str(caught.value)


def test_failed_trailer_discards_preceding_directory_data():
    with pytest.raises(cd2_grpc_web.GrpcWebError, match="未确认"):
        invoke(response([wire.SubFilesReply(subFiles=[wire.CloudDriveFile(name="partial")])], status="13"))


def test_redirect_and_html_are_rejected():
    with pytest.raises(cd2_grpc_web.GrpcWebError, match="接口不可用"):
        invoke(b"", headers={"location": "https://elsewhere.example"}, status_code=302)
    with pytest.raises(cd2_grpc_web.GrpcWebError, match="接口不可用"):
        invoke(b"<html />", headers={"content-type": "text/html"})


def test_oversized_response_is_rejected():
    with patch.object(cd2_grpc_web, "MAX_RESPONSE_BYTES", 8):
        with pytest.raises(cd2_grpc_web.GrpcWebError, match="超过读取上限"):
            invoke(response())


@pytest.mark.parametrize("messages", [[], [wire.SubFilesReply(), wire.SubFilesReply()]])
def test_unary_rpc_requires_exactly_one_message(messages):
    with pytest.raises(cd2_grpc_web.GrpcWebError, match="唯一响应"):
        invoke(response(messages), stream=False)


class RpcFailure(grpc.RpcError):
    def __init__(self, code=grpc.StatusCode.UNKNOWN):
        self._code = code

    def code(self):
        return self._code


def failed_channel(code=grpc.StatusCode.UNKNOWN):
    channel = Mock()
    channel.__enter__ = Mock(return_value=channel)
    channel.__exit__ = Mock(return_value=False)
    channel.unary_unary.return_value = Mock(side_effect=RpcFailure(code))
    return channel


def test_first_write_negotiates_with_read_and_submits_once_over_web():
    client = Cd2Client("http://cd2.example", "fixture-token")
    web = Mock(side_effect=[wire.GetCopyTaskResult(), wire.CreateFolderResult(result=wire.FileOperationResult(success=True))])
    with patch("app.clients.cd2.grpc.insecure_channel", return_value=failed_channel()) as native, patch(
        "app.clients.cd2.grpc_web_call", web,
    ):
        assert client.mkdir("/test/new") == {"ok": True}
    assert native.call_count == 1
    assert [call.args[2] for call in web.call_args_list] == ["GetCopyTasks", "CreateFolder"]


def test_ambiguous_native_write_is_never_replayed_over_web():
    client = Cd2Client("http://cd2.example", "fixture-token")
    client._protocol = "native"
    with patch("app.clients.cd2.grpc.insecure_channel", return_value=failed_channel()), patch(
        "app.clients.cd2.grpc_web_call",
    ) as web:
        with pytest.raises(Cd2Error, match="未确认"):
            client.mkdir("/test/new")
    web.assert_not_called()


def test_native_auth_failure_does_not_try_another_protocol():
    client = Cd2Client("http://cd2.example", "fixture-token")
    with patch("app.clients.cd2.grpc.insecure_channel", return_value=failed_channel(grpc.StatusCode.UNAUTHENTICATED)), patch(
        "app.clients.cd2.grpc_web_call",
    ) as web:
        with pytest.raises(Cd2Error, match="授权失败"):
            client._rpc("GetCopyTasks", Empty(), wire.GetCopyTaskResult)
    web.assert_not_called()
