#!/usr/bin/env python3
"""
Twitch Chat Translator Bot
-------------------------
A real-time translator bot for Twitch chat. Inspired by kick-chat-translator.py but adapted
for Twitch's IRC-over-WebSocket protocol.

Features:
  • Connects to Twitch IRC via secure WebSocket
  • Detects language of each incoming chat message
  • Translates only if the detected language is in the ALLOWED_LANGUAGES set
  • Posts translated text back to chat (if OAuth token provided) or prints to console
  • Uses *separate* Azure Translator credentials so it won't consume the Kick quota

Environment variables (see env.example):
  TWITCH_OAUTH_TOKEN        – OAuth token with chat:read (+ chat:edit if sending) scope
  TWITCH_BOT_USERNAME       – Twitch login name of your bot (lowercase)
  TWITCH_CHANNEL            – Channel to join (without the #)
  AZURE_TRANSLATOR_KEY          – Azure Translator key for Twitch translations
  AZURE_TRANSLATOR_ENDPOINT     – Endpoint, default https://api.cognitive.microsofttranslator.com
  AZURE_TRANSLATOR_REGION       – Region (e.g. eastus)
  TARGET_LANGUAGE           – Output language for Twitch (default: en)
  MIN_MESSAGE_LENGTH        – Skip very short messages (default: 1)
  RATE_LIMIT_DELAY          – Seconds between translations (0 = unlimited)

Run locally:
  python twitch-chat-translator.py <channel> [oauth_token]
"""

import html
import json
import os
import sys
import threading
import time
import uuid
import re
from typing import Optional

import requests
import websocket
from dotenv import load_dotenv
from langdetect import detect
import unicodedata

load_dotenv()

# ─── CONFIG ──────────────────────────────────────────────────────────────
IRC_URL = "wss://irc-ws.chat.twitch.tv:443"

# Twitch credentials
TWITCH_OAUTH_TOKEN = os.getenv("TWITCH_OAUTH_TOKEN")
TWITCH_BOT_USERNAME = os.getenv("TWITCH_BOT_USERNAME", "").lower()

# Azure (separate) for Twitch
AZURE_TRANSLATOR_KEY = os.getenv("AZURE_TRANSLATOR_KEY")
AZURE_TRANSLATOR_ENDPOINT = os.getenv("AZURE_TRANSLATOR_ENDPOINT", "https://api.cognitive.microsofttranslator.com")
AZURE_TRANSLATOR_REGION = os.getenv("AZURE_TRANSLATOR_REGION")

TARGET_LANGUAGE = os.getenv("TARGET_LANGUAGE", "en")
MIN_MESSAGE_LENGTH = int(os.getenv("MIN_MESSAGE_LENGTH", "2"))
RATE_LIMIT_DELAY = int(os.getenv("RATE_LIMIT_DELAY", "0"))

# Only translate these languages in Twitch chat
ALLOWED_LANGUAGES = {"tr", "ko", "ru", "zh"}

# Add set of common English phrases
COMMON_ENGLISH_PHRASES = {
    'lol', 'gg', 'wp', 'ez', 'kekw', 'pog', 'poggers', 'omegalul', 'lul', 'xd', 'lmao',
    'rofl', 'wtf', 'brb', 'afk', 'hi', 'hello', 'bye', 'thanks', 'thank you', 'ok', 'okay',
    'nice', 'good', 'bad', 'cool', 'great', 'awesome', 'amazing', 'wow', 'yes', 'no',
    'yo', 'sup','hii', 'hiii','bye', 'yes', 'yeah', 'no', 'nah', 'nope',
}

# Add set of known bot usernames
KNOWN_BOT_USERNAMES = {
    'streamelements', 'nightbot', 'moobot', 'wizebot', 'streamlabs', 'fossabot',
}

# ────────────────────────────────────────────────────────────────────────

