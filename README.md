# Plex Rating Sync

Plex-Rating-Sync is a Python script that synchronizes ratings between Plex and your music files' tags (MP3 and FLAC). It supports two-way synchronization with configurable conflict resolution, ensuring your music library stays consistently rated across different platforms.

If you found this script useful, you can [![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-☕-yellow.svg)](https://www.buymeacoffee.com/Mythic82)

## How It Works

1. **Connection**: The script connects to your Plex server using the provided URL and token.

2. **Library Scanning**: It fetches every track in your Plex music library in a single paginated request (fast, even on large libraries).

3. **File Matching**: For each track, it matches the Plex entry with the corresponding file on your local system using file paths.

4. **Rating Comparison**: The script compares the Plex rating with the rating stored in the file's tag.

5. **Synchronization**:
   - If Plex has a rating and the file doesn't, it updates the file tag.
   - If the file has a rating and Plex doesn't, it updates Plex.
   - If both have ratings but they differ, the winner is decided by the `CONFLICT_WINNER` setting (Plex wins by default). Every conflict is logged with both ratings and which side won, so nothing is overwritten silently.

6. **Verification**: After each file update, it re-reads the file to verify the change was applied successfully.

7. **Logging**: All actions and errors are logged to the console, and optionally to a log file.

## Supported Formats and Rating Conventions

- **MP3**: ratings are stored in a POPM frame with a blank email, using the common Windows / MediaMonkey byte convention (1 = 1 star … 255 = 5 stars). Plex 0.5-star ratings are stored as 1 star, the lowest step POPM supports.
- **FLAC**: ratings are stored in the `RATING` tag on a 0–5 scale with half-star precision. Tags written by other programs on a 0–100 scale (Winamp / foobar2000 style) are detected automatically and converted.
- Other file types are skipped and reported per extension in the summary.

## Requirements

- Python 3.6 or higher
- `plexapi` library
- `mutagen` library
- Access to your Plex server and the ability to read/write to your music files

## Suggested Usage

It's recommended to run this script periodically (e.g., weekly or monthly) to ensure your music file tags always reflect your Plex ratings. This practice is beneficial if you ever decide to use a different media player or music management software, as your ratings will be stored directly in the music files.

You could set up a cron job (on Linux/Mac) or a scheduled task (on Windows) to run the script automatically at your preferred interval.

## User-Settable Variables

At the beginning of the script, you'll find several variables you can adjust:

- `PLEX_URL`: The URL of your Plex server (e.g., 'http://192.168.1.100:32400')
- `PLEX_TOKEN`: Your Plex authentication token
- `PLEX_MUSIC_LIBRARY_NAME`: The name of your music library in Plex
- `LOG_LEVEL`: The desired logging level (e.g., 'INFO', 'DEBUG', 'ERROR')
- `LOG_FILE`: Optional log file path. Everything printed to the console is also written here with timestamps. Set to `None` to disable file logging.
- `TEST_MODE`: Set to True to run the script without making any changes (dry run)
- `CONFLICT_WINNER`: What to do when Plex **and** the file both have a rating but they differ:
  - `'plex'` — the Plex rating wins and is written to the file (default)
  - `'file'` — the file rating wins and is written to Plex
  - `'newest'` — whichever side changed most recently wins. Compares Plex's `lastRatedAt` timestamp against the file's modification time. **Caveat:** a file's modification time updates when *any* tag is edited, not just the rating, so a recently retagged file can win a conflict even if its rating is old. If Plex has no `lastRatedAt` timestamp, the script falls back to `'plex'` and logs it.
- `PLEX_PATH_PREFIX`: The path prefix for your music files on the Plex server
- `HOST_PATH_PREFIX`: The corresponding path prefix on your local system

Make sure to set these variables correctly before running the script.

## Running the Script

1. Clone this repository or download the script.
2. Install the required libraries: `pip install plexapi mutagen`
3. Set the user variables at the top of the script.
4. Run the script: `python Syncplexrating.py`

Remember to run in test mode first and review the logs before making any changes to your library! Test mode prints exactly what would change, including every conflict and how it would be resolved.
