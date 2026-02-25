# Milestone Intent Brief v1: Ship Daily major news summary

## Target User

User who needs to get news for a specific topic in a Telegram channel.

## Problem

Users have to proactively check news, which takes time.

## Success Signal

The application fetches news updates every 15 minutes, checks to exclude duplication, and provides a summary as a new message in a Telegram channel with a link to the related most trusted source.

## Constraints

- Runtime: GitHub Actions scheduled workflows.
- Storage for state: GitHub Release assets (not committed to repo).
- Secrets: GitHub Secrets only.
- Sources: RSS feeds only.
- Output channel: Telegram.
- Dedup: Avoid repost within 24 hours using a stable key.

## In Scope

- Fetching news from RSS feeds.
- Deduplicating news items.
- Summarizing news content.
- Posting summaries to a Telegram channel.
- Including a link to the most trusted source for each news item.
- Scheduling the process to run every 15 minutes.

## Out of Scope

- User authentication or profile management.
- Multiple Telegram channels or topics per user.
- Advanced natural language processing for summary generation beyond basic extraction.
- Real-time news delivery.
- Support for sources other than RSS feeds.
- Direct user interaction within the Telegram bot.