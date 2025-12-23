import asyncio
import aiohttp
import logging
import argparse
import sys
import base64
import hashlib
import json
import time
import secrets  # Добавлен для генерации случайных session_id
from datetime import datetime, timezone
from typing import Dict, Tuple, Optional
import os
from nio import (
    AsyncClient, MatrixRoom, RoomMessageText, RoomMessageFile,
    InviteMemberEvent, LoginError, MegolmEvent, ToDeviceEvent,
    EncryptionError, KeyVerificationEvent, KeyVerificationStart,
    RoomMessageNotice, UnknownEvent, RoomEncryptedMedia
)
from nio.store import SqliteMemoryStore
from nio.crypto import Olm
from nio.exceptions import OlmUnverifiedDeviceError
from nio.events.room_events import RoomEncryptedFile

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
        
        import tempfile
        import os
        
        # Временная директория для SQLite
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
        
        # Отключение E2EE шифрования
        self.client.olm_enabled = True
        self.client.olm_verify_device = False
        self.client.olm_force_claim_keys = False

        self.start_time = int(time.time() * 1000)
        logger.info(f"⏰ Bot start time: {self.start_time}")
        
        self.file_cache: Dict[Tuple[str, str], dict] = {}
        self.session_cache: Dict[str, str] = {}
        
        # Флаг инициализации OLM
        self.olm_initialized = False
    
    async def init_olm(self):
        """Инициализирует OLM для E2EE"""
        try:
            if not self.client.olm:
                logger.info("🔄 Initializing OLM for E2EE...")
                self.client.load_store()
                
                # Проверяем, есть ли OLM аккаунт
                if not self.client.olm_account_loaded:
                    logger.info("📝 Creating new OLM account...")
                    await self.client.receive_response(
                        await self.client.login(self.password, device_name="FlowiseBot")
                    )
                
                # Проверяем OLM
                if hasattr(self.client, 'olm') and self.client.olm:
                    logger.info(f"✅ OLM initialized: {self.client.user_id}")
                    self.olm_initialized = True
                    return True
                else:
                    logger.error("❌ OLM not initialized properly")
                    return False
                    
        except Exception as e:
            logger.error(f"❌ OLM initialization error: {e}")
            import traceback
            traceback.print_exc()
            return False

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
    
    def generate_random_session_id(self, room_id: str = None) -> str:
        """Генерирует случайный session_id с привязкой к room_id и временной меткой"""
        timestamp = int(time.time() * 1000)
        random_hash = secrets.token_hex(8)  # 16 символов случайных данных
        if room_id:
            room_hash = hashlib.sha256(room_id.encode()).hexdigest()[:8]
            return f"matrix_{room_hash}_{random_hash}_{timestamp}"
        else:
            return f"matrix_{random_hash}_{timestamp}"
    
    def get_or_create_session(self, room_id: str) -> str:
        if room_id not in self.session_cache:
            session_id = self.generate_random_session_id(room_id)
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
    
    async def on_encrypted_event(self, room: MatrixRoom, event: MegolmEvent) -> None:
        try:
            logger.info(f"🔐 Received encrypted event from {event.sender} (for keys)")

            if event.sender == self.client.user_id:
                return

            try:
                decrypted_event = await self.client.decrypt_event(event)
                logger.debug(f"🔓 Decrypted event type: {type(decrypted_event).__name__}")

                if isinstance(decrypted_event, RoomMessageText):
                    logger.info(f"📨 Encrypted text message: {decrypted_event.body[:50]}...")
                
            except Exception as e:
                logger.debug(f"⚠️ Could not decrypt (might be keys only): {e}")
                
        except Exception as e:
            logger.error(f"❌ Error in on_encrypted_event: {e}")

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

    async def handle_to_device(self, event: ToDeviceEvent) -> None:
        # Обработка device-to-device сообщения (для E2EE)
        try:
            logger.debug(f"📱 Received ToDeviceEvent: {event.__class__.__name__}")
            
            event_type = event.__class__.__name__
            
            if event_type == "RoomKeyEvent":
                logger.info(f"🔑 Received room key from {event.sender}")
            elif event_type == "ForwardedRoomKeyEvent":
                logger.info(f"🔑 Received forwarded room key from {event.sender}")
            elif event_type == "KeyVerificationStart":
                logger.info(f"🤝 Key verification started by {event.sender}")

                await self.handle_key_verification(event)
            elif event_type == "DummyEvent":
                logger.debug("💓 Received dummy event (E2EE keep-alive)")
            else:
                logger.debug(f"📱 Unknown ToDeviceEvent: {event_type}")
                
        except Exception as e:
            logger.error(f"❌ Error handling ToDeviceEvent: {e}")
            import traceback
            traceback.print_exc()

    async def handle_key_verification(self, event):
        try:
            logger.info(f"🔐 Auto-accepting key verification from {event.sender}")
            
            await self.client.accept_key_verification(event.transaction_id)
            
            logger.info(f"✅ Auto-verified device from {event.sender}")
            
        except Exception as e:
            logger.error(f"❌ Key verification error: {e}")

    async def download_and_encode_file(self, mxc_url: str) -> Optional[str]:
        # Скачивание файла с Matrix сервера и кодировка в base64
        try:
            logger.info(f"⬇️ Downloading file: {mxc_url}")

            response = await self.client.download(mxc_url)
            if response and hasattr(response, 'body'):
                if len(response.body) > 100 * 1024 * 1024:
                    logger.warning(f"File too large: {len(response.body)} bytes")
                    return None

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

    async def on_megolm_message(self, room: MatrixRoom, event: MegolmEvent) -> None:
        # Обработка зашифрованных сообщений (события Megolm)
        logger.debug(f"🔐 Received MegolmEvent in room {room.room_id[:20]}... from {event.sender}")
        
        if event.sender == self.client.user_id:
            return
        
        if not self.should_process_message(event):
            return
        
        try:
            decrypted_event = await self.client.decrypt_event(event)

            if isinstance(decrypted_event, RoomMessageText):
                logger.info(f"🔓 Decrypted text message from {event.sender}: {decrypted_event.body[:100]}...")
                await self.on_message(room, decrypted_event)
            elif isinstance(decrypted_event, RoomMessageFile):
                logger.info(f"🔓 Decrypted file message from {event.sender}: {decrypted_event.body}")
                await self.on_file(room, decrypted_event)
            elif isinstance(decrypted_event, RoomEncryptedMedia):
                logger.info(f"🔓 Decrypted media from {event.sender}")
                await self.handle_encrypted_media(room, decrypted_event)
            else:
                logger.info(f"🔓 Decrypted unknown event type from {event.sender}: {type(decrypted_event)}")
                
        except EncryptionError as e:
            logger.error(f"❌ Failed to decrypt message from {event.sender}: {e}")
        except Exception as e:
            logger.error(f"💥 Error processing encrypted message: {e}")
            import traceback
            traceback.print_exc()
    
    async def handle_encrypted_media(self, room: MatrixRoom, event: RoomEncryptedMedia) -> None:
        try:
            decrypted_info = await self.client.decrypt_media(event)
            
            logger.info(f"🔓 Decrypted media: {decrypted_info.get('body', 'unknown')}")
            
            # Здесь можно добавить обработку дешифрованных медиафайлов
            # Например, сохранить файл или отправить его в Flowise
            
        except Exception as e:
            logger.error(f"❌ Failed to decrypt media: {e}")

    async def on_file(self, room: MatrixRoom, event: RoomMessageFile) -> None:
        if event.sender == self.client.user_id:
            return

        if not self.should_process_message(event):
            return
            
        logger.info(f"📎 File from {event.sender}: {event.body}")
        
        try:
            file_name = event.body or 'file'

            mime_type = 'application/octet-stream'
            file_size = 0

            if hasattr(event, 'file') and event.file:
                if hasattr(event.file, 'mimetype') and event.file.mimetype:
                    mime_type = event.file.mimetype
                if hasattr(event.file, 'size'):
                    file_size = event.file.size

            if mime_type == 'application/octet-stream' and hasattr(event, 'source'):
                source_content = event.source.get('content', {})
                if 'info' in source_content and 'mimetype' in source_content['info']:
                    mime_type = source_content['info']['mimetype']
                if 'info' in source_content and 'size' in source_content['info']:
                    file_size = source_content['info']['size']

            if '.' not in file_name and mime_type in MIME_TO_EXTENSION:
                file_name += MIME_TO_EXTENSION[mime_type]
                
            logger.info(f"📦 File info: {file_name} ({mime_type}), {file_size} bytes")

            supported_types = list(MIME_TO_EXTENSION.keys())
        
            if mime_type not in supported_types:
                logger.warning(f"⚠️ Unsupported file type: {mime_type}")
                await self.send_text_message(
                    room.room_id,
                    f"⚠️ Формат файла {mime_type} не поддерживается. Поддерживаются: PDF, TXT, DOCX, Excel, изображения, код."
                )
                return

            if hasattr(event, 'url'):
                file_data = await self.download_and_encode_file(event.url)
                if file_data:
                    cache_key = (room.room_id, event.sender)
                    self.file_cache[cache_key] = {
                        'data': file_data,
                        'mime': mime_type,
                        'name': file_name,
                        'size': file_size
                    }
                    logger.info(f"💾 Saved file '{file_name}' ({mime_type}) for {event.sender}")
                    
                    size_info = f" ({file_size} байт)" if file_size > 0 else ""
                    await self.send_text_message(
                        room.room_id,
                        f"📁 Файл '{file_name}' получен{size_info}. Теперь задайте вопрос по этому файлу."
                    )
                else:
                    await self.send_text_message(
                        room.room_id,
                        f"❌ Не удалось загрузить файл '{file_name}'. Возможно, он слишком большой (>10MB)."
                    )
            else:
                logger.error(f"No URL found in file event")
                await self.send_text_message(
                    room.room_id,
                    f"❌ Не удалось получить файл '{file_name}' (нет ссылки)."
                )
                
        except Exception as e:
            logger.error(f"💥 Error processing file: {e}")
            import traceback
            traceback.print_exc()
            await self.send_text_message(
                room.room_id,
                f"❌ Ошибка при обработке файла: {str(e)[:100]}"
            )

    async def on_encrypted_file(self, room: MatrixRoom, event: RoomEncryptedFile):
        try:
            logger.info(f"🔐 Received encrypted file from {event.sender}")
            
            if event.sender == self.client.user_id:
                return
            
            if not self.should_process_message(event):
                return
            
            try:
                if hasattr(event, 'url'):
                    logger.info(f"⬇️ Downloading encrypted file: {event.body or 'unnamed'}")
                    
                    response = await self.client.download(event.url)
                    
                    if response and hasattr(response, 'body'):
                        if len(response.body) > 100 * 1024 * 1024:
                            logger.warning(f"File too large: {len(response.body)} bytes")
                            await self.send_text_message(
                                room.room_id,
                                "❌ Файл слишком большой (>100MB)."
                            )
                            return

                        file_name = getattr(event, 'body', 'file')
                        mime_type = 'application/octet-stream'
                        file_size = 0

                        if hasattr(event, 'file') and event.file and hasattr(event.file, 'mimetype'):
                            mime_type = event.file.mimetype
                        elif hasattr(event, 'source'):
                            source = getattr(event, 'source', {})
                            content = source.get('content', {})
                            if 'info' in content and 'mimetype' in content['info']:
                                mime_type = content['info']['mimetype']
                            if 'info' in content and 'size' in content['info']:
                                file_size = content['info']['size']

                        if '.' not in file_name and mime_type in MIME_TO_EXTENSION:
                            file_name += MIME_TO_EXTENSION[mime_type]
                        
                        logger.info(f"🔓 Successfully decrypted file: {file_name} ({mime_type})")

                        file_data = base64.b64encode(response.body).decode('utf-8')

                        cache_key = (room.room_id, event.sender)
                        self.file_cache[cache_key] = {
                            'data': file_data,
                            'mime': mime_type,
                            'name': file_name,
                            'size': file_size
                        }
                        
                        logger.info(f"💾 Saved encrypted file '{file_name}' ({mime_type}) for {event.sender}")

                        size_info = f" ({file_size} байт)" if file_size > 0 else ""
                        await self.send_text_message(
                            room.room_id,
                            f"📁 Зашифрованный файл '{file_name}' получен{size_info}. Теперь задайте вопрос по этому файлу."
                        )
                    else:
                        await self.send_text_message(
                            room.room_id,
                            "❌ Не удалось загрузить зашифрованный файл."
                        )
                else:
                    logger.error("No URL found in encrypted file event")
                    await self.send_text_message(
                        room.room_id,
                        "❌ Не удалось получить зашифрованный файл (нет ссылки)."
                    )
                    
            except Exception as e:
                logger.error(f"❌ Error downloading encrypted file: {e}")
                await self.send_text_message(
                    room.room_id,
                    "❌ Не удалось расшифровать файл. Возможно, отсутствуют ключи дешифровки.\n"
                    "Пожалуйста, отправьте файл без шифрования или используйте команду !help в незашифрованной комнате."
                )
                
        except Exception as e:
            logger.error(f"💥 Error processing encrypted file: {e}")
            import traceback
            traceback.print_exc()
            await self.send_text_message(
                room.room_id,
                f"❌ Ошибка при обработке зашифрованного файла: {str(e)[:100]}"
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
                
            except OlmUnverifiedDeviceError as e:
                logger.warning(f"⚠️ Attempt {attempt+1}/{max_retries}: Device verification error: {e}")

                await self.verify_all_devices()

                await asyncio.sleep(1)
                
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
                timeout = aiohttp.ClientTimeout(total=240)
            else:
                logger.info(f"📤 Sending text query to Flowise with session_id: {session_id}")
                timeout = aiohttp.ClientTimeout(total=120)

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.flowise_url,
                    json=data,
                    timeout=timeout
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        answer = result.get('text', '🤖 No response from Flowise')

                    elif response.status == 413:
                        answer = "❌ Файл слишком большой для обработки Flowise (макс. ~10MB)."
                    else:
                        error_text = await response.text()
                        logger.error(f"Flowise error {response.status}: {error_text}")
                        answer = f"❌ Flowise error: {response.status}"
                        
            # Отправляем ответ
            await self.send_text_message(room.room_id, answer)
            logger.info(f"📤 Sent response to {event.sender}")
            
        except asyncio.TimeoutError:
            logger.error("⏰ Flowise request timeout")
            await self.send_text_message(room.room_id, "⏰ Flowise не ответил вовремя. Попробуйте позже.")
        except Exception as e:
            logger.error(f"💥 Error: {e}")
            import traceback
            traceback.print_exc()
            await self.send_text_message(room.room_id, f"❌ Error processing request: {str(e)[:200]}")
    
    async def verify_all_devices(self):
        try:
            logger.info("🔄 Starting aggressive device verification...")

            if hasattr(self.client, 'device_store'):
                for user_id, devices in self.client.device_store.items():
                    for device_id, device_info in devices.items():
                        try:
                            if not device_info.verified:
                                logger.info(f"✅ Verifying device {device_id} for {user_id}")
                                self.client.verify_device(device_info)
                        except Exception as e:
                            logger.warning(f"⚠️ Could not verify device {device_id}: {e}")

            if hasattr(self.client, 'users_for_key_query'):
                for user_id in self.client.users_for_key_query:
                    try:
                        await self.client.keys_query(user_id)
                    except Exception as e:
                        logger.warning(f"⚠️ Keys query failed for {user_id}: {e}")

            try:
                response = await self.client.devices()
                for device in response.devices:
                    if device.device_id != self.client.device_id:
                        logger.info(f"📱 Found own device: {device.device_id}")
            except Exception as e:
                logger.warning(f"⚠️ Cannot get own devices: {e}")
                
            logger.info("✅ Aggressive device verification completed")
            
        except Exception as e:
            logger.error(f"❌ Error in verify_all_devices: {e}")
            import traceback
            traceback.print_exc()

    async def handle_command(self, room: MatrixRoom, event: RoomMessageText):
        command = event.body.strip()
        
        if command == "!reset":
            new_session_id = self.reset_session(room.room_id)
            await self.send_text_message(
                room.room_id, 
                f"🔄 Сессия сброшена. Начинаем новый диалог.\n🆔 Новая сессия: {new_session_id}"
            )
                
        elif command == "!session":
            session_id = self.get_or_create_session(room.room_id)
            await self.send_text_message(
                room.room_id, 
                f"🆔 ID текущей сессии: {session_id}\nКомната: {room.room_id[:30]}..."
            )
            
        elif command == "!help" or command == "!start":
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
            
            await self.send_text_message(room.room_id, help_text)
            
        elif command == "!status":
            status_text = f"""🤖 **Статус бота:**
Пользователь: {self.client.user_id}
Активные сессии: {len(self.session_cache)}
Файлы в кэше: {len(self.file_cache)}
Flowise: {self.flowise_url}
Время запуска: {datetime.fromtimestamp(self.start_time/1000, timezone.utc)}"""
            
            await self.send_text_message(room.room_id, status_text)
            
        else:
            await self.send_text_message(room.room_id, f"❓ Неизвестная команда: {command}\nИспользуйте !help для списка команд.")

    async def run(self):
        try:
            logger.info(f"🚀 Starting Flowise Matrix Bot {self.user_id}...")
            logger.info(f"Homeserver: {self.homeserver}")
            logger.info(f"Flowise URL: {self.flowise_url}")
            logger.info(f"⏰ Filter messages newer than: {datetime.fromtimestamp(self.start_time/1000, timezone.utc)}")

            if not await self.login_with_retry():
                logger.error("❌ Failed to login after all retries")
                return
            
            if not await self.init_olm():
                logger.warning("⚠️ E2EE might not work properly")

            if not self.client.user_id or not self.client.access_token:
                logger.error("❌ Not properly logged in. Missing user_id or access_token")
                return
            
            logger.info(f"✅ Logged in as {self.client.user_id}")
            
            self.client.olm_device_verification = False

            self.client.add_event_callback(self.on_invite, InviteMemberEvent)
            self.client.add_event_callback(self.on_message, RoomMessageText)
            self.client.add_event_callback(self.on_file, RoomMessageFile)
            self.client.add_event_callback(self.on_encrypted_file, RoomEncryptedFile)
            self.client.add_event_callback(self.on_encrypted_event, MegolmEvent)
            self.client.add_to_device_callback(self.handle_to_device, ToDeviceEvent)

            logger.info("🔄 Starting initial sync...")
            sync_response = await self.client.sync(timeout=30000)
            if sync_response:
                logger.info(f"✅ Initial sync completed. Next batch: {sync_response.next_batch[:20]}...")
            else:
                logger.warning("⚠️ Initial sync returned empty response")
            
            logger.info("👂 Bot is ready and listening for messages and files...")
            logger.info("📁 Supported file types: PDF, TXT, DOCX, Excel, JSON, CSV, images, code")
            logger.info("💬 Commands: !help, !reset, !session, !status")
            
            while True:
                try:
                    await self.client.sync_forever(timeout=30000)
                except OlmUnverifiedDeviceError as e:
                    logger.error(f"🔒 Device verification error: {e}")
                    await self.verify_all_devices()
                    continue
            
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