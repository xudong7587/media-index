"""Bounded binary gRPC-Web transport for CD2 reverse proxies.

https://github.com/grpc/grpc/blob/master/doc/PROTOCOL-WEB.md
No redirects, proxy environment, remote error text, or automatic retries.
"""
from __future__ import annotations

import struct

import httpx
from google.protobuf.message import DecodeError

from app.clients.openlist import OpenListError


MAX_RESPONSE_BYTES = 16 * 1024 * 1024


class GrpcWebError(OpenListError):
    pass


def _check_status(status: str | None) -> None:
    if status == "0":
        return
    if status in {"7", "16"}:
        raise GrpcWebError("CD2 授权失败，请检查 API Token 是否有效及文件、复制任务权限")
    if status == "5":
        raise GrpcWebError("CD2 目录不存在 (not found)")
    raise GrpcWebError("CD2 gRPC-Web 响应未确认，请查询复制队列后再决定是否重试")


def call(base_url: str, token: str, method: str, request, response_type, *, stream: bool = False):
    message = request.SerializeToString()
    headers = {"content-type": "application/grpc-web+proto", "accept": "application/grpc-web+proto",
               "x-grpc-web": "1", "authorization": f"Bearer {token}"}
    try:
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=30) as client:
            with client.stream("POST", f"{base_url}/clouddrive.CloudDriveFileSrv/{method}",
                               headers=headers, content=struct.pack(">BI", 0, len(message)) + message) as response:
                if response.status_code in {401, 403}:
                    _check_status("16")
                if response.status_code != 200 or response.headers.get("content-type", "").split(";", 1)[0].strip() not in {
                    "application/grpc-web", "application/grpc-web+proto",
                }:
                    raise GrpcWebError("CD2 gRPC-Web 接口不可用，请检查服务地址和反向代理")
                data = bytearray()
                for chunk in response.iter_bytes():
                    if len(data) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise GrpcWebError("CD2 响应超过读取上限，未使用不完整目录或复制队列")
                    data.extend(chunk)
                status = response.headers.get("grpc-status")
    except httpx.HTTPError:
        raise GrpcWebError("CD2 gRPC-Web 通信未确认，请查询复制队列后再决定是否重试") from None

    replies = []
    offset = 0
    trailer_seen = False
    try:
        while offset < len(data):
            if trailer_seen or len(data) - offset < 5:
                raise ValueError
            flag, size = struct.unpack_from(">BI", data, offset)
            offset += 5
            if size > len(data) - offset:
                raise ValueError
            payload = bytes(data[offset:offset + size])
            offset += size
            if flag == 128:
                trailer_seen = True
                for line in payload.decode("ascii").split("\r\n"):
                    if not line:
                        continue
                    name, separator, value = line.partition(":")
                    if not separator:
                        raise ValueError
                    if name.lower() == "grpc-status":
                        if status is not None:
                            raise ValueError
                        status = value.strip()
            elif flag == 0:
                replies.append(response_type.FromString(payload))
            else:
                # Compressed frames are not negotiated by this client.
                raise ValueError
    except (ValueError, DecodeError):
        raise GrpcWebError("CD2 gRPC-Web 响应不完整或格式无效，未确认操作结果") from None
    _check_status(status)
    if not stream and len(replies) != 1:
        raise GrpcWebError("CD2 gRPC-Web 缺少唯一响应，未确认操作结果")
    return replies if stream else replies[0]
