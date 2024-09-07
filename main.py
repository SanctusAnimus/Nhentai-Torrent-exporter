import argparse

from dotenv import load_dotenv

from export_fav_ids import export_fav_ids, download_from_index_file

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Exports your favourites via QBitTorrent"
    )

    parser.add_argument("--config", default="config.env", help="ENV source, defaults to config.env",
                        type=str)
    parser.add_argument("-w", "--open_window", action="store_true",
                        help="Will try to open new Chrome window with debug port automatically")

    subparsers = parser.add_subparsers(dest='command', help="Available commands")

    # Subcommand for 'export'
    export_parser = subparsers.add_parser('export', help="Export favourites into index, then download via torrent")
    export_parser.add_argument(
        '-st', "--skip_torrent", action="store_true",
        help="Skip torrent download, stopping once indexing is finished"
    )

    # Subcommand for 'download_indexed'
    download_parser = subparsers.add_parser(
        'download_indexed',
        help="Download all index entries (skipping favourite index)"
    )
    download_parser.add_argument(
        '--index-file',
        default='fav_by_author.txt',
        help="Optional index file name (defaults to fav_by_author.txt)"
    )

    args = parser.parse_args()

    load_dotenv(dotenv_path=args.config)

    if args.command == "export":
        export_fav_ids(args.open_window, args.skip_torrent)
    elif args.command == "download_indexed":
        download_from_index_file(args.index_file)
    else:
        parser.print_help()
