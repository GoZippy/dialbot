"""
Twilio WebSocket server for PSAP voice bridge.

This server:
1. Receives incoming calls via /voice webhook
2. Establishes WebSocket connection with Twilio for audio streaming
3. Bridges audio between Twilio and Discord via the bridge module
"""

from aiohttp import web
import logging
import asyncio

from twilio.twiml.voice_response import VoiceResponse, Connect

from config import get_config
import bridge

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)


async def voice_webhook_handler(request):
    """
    Handle incoming calls from Twilio.
    
    Returns TwiML that connects the call to our WebSocket endpoint.
    """
    logger.info("📞 Received incoming call on /voice webhook")
    
    config = get_config()
    
    # Generate TwiML response
    response = VoiceResponse()
    connect = Connect()
    
    # Tell Twilio to connect to our WebSocket for bidirectional audio
    # Use "inbound_track" to receive caller's audio
    connect.stream(url=config.network.public_wss_url, track="inbound_track")
    response.append(connect)
    
    twiml = response.to_xml()
    logger.info(f"📋 Generated TwiML:\n{twiml}")
    
    return web.Response(text=twiml, content_type="application/xml")


async def websocket_handler(request):
    """
    Handle WebSocket connection from Twilio for audio streaming.
    
    This manages bidirectional audio flow:
    - Receives audio from Twilio (caller speaking)
    - Sends audio to Twilio (Discord users speaking)
    """
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    
    logger.info("🔌 Twilio WebSocket connected")
    
    # Store stream SID when we receive it
    ws.stream_sid = None
    
    # Start sender task (Discord → Twilio)
    sender_task = asyncio.create_task(bridge.twilio_sender(ws))
    
    try:
        # Receive messages from Twilio (Twilio → Discord)
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                import json
                data = json.loads(msg.data)
                event_type = data.get("event")
                
                if event_type == "start":
                    ws.stream_sid = data.get("streamSid")
                    logger.info(f"📞 Twilio stream started - SID: {ws.stream_sid}")
                    
                elif event_type == "media":
                    # Extract and queue audio for Discord
                    payload_b64 = data["media"]["payload"]
                    import base64
                    mulaw_data = base64.b64decode(payload_b64)
                    
                    # Convert mulaw to PCM and send to Discord
                    pcm_data = bridge.mulaw_to_pcm(mulaw_data)
                    await bridge.send_to_discord(pcm_data)
                    
                    logger.debug(f"🔊 Received {len(mulaw_data)} bytes from Twilio")
                    
                elif event_type == "stop":
                    logger.info("📞 Twilio stream stopped")
                    break
                    
            elif msg.type == web.WSMsgType.ERROR:
                logger.error(f"⚠️ WebSocket error: {ws.exception()}")
                break
                
    except Exception as e:
        logger.error(f"⚠️ Error in WebSocket handler: {e}")
        
    finally:
        logger.info("🔌 Closing Twilio WebSocket")
        
        # Cancel sender task
        sender_task.cancel()
        try:
            await sender_task
        except asyncio.CancelledError:
            pass
        
        await ws.close()
    
    return ws


async def status_handler(request):
    """Health check endpoint."""
    config = get_config()
    
    status = {
        "status": "ok",
        "service": "PSAP Voice Bridge",
        "node_ws_connected": bridge.node_ws_connection is not None and not bridge.node_ws_connection.closed,
        "node_ws_url": config.network.node_ws_url,
        "public_wss_url": config.network.public_wss_url
    }
    
    return web.json_response(status)


async def on_startup(app):
    """Initialize bridge when server starts."""
    logger.info("🚀 Starting PSAP Voice Bridge Server")
    
    config = get_config()
    config.log_config()
    
    # Start the bridge
    await bridge.start_bridge()


async def on_cleanup(app):
    """Cleanup bridge when server stops."""
    logger.info("🛑 Shutting down PSAP Voice Bridge Server")
    
    # Stop the bridge
    await bridge.stop_bridge()


def create_app():
    """Create and configure the aiohttp application."""
    app = web.Application()
    
    # Register routes
    app.router.add_post('/voice', voice_webhook_handler)
    app.router.add_route('*', '/ws', websocket_handler)  # Handle WebSocket upgrade
    app.router.add_get('/status', status_handler)
    
    # Register lifecycle handlers
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    
    return app


def main():
    """Main entry point."""
    config = get_config()
    app = create_app()
    
    logger.info(f"🌐 Starting Twilio server on port {config.twilio.server_port}")
    logger.info(f"📡 Webhook URL: https://{config.network.ngrok_domain}/voice")
    logger.info(f"🔌 WebSocket URL: {config.network.public_wss_url}")
    
    web.run_app(
        app,
        host='0.0.0.0',
        port=config.twilio.server_port
    )


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n🛑 Server stopped by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)