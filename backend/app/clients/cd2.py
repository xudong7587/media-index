"""CloudDrive2's native gRPC transport; no provider identity or DB decisions."""
from __future__ import annotations

from pathlib import PurePosixPath
from urllib.parse import urlsplit

import grpc
from google.protobuf.empty_pb2 import Empty

from app.clients import cd2_pb2 as wire
from app.clients.openlist import OpenListClient, OpenListError


class Cd2Error(OpenListError):
    """Compatible workflow error, with only safe, locally generated messages."""


def normalize_path(value: str) -> str:
    path = str(value or "").strip().replace("\\", "/")
    if not path.startswith("/") or any(p in {".", ".."} for p in path.split("/")) or any(ord(c) < 32 for c in path):
        raise Cd2Error("CD2 目录必须是有效的云端绝对路径")
    return "/" + "/".join(p for p in path.split("/") if p)


def validate_endpoint(value: str) -> str:
    parsed = urlsplit(str(value or "").strip())
    try:
        port = parsed.port
    except ValueError:
        raise Cd2Error("CD2 地址端口无效") from None
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or
            parsed.username or parsed.password or parsed.path not in {"", "/"} or
            parsed.query or parsed.fragment or any(c.isspace() for c in value)):
        raise Cd2Error("CD2 地址需为 HTTP 或 HTTPS 服务地址，不包含路径、账号或参数")
    if port is not None and not 1 <= port <= 65535:
        raise Cd2Error("CD2 地址端口无效")
    return parsed.geturl().rstrip("/")


