import asyncio
import aiohttp
import logging
import argparse
import sys
import base64
import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Dict, Tuple, Optional
from nio import AsyncClient, MatrixRoom, RoomMessageText, RoomMessageFile, InviteMemberEvent, LoginResponse, LoginError

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Сопоставление MIME-типов с расширениями
MIME_TO_EXTENSION = {
    'application/pdf': '.pdf',
    'text/plain': '.txt',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
    'application/json': '.json',
    'text/csv': '.csv',
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'image/gif': '.gif',
    'text/markdown': '.md',
    'text/x-python': '.py',
    'application/x-python-code': '.py',
    'application/javascript': '.js',
    'text/html': '.html',
    'text/css': '.css',
    'application/vnd.ms-excel': '.xls',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
}

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
        
        # Время запуска бота для фильтрации старых сообщений (в миллисекундах)
        self.start_time = int(time.time() * 1000)
        logger.info(f"⏰ Bot start time: {self.start_time} ({datetime.fromtimestamp(self.start_time/1000, timezone.utc)})")
        
        # Кэш для хранения файлов пользователей: {(room_id, user_id): file_data}
        self.file_cache: Dict[Tuple[str, str], dict] = {}
        
        # Кэш для хранения истории сессий (room_id -> session_id)
        self.session_cache: Dict[str, str] = {}
    
    def should_process_message(self, event) -> bool:
        """
        Проверяет, является ли сообщение новым (отправлено после запуска бота)
        """
        # Получаем timestamp события из источника
        event_source = getattr(event, 'source', {})
        content = event_source.get('content', {})
        event_ts = event_source.get('origin_server_ts', 0)
        
        # Если timestamp отсутствует - обрабатываем сообщение (на всякий случай)
        if event_ts == 0:
            logger.debug("❓ Message has no timestamp, processing anyway")
            return True
        
        # Если сообщение старше времени запуска бота - пропускаем
        if event_ts < self.start_time:
            logger.debug(f"⏭️ Skipping old message (event ts: {event_ts} < bot start ts: {self.start_time})")
            return False
        
        return True
    
    async def login_with_retry(self, retries=3):
        """Логинимся с повторными попытками"""
        for attempt in range(retries):
            try:
                logger.info(f"🔐 Login attempt {attempt + 1}/{retries}...")
                
                # Пытаемся залогиниться
                login_response = await self.client.login(self.password)
                
                if isinstance(login_response, LoginError):
                    logger.error(f"❌ Login failed: {login_response.message}")
                    if attempt < retries - 1:
                        await asyncio.sleep(2 ** attempt)  # Экспоненциальная задержка
                        continue
                    else:
                        raise Exception(f"Login failed after {retries} attempts: {login_response.message}")
                
                logger.info(f"✅ Login successful! User: {self.client.user_id}, Device: {self.client.device_id}")
                return True
                
            except Exception as e:
                logger.error(f"❌ Login error (attempt {attempt + 1}): {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise
        
        return False
    
    def generate_session_id(self, room_id: str) -> str: 
        session_hash = hashlib.sha256(room_id.encode()).hexdigest()[:16]
        return f"matrix_{session_hash}"
    
    def get_or_create_session(self, room_id: str) -> str:
        """Получает существующий session_id для комнаты или создает новый"""
        if room_id not in self.session_cache:
            self.session_cache[room_id] = self.generate_session_id(room_id)
            logger.info(f"📝 Created new session for room {room_id[:20]}...: {self.session_cache[room_id]}")
        
        return self.session_cache[room_id]
        
    async def on_invite(self, room: MatrixRoom, event: InviteMemberEvent) -> None:
        """Автоматически принимаем приглашения"""
        if event.state_key == self.user_id:
            logger.info(f"🤝 Accepting invitation to room {room.room_id[:20]}...")
            try:
                await self.client.join(room.room_id)
                logger.info(f"✅ Joined room: {room.room_id[:20]}...")
                
                # Создаем сессию для новой комнаты
                self.get_or_create_session(room.room_id)
            except Exception as e:
                logger.error(f"❌ Failed to join room {room.room_id[:20]}: {e}")
    
    async def download_and_encode_file(self, mxc_url: str) -> Optional[str]:
        """Скачивает файл с Matrix сервера и кодирует в base64"""
        try:
            logger.info(f"⬇️ Downloading file: {mxc_url}")
            # Скачиваем файл
            response = await self.client.download(mxc_url)
            if response and hasattr(response, 'body'):
                # Проверяем размер файла (ограничение ~10MB)
                if len(response.body) > 10 * 1024 * 1024:
                    logger.warning(f"File too large: {len(response.body)} bytes")
                    return None
                
                # Кодируем в base64
                file_data = base64.b64encode(response.body).decode('utf-8')
                logger.info(f"📄 Encoded file: {len(file_data)} chars base64")
                return file_data
            else:
                logger.error(f"Failed to download file from {mxc_url}")
                return None
        except Exception as e:
            logger.error(f"Error downloading file: {e}")
            import traceback
            traceback.print_exc()
            return None
        
    async def on_file(self, room: MatrixRoom, event: RoomMessageFile) -> None:
        """Обрабатываем файлы"""
        # Игнорируем свои файлы
        if event.sender == self.client.user_id:
            return
        
        # Пропускаем старые файлы
        if not self.should_process_message(event):
            return
            
        logger.info(f"📎 File from {event.sender}: {event.body}")
        
        try:
            # Получаем информацию о файле
            file_name = event.body or 'file'
            
            # Получаем MIME-тип из file_info если он есть
            mime_type = 'application/octet-stream'
            file_size = 0
            
            # Проверяем различные способы получения информации о файле
            if hasattr(event, 'file') and event.file:
                if hasattr(event.file, 'mimetype') and event.file.mimetype:
                    mime_type = event.file.mimetype
                if hasattr(event.file, 'size'):
                    file_size = event.file.size
            
            # Также проверяем source
            if mime_type == 'application/octet-stream' and hasattr(event, 'source'):
                source_content = event.source.get('content', {})
                if 'info' in source_content and 'mimetype' in source_content['info']:
                    mime_type = source_content['info']['mimetype']
                if 'info' in source_content and 'size' in source_content['info']:
                    file_size = source_content['info']['size']
            
            # Добавляем расширение если его нет
            if '.' not in file_name and mime_type in MIME_TO_EXTENSION:
                file_name += MIME_TO_EXTENSION[mime_type]
                
            logger.info(f"📦 File info: {file_name} ({mime_type}), {file_size} bytes")
            
            # Проверяем поддерживаемые типы
            supported_types = list(MIME_TO_EXTENSION.keys())
            
            if mime_type not in supported_types:
                logger.warning(f"⚠️ Unsupported file type: {mime_type}")
                await self.client.room_send(
                    room_id=room.room_id,
                    message_type="m.room.message",
                    content={
                        "msgtype": "m.text", 
                        "body": f"⚠️ Формат файла {mime_type} не поддерживается. Поддерживаются: PDF, TXT, DOCX, Excel, изображения, код."
                    }
                )
                return
                
            # Скачиваем и кодируем файл
            if hasattr(event, 'url'):
                file_data = await self.download_and_encode_file(event.url)
                if file_data:
                    # Сохраняем в кэше
                    cache_key = (room.room_id, event.sender)
                    self.file_cache[cache_key] = {
                        'data': file_data,
                        'mime': mime_type,
                        'name': file_name,
                        'size': file_size
                    }
                    logger.info(f"💾 Saved file '{file_name}' ({mime_type}) for {event.sender}")
                    
                    # Уведомляем пользователя
                    size_info = f" ({file_size} байт)" if file_size > 0 else ""
                    await self.client.room_send(
                        room_id=room.room_id,
                        message_type="m.room.message",
                        content={
                            "msgtype": "m.text", 
                            "body": f"📁 Файл '{file_name}' получен{size_info}. Теперь задайте вопрос по этому файлу."
                        }
                    )
                else:
                    await self.client.room_send(
                        room_id=room.room_id,
                        message_type="m.room.message",
                        content={
                            "msgtype": "m.text", 
                            "body": f"❌ Не удалось загрузить файл '{file_name}'. Возможно, он слишком большой (>10MB)."
                        }
                    )
            else:
                logger.error(f"No URL found in file event")
                await self.client.room_send(
                    room_id=room.room_id,
                    message_type="m.room.message",
                    content={
                        "msgtype": "m.text", 
                        "body": f"❌ Не удалось получить файл '{file_name}' (нет ссылки)."
                    }
                )
                
        except Exception as e:
            logger.error(f"💥 Error processing file: {e}")
            import traceback
            traceback.print_exc()
            await self.client.room_send(
                room_id=room.room_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.text", 
                    "body": f"❌ Ошибка при обработке файла: {str(e)[:100]}"
                }
            )
        
    async def on_message(self, room: MatrixRoom, event: RoomMessageText) -> None:
        """Обрабатываем текстовые сообщения"""
        # Игнорируем свои сообщения
        if event.sender == self.client.user_id:
            return
        
        # Пропускаем старые сообщения
        if not self.should_process_message(event):
            return
            
        logger.info(f"📨 Message from {event.sender} in room {room.room_id[:20]}...: {event.body}")
        
        # Проверяем команды бота
        if event.body.startswith('!'):
            await self.handle_command(room, event)
            return
        
        # Проверяем, есть ли файл в кэше для этого пользователя
        cache_key = (room.room_id, event.sender)
        file_info = self.file_cache.pop(cache_key, None)  # Удаляем из кэша после использования
        
        # Получаем или создаем session_id для этой комнаты
        session_id = self.get_or_create_session(room.room_id)
        
        try:
            # Формируем запрос к Flowise
            data = {
                "question": event.body,
                "session_id": session_id,
                "overrideConfig": {
                    "sessionId": session_id
                }
            }
            
            if file_info:
                logger.info(f"📤 Sending file '{file_info['name']}' to Flowise with session_id: {session_id}")
                data["uploads"] = [{
                    "data": f"data:{file_info['mime']};base64,{file_info['data']}",
                    "type": "file:full",
                    "name": file_info['name'],
                    "mime": file_info['mime']
                }]
                # Для файлов можно увеличить таймаут
                timeout = aiohttp.ClientTimeout(total=120)
            else:
                logger.info(f"📤 Sending text query to Flowise with session_id: {session_id}")
                timeout = aiohttp.ClientTimeout(total=60)
            
            # Отправляем запрос в Flowise
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.flowise_url,
                    json=data,
                    timeout=timeout
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        answer = result.get('text', '🤖 No response from Flowise')
                        
                        # Обрезаем слишком длинные ответы
                        if len(answer) > 4000:
                            answer = answer[:4000] + "...\n\n(Ответ слишком длинный, обрезан)"
                    elif response.status == 413:
                        answer = "❌ Файл слишком большой для обработки Flowise (макс. ~10MB)."
                    else:
                        error_text = await response.text()
                        logger.error(f"Flowise error {response.status}: {error_text}")
                        answer = f"❌ Flowise error: {response.status}"
                        
            # Отправляем ответ
            await self.client.room_send(
                room_id=room.room_id,
                message_type="m.room.message",
                content={"msgtype": "m.text", "body": answer}
            )
            logger.info(f"📤 Sent response to {event.sender}")
            
        except asyncio.TimeoutError:
            logger.error("⏰ Flowise request timeout")
            await self.client.room_send(
                room_id=room.room_id,
                message_type="m.room.message",
                content={"msgtype": "m.text", "body": "⏰ Flowise не ответил вовремя. Попробуйте позже."}
            )
        except Exception as e:
            logger.error(f"💥 Error: {e}")
            import traceback
            traceback.print_exc()
            await self.client.room_send(
                room_id=room.room_id,
                message_type="m.room.message",
                content={"msgtype": "m.text", "body": f"❌ Error processing request: {str(e)[:200]}"}
            )
    
    async def handle_command(self, room: MatrixRoom, event: RoomMessageText):
        """Обрабатывает команды бота"""
        command = event.body.strip()
        
        if command == "!reset":
            # Сброс сессии
            if room.room_id in self.session_cache:
                old_session = self.session_cache.pop(room.room_id)
                logger.info(f"🔄 Reset session for room {room.room_id[:20]}: {old_session}")
                await self.client.room_send(
                    room_id=room.room_id,
                    message_type="m.room.message",
                    content={"msgtype": "m.text", "body": "🔄 Сессия сброшена. Начинаем новый диалог."}
                )
            else:
                await self.client.room_send(
                    room_id=room.room_id,
                    message_type="m.room.message",
                    content={"msgtype": "m.text", "body": "ℹ️ Нет активной сессии для сброса."}
                )
                
        elif command == "!session":
            session_id = self.get_or_create_session(room.room_id)
            await self.client.room_send(
                room_id=room.room_id,
                message_type="m.room.message",
                content={"msgtype": "m.text", "body": f"🆔 ID сессии: {session_id}\nКомната: {room.room_id[:30]}..."}
            )
            
        elif command == "!help" or command == "!start":
            # Помощь
            help_text = """🤖 **Команды бота:**
!help или !start - Показать это сообщение
!reset - Сбросить историю диалога (начать новый разговор)
!session - Показать ID текущей сессии

📁 **Как отправить файл:**
1. Просто отправьте файл в чат (PDF, TXT, DOCX, изображения)
2. Бот подтвердит получение файла
3. Задайте вопрос по файлу

💾 **Лимит файла:** ~10MB
🆔 **Сессии:** Каждая комната имеет свою сессию, бот помнит контекст в рамках комнаты"""
            
            await self.client.room_send(
                room_id=room.room_id,
                message_type="m.room.message",
                content={"msgtype": "m.text", "body": help_text}
            )
            
        elif command == "!status":
            # Статус бота
            status_text = f"""🤖 **Статус бота:**
Пользователь: {self.client.user_id}
Активные сессии: {len(self.session_cache)}
Файлы в кэше: {len(self.file_cache)}
Flowise: {self.flowise_url}
Время запуска: {datetime.fromtimestamp(self.start_time/1000, timezone.utc)}"""
            
            await self.client.room_send(
                room_id=room.room_id,
                message_type="m.room.message",
                content={"msgtype": "m.text", "body": status_text}
            )
            
        else:
            # Неизвестная команда
            await self.client.room_send(
                room_id=room.room_id,
                message_type="m.room.message",
                content={"msgtype": "m.text", "body": f"❓ Неизвестная команда: {command}\nИспользуйте !help для списка команд."}
            )

    async def run(self):
        try:
            logger.info(f"🚀 Starting Flowise Matrix Bot {self.user_id}...")
            logger.info(f"Homeserver: {self.homeserver}")
            logger.info(f"Flowise URL: {self.flowise_url}")
            logger.info(f"⏰ Filter messages newer than: {datetime.fromtimestamp(self.start_time/1000, timezone.utc)}")
            
            # Логинимся с повторными попытками
            if not await self.login_with_retry():
                logger.error("❌ Failed to login after all retries")
                return
            
            # Проверяем, что мы залогинены
            if not self.client.user_id or not self.client.access_token:
                logger.error("❌ Not properly logged in. Missing user_id or access_token")
                return
            
            logger.info(f"✅ Logged in as {self.client.user_id}")
            
            # Добавляем обработчики
            self.client.add_event_callback(self.on_invite, InviteMemberEvent)
            self.client.add_event_callback(self.on_message, RoomMessageText)
            self.client.add_event_callback(self.on_file, RoomMessageFile)
            
            # Сначала синхронизируемся чтобы получить текущее состояние
            logger.info("🔄 Starting initial sync...")
            sync_response = await self.client.sync(timeout=30000)
            if sync_response:
                logger.info(f"✅ Initial sync completed. Next batch: {sync_response.next_batch[:20]}...")
            else:
                logger.warning("⚠️ Initial sync returned empty response")
            
            logger.info("👂 Bot is ready and listening for messages and files...")
            logger.info("📁 Supported file types: PDF, TXT, DOCX, Excel, JSON, CSV, images, code")
            logger.info("💬 Commands: !help, !reset, !session, !status")
            
            # Бесконечная синхронизация
            await self.client.sync_forever(timeout=30000)
            
        except Exception as e:
            logger.error(f"💀 Fatal error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if self.client:
                await self.client.close()
            logger.info("👋 Bot stopped")

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