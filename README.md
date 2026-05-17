# GitHub Downloader

A simple GitHub Actions downloader project for direct links, Telegram, YouTube, and web browsing capture.

## Setup

1. Copy `.env.example` to `.env`
2. Fill in `GITHUB_TOKEN`, `GITHUB_OWNER`, and `GITHUB_REPO`
3. Run `python main.py`

## Usage

- Start workflows from the menu
- A logs terminal will open if available
- List downloaded folders and download them directly from raw links

## Workflow files

- `.github/workflows/download.yaml`
- `.github/workflows/youtube.yaml`
- `.github/workflows/telegram.yaml`
- `.github/workflows/browse.yaml`
- `.github/workflows/clean.yaml`
- `.github/workflows/sort.yaml`
- `.github/workflows/cancel.yaml`
