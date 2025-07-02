# TwitchAITranslatorBot

A real-time Twitch chat translator bot that connects to Twitch IRC, detects the language of incoming chat messages, translates them (using Azure Translator), and posts the translation back to chat or prints it to the console.

## Features
- Connects to Twitch IRC via secure WebSocket
- Detects language of each incoming chat message
- Translates only if the detected language is in the allowed set
- Posts translated text back to chat (if OAuth token provided) or prints to console
- Uses Azure Translator API

## Requirements
- Python 3.7+
- Twitch account and OAuth token
- Azure Translator credentials

## Setup
1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/TwitchAITranslatorBot.git
   cd TwitchAITranslatorBot
   ```
2. Create and activate a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Copy `.env.example` to `.env` and fill in your credentials:
   ```bash
   cp .env.example .env
   # Edit .env with your values
   ```

## Usage
Run the bot with:
```bash
python twitch-chat-translator.py
```
Or specify the channel and OAuth token as arguments:
```bash
python twitch-chat-translator.py <channel> [oauth_token]
```

## Environment Variables
See `.env.example` for all required and optional environment variables.

## Contributing
Pull requests are welcome! For major changes, please open an issue first to discuss what you would like to change.

## License
MIT 