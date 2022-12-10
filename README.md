# Discord Autodelete 🎇

Discord Autodelete is a [Discord](https://discord.com/) bot to configure channels that automatically delete messages after a custom delay,
written in Python using
[discord.py](https://github.com/Rapptz/discord.py) and [aiosqlite](https://github.com/omnilib/aiosqlite).


## Features

This bot comes with three [slash commands](https://support.discord.com/hc/en-us/articles/1500000368501-Slash-Commands-FAQ):

```
/autodelete enable <channel> <duration>   : Configure a channel for message autodeletion.
/autodelete disable <channnel>            : Turn off message autodeletion for a channel.
/autodelete list                          : List channels with autodeletion enabled.
```


### Channel Setup: `/autodelete enable <channel> <duration>`

`/autodelete enable` can both initially set up a channel with autodeletion semantics,
and modify previously configured channels. Once autodeletion is enabled in a channel,
any *new* messages will be deleted on a rolling basis with a delay of `duration` after they were sent.

> **NOTE:** Messages already in the channel will **not** be deleted.

Duration parsing is provided by the [pytimeparse](https://github.com/wroberts/pytimeparse) library and handles
many intuitive time specifications written in natural language (in English). For instance:

```
/autodelete enable channel: #general duration: 1 day
/autodelete enable channel: #general duration: 20 minutes
/autodelete enable channel: #general duration: 1h, 20m
/autodelete enable channel: #general duration: 01:20:30
/autodelete enable channel: #general duration: 10s
/autodelete enable channel: #general duration: 2.5 weeks
/autodelete enable channel: #general duration: 52 weeks
```

Good-to-knows:

- There is no (reasonable) limit to duration, though ambiguous units of time such as "months" or "years"
cannot be specified directly. Try counting by days instead for very long periods of time.
- The bot handles long durations effectively by storing new messages and their scheduled deletion time in a persistent
[SQLite](https://www.sqlite.org/index.html) database, and incrementally updating it during execution and at startup,
based on the bot's last known state.
- Disabling autodelete in a channel cancels all pending deletions.
- Modifying the autodelete timer also cancels deletions, as anything prior to the modification is considered
"before the channel was configured," and those messages are never touched.


## Bot Setup

Discord Autodelete is built for Python 3.9 or later, and is tested on CPython 3.9, CPython 3.11, and PyPy 3.9.

As there is no public bot instance, to host your own instance of the bot:

1. [Install Python](https://www.python.org/downloads/) if you don't already have it.
2. Run `git clone https://github.com/Eta0/DiscordAutoDelete` if you have `git` installed, or download and unzip the
   [zipped repository](http://github.com/Eta0/DiscordAutoDelete/zipball/master/) through a web browser.
3. Open that directory.
4. Register an application through [Discord's developer portal](https://discord.com/developers).
   1. Find your *Application ID* on the "General Information" page,
   2. Find your *Token* on the "Bot" page (you may need to press "Reset Token" to view it), 
   3. Open the file named `.env` and paste the *Token* onto the end of the first line, after `API_TOKEN=`
   4. In the same file, paste the *Application ID* onto the end of the second line, after `APPLICATION_ID=`.
      No quotation marks are needed around either.
   5. Join the bot to your server(s) of choice by navigating to the "OAuth2 / URL Generator" page,
      checking `bot`, and in the "Bot Permissions" matrix checking `Read Messages/View Channels`, `Read Message History`,
      and `Manage Messages`, and then navigating to the generated URL.
   6. (Optional) Uncheck "Public Bot" on the "Bot" page if you want to be the only one who can use the link generated in step 5.
5. In a terminal opened to the bot installation directory, run `python -m pip install -e .`.
6. Launch the bot by running `python -m discord_autodelete` or simply `discord-autodelete` (note the dash on the second one).

Run `python -m discord_autodelete --help` for more information about launch options. Notably:
> **IMPORTANT:** You need to launch the bot at least once with the `--sync` flag (`python -m discord_autodelete --sync`)
> for commands to appear in your server(s).

*Bonus:* Replace the installation command with `python -m pip install -e .[speed]` for more efficiency, with extra dependencies.


## License

Discord Autodelete is free and open-source software provided under the [zlib license](https://opensource.org/licenses/Zlib).

- This project is not affiliated with Discord Inc.