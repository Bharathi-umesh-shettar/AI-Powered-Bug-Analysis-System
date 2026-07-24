# Auto-Watch Folder

Drop any `.log` or `.txt` file into this folder while the app is running.

The Folder Watcher (backend/watcher.py) will:
1. Detect the new file within a few seconds
2. Read its contents
3. Run the Triage + Log Analysis agents
4. Save the bug and analysis in the database
5. Update the dashboard automatically

You can also trigger a manual scan from the "Auto-Watch" section of the UI
or via `POST /watcher/scan`.
