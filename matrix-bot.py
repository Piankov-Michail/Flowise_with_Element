import asyncio
import aiohttp
import logging
import argparse
import sys
from nio import AsyncClient, MatrixRoom, RoomMessageText, InviteMemberEvent

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class FlowiseBot:
    def __init__(self, homeserver, user_id, password, flowise_url):
        self.homeserver = homeserver
        self.user_id = user_id
        self.password = password
        self.flowise_url = flowise_url
        self.client = AsyncClient(
            homeserver=self.homeserver,
            user=self.user_id,
            ssl=False,
            store_path=f"./matrix_store_{user_id.replace('@', '').replace(':', '_')}"
        )
        
    async def on_invite(self, room: MatrixRoom, event: InviteMemberEvent) -> None:
        """Автоматически принимаем приглашения"""
        if event.state_key == self.user_id:
            logger.info(f"🤝 Accepting invitation to room {room.room_id}")
            try:
                await self.client.join(room.room_id)
                logger.info(f"✅ Joined room: {room.room_id}")
            except Exception as e:
                logger.error(f"❌ Failed to join room {room.room_id}: {e}")
        
    async def on_message(self, room: MatrixRoom, event: RoomMessageText) -> None:
        """Обрабатываем сообщения"""
        if event.sender == self.client.user_id:
            return
            
        logger.info(f"📨 Message from {event.sender}: {event.body}")
        
        try:
            # Проверяем Flowise
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.flowise_url,
                    json={"question": event.body},
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        answer = result.get('text', '🤖 No response from Flowise')
                    else:
                        answer = f"❌ Flowise error: {response.status}"
                        
            # Отправляем ответ
            await self.client.room_send(
                room_id=room.room_id,
                message_type="m.room.message",
                content={"msgtype": "m.text", "body": answer}
            )
            logger.info(f"📤 Sent: {answer}")
            
        except Exception as e:
            logger.error(f"💥 Error: {e}")
            await self.client.room_send(
                room_id=room.room_id,
                message_type="m.room.message",
                content={"msgtype": "m.text", "body": "❌ Error processing request"}
            )

    async def run(self):
        try:
            logger.info(f"🚀 Starting Flowise Matrix Bot {self.user_id}...")
            logger.info(f"Homeserver: {self.homeserver}")
            logger.info(f"Flowise URL: {self.flowise_url}")
            
            # Логинимся
            await self.client.login(self.password)
            logger.info("✅ Login successful!")
            
            # Добавляем обработчики
            self.client.add_event_callback(self.on_invite, InviteMemberEvent)
            self.client.add_event_callback(self.on_message, RoomMessageText)
            
            # Сначала синхронизируемся чтобы получить текущее состояние
            await self.client.sync(timeout=30000)
            logger.info("🔄 Initial sync completed")
            
            logger.info("👂 Bot is ready and listening for messages...")
            
            # Бесконечная синхронизация
            await self.client.sync_forever(timeout=30000)
            
        except Exception as e:
            logger.error(f"💀 Fatal error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await self.client.close()

async def main():
    parser = argparse.ArgumentParser(description='Matrix Flowise Bot')
    parser.add_argument('--homeserver', required=True, help='Matrix homeserver URL')
    parser.add_argument('--user', required=True, help='Bot user ID (e.g., @bot:localhost)')
    parser.add_argument('--password', required=True, help='Bot password')
    parser.add_argument('--flowise-url', required=True, help='Flowise API URL')
    
    args = parser.parse_args()
    
    bot = FlowiseBot(
        homeserver=args.homeserver,
        user_id=args.user,
        password=args.password,
        flowise_url=args.flowise_url
    )
    await bot.run()

if __name__ == "__main__":
    asyncio.run(main())