# GOGLibrary

A Steam-like desktop client for a GOG.com library — browse your collection,
download/install, and launch games, without the command line.

Starting point: `gogrepo_gui.py`, a customtkinter desktop app built earlier
against `gogrepoc_backend.py` (a GUI-only fork of the
[gogrepo](https://github.com/Revan67/gogrepo) CLI engine's `update`/
`download`/`verify` commands). Being reworked from here into an actual
library-management UI rather than a thin GUI wrapper around the CLI's
options.

An earlier attempt at this same idea (a different UI approach, SQLite-backed,
its own downloader/installer) lives at
`C:\Dev\GOGLibrary-old-2026-07-31` for reference -- not carried forward.
