import asyncio
import aiohttp
import logging
import argparse

import uuid

import json
import time
import secrets
from datetime import datetime, timezone
from typing import Dict, Tuple, Optional

import tempfile
import os

from io import BytesIO

from nio import (
    AsyncClient, MatrixRoom, RoomMessageText, RoomMessageFile,
    InviteMemberEvent, LoginError
)

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
    'text/markdown': '.md',
    'text/html': '.html',
    'text/css': '.css',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
}

EXTENSION_TO_MIME = {ext: mime for mime, ext in MIME_TO_EXTENSION.items()}

class FlowiseBot:
    def __init__(self, homeserver, user_id, password, flowise_url):
        self.homeserver = homeserver
        self.user_id = user_id
        self.password = password
        self.flowise_url = flowise_url

        temp_dir = tempfile.gettempdir()
        safe_user_id = user_id.replace('@', '').replace(':', '_').replace('.', '_')
        store_path = os.path.join(temp_dir, f"matrix_store_{safe_user_id}")
        os.makedirs(store_path, exist_ok=True)
        
        logger.info(f"📁 Store path: {store_path}")
        
        self.client = AsyncClient(
            homeserver=self.homeserver,
            user=self.user_id,
            ssl=False,
            store_path=store_path
        )

        self.start_time = int(time.time() * 1000)
        logger.info(f"⏰ Bot start time: {self.start_time}")
        
        self.file_cache: Dict[Tuple[str, str], dict] = {}
        self.session_cache: Dict[str, str] = {}

    def should_process_message(self, event) -> bool:
        event_source = getattr(event, 'source', {})
        content = event_source.get('content', {})
        event_ts = event_source.get('origin_server_ts', 0)
        
        if event_ts == 0:
            logger.debug("❓ Message has no timestamp, processing anyway")
            return True
        
        if event_ts < self.start_time:
            logger.debug(f"⏭️ Skipping old message (event ts: {event_ts} < bot start ts: {self.start_time})")
            return False
        
        return True
    
    async def login_with_retry(self, retries=3):
        for attempt in range(retries):
            try:
                logger.info(f"🔐 Login attempt {attempt + 1}/{retries}...")

                login_response = await self.client.login(self.password)
                
                if isinstance(login_response, LoginError):
                    logger.error(f"❌ Login failed: {login_response.message}")
                    if attempt < retries - 1:
                        await asyncio.sleep(2 ** attempt)
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
    
    @staticmethod
    def generate_random_session_id() -> str:
        return str(uuid.uuid4())
    
    def get_or_create_session(self, room_id: str) -> str:
        if room_id not in self.session_cache:
            session_id = self.generate_random_session_id()
            self.session_cache[room_id] = session_id
            logger.info(f"📝 Created new session for room {room_id[:20]}...: {session_id}")
        
        return self.session_cache[room_id]
        
    def reset_session(self, room_id: str) -> str:
        """Сбрасывает сессию для комнаты и возвращает новый session_id"""
        old_session = self.session_cache.get(room_id, "no session")
        session_id = self.generate_random_session_id(room_id)
        self.session_cache[room_id] = session_id
        
        # Очищаем кэш файлов для этой комнаты и отправителя
        keys_to_remove = []
        for key in self.file_cache.keys():
            if key[0] == room_id:
                keys_to_remove.append(key)
        
        for key in keys_to_remove:
            del self.file_cache[key]
        
        logger.info(f"🔄 Reset session for room {room_id[:20]}...: {old_session} -> {session_id}")
        return session_id
    
    async def on_invite(self, room: MatrixRoom, event: InviteMemberEvent) -> None:
        if event.state_key == self.user_id:
            logger.info(f"🤝 Accepting invitation to room {room.room_id[:20]}...")
            try:
                await self.client.join(room.room_id)
                logger.info(f"✅ Joined room: {room.room_id[:20]}...")

                self.get_or_create_session(room.room_id)
            except Exception as e:
                logger.error(f"❌ Failed to join room {room.room_id[:20]}: {e}")
    
    async def send_unencrypted_message(self, room_id: str, text: str):
        try:
            # Прямой HTTP запрос к Matrix API
            url = f"{self.homeserver}/_matrix/client/v3/rooms/{room_id}/send/m.room.message"
            
            headers = {
                "Authorization": f"Bearer {self.client.access_token}",
                "Content-Type": "application/json"
            }
            
            data = {
                "msgtype": "m.text",
                "body": text
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=data, headers=headers) as response:
                    if response.status == 200:
                        logger.info("✅ Sent unencrypted message")
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ Failed to send unencrypted message: {response.status} - {error_text}")
                        
        except Exception as e:
            logger.error(f"❌ Error sending unencrypted message: {e}")

    async def upload_file_to_flowise(self, file_bytes: bytes, filename: str, mime_type: str, chat_id: str) -> str:
        url = self.flowise_url.replace('/prediction/', '/attachments/') + '/' + chat_id
        
        form = aiohttp.FormData()

        file_obj = BytesIO(file_bytes)

        form.add_field('files', file_obj, filename=filename, content_type=mime_type)
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=form, timeout=aiohttp.ClientTimeout(total=60)) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Flowise attachments error {response.status}: {error_text}")
                        raise Exception(f"Flowise attachments error: {response.status}")
                    
                    file_info_list = await response.json()
                    if not file_info_list or not isinstance(file_info_list, list):
                        raise Exception("Invalid response from Flowise attachments API")
                    
                    file_info = file_info_list[0]
                    extracted_text = file_info.get('content', '').strip()
                    
                    if not extracted_text:
                        logger.warning("⚠️ Flowise returned empty content for file")

                        extracted_text = f"[Содержимое файла '{filename}' не было извлечено автоматически]"
                    
                    logger.info(f"✅ Flowise извлёк текст ({len(extracted_text)} символов) из '{filename}'")
                    return extracted_text
                    
        except asyncio.TimeoutError:
            logger.error("⏰ Flowise attachments request timeout")
            raise Exception("Flowise не ответил вовремя при загрузке файла")
        except Exception as e:
            logger.error(f"💥 Ошибка загрузки файла в Flowise: {e}")
            raise Exception

    async def download_file_bytes(self, mxc_url: str) -> Optional[bytes]:
        try:
            logger.info(f"⬇️ Downloading file bytes: {mxc_url}")

            response = await self.client.download(mxc_url)
            if response and hasattr(response, 'body'):
                if len(response.body) > 100 * 1024 * 1024:
                    logger.warning(f"File too large: {len(response.body)} bytes")
                    return None
                
                logger.info(f"✅ Downloaded file: {len(response.body)} bytes")
                return response.body
                
            logger.error(f"Failed to download file from {mxc_url}")
            return None
        except Exception as e:
            logger.error(f"Error downloading file bytes: {e}")
            import traceback
            traceback.print_exc()
            return None

    @staticmethod
    def detect_mime_type(event, file_name: str, logger) -> tuple[str, int, str]:
        mime_type = 'application/octet-stream'
        file_size = 0
        method = "unknown"

        if hasattr(event, 'file') and event.file:
            if hasattr(event.file, 'mimetype') and event.file.mimetype:
                mime_type = event.file.mimetype
                method = "event.file.mimetype"
            if hasattr(event.file, 'size'):
                file_size = event.file.size

        if mime_type == 'application/octet-stream' and hasattr(event, 'source'):
            source_content = event.source.get('content', {})
            info = source_content.get('info', {}) if isinstance(source_content, dict) else {}
            if isinstance(info, dict):
                if info.get('mimetype'):
                    mime_type = info['mimetype']
                    method = "source.info.mimetype"
                if info.get('size'):
                    file_size = info['size']

        if mime_type == 'application/octet-stream' and '.' in file_name:
            ext = '.' + file_name.split('.')[-1].lower()
            if ext in EXTENSION_TO_MIME:
                mime_type = EXTENSION_TO_MIME[ext]
                method = f"extension_fallback:{ext}"
                logger.info(f"🔄 MIME determined from extension: {ext} → {mime_type}")
        
        return mime_type, file_size, method

    async def on_file(self, room: MatrixRoom, event: RoomMessageFile) -> None:
        if event.sender == self.client.user_id:
            return

        if not self.should_process_message(event):
            return
            
        logger.info(f"File from {event.sender}: {event.body}")
        
        try:
            file_name = event.body or 'file'
            original_name = file_name

            mime_type, file_size, detection_method = self.detect_mime_type(event, file_name, logger)

            if '.' not in file_name and mime_type in MIME_TO_EXTENSION:
                file_name += MIME_TO_EXTENSION[mime_type]
                logger.debug(f"✏️ Added extension: {file_name}")
                
            logger.info(f"📦 File: '{original_name}' → '{file_name}' | MIME: {mime_type} | Size: {file_size}B | Method: {detection_method}")

            supported_types = list(MIME_TO_EXTENSION.keys())
        
            if mime_type not in supported_types:
                logger.warning(f"⚠️ Unsupported file type: {mime_type}")
                await self.send_text_message(
                    room.room_id,
                    f"Формат файла {mime_type} не поддерживается. Поддерживаются: PDF, TXT, DOCX, Excel, изображения, код."
                )
                return

            if hasattr(event, 'url'):
                file_bytes = await self.download_file_bytes(event.url)
                if file_bytes:
                    cache_key = (room.room_id, event.sender)
                    self.file_cache[cache_key] = {
                        'bytes': file_bytes,
                        'mime': mime_type,
                        'name': file_name,
                        'size': file_size
                    }
                    logger.info(f"💾 Saved file bytes '{file_name}' ({mime_type}) for {event.sender}")
                    
                    size_info = f" ({file_size} байт)" if file_size > 0 else ""
                    await self.send_text_message(
                        room.room_id,
                        f"Файл '{file_name}' получен{size_info}. Теперь задайте вопрос по этому файлу или загрузите его в базу данных командой !rag."
                    )
                else:
                    await self.send_text_message(
                        room.room_id,
                        f"Не удалось загрузить файл '{file_name}'. Возможно, он слишком большой (>100MB)."
                    )
                
        except Exception as e:
            logger.error(f"💥 Error processing file: {e}")
            import traceback
            traceback.print_exc()
            await self.send_text_message(
                room.room_id,
                f"Ошибка при обработке файла: {str(e)[:100]}"
            )

    async def send_text_message(self, room_id: str, text: str):
        content = {
            "msgtype": "m.text",
            "body": text
        }
        await self.safe_room_send(room_id, content)

    async def safe_room_send(self, room_id: str, content: dict, max_retries=3):
        for attempt in range(max_retries):
            try:
                await self.client.room_send(
                    room_id=room_id,
                    message_type="m.room.message",
                    content=content
                )
                return True
                
            except KeyError as e:
                logger.warning(f"⚠️ Attempt {attempt+1}/{max_retries}: KeyError, retrying...: {e}")
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"❌ Attempt {attempt+1}/{max_retries}: Unexpected error: {e}")
                break

        logger.error(f"❌ All {max_retries} attempts failed, trying HTTP API...")
        try:
            await self.send_unencrypted_message(room_id, content.get('body', 'Message failed'))
            return True
        except Exception as e:
            logger.error(f"❌ HTTP API also failed: {e}")
            return False

    async def on_message(self, room: MatrixRoom, event: RoomMessageText) -> None:
        if event.sender == self.client.user_id:
            return

        if not self.should_process_message(event):
            return
            
        logger.info(f"📨 Message from {event.sender} in room {room.room_id[:20]}...: {event.body}")

        if event.body.startswith('!'):
            await self.handle_command(room, event)
            return

        cache_key = (room.room_id, event.sender)
        file_info = self.file_cache.pop(cache_key, None)

        session_id = self.get_or_create_session(room.room_id)
        
        try:
            payload = {
                "question": event.body,
                "overrideConfig": {
                    "chatId" : session_id,
                    "sessionId": session_id
                }
            }
            
            if file_info:
                logger.info(f"📤 Обрабатываю файл '{file_info['name']}' ({file_info['mime']}) для Flowise...")
                
                try:
                    extracted_text = await self.upload_file_to_flowise(
                        file_bytes=file_info['bytes'],
                        filename=file_info['name'],
                        mime_type=file_info['mime'],
                        chat_id=session_id
                    )
                    
                    payload["question"] = (
                        f"Вопрос: {event.body}\n\n"
                        f"Документ ({file_info['name']}):\n{extracted_text}"
                    )
                    
                    logger.info(f"📤 Отправка вопрос + текст документа ({len(payload['question'])} символов) в Flowise")
                    
                except Exception as upload_error:
                    logger.warning(f"⚠️ Не удалось загрузить файл в Flowise: {upload_error}")
                    payload["question"] = (
                        f"⚠️ Файл '{file_info['name']}' был получен, но не удалось извлечь из него текст.\n"
                        f"Вопрос: {event.body}"
                    )
            
            timeout = aiohttp.ClientTimeout(total=300)
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.flowise_url,
                    json=payload,
                    timeout=timeout
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        answer = result.get('text', 'No response from Flowise')
                    elif response.status == 413:
                        answer = "Файл слишком большой для обработки Flowise (макс. ~10-15MB)."
                    else:
                        error_text = await response.text()
                        logger.error(f"Flowise error {response.status}: {error_text[:500]}")
                        answer = f"Ошибка Flowise: {response.status}. Попробуйте позже или уменьшите размер файла."
            
            await self.send_text_message(room.room_id, answer)
            logger.info(f"📤 Ответ отправлен пользователю {event.sender}")
            
        except asyncio.TimeoutError:
            logger.error("⏰ Flowise request timeout")
            await self.send_text_message(room.room_id, "Flowise не ответил вовремя. Попробуйте позже.")
        except Exception as e:
            logger.error(f"💥 Ошибка обработки запроса: {e}")
            import traceback
            traceback.print_exc()
            error_msg = f"Ошибка: {str(e)[:300]}"
            await self.send_text_message(room.room_id, error_msg)

    async def handle_command(self, room: MatrixRoom, event: RoomMessageText):
        command = event.body.strip()
        if command.startswith('!rag'):
            args = command.split()
            chunk_size = 300
            chunk_overlap = 150

            session_id = self.get_or_create_session(room.room_id)

            for arg in args[1:]:
                if '=' in arg:
                    key, value = arg.split('=', 1)
                    if key == 'chunkSize':
                        try:
                            chunk_size = int(value)
                        except ValueError:
                            await self.send_text_message(room.room_id, f"Неверное значение chunkSize: {value}")
                            return
                    elif key == 'chunkOverlap':
                        try:
                            chunk_overlap = int(value)
                        except ValueError:
                            await self.send_text_message(room.room_id, f"Неверное значение chunkOverlap: {value}")
                            return
            
            cache_key = (room.room_id, event.sender)
            if cache_key in self.file_cache:
                file_info = self.file_cache[cache_key]
                
                try:
                    API_URL = self.flowise_url.replace('/prediction/', '/vector/upsert/')
                    
                    logger.info(f"📤 Отправка файла '{file_info['name']}' в Flowise по адресу: {API_URL}")

                    form = aiohttp.FormData()

                    form.add_field('chatId', session_id)
                    form.add_field('sessionId', session_id)

                    form.add_field(
                        'files',
                        file_info['bytes'],
                        filename=file_info['name'],
                        content_type=file_info['mime']
                    )
                    
                    form.add_field('chunkSize', str(chunk_size))
                    form.add_field('chunkOverlap', str(chunk_overlap))

                    headers = {
                        "Accept": "application/json"
                    }
                    
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            API_URL,
                            data=form,
                            headers=headers,
                            timeout=aiohttp.ClientTimeout(total=300)
                        ) as response:
                            
                            response_text = await response.text()
                            logger.info(f"Flowise response ({response.status}): {response_text}")
                            
                            if response.status == 200:
                                try:
                                    result = json.loads(response_text)
        
                                    added = result.get('numAdded', 0)
                                    updated = result.get('numUpdated', 0)
                                    
                                    if added > 0 or updated > 0:
                                        status_msg = f"Файл успешно обработан!"
                                        details = f"Добавлено чанков: {added}"
                                        if updated > 0:
                                            details += f"\nОбновлено чанков: {updated}"
                                    else:
                                        status_msg = "Файл обработан, но новые чанки не были добавлены."
                                        details = "Возможно, такой контент уже есть в базе."

                                    await self.send_text_message(
                                        room.room_id, 
                                        f"{status_msg}\n"
                                        f"{details}\n"
                                        f"Настройки: chunk={chunk_size}, overlap={chunk_overlap}"
                                    )
                                    
                                    _ = self.file_cache.pop(cache_key, None)
                                    
                                except json.JSONDecodeError:
                                    await self.send_text_message(
                                        room.room_id,
                                        f"Успешный ответ, но не удалось распарсить JSON: {response_text[:200]}"
                                    )
                            else:
                                logger.error(f"❌ Upsert error {response.status}: {response_text}")
                                await self.send_text_message(
                                    room.room_id,
                                    f"Ошибка Flowise ({response.status}): {response_text[:300]}"
                                )
                                
                except asyncio.TimeoutError:
                    logger.error("⏰ Flowise upsert request timeout")
                    await self.send_text_message(
                        room.room_id, 
                        "Flowise не ответил вовремя. Возможно, файл слишком большой или сервер перегружен."
                    )
                except Exception as e:
                    logger.error(f"❌ Ошибка при отправке файла в Flowise: {e}")
                    import traceback
                    traceback.print_exc()
                    await self.send_text_message(
                        room.room_id, 
                        f"Ошибка при отправке файла: {str(e)[:200]}"
                    )
            else:
                await self.send_text_message(
                    room.room_id, 
                    "Нет файла для загрузки. Сначала отправьте файл, затем используйте команду !rag.\n\n"
                    "Пример использования:\n"
                    "1. Отправьте файл (PDF, DOCX, TXT и т.д.)\n"
                    "2. Используйте команду:\n"
                    "   !rag\n"
                    "   !rag chunkSize=500 chunkOverlap=100\n"
                    "   !rag chunkSize=300 chunkOverlap=150"
                )

        elif command == "!reset":
            new_session_id = self.reset_session(room.room_id)
            self.file_cache = {}
            await self.send_text_message(
                room.room_id, 
                f"Сессия сброшена. Начинаем новый диалог.\nНовая сессия: {new_session_id}"
            )
                
        elif command == "!session":
            session_id = self.get_or_create_session(room.room_id)
            await self.send_text_message(
                room.room_id, 
                f"ID текущей сессии: {session_id}\nКомната: {room.room_id[:30]}..."
            )
            
        elif command == "!help" or command == "!start":
            help_text = """Команды бота:
!help или !start - Показать это сообщение
!reset - Сбросить историю диалога (начать новый разговор)
!session - Показать ID текущей сессии
!rag [chunkSize=300] [chunkOverlap=150] [metadata="{}"] - Загрузить файл в базу данных

Как отправить файл:
1. Просто отправьте файл в чат (PDF, TXT, DOCX, изображения)
2. Бот подтвердит получение файла
3. Задайте вопрос по файлу

Лимит файла: ~10MB
Сессии: Каждая комната имеет свою сессию, бот помнит контекст в рамках комнаты"""
            
            await self.send_text_message(room.room_id, help_text)
            
        elif command == "!status":
            status_text = f"""Статус бота:
Пользователь: {self.client.user_id}
Активные сессии: {len(self.session_cache)}
Файлы в кэше: {len(self.file_cache)}
Flowise: {self.flowise_url}
Время запуска: {datetime.fromtimestamp(self.start_time/1000, timezone.utc)}"""
            
            await self.send_text_message(room.room_id, status_text)
            
        else:
            await self.send_text_message(room.room_id, f"Неизвестная команда: {command}\nИспользуйте !help для списка команд.")

    async def run(self):
        try:
            logger.info(f"Starting Flowise Matrix Bot {self.user_id}...")
            logger.info(f"Homeserver: {self.homeserver}")
            logger.info(f"Flowise URL: {self.flowise_url}")
            logger.info(f"Filter messages newer than: {datetime.fromtimestamp(self.start_time/1000, timezone.utc)}")

            if not await self.login_with_retry():
                logger.error("Failed to login after all retries")
                return

            if not self.client.user_id or not self.client.access_token:
                logger.error("❌ Not properly logged in. Missing user_id or access_token")
                return
            
            logger.info(f"✅ Logged in as {self.client.user_id}")

            self.client.add_event_callback(self.on_invite, InviteMemberEvent)
            self.client.add_event_callback(self.on_message, RoomMessageText)
            self.client.add_event_callback(self.on_file, RoomMessageFile)

            logger.info("🔄 Starting initial sync...")
            sync_response = await self.client.sync(timeout=30000)
            if sync_response:
                logger.info(f"✅ Initial sync completed. Next batch: {sync_response.next_batch[:20]}...")
            else:
                logger.warning("⚠️ Initial sync returned empty response")
            
            logger.info("👂 Bot is ready and listening for messages and files...")
            logger.info("📁 Supported file types: PDF, TXT, DOCX, Excel, JSON, CSV, images, code")
            logger.info("💬 Commands: !help, !reset, !session, !status")
            
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