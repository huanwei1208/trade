from __future__ import annotations

import argparse

from trade_py.infra.settings import default_data_root


def make_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data-root", default=str(default_data_root()))

    parser = argparse.ArgumentParser(
        prog="trade backup",
        description="TradeDB 备份与恢复",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", description="创建本地 data_root 快照", parents=[common])
    p_create.add_argument("--label", default="")

    p_push = sub.add_parser("push", description="将快照推送到远端备份驱动", parents=[common])
    p_push.add_argument("--snapshot-id", default=None)

    p_restore = sub.add_parser("restore", description="恢复快照到目标目录", parents=[common])
    p_restore.add_argument("snapshot_id")
    p_restore.add_argument("--target-root", default=None)

    p_list = sub.add_parser("list", description="列出最近备份", parents=[common])
    p_list.add_argument("--limit", type=int, default=20)

    sub.add_parser("doctor", description="检查远端备份驱动配置", parents=[common])
    return parser


def main(argv: list[str] | None = None) -> int:
    from trade_py.backup import (
        backup_doctor,
        create_backup_snapshot,
        list_backup_snapshots,
        push_backup_snapshot,
        restore_backup_snapshot,
    )

    args = make_parser().parse_args(argv or [])

    if args.command == "create":
        result = create_backup_snapshot(args.data_root, label=args.label)
        print(
            f"snapshot={result['snapshot_id']} files={result['file_count']} "
            f"size={result['size_bytes']} archive={result['archive_path']}"
        )
        return 0

    if args.command == "push":
        result = push_backup_snapshot(args.data_root, snapshot_id=args.snapshot_id)
        print(
            f"snapshot={result['snapshot_id']} remote_archive={result['remote_archive_path']} "
            f"remote_manifest={result['remote_manifest_path']}"
        )
        return 0

    if args.command == "restore":
        result = restore_backup_snapshot(
            args.data_root,
            snapshot_id=args.snapshot_id,
            target_root=args.target_root,
        )
        print(
            f"snapshot={result['snapshot_id']} restored_to={result['target_root']} "
            f"archive={result['archive_path']}"
        )
        return 0

    if args.command == "list":
        rows = list_backup_snapshots(args.data_root, limit=args.limit)
        if not rows:
            print("无备份")
            return 0
        for row in rows:
            print(
                f"{row.get('snapshot_id')}  {row.get('status'):<8}  "
                f"{row.get('size_bytes', 0):>10}  {row.get('created_at')}  "
                f"{row.get('driver') or 'local'}"
            )
        return 0

    if args.command == "doctor":
        result = backup_doctor(args.data_root)
        print(
            f"backend={result['backend']} enabled={result['enabled']} "
            f"gdrive_available={result['google_drive_available']} "
            f"folder_id={result['google_drive_folder_id'] or '-'} key_file={result['google_drive_key_file'] or '-'}"
        )
        return 0

    return 1
