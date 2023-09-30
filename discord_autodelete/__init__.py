import dotenv

import os
import sys
import asyncio
import argparse

from .AutoDeleteBot import AutoDeleteBot
from .commands import AutoDeleteChannelControl


async def async_main():
    parser = argparse.ArgumentParser(
        description="Discord bot for expiring messages with per-channel custom time limits."
    )
    parser.add_argument(
        "-s",
        "--sync",
        dest="sync",
        action="store_true",
        help="update all commands with Discord. Use this after changing the source code or updating the bot.",
    )
    parser.add_argument(
        "-d",
        "--database",
        dest="database",
        help=(
            'path for the bot\'s working database. Defaults to "autodelete.sqlite", or the environment variable'
            ' "AUTODELETE_DATABASE_PATH", if set.'
        ),
    )
    parser.add_argument(
        "-l",
        "--log",
        dest="log",
        help=(
            'path for bot\'s runtime log file. Defaults to "autodelete.log", or the environment variable'
            ' "AUTODELETE_LOG_PATH", if set.'
        ),
    )
    parser.add_argument(
        "-e",
        "--env",
        dest="env",
        help=(
            "path for bot's environment variable config file. "
            'Defaults to the first ".env" file in the installation directory or any of its parent directories.'
        ),
    )
    parser.add_argument(
        "-c",
        "--cwd-env",
        dest="cwd_env",
        action="store_true",
        help=(
            'when --env is not provided, search for ".env" files starting from the current working directory,'
            " rather than the installation directory."
        ),
    )
    parser.add_argument(
        "-t",
        "--token",
        dest="token",
        help='the bot\'s API token, if not provided in a ".env" file in the installation directory.',
    )
    parser.add_argument(
        "-a",
        "--application-id",
        dest="application_id",
        help='the bot\'s application ID, if not provided in a ".env" file in the installation directory.',
    )
    parser.add_argument(
        "--protect-pins",
        action="store_true",
        help=argparse.SUPPRESS  # Experimental and thus undocumented
        # help="if set, pinned messages are excluded from deletion. Incurs a performance penalty."
    )
    args = parser.parse_args()

    if not (args.token and args.application_id and args.database and args.log):
        dotenv_path = args.env or dotenv.find_dotenv(usecwd=args.cwd_env)
        dotenv.load_dotenv(dotenv_path)
    if args.token:
        os.putenv("API_TOKEN", args.token)
    if args.application_id:
        os.putenv("APPLICATION_ID", args.application_id)
    if not args.database:
        args.database = os.getenv("AUTODELETE_DATABASE_PATH", "autodelete.sqlite")
    if not args.log:
        args.log = os.getenv("AUTODELETE_LOG_PATH", "autodelete.log")

    if not (os.getenv("API_TOKEN") and os.getenv("APPLICATION_ID")):
        print(
            (
                "ERROR: The bot has not been properly configured. Please set the API_TOKEN and APPLICATION_ID "
                'in the file named ".env" in the bot\'s installation directory '
                "according to the instructions in the README, or use the equivalent command line options "
                "described in the --help text."
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        # noinspection PyPackageRequirements,PyUnresolvedReferences
        import uvloop

        uvloop.install()
    except ImportError:
        pass

    bot = AutoDeleteBot(
        sync_commands=args.sync, db_path=args.database, log_path=args.log, protect_pins=args.protect_pins
    )
    bot.tree.add_command(AutoDeleteChannelControl())
    async with bot:
        await bot.start(os.getenv("API_TOKEN"))


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
