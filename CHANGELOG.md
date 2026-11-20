# Changelog

## 1.0.0 (2026-11-20)

First public version.

- Read-only commands: `search`, `thread`, `link`, `history`, `file`.
- One-step `install.sh` (computes the extension ID from its folder, installs the command in `~/.local/bin`).
- `install`, `uninstall` and `doctor` for the Native Messaging bridge (Chrome, Chrome Beta, Chromium, Brave, Edge on macOS).
- User IDs replaced with names in authors and mentions, with a local name cache.
- File download through the Slack tab, with text extraction for PDFs (`pdftotext`) and text files.
- Two Claude Code skills: `slack-search` and `slack-thread`.
