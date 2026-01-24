"""
Audio bridge between Twilio and Discord via Node.js WebSocket.

This module manages bidirectional audio flow:
- Discord → Twilio: Receives PCM from Node.js, converts to mulaw, sends to Twilio
- Twilio → Discord: Receives mulaw from Twilio, converts to PCM, sends to Node.js

Audio format conversions:
- Discord/Node.js: PCM s16le, 48kHz, mono
- Twilio: mulaw, 8kHz, mono
"""

import asyncio
import logging
import base64
import audioop
import websockets
from typing import Optional

from config import get_config

# --- Queues for audio flow ---
# Discord → Twilio direction
discord_to_twilio_queue: asyncio.Queue = asyncio.Queue()

# Twilio → Discord direction  
twilio_to_discord_queue: asyncio.Queue = asyncio.Queue()

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)

# --- WebSocket connection to Node.js ---
node_ws_connection: Optional[websockets.WebSocketClientProtocol] = None


async def connect_to_node():
    """
    Connect to Node.js Discord bot WebSocket server.
    Maintains connection and handles reconnection.
    """
    global node_ws_connection
    config = get_config()
    uri = config.network.node_ws_url
    
    while True:
        try:
            logger.info(f"Connecting to Node.js at {uri}")
            async with websockets.connect(uri) as ws:
                node_ws_connection = ws
                logger.info("✅ Connected to Node.js Discord audio server")
                
                # Listen for audio from Discord (Discord → Twilio direction)
                async for message in ws:
                    if isinstance(message, bytes):
                        # Received PCM audio from Discord
                        await discord_to_twilio_queue.put(message)
                        logger.debug(f"📥 Received {len(message)} bytes from Discord")
                    
        except websockets.exceptions.WebSocketException as e:
            logger.error(f"⚠️ Node.js WebSocket error: {e}")
            node_ws_connection = None
        except Exception as e:
            logger.error(f"⚠️ Unexpected error in Node.js connection: {e}")
            node_ws_connection = None
        
        # Wait before reconnecting
        logger.info("Reconnecting to Node.js in 5 seconds...")
        await asyncio.sleep(5)


async def send_to_discord(pcm_data: bytes):
    """
    Send PCM audio to Discord via Node.js WebSocket.
    
    Args:
        pcm_data: PCM s16le audio data at 48kHz mono
    """
    global node_ws_connection
    
    if node_ws_connection:
        try:
            await node_ws_connection.send(pcm_data)
            logger.debug(f"📤 Sent {len(pcm_data)} bytes to Discord")
        except Exception as e:
            logger.error(f"⚠️ Error sending to Discord: {e}")
    else:
        logger.warning("⚠️ Node.js WebSocket not connected, cannot send to Discord")


# --- Audio conversion functions ---

def mulaw_to_pcm(mulaw_data: bytes) -> bytes:
    """
    Convert mulaw (8kHz) to PCM s16le (48kHz, stereo) for Discord.
    
    Twilio sends mulaw at 8kHz mono, Discord expects PCM at 48kHz stereo.
    """
    # Convert mulaw to linear PCM (mono)
    pcm_8k_mono = audioop.ulaw2lin(mulaw_data, 2)  # 2 bytes per sample (s16le)
    
    # Upsample from 8kHz to 48kHz (6x) - still mono
    pcm_48k_mono = audioop.ratecv(pcm_8k_mono, 2, 1, 8000, 48000, None)[0]
    
    # Convert mono to stereo by duplicating the channel
    pcm_48k_stereo = audioop.tostereo(pcm_48k_mono, 2, 1, 1)
    
    return pcm_48k_stereo


def pcm_to_mulaw(pcm_data: bytes) -> bytes:
    """
    Convert PCM s16le (48kHz, stereo) to mulaw (8kHz, mono) for Twilio.
    
    Discord sends PCM at 48kHz stereo, Twilio expects mulaw at 8kHz mono.
    """
    # Convert stereo to mono by averaging both channels
    pcm_48k_mono = audioop.tomono(pcm_data, 2, 0.5, 0.5)
    
    # Downsample from 48kHz to 8kHz (1/6)
    pcm_8k_mono = audioop.ratecv(pcm_48k_mono, 2, 1, 48000, 8000, None)[0]
    
    # Convert linear PCM to mulaw
    mulaw = audioop.lin2ulaw(pcm_8k_mono, 2)
    
    return mulaw


# --- Twilio WebSocket handlers ---

async def twilio_sender(ws):
    """
    Send audio from Discord to Twilio WebSocket.
    
    This handles the Discord → Twilio direction.
    
    Args:
        ws: Twilio WebSocket connection (aiohttp WebSocketResponse)
    """
    logger.info("📢 Twilio sender started")
    
    try:
        while True:
            # Get PCM audio from Discord
            pcm_data = await discord_to_twilio_queue.get()
            
            if pcm_data is None:
                # Shutdown signal
                logger.info("📢 Twilio sender received shutdown signal")
                break
            
            # Convert PCM (48kHz) to mulaw (8kHz)
            mulaw_data = pcm_to_mulaw(pcm_data)
            
            # Encode as base64
            payload_b64 = base64.b64encode(mulaw_data).decode('utf-8')
            
            # Send to Twilio
            await ws.send_json({
                "event": "media",
                "streamSid": getattr(ws, 'stream_sid', None),
                "media": {
                    "payload": payload_b64
                }
            })
            
            logger.debug(f"🔊 Sent {len(mulaw_data)} bytes to Twilio")
            
    except asyncio.CancelledError:
        logger.info("📢 Twilio sender cancelled")
    except Exception as e:
        logger.error(f"⚠️ Error in Twilio sender: {e}")
    finally:
        logger.info("📢 Twilio sender stopped")


# --- Bridge lifecycle ---

async def start_bridge():
    """
    Start the bridge components.
    
    This should be called when the application starts.
    """
    logger.info("🌉 Starting audio bridge...")
    
    # Start Node.js connection in background
    asyncio.create_task(connect_to_node())
    
    logger.info("✅ Audio bridge started")


async def stop_bridge():
    """
    Stop the bridge and cleanup.
    
    This should be called when the application shuts down.
    """
    logger.info("🌉 Stopping audio bridge...")
    
    # Signal shutdown to sender
    await discord_to_twilio_queue.put(None)
    
    # Close Node.js connection
    global node_ws_connection
    if node_ws_connection:
        await node_ws_connection.close()
        node_ws_connection = None
    
    logger.info("✅ Audio bridge stopped")