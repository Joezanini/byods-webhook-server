"""Generate missing gRPC stubs for webex-byova media if not packaged."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import webex_byova


def main() -> int:
    pkg_root = Path(webex_byova.__file__).resolve().parent
    proto_dir = pkg_root / "media" / "_internal" / "proto"
    out_dir = pkg_root / "media" / "_internal" / "generated"

    if (out_dir / "voicevirtualagent_pb2.py").exists():
        print("SDK media protos already present")
        return 0

    if not proto_dir.exists():
        print(f"Proto directory not found: {proto_dir}", file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "__init__.py").touch()

    cmd = [
        sys.executable,
        "-m",
        "grpc_tools.protoc",
        f"-I{proto_dir}",
        f"--python_out={out_dir}",
        f"--grpc_python_out={out_dir}",
        str(proto_dir / "byova_common.proto"),
        str(proto_dir / "voicevirtualagent.proto"),
    ]
    print("Generating SDK media protobuf stubs...")
    subprocess.run(cmd, check=True)

    # Fix relative imports in generated modules
    pb2_file = out_dir / "voicevirtualagent_pb2.py"
    if pb2_file.exists():
        text = pb2_file.read_text(encoding="utf-8")
        text = text.replace(
            "import byova_common_pb2 as byova__common__pb2",
            "from webex_byova.media._internal.generated import byova_common_pb2 as byova__common__pb2",
        )
        pb2_file.write_text(text, encoding="utf-8")

    grpc_file = out_dir / "voicevirtualagent_pb2_grpc.py"
    if grpc_file.exists():
        text = grpc_file.read_text(encoding="utf-8")
        text = text.replace(
            "import byova_common_pb2 as byova__common__pb2",
            "from webex_byova.media._internal.generated import byova_common_pb2 as byova__common__pb2",
        )
        text = text.replace(
            "import voicevirtualagent_pb2 as voicevirtualagent__pb2",
            "from webex_byova.media._internal.generated import voicevirtualagent_pb2 as voicevirtualagent__pb2",
        )
        grpc_file.write_text(text, encoding="utf-8")

    print(f"Generated stubs in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