class Cd2Client:
    def __init__(self, base_url: str, token: str):
        if not token.strip():
            raise Cd2Error("CD2 API Token 尚未配置")
        self.base_url = validate_endpoint(base_url)
        self.token = token.strip()
        self.on_copy_prepared = None

    def _rpc(self, method: str, request, response_type, *, stream: bool = False):
        parsed = urlsplit(self.base_url)
        target = parsed.netloc if parsed.port else f"{parsed.netloc}:{443 if parsed.scheme == 'https' else 80}"
        options = (("grpc.enable_http_proxy", 0), ("grpc.max_receive_message_length", 16 * 1024 * 1024))
        channel = (grpc.secure_channel(target, grpc.ssl_channel_credentials(), options=options)
                   if parsed.scheme == "https" else grpc.insecure_channel(target, options=options))
        try:
            with channel:
                factory = channel.unary_stream if stream else channel.unary_unary
                call = factory(f"/clouddrive.CloudDriveFileSrv/{method}",
                               request_serializer=lambda message: message.SerializeToString(),
                               response_deserializer=response_type.FromString)
                result = call(request, timeout=30, metadata=(("authorization", f"Bearer {self.token}"),))
                return list(result) if stream else result
        except grpc.RpcError as exc:
            code = exc.code()
            if code == grpc.StatusCode.NOT_FOUND:
                raise Cd2Error("CD2 目录不存在 (not found)") from None
            if code in {grpc.StatusCode.UNAUTHENTICATED, grpc.StatusCode.PERMISSION_DENIED}:
                raise Cd2Error("CD2 授权失败，请检查 API Token 及文件、复制任务权限") from None
            raise Cd2Error(f"CD2 通信未确认（{code.name}），请查询复制队列后再决定是否重试") from None

    def list_entries(self, path: str) -> list[dict]:
        replies = self._rpc("GetSubFiles", wire.ListSubFileRequest(path=normalize_path(path), forceRefresh=True),
                            wire.SubFilesReply, stream=True)
        entries = []
        for reply in replies:
            for item in reply.subFiles:
                if not item.name or "/" in item.name or "\\" in item.name or item.name in {".", ".."}:
                    raise Cd2Error("CD2 返回了无效文件名")
                entries.append({"name": item.name, "is_dir": item.isDirectory or item.fileType == wire.CloudDriveFile.Directory,
                                "size": item.size, "modified": item.writeTime.ToJsonString() if item.HasField("writeTime") else ""})
                if len(entries) > 100_000:
                    raise Cd2Error("CD2 目录超过单次读取上限，未使用不完整目录")
        return entries

    def list_directory(self, path: str) -> dict:
        return {"data": {"content": self.list_entries(path)}}

    def list_directories(self, path: str) -> list[dict]:
        return [item for item in self.list_entries(path) if item["is_dir"]]

    def mkdir(self, path: str) -> dict:
        path = normalize_path(path)
        result = self._rpc("CreateFolder", wire.CreateFolderRequest(parentPath=str(PurePosixPath(path).parent),
                           folderName=PurePosixPath(path).name), wire.CreateFolderResult)
        if not result.result.success:
            raise Cd2Error("CD2 创建目录失败，请检查目标路径和写入权限")
        return {"ok": True}

    def copy(self, source_dir: str, target_dir: str, names: list[str], *, overwrite: bool = False) -> dict:
        source, target = normalize_path(source_dir), normalize_path(target_dir)
        if not names or any(not n or n in {".", ".."} or "/" in n or "\\" in n or any(ord(c) < 32 for c in n) for n in names):
            raise Cd2Error("CD2 复制只接受选中目录的直接文件名")
        existing = {item["name"] for item in self.list_entries(target)} if not overwrite else set()
        before = self.copy_tasks(done_limit=0)
        pending = [name for name in dict.fromkeys(names) if name not in existing or any(
            task["state"] == "running" for task in self._matching_tasks(before, f"{source.rstrip('/')}/{name}", target)
        )]
        receipts = []
        submit = []
        for name in pending:
            full_source = f"{source.rstrip('/')}/{name}"
            matches = self._matching_tasks(before, full_source, target)
            active = [task for task in matches if task["state"] == "running"]
            if len(active) > 1:
                raise Cd2Error("CD2 同一路径存在多个活动复制任务，请先复核")
            receipts.append({"source": full_source, "target": target,
                             "previous_starts": [] if active else [task["start_time"] for task in matches]})
            if not active:
                submit.append(full_source)
        if self.on_copy_prepared:
            self.on_copy_prepared(target, names, receipts)
        if submit:
            try:
                result = self._rpc("CopyFile", wire.CopyFileRequest(theFilePaths=submit, destPath=target,
                                   conflictPolicy=wire.CopyFileRequest.Overwrite if overwrite else wire.CopyFileRequest.Skip,
                                   handleConflictRecursively=True), wire.FileOperationResult)
            except Cd2Error:
                # A network error may follow a successful remote submission. Never resubmit
                # automatically; let the persisted landing context inspect the exact queue.
                return {"accepted": None, "copy_receipts": receipts}
            if not result.success:
                raise Cd2Error("CD2 未接受复制请求，请检查源文件和目标写入权限")
        return {"accepted": True, "copy_receipts": receipts}

    @staticmethod
    def _matching_tasks(tasks: list[dict], source: str, target: str) -> list[dict]:
        destinations = {target, f"{target.rstrip('/')}/{PurePosixPath(source).name}"}
        return [task for task in tasks if task.get("source_path") == source and task.get("target_path") in destinations]

    def copies_complete(self, receipts: list[dict], *, target_dir: str = "", names: list[str] | None = None) -> bool:
        tasks = self.copy_tasks(done_limit=0) if receipts or target_dir else []
        # An existing directory entry may still belong to an uploading task.
        # This also covers callers that skipped a same-named destination file.
        selected_paths = [f"{target_dir.rstrip('/')}/{name}" for name in names or []]
        for task in tasks:
            if task["state"] != "running":
                continue
            source_name = PurePosixPath(task["source_path"]).name
            destination = task["target_path"].rstrip("/")
            if PurePosixPath(destination).name != source_name:
                destination = f"{destination}/{source_name}"
            if any(path == destination or path.startswith(destination + "/") for path in selected_paths):
                return False
        for receipt in receipts:
            matches = [task for task in self._matching_tasks(tasks, receipt["source"], receipt["target"])
                       if task["start_time"] not in receipt.get("previous_starts", [])]
            if len(matches) > 1:
                raise Cd2Error("CD2 复制记录不唯一，需人工复核")
            if matches and matches[0]["state"] == "failed":
                raise Cd2Error("CD2 复制存在失败或取消项，需人工复核")
            if len(matches) != 1 or matches[0]["state"] != "done":
                return False
        return True

    def copy_tasks(self, *, done_limit: int = 50) -> list[dict]:
        response = self._rpc("GetCopyTasks", Empty(), wire.GetCopyTaskResult)
        tasks = []
        for task in response.copyTasks:
            if task.taskMode != wire.CopyTask.Copy:
                continue
            failed = bool(task.status == wire.CopyTask.Failed or task.failedFiles or task.failedFolders or task.cancelledFiles or task.errors)
            done = task.status == wire.CopyTask.Completed and not failed
            tasks.append({"id": f"{task.sourcePath}:{task.destPath}", "name": f"{task.sourcePath} → {task.destPath}",
                          "state": "failed" if failed else "done" if done else "running",
                          "status": "paused" if task.paused else wire.CopyTask.TaskStatus.Name(task.status),
                          "progress": 100 if done else min(99, task.uploadedBytes * 100 / task.totalBytes) if task.totalBytes else 0,
                          "total_bytes": task.totalBytes, "error": "CD2 复制存在失败或取消项，请在 CD2 查看详情" if failed else "",
                          "start_time": task.startTime.ToJsonString() if task.HasField("startTime") else "",
                          "end_time": task.endTime.ToJsonString() if task.HasField("endTime") else "",
                          "source_path": task.sourcePath, "target_path": task.destPath})
        active = [task for task in tasks if task["state"] == "running"]
        finished = [task for task in tasks if task["state"] != "running"]
        return active + (finished[:done_limit] if done_limit > 0 else finished)

    def clear_finished_copy_tasks(self) -> None:
        self._rpc("RemoveCompletedCopyTasks", Empty(), Empty)

    def test(self, qas_path: str, p115_path: str) -> dict:
        self.list_entries(qas_path)
        self.list_entries(p115_path)
        self.copy_tasks()
        return {"ok": True, "message": "CD2 连接成功，两个媒体库目录和复制任务均可读取"}

    # Reuse the established directory-diff algorithm, dispatching all IO to CD2.
    _items = staticmethod(OpenListClient._items)
    sync_tree = OpenListClient.sync_tree