class TwitchChatTranslator:
    def __init__(self, channel: str, oauth_token: Optional[str]):
        self.channel = channel.lower()
        self.oauth_token = oauth_token  # Without the leading "oauth:" – we add below
        self.last_translation_time = 0

        # HTTP session for Azure
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/json",
        })

    # ─── Language Detection & Translation ────────────────────────────

    def detect_language(self, text: str) -> Optional[str]:
        try:
            clean = text.strip()
            if len(clean) < MIN_MESSAGE_LENGTH:
                return None
            alpha = sum(c.isalpha() for c in clean)
            if alpha < 1:
                return None
            return detect(clean)
        except Exception:
            return None

    def translate_text(self, text: str, source_lang: str) -> Optional[str]:
        if not AZURE_TRANSLATOR_KEY:
            print("⚠️ No Azure Translator key for Twitch – cannot translate.")
            return None

        path = "/translate"
        url = AZURE_TRANSLATOR_ENDPOINT + path
        params = {
            "api-version": "3.0",
            "from": source_lang,
            "to": TARGET_LANGUAGE,
        }
        headers = {
            "Ocp-Apim-Subscription-Key": AZURE_TRANSLATOR_KEY,
            "Ocp-Apim-Subscription-Region": AZURE_TRANSLATOR_REGION,
            "Content-type": "application/json",
            "X-ClientTraceId": str(uuid.uuid4()),
        }
        body = [{"text": text}]

        try:
            resp = self.session.post(url, params=params, headers=headers, json=body, timeout=10)
            resp.raise_for_status()
            res = resp.json()
            if res and len(res) > 0:
                translated = res[0]["translations"][0]["text"]
                return html.unescape(translated)
        except Exception as e:
            print(f"⚠️ Azure error: {e}")
        return None

    # ─── IRC Helpers ─────────────────────────────────────────────────

    def send_raw(self, ws: websocket.WebSocketApp, msg: str):
        ws.send(msg + "\r\n")

    def send_chat(self, ws: websocket.WebSocketApp, message: str):
        if not self.oauth_token:
            print("⚠️ No OAuth – printing translation only: ", message)
            return
        rate_ok = True
        if RATE_LIMIT_DELAY > 0:
            now = time.time()
            if now - self.last_translation_time < RATE_LIMIT_DELAY:
                rate_ok = False
        if rate_ok:
            self.send_raw(ws, f"PRIVMSG #{self.channel} :{message}")
            self.last_translation_time = time.time()
            print(f"✅ Sent: {message}")
        else:
            print("⏳ Rate limited – skipping send")

    # ─── WebSocket Callbacks ─────────────────────────────────────────

    def on_open(self, ws):
        print("🔗 IRC connection opened – authenticating…")
        if self.oauth_token:
            self.send_raw(ws, f"PASS oauth:{self.oauth_token}")
            self.send_raw(ws, f"NICK {TWITCH_BOT_USERNAME or 'justinfan12345'}")
        else:
            # Anonymous login (read-only)
            self.send_raw(ws, "NICK justinfan12345")
        # Request tags for easier parsing (optional)
        self.send_raw(ws, "CAP REQ :twitch.tv/tags")
        self.send_raw(ws, f"JOIN #{self.channel}")
        print(f"✅ Joined #{self.channel}")

    def handle_privmsg(self, ws, prefix: str, tags: str, msg: str):
        # Extract username from prefix
        username = prefix.split("!")[0]
        if TWITCH_BOT_USERNAME and username.lower() == TWITCH_BOT_USERNAME:
            return  # Skip own messages

        # Skip messages from known bots
        if username.lower() in KNOWN_BOT_USERNAMES:
            print(f"   ⏭️ Skipped: Message from known bot '{username}'")
            print()
            return

        print(f"👤 {username}: {msg}")

        # Skip messages that start with '!'
        if msg.strip().startswith("!"):
            print("   ⏭️ Skipped: Message starts with '!' (likely a command)")
            print()
            return

        # Skip messages that only contain one or more Kick emotes [emote:id:name] (with optional whitespace)
        emote_pattern = r'^(\s*\[emote:\d+:[^\]]+\]\s*)+$'
        if re.fullmatch(emote_pattern, msg.strip()):
            print("   ⏭️ Skipped: Message contains only emote(s)")
            print()
            return

        # Skip if message is only common English phrases
        if is_mostly_common_english(msg):
            print("   ⏭️ Skipped: Message is only common English phrases")
            print()
            return

        clean = msg.strip()
        if len(clean) < MIN_MESSAGE_LENGTH:
            print(f"   ⏭️ Skipped: Too short (length {len(clean)} < {MIN_MESSAGE_LENGTH})")
            print()
            return
        alpha = sum(c.isalpha() for c in clean)
        if alpha < 1:
            print(f"   ⏭️ Skipped: Not enough letters (alpha count {alpha})")
            print()
            return
        try:
            detected = detect(clean)
        except Exception:
            print("   ⏭️ Skipped: Language detection failed")
            print()
            return
        # Allow base language match (e.g., zh, zh-cn, zh-tw)
        if not any(detected == lang or detected.startswith(f"{lang}-") for lang in ALLOWED_LANGUAGES):
            print(f"   ⏭️ Skipped: Language '{detected}' not in allowed list {ALLOWED_LANGUAGES}")
            print()
            return

        translated = self.translate_text(msg, detected)
        if not translated:
            print("   ⏭️ Skipped: Translation failed or not available")
            print()
            return

        # Skip if translation is redundant
        if is_redundant_translation(msg, translated):
            print("   ⏭️ Skipped: Translation is redundant (same as original)")
            print()
            return

        # Format translation message as plain text (no /me)
        translation = f"[by {username}] {translated} ({detected} > {TARGET_LANGUAGE})"
        print(f"➡️  {translation}")
        self.send_chat(ws, translation)
        print()  # Add a blank line for readability between messages

    def on_message(self, ws, raw):
        # Twitch may send multiple IRC messages in one frame
        for line in raw.split("\r\n"):
            if not line:
                continue
            if line.startswith("PING"):
                self.send_raw(ws, "PONG :tmi.twitch.tv")
                continue
            # Parse IRC message: [@tags ]:prefix command #channel :message
            tags = ""
            rest = line
            if line.startswith("@"):  # tags present
                tags, rest = line.split(" ", 1)
            if rest.startswith(":"):
                prefix, rest = rest[1:].split(" ", 1)
            else:
                prefix = ""
            if " :" in rest:
                command, msg = rest.split(" :", 1)
            else:
                command, msg = rest, ""
            command_parts = command.split()
            if len(command_parts) >= 1 and command_parts[0] == "PRIVMSG":
                self.handle_privmsg(ws, prefix, tags, msg)

    def on_error(self, ws, err):
        print("⚠️ WebSocket error:", err)

    def on_close(self, ws, code, reason):
        print(f"🔌 Connection closed: {code} {reason}")
        if code != 1000:
            print("Reconnecting in 5 seconds…")
            time.sleep(5)
            self.start()

    # ─── Main Loop ───────────────────────────────────────────────────

    def start(self):
        print(f"🤖 Twitch Chat Translator for #{self.channel}")
        if not AZURE_TRANSLATOR_KEY:
            print("⚠️ Missing Azure credentials – will not translate.")
        ws = websocket.WebSocketApp(
            IRC_URL,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
        )
        ws.run_forever()

# ─── Entry Point ─────────────────────────────────────────────────────

def main():
    channel = os.getenv("TWITCH_CHANNEL")
    if not channel and len(sys.argv) >= 2:
        channel = sys.argv[1]
    if not channel:
        print("Usage: python twitch-chat-translator.py <channel> [oauth_token]")
        sys.exit(1)

    oauth = None
    if len(sys.argv) >= 3:
        oauth = sys.argv[2]
    elif TWITCH_OAUTH_TOKEN:
        oauth = TWITCH_OAUTH_TOKEN

    if oauth:
        print("🗝️  OAuth token provided – translations will be posted to chat.")
    else:
        print("👀 No OAuth token – read-only mode.")

    translator = TwitchChatTranslator(channel, oauth)
    translator.start()

def is_mostly_common_english(msg: str) -> bool:
    # Remove punctuation, lowercase, split into words
    words = re.findall(r"\b\w+\b", msg.lower())
    if not words:
        return False
    # Count how many words are in the common set
    common_count = sum(word in COMMON_ENGLISH_PHRASES for word in words)
    # If all or all but one are common, skip
    return common_count >= len(words) - 0

def is_redundant_translation(original: str, translated: str) -> bool:
    def normalize(s):
        s = s.strip().lower()
        s = unicodedata.normalize('NFKD', s)
        s = ''.join(c for c in s if not unicodedata.combining(c))
        return s
    return normalize(original) == normalize(translated)

if __name__ == "__main__":
    main() 